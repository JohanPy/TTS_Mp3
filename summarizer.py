#!/usr/bin/env python3
"""
Module de résumé IA via l'API REST Gemini/Gemma.

Utilise l'API REST directement (pas de nouvelle dépendance, `requests` est déjà requis).
Implémente un rate limiter simple pour respecter la limite de l'API (15 req/min max).
"""

import asyncio
import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

# --- SINGLETON ---
_summarizer_instance = None

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_config.json")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"

# Longueur maximale du texte envoyé à l'API (en caractères) pour éviter de dépasser les quotas de tokens
MAX_TEXT_LENGTH = 8000

# Délai initial entre tentatives en cas d'erreur API transitoire (secondes)
RETRY_BASE_DELAY = 5.0
# Nombre maximum de tentatives (1 essai initial + N-1 répétitions)
MAX_RETRIES = 5
# Codes HTTP transitoires qui méritent un retry
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def load_gemini_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """
    Charge la configuration Gemini depuis un fichier JSON.

    La clé API peut être surchargée via la variable d'environnement GEMINI_API_KEY,
    ce qui évite de stocker des secrets dans un fichier.

    Raises:
        FileNotFoundError: si le fichier de configuration est absent.
        ValueError: si des clés obligatoires manquent ou si la clé API est un placeholder.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Fichier de configuration Gemini introuvable : {config_path}\n"
            "Copiez gemini_config.example.json vers gemini_config.json et renseignez vos paramètres.\n"
            "Vous pouvez aussi définir la variable d'environnement GEMINI_API_KEY."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # La variable d'environnement prend la priorité sur le fichier
    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key:
        config["api_key"] = env_key

    required_keys = ("api_key", "model", "prompt", "max_requests_per_minute")
    missing = [k for k in required_keys if k not in config]
    if missing:
        raise ValueError(f"Clés manquantes dans gemini_config.json : {missing}")

    if config.get("api_key") in ("", "VOTRE_CLE_API_GEMINI"):
        raise ValueError(
            "La clé API Gemini n'est pas configurée.\n"
            "Définissez GEMINI_API_KEY en variable d'environnement ou renseignez api_key dans gemini_config.json."
        )

    rpm = config["max_requests_per_minute"]
    if not isinstance(rpm, (int, float)) or rpm <= 0 or rpm > 15:
        raise ValueError(
            f"max_requests_per_minute doit être un nombre entre 1 et 15 (reçu : {rpm})"
        )

    return config


class GeminiSummarizer:
    """
    Résumeur d'articles via l'API REST Gemini/Gemma.

    Gère automatiquement le rate limiting : au plus `max_requests_per_minute`
    appels par minute. Si la limite est atteinte, attend le délai nécessaire.
    En cas d'erreur API, retourne le texte original (fallback silencieux).
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config = load_gemini_config(config_path)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()

        self._api_key: str = self._config["api_key"]
        self._model: str = self._config["model"]
        self._prompt_template: str = self._config["prompt"]
        self._max_rpm: int = int(self._config["max_requests_per_minute"])
        self._min_interval: float = 60.0 / self._max_rpm

        logger.info(
            f"GeminiSummarizer initialisé — modèle : {self._model}, "
            f"limite : {self._max_rpm} req/min (intervalle min : {self._min_interval:.1f}s)"
        )

    async def _enforce_rate_limit(self) -> None:
        """Attend si nécessaire pour respecter la limite de requêtes par minute."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                logger.debug(f"Rate limiting : attente de {wait:.2f}s avant appel Gemini")
                await asyncio.sleep(wait)
            self._last_request_time = time.monotonic()

    def _extract_core_response(self, text: str) -> str:
        """
        Filet de sécurité : extrait le résumé final si le modèle a exposé son
        raisonnement interne (marqueurs « Draft N » ou méta-commentaires anglais).
        Avec thinkingLevel HIGH et streamGenerateContent, les parts thought sont
        filtrées en amont — cette méthode ne s'applique qu'en dernier recours.
        """
        import re

        # Chercher le dernier marqueur « Draft N » et prendre ce qui suit
        matches = list(re.finditer(
            r'(?:Draft|Version|Révision)\s+\d+[^\n:]*:?', text, re.IGNORECASE
        ))
        if matches:
            candidate = text[matches[-1].end():].strip()
            cutoff = re.search(
                r'\n\s*(?:Concis|Key|Target|Okay|Done|Check).*?[\?\.]',
                candidate, re.IGNORECASE
            )
            if cutoff:
                candidate = candidate[:cutoff.start()].strip()
            if len(candidate) >= 80:
                return candidate

        # Filtrer les lignes de méta-analyse anglaises
        english_re = re.compile(
            r'^\s*(?:yes|no|okay|done|check|key|target|source|constraint'
            r'|refin|mental|factual tone|article about|french$'
            r'|core topic|competit|context|endur)',
            re.IGNORECASE
        )
        kept = [
            line.strip() for line in text.splitlines()
            if line.strip()
            and not re.match(r'^[A-Z][a-z\s/]+\?\s*(Yes|No)\.?$', line.strip())
            and not english_re.match(line.strip())
        ]
        if kept:
            result = ' '.join(kept)
            if len(result) >= 80:
                return result

        return text

    def _strip_markdown_for_tts(self, text: str) -> str:
        """
        Supprime les éléments Markdown du texte pour que le TTS le lise correctement.
        - **gras** → gras
        - *italique* → italique
        - `code` → code
        - # Titre → Titre
        - * puce → texte de la puce (avec virgule pour liaison)
        """
        import re
        t = text
        # Gras **text** ou __text__
        t = re.sub(r'\*{2}(.+?)\*{2}', r'\1', t)
        t = re.sub(r'_{2}(.+?)_{2}', r'\1', t)
        # Italique *text* ou _text_ (après avoir traité le gras)
        t = re.sub(r'\*(.+?)\*', r'\1', t)
        t = re.sub(r'_(.+?)_', r'\1', t)
        # Code inline `text`
        t = re.sub(r'`(.+?)`', r'\1', t)
        # Titres # / ## / ###
        t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
        # Puces : lignes commençant par * ou - ou +
        t = re.sub(r'^\s*[\*\-\+]\s+', '', t, flags=re.MULTILINE)
        # Puces numérotées : 1. item
        t = re.sub(r'^\s*\d+\.\s+', '', t, flags=re.MULTILINE)
        # Normaliser les espaces et les sauts de ligne
        t = re.sub(r'\n{2,}', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def _preprocess_for_api(self, text: str) -> str:
        """
        Nettoie le texte avant envoi à l'API pour améliorer la qualité du résumé.

        Supprime :
        - Les separateurs TTS ``.. `` (remplacés par un espace)
        - Les blocs de titre/description en début (lignes entre guillemets)
        - Les sections de forum/boilerplate (« Et vous ? », « Voir aussi »,
          abonnements, publicité, commentaires)
        - Les lignes trop courtes (artefacts de formatage)
        """
        import re
        t = text

        # 1. Supprimer les guillemets typographiques de section ("Titre..." .. "Sous-titre...") 
        #    qui dupliquent le titre et le résumé déjà connus
        t = re.sub(r'^(?:\s*"[^"]{0,300}"\s*\.{0,3}\s*)+', '', t, flags=re.DOTALL)

        # 2. Couper au premier marqueur de section-parasites
        noise_markers = [
            r'"Et vous\s*\?"',
            r'"Voir aussi"',
            r'"Et vous aussi"',
            r'Vous avez lu gratuitement',
            r'Soutenez le club',
            r'en souscrivant un abonnement',
            r'Donnez votre avis',
        ]
        for marker in noise_markers:
            m = re.search(marker, t, flags=re.IGNORECASE)
            if m:
                t = t[:m.start()]

        # 3. Remplacer les séparateurs TTS « .. » par un espace propre
        t = re.sub(r'\s*\.\.\s*', ' ', t)

        # 4. Supprimer les lignes trop courtes (< 20 chars) qui sont des artefacts
        lines = [l.strip() for l in t.splitlines()]
        lines = [l for l in lines if len(l) >= 20 or l == '']
        t = ' '.join(lines)

        # 5. Normaliser les espaces
        t = re.sub(r'\s+', ' ', t).strip()

        if len(t) < 100:
            logger.debug("Pré-traitement API : texte trop court après nettoyage, utilisation du texte original")
            return text

        logger.debug(
            f"Pré-traitement API : {len(text)} → {len(t)} chars "
            f"({100 * len(t) // len(text)}% conservé)"
        )
        return t

    def _build_prompt(self, text: str) -> str:
        """Construit le prompt complet en substituant {text} dans le template."""
        # Pré-nettoyer avant troncature pour maximiser l'information utile
        cleaned = self._preprocess_for_api(text)
        truncated = cleaned[:MAX_TEXT_LENGTH]
        if len(cleaned) > MAX_TEXT_LENGTH:
            logger.debug(
                f"Texte tronqué de {len(cleaned)} à {MAX_TEXT_LENGTH} caractères pour l'API Gemini"
            )
        return self._prompt_template.replace("{text}", truncated)

    def _call_api_sync(self, prompt: str) -> str:
        """
        Appel synchrone à l'API REST Gemini avec retry sur erreurs transitoires.
        Retourne le texte résumé ou lève une exception en cas d'échec définitif.
        """
        import time as _time

        url = GEMINI_API_URL.format(model=self._model)
        params = {"key": self._api_key}
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "thinkingConfig": {
                    "thinkingLevel": "HIGH"
                }
            }
        }

        last_exc: Exception = RuntimeError("Aucune tentative effectuée")
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.post(url, params=params, json=body, timeout=60)
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"Gemini API tentative {attempt}/{MAX_RETRIES} — erreur réseau ({e}). "
                        f"Nouvelle tentative dans {wait:.0f}s…"
                    )
                    _time.sleep(wait)
                continue

            if response.status_code == 200:
                break

            if response.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    f"Gemini API tentative {attempt}/{MAX_RETRIES} — HTTP {response.status_code}. "
                    f"Nouvelle tentative dans {wait:.0f}s…"
                )
                _time.sleep(wait)
                last_exc = RuntimeError(
                    f"Gemini API erreur {response.status_code} : {response.text[:300]}"
                )
                continue

            raise RuntimeError(
                f"Gemini API erreur {response.status_code} : {response.text[:300]}"
            )
        else:
            raise last_exc

        # streamGenerateContent renvoie un tableau JSON de chunks
        # Chaque chunk a la même structure que generateContent.
        # Les parts avec {"thought": true} contiennent le raisonnement interne
        # (filtré) ; les autres contiennent la réponse finale.
        try:
            chunks = response.json()
            if not isinstance(chunks, list):
                chunks = [chunks]  # fallback si l'API renvoie un objet unique

            answer_parts = []
            for chunk in chunks:
                candidates = chunk.get("candidates", [])
                if not candidates:
                    continue
                parts = candidates[0].get("content", {}).get("parts", [])
                for p in parts:
                    if not p.get("thought", False) and "text" in p:
                        answer_parts.append(p["text"])

            if not answer_parts:
                raise ValueError("Aucune part de réponse non-thinking trouvée")
            summary_text = "".join(answer_parts).strip()
            return summary_text
        except (KeyError, IndexError) as e:
            raise ValueError(f"Structure de réponse Gemini inattendue : {e}")

    async def summarize(self, text: str) -> str:
        """
        Résume le texte fourni via l'API Gemini.

        En cas d'erreur (réseau, API, quota), retourne le texte original
        pour ne pas bloquer la génération audio (fallback silencieux).

        Args:
            text: Texte brut de l'article à résumer.

        Returns:
            Texte résumé, ou texte original si l'API est indisponible.
        """
        if not text or len(text.strip()) < 50:
            return text

        await self._enforce_rate_limit()

        prompt = self._build_prompt(text)

        try:
            loop = asyncio.get_event_loop()
            summary = await loop.run_in_executor(None, self._call_api_sync, prompt)
            # Extraire le résumé final depuis la sortie potentiellement verbose
            summary = self._extract_core_response(summary)
            # Nettoyer le Markdown résiduel pour que le TTS lise correctement
            summary = self._strip_markdown_for_tts(summary)
            logger.info(
                f"Résumé généré : {len(text)} chars → {len(summary)} chars "
                f"({100 * len(summary) // len(text)}% du texte original)"
            )
            return summary
        except Exception as e:
            logger.warning(
                f"Échec de la résumé Gemini ({e.__class__.__name__}: {e}). "
                "Utilisation du texte original."
            )
            return text


def get_summarizer(config_path: str = DEFAULT_CONFIG_PATH) -> GeminiSummarizer:
    """
    Retourne l'instance singleton de GeminiSummarizer.
    Initialise l'instance au premier appel.

    Raises:
        FileNotFoundError: si gemini_config.json est introuvable.
        ValueError: si la configuration est invalide.
    """
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = GeminiSummarizer(config_path)
    return _summarizer_instance


def reset_summarizer() -> None:
    """Réinitialise le singleton (utile pour les tests)."""
    global _summarizer_instance
    _summarizer_instance = None
