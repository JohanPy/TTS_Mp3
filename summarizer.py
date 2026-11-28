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
import threading
import time

import requests
from text_utils import preprocess_for_api, strip_markdown_for_tts

logger = logging.getLogger(__name__)

# --- SINGLETON ---
_summarizer_instance = None

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_config.json")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"

# Longueur maximale du texte envoyé à l'API (en caractères) pour éviter de dépasser les quotas de tokens
MAX_TEXT_LENGTH = 8000

# Quota par défaut de tokens par minute (marge de sécurité sous les 16K TPM de Gemma)
DEFAULT_MAX_TPM = 14000
TPM_WINDOW_SECONDS = 60.0
OUTPUT_TOKEN_RESERVE = 600

# Délai d'attente réseau par défaut pour l'API Gemini (secondes)
DEFAULT_TIMEOUT_SECONDS = 180

# Délai initial entre tentatives en cas d'erreur API transitoire (secondes)
RETRY_BASE_DELAY = 5.0
# Délai avant la dernière tentative (secondes, 2 minutes)
RETRY_LAST_DELAY = 120.0
# Délais progressifs spécifiques en cas de surcharge serveur (HTTP 503)
RETRY_OVERLOAD_DELAYS = (15.0, 30.0, 60.0, 120.0)
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
    if not isinstance(rpm, (int, float)) or rpm <= 0 or rpm > 1800:
        raise ValueError(
            f"max_requests_per_minute doit être un nombre entre 1 et 1800 (reçu : {rpm})"
        )

    # Concurrence optionnelle pour les résumés simultanés (défaut : 6)
    raw_concurrency = config.get("concurrency", 6)
    if not isinstance(raw_concurrency, (int, float)) or raw_concurrency <= 0 or raw_concurrency > 30:
        raise ValueError(
            f"concurrency doit être un nombre entre 1 et 30 (reçu : {raw_concurrency})"
        )
    config["concurrency"] = int(raw_concurrency)

    # Timeout optionnel (secondes, défaut: DEFAULT_TIMEOUT_SECONDS)
    raw_timeout = config.get("timeout") or config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS
    if not isinstance(raw_timeout, (int, float)) or raw_timeout <= 0:
        raise ValueError(
            f"timeout doit être un nombre positif en secondes (reçu : {raw_timeout})"
        )
    config["timeout"] = int(raw_timeout)

    # Quota optionnel de tokens par minute (défaut : DEFAULT_MAX_TPM)
    raw_tpm = config.get("max_tokens_per_minute", DEFAULT_MAX_TPM)
    if not isinstance(raw_tpm, (int, float)) or raw_tpm <= 0:
        raise ValueError(
            f"max_tokens_per_minute doit être un nombre positif (reçu : {raw_tpm})"
        )
    config["max_tokens_per_minute"] = int(raw_tpm)

    return config


class SummarizationError(Exception):
    """Exception levée lorsque la génération du résumé par l'IA échoue."""
    pass


class GeminiSummarizer:
    """
    Résumeur d'articles via l'API REST Gemini/Gemma.

    Gère automatiquement le rate limiting : au plus `max_requests_per_minute`
    appels par minute. Si la limite est atteinte, attend le délai nécessaire.
    En cas d'erreur API, lève une SummarizationError (l'article est retenté plus tard).
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self._config = load_gemini_config(config_path)
        self._last_request_time: float = 0.0
        self._lock = asyncio.Lock()
        self._state_lock = threading.Lock()
        self._token_history: list[list] = []

        self._api_key: str = self._config["api_key"]
        self._model: str = self._config["model"]
        self._prompt_template: str = self._config["prompt"]
        self._max_rpm: int = int(self._config["max_requests_per_minute"])
        self._min_interval: float = 60.0 / self._max_rpm
        self._max_tpm: int = int(self._config.get("max_tokens_per_minute", DEFAULT_MAX_TPM))
        self._timeout: int = self._config.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        self._concurrency: int = self._config.get("concurrency", 6)
        self._semaphore = asyncio.Semaphore(self._concurrency)

        logger.info(
            f"GeminiSummarizer initialisé — modèle : {self._model}, "
            f"timeout : {self._timeout}s, "
            f"concurrence : {self._concurrency}, "
            f"limite : {self._max_rpm} req/min (intervalle min : {self._min_interval:.1f}s), "
            f"TPM max : {self._max_tpm} tok/min"
        )

    def _estimate_tokens(self, prompt: str) -> int:
        """Estime le nombre total de tokens (entrée + marge sortie/thinking)."""
        return max(1, (len(prompt) + 2) // 3 + OUTPUT_TOKEN_RESERVE)

    def _prune_token_history_locked(self, now: float) -> None:
        """Supprime les entrées hors de la fenêtre glissante de 60s (sous _state_lock)."""
        cutoff = now - TPM_WINDOW_SECONDS
        self._token_history = [entry for entry in self._token_history if entry[0] > cutoff]

    def _compute_tpm_wait_locked(self, now: float, estimated_tokens: int) -> float:
        """Calcule le délai d'attente (s) pour respecter max_tokens_per_minute (sous _state_lock)."""
        if estimated_tokens <= 0 or not self._token_history:
            return 0.0
        self._prune_token_history_locked(now)
        needed = min(estimated_tokens, self._max_tpm)
        used = sum(entry[1] for entry in self._token_history)
        if used + needed <= self._max_tpm:
            return 0.0
        for ts, tokens in self._token_history:
            used -= tokens
            if used + needed <= self._max_tpm:
                return max(0.0, TPM_WINDOW_SECONDS - (now - ts) + 0.05)
        return max(0.0, TPM_WINDOW_SECONDS - (now - self._token_history[-1][0]) + 0.05)

    async def _enforce_rate_limit(self, estimated_tokens: int = 0) -> list | None:
        """Attend si nécessaire pour respecter les limites RPM et TPM."""
        async with self._lock:
            with self._state_lock:
                now = time.monotonic()
                rpm_wait = 0.0
                if self._last_request_time > 0:
                    elapsed = now - self._last_request_time
                    if elapsed < self._min_interval:
                        rpm_wait = self._min_interval - elapsed
                tpm_wait = self._compute_tpm_wait_locked(now, estimated_tokens)
                wait = max(rpm_wait, tpm_wait)

            if wait > 0:
                if tpm_wait > 2.0:
                    logger.info(
                        f"⏳ Rate limiting TPM : attente de {wait:.1f}s "
                        f"(quota {self._max_tpm} tok/min)…"
                    )
                else:
                    logger.debug(f"Rate limiting : attente de {wait:.2f}s avant appel Gemini")
                await asyncio.sleep(wait)

            with self._state_lock:
                now = time.monotonic()
                self._last_request_time = now
                self._prune_token_history_locked(now)
                if estimated_tokens > 0:
                    entry = [now, estimated_tokens]
                    self._token_history.append(entry)
                    return entry
                return None

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



    def _build_prompt(self, text: str) -> str:
        """Construit le prompt complet en substituant {text} dans le template."""
        # Pré-nettoyer avant troncature pour maximiser l'information utile
        cleaned = preprocess_for_api(text)
        truncated = cleaned[:MAX_TEXT_LENGTH]
        if len(cleaned) > MAX_TEXT_LENGTH:
            logger.debug(
                f"Texte tronqué de {len(cleaned)} à {MAX_TEXT_LENGTH} caractères pour l'API Gemini"
            )
        return self._prompt_template.replace("{text}", truncated)

    def _call_api_sync(
        self,
        prompt: str,
        label: str = "",
        token_entry: list | None = None,
        estimated_tokens: int = 0,
    ) -> str:
        """
        Appel synchrone à l'API REST Gemini avec retry sur erreurs transitoires.
        Retourne le texte résumé ou lève une exception en cas d'échec définitif.
        """
        import time as _time

        tag = f" {label}" if label else ""
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
            if attempt > 1 and estimated_tokens > 0:
                with self._state_lock:
                    tpm_wait = self._compute_tpm_wait_locked(_time.monotonic(), estimated_tokens)
                if tpm_wait > 0:
                    logger.info(
                        f"⏳ Rate limiting TPM avant retry{tag} : attente de {tpm_wait:.1f}s…"
                    )
                    _time.sleep(tpm_wait)
                with self._state_lock:
                    now = _time.monotonic()
                    self._prune_token_history_locked(now)
                    token_entry = [now, estimated_tokens]
                    self._token_history.append(token_entry)

            try:
                response = requests.post(url, params=params, json=body, timeout=self._timeout)
            except Exception as e:
                if token_entry is not None:
                    with self._state_lock:
                        token_entry[1] = 0
                last_exc = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_LAST_DELAY if attempt == MAX_RETRIES - 1 else RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"Gemma tentative {attempt}/{MAX_RETRIES}{tag} — erreur réseau ({e}). "
                        f"Nouvelle tentative dans {wait:.0f}s…"
                    )
                    _time.sleep(wait)
                continue

            if response.status_code != 200:
                if response.status_code >= 500 and token_entry is not None:
                    # Les erreurs serveur (503, 500, etc.) ne consomment pas le quota TPM
                    with self._state_lock:
                        token_entry[1] = 0
                if response.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                    if response.status_code == 503:
                        wait = RETRY_OVERLOAD_DELAYS[min(attempt - 1, len(RETRY_OVERLOAD_DELAYS) - 1)]
                    else:
                        wait = RETRY_LAST_DELAY if attempt == MAX_RETRIES - 1 else RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"Gemma tentative {attempt}/{MAX_RETRIES}{tag} — HTTP {response.status_code}. "
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

            # streamGenerateContent renvoie un tableau JSON de chunks
            # Chaque chunk a la même structure que generateContent.
            # Les parts avec {"thought": true} contiennent le raisonnement interne
            # (filtré) ; les autres contiennent la réponse finale.
            try:
                chunks = response.json()
                if not isinstance(chunks, list):
                    chunks = [chunks]  # fallback si l'API renvoie un objet unique

                answer_parts = []
                actual_tokens = None
                for chunk in chunks:
                    usage = chunk.get("usageMetadata")
                    if isinstance(usage, dict) and "totalTokenCount" in usage:
                        actual_tokens = int(usage["totalTokenCount"])
                    candidates = chunk.get("candidates", [])
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for p in parts:
                        if not p.get("thought", False) and "text" in p:
                            answer_parts.append(p["text"])

                if actual_tokens is not None and token_entry is not None:
                    with self._state_lock:
                        token_entry[1] = actual_tokens

                if not answer_parts:
                    raise ValueError("Aucune part de réponse non-thinking trouvée")
                summary_text = "".join(answer_parts).strip()
                return summary_text
            except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_LAST_DELAY if attempt == MAX_RETRIES - 1 else RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"Gemma tentative {attempt}/{MAX_RETRIES}{tag} — {e} (réponse incomplète ou interruption). "
                        f"Nouvelle tentative dans {wait:.0f}s…"
                    )
                    _time.sleep(wait)
                continue
        else:
            raise last_exc

    async def summarize(self, text: str, label: str = "") -> str:
        """
        Résume le texte fourni via l'API Gemini.

        En cas d'erreur (réseau, API, quota), lève une SummarizationError
        afin de pouvoir retenter plus tard sans conserver l'article complet.

        Args:
            text: Texte brut de l'article à résumer.
            label: Identifiant optionnel pour les logs (ex: '[1/12]').

        Returns:
            Texte résumé.

        Raises:
            SummarizationError: Si la génération du résumé échoue.
        """
        if not text or len(text.strip()) < 50:
            return text

        tag = f" {label}" if label else ""
        async with self._semaphore:
            prompt = self._build_prompt(text)
            estimated_tokens = self._estimate_tokens(prompt)
            token_entry = await self._enforce_rate_limit(estimated_tokens)
            start_t = time.monotonic()

            try:
                loop = asyncio.get_event_loop()
                try:
                    summary = await loop.run_in_executor(
                        None,
                        lambda: self._call_api_sync(
                            prompt,
                            label=label,
                            token_entry=token_entry,
                            estimated_tokens=estimated_tokens,
                        ),
                    )
                except TypeError:
                    summary = await loop.run_in_executor(None, lambda: self._call_api_sync(prompt))

                # Extraire le résumé final depuis la sortie potentiellement verbose
                summary = self._extract_core_response(summary)
                # 3. Supprimer le Markdown pour ne pas polluer le TTS
                summary = strip_markdown_for_tts(summary)
                duration = time.monotonic() - start_t
                ratio = 100 * len(summary) // len(text)
                reduction = 100 - ratio
                logger.info(
                    f"🤖 Résumé IA généré{tag} : {len(text)} → {len(summary)} car. "
                    f"({ratio}%, -{reduction}%) en {duration:.1f}s"
                )
                return summary
            except Exception as e:
                logger.error(
                    f"Échec du résumé Gemini{tag} ({e.__class__.__name__}: {e})."
                )
                raise SummarizationError(f"Échec du résumé Gemini : {e}") from e


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
