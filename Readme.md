# 🎙️ HTML to Podcast Converter

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

> **Automatisez la transformation de vos articles web en épisodes de podcast.**
> Ce script convertit des fichiers HTML (sauvegardés via SingleFile) ou des flux RSS en fichiers MP3 enrichis, prêts à être diffusés sur votre flux RSS personnel (Nextcloud, Audiobookshelf, etc.).
> Les articles peuvent être **résumés automatiquement par IA (Gemini/Gemma)** avant la synthèse vocale, et les résumés d'une même source peuvent être **regroupés en un seul MP3 par période**.

---

## ✨ Fonctionnalités

- **🗣️ Synthèse Vocale Neurale (TTS)** : Utilise le moteur `edge-tts` (voix *Vivienne Neural* par défaut) pour une qualité audio quasi-humaine.
- **📰 Mode "Reader" Robuste & Pauses Naturelles** : Génère un texte propre et structuré pour la lecture :
    - Extraction via `Trafilatura` avec filtrage automatique du bruit (notes de bas de page, résidus de menus).
    - Points de suspension ` ... ` forcés entre les paragraphes pour garantir la respiration du TTS.
    - Points `.` et virgules `,` préservés pour les pauses moyennes et courtes.
    - **Intro Scriptée** : *"Article de [Média]... [Titre]... Par [Auteur]"*.
    - Conversion automatique de l'**écriture inclusive** (client·e·s → "clientes et clients") et des **chiffres romains** (XIXe siècle → 19e siècle).
- **🤖 Résumé IA (Gemini/Gemma)** : Option de résumé automatique des articles via l'API Gemini avant la synthèse vocale. Configurable par flux RSS. Voir la section [Configuration Gemini](#-configuration-gemini-résumé-ia).
- **📦 Regroupement Temporel** : Les résumés d'un même flux peuvent être regroupés en un seul MP3 sur une fenêtre de temps (ex. : toute la production du jour en un seul fichier audio).
- **🏷️ Métadonnées Enrichies (ID3)** :
    - **Titre & Auteur** : directement extraits de l'article.
    - **Image de Couverture** : récupère automatiquement l'image principale (`og:image`) et l'intègre au MP3.
    - **Description** : ajoute le chapô/résumé dans les tags `USLT` (Lyrics).
    - **URL Source** : ajoutée dans les commentaires `COMM`.
- **📡 Suivi Automatique de Flux RSS** : configure des flux pour convertir les nouveaux articles en MP3 au fil de leur publication.
- **✓ Initialisation Intelligente des Flux** : lors du premier lancement sur un flux, tous les articles existants sont marqués "lus" — seuls les futurs articles seront traités.
- **✨ Architecture Modulaire (Adapters)** : détection automatique de la source pour l'extraction la plus précise (adapters dédiés pour Mediapart, Cairn, UCL, Europresse, etc. ; fallback Trafilatura générique).


## 🚀 Installation

### Pré-requis
- Python 3.12 ou supérieur
- Linux (recommandé) ou macOS/Windows.

### Installation des dépendances

```bash
pip install -r requirements.txt
```

*Dépendances principales : `edge-tts`, `beautifulsoup4`, `mutagen`, `trafilatura`, `requests`, `feedparser`.*


## ⚙️ Configuration

### Chemins et paramètres globaux

Les chemins et options sont définis en haut de `html_to_mp3.py` :

```python
INPUT_DIR  = "~/Téléchargements/versaudio"           # Dossier surveillé (fichiers HTML)
OUTPUT_DIR = "~/Documents/Perso/Podcasts/ArtcleTTS"  # Dossier de sortie MP3
ARCHIVE_DIR= "~/Téléchargements/versaudio/Archived"  # Dossier d'archivage après traitement
VOICE      = "fr-FR-VivienneNeural"                  # Voix globale par défaut
```

### Configuration des flux RSS

La liste `RSS_FEEDS` accepte deux formes pour chaque flux :

**Forme simple** — URL seule, utilise la voix par défaut, sans IA :
```python
RSS_FEEDS = [
    "https://www.acrimed.org/spip.php?page=backend",
]
```

**Forme complète** — dictionnaire avec toutes les options :
```python
RSS_FEEDS = [
    {
        "url": "http://www.developpez.com/index/rss",
        "voice": "fr-FR-VivienneNeural",  # Voix spécifique (optionnel)
        "summarize": True,                # Active le résumé IA avant TTS
        "group_window_hours": 24          # Regroupe les résumés sur 24h en 1 MP3
    }
]
```

| Clé | Type | Défaut | Description |
|-----|------|--------|-------------|
| `url` | str | — | URL du flux RSS (**obligatoire**) |
| `voice` | str | `VOICE` global | Voix edge-tts pour ce flux |
| `summarize` | bool | `False` | Active le résumé IA via Gemini |
| `group_window_hours` | int | — | Durée de regroupement en heures (ex. `24` = 1 MP3/jour) |

> ⚠️ `group_window_hours` n'a d'effet que si `summarize: True`. Les résumés sont accumulés dans `grouped_summaries.json` et le MP3 groupé est généré au prochain lancement **après** la fin de la fenêtre.


## 🤖 Configuration Gemini (résumé IA)

Le résumé IA est piloté par le fichier `gemini_config.json` à la racine du projet :

```json
{
    "api_key": "VOTRE_CLE_API_GEMINI",
    "model": "gemma-4-31b-it",
    "max_requests_per_minute": 15,
    "prompt": "Voici un article de presse :\n\n{text}\n\nRésume cet article en 5 à 8 phrases..."
}
```

| Clé | Description |
|-----|-------------|
| `api_key` | Clé API Google AI Studio (ne pas commiter dans git) |
| `model` | Modèle Gemini/Gemma à utiliser |
| `max_requests_per_minute` | Limite de requêtes (max 15 pour le plan gratuit) |
| `prompt` | Template du prompt — `{text}` est remplacé par le texte de l'article |

**Comportement en cas d'erreur API** : le résumé est réessayé jusqu'à 5 fois avec un backoff exponentiel (5 s, 10 s, 20 s, 40 s). En cas d'échec définitif, le texte original est utilisé (fallback silencieux, aucun article perdu).

> ⚠️ Ne commitez pas `gemini_config.json` si votre dépôt est public — ajoutez-le à `.gitignore`.


## 🗂️ Fichiers de persistance

Le projet maintient trois fichiers JSON à la racine (gérés automatiquement) :

| Fichier | Contenu |
|---------|---------|
| `processed_urls.json` | Liste des URLs d'articles déjà convertis (évite les doublons) |
| `seen_feeds.json` | Liste des flux déjà initialisés (évite de convertir les anciens articles) |
| `grouped_summaries.json` | Résumés en attente de regroupement (fenêtre temporelle non fermée) |


## 🖥️ Utilisation

### Lancement manuel

```bash
# Traitement normal (HTML locaux + flux RSS)
python3 html_to_mp3.py

# Limiter à N articles par flux (utile pour tester)
python3 html_to_mp3.py --rss-limit 2

# Mode test : génère des fichiers .txt dans Article-Test/ sans appel TTS
python3 html_to_mp3.py --test
```

### Automatisation (CRON)

Pour scanner le dossier et les flux toutes les heures :
```bash
0 * * * * /usr/bin/python3 /chemin/vers/html_to_mp3.py >> /var/log/tts_mp3.log 2>&1
```

> Pour les flux avec regroupement par jour (`group_window_hours: 24`), le MP3 groupé est produit lors du premier lancement du lendemain.

### Tester le résumé IA en isolation

```bash
python3 tests/test_summarizer_live.py --feed "http://www.developpez.com/index/rss" --limit 2
```

Ce script appelle l'API Gemini sur les 2 derniers articles du flux et affiche le résumé sans générer de MP3.


## 📋 Workflow Recommandé

1. **Sur le navigateur** : utilisez [SingleFile](https://github.com/gildas-lormeau/SingleFile) pour sauvegarder un article dans `INPUT_DIR` (synchronisé via Nextcloud/Syncthing).
2. **Sur le serveur** : le script détecte le fichier `.html` et :
    - Extrait le contenu via l'adapter adapté (ou Trafilatura en fallback).
    - Optionnellement, résume via Gemini.
    - Génère le texte avec ponctuation naturelle pour les pauses.
    - Télécharge la couverture, tague en ID3, produit le MP3.
3. **Résultat** : un fichier MP3 apparaît dans `OUTPUT_DIR`, prêt à être écouté.


---

## 🛠️ Guide Développeur

### Architecture du projet

```
TTS_Mp3/
├── html_to_mp3.py          # Orchestrateur principal (pipeline, RSS, grouping)
├── summarizer.py           # Client Gemini (rate-limit, retry, nettoyage)
├── gemini_config.json      # Config API Gemini (à ne pas commiter)
├── adapters/
│   ├── __init__.py         # Factory : sélectionne l'adapter selon la source
│   ├── base.py             # Classe abstraite BaseAdapter
│   ├── generic.py          # Fallback Trafilatura (utilisé si aucun adapter ne matche)
│   ├── ADAPTER_GUIDE.md    # Guide détaillé de création d'adapter
│   ├── mediapart.py        # Adapters spécifiques…
│   ├── cairn.py
│   ├── ucl.py
│   └── ...
├── tests/
│   ├── test_summarizer.py      # Tests unitaires du résumeur (17 tests)
│   ├── test_grouping.py        # Tests unitaires du regroupement (16 tests)
│   └── test_summarizer_live.py # Test live (appel API réel, sans MP3)
├── processed_urls.json     # Persistance URLs traitées
├── seen_feeds.json         # Persistance flux initialisés
└── grouped_summaries.json  # Résumés en attente de groupement
```

### Pipeline de traitement RSS

```
process_rss_feed()
  └─ feedparser → articles non encore traités
       └─ adapter.extract_metadata() + adapter.get_content()
            ├─ [si summarize=True] → GeminiSummarizer.summarize()
            │       ├─ _preprocess_for_api()   # nettoie boilerplate
            │       ├─ _build_prompt()         # injecte le texte dans le template
            │       ├─ _call_api_sync()        # appel REST streamGenerateContent
            │       │       └─ retry x5 (5s→10s→20s→40s) sur HTTP 429/500/502/503/504
            │       ├─ filtre les parts "thought" (raisonnement interne Gemma)
            │       ├─ _extract_core_response() # filet de sécurité
            │       └─ _strip_markdown_for_tts()
            │
            ├─ [si group_window_hours] → store_pending_summary()
            │       └─ grouped_summaries.json (bucket par date)
            └─ [sinon] → generate_audio_from_content() → MP3
```

```
flush_grouped_summaries()           # appelé à chaque run
  └─ pour chaque bucket dont la fenêtre est fermée (date < aujourd'hui)
       └─ _build_grouped_text() → generate_audio_from_content() → MP3 groupé
```

### Ajouter un adapter pour un nouveau site

1. Créez `adapters/monsite.py` et héritez de `BaseAdapter` :

```python
from .base import BaseAdapter

class MonSiteAdapter(BaseAdapter):
    def can_handle(self):
        og = self.soup.find("meta", property="og:site_name")
        return bool(og and "MonSite" in og.get("content", ""))

    def extract_metadata(self):
        meta = super().extract_metadata()
        # Surcharger title, author, media, image_url, url, description, date
        return meta

    def _extract_content(self):
        # Retourner le texte brut nettoyé, sans HTML
        article = self.soup.find("article")
        return article.get_text(" ") if article else ""
```

2. Enregistrez-le dans `adapters/__init__.py` :

```python
from .monsite import MonSiteAdapter
ADAPTERS = [MonSiteAdapter, ..., GenericAdapter]  # GenericAdapter TOUJOURS en dernier
```

> Consultez [adapters/ADAPTER_GUIDE.md](adapters/ADAPTER_GUIDE.md) pour le guide complet avec tous les champs ID3 et les stratégies de détection.

### Erreurs courantes et pièges

| Problème | Cause | Solution |
|----------|-------|----------|
| **L'article est retraité à chaque run** | URL absente de `processed_urls.json` | Vérifier que `save_processed_url(url)` est bien appelé après succès |
| **Tous les anciens articles d'un flux sont convertis** | Flux absent de `seen_feeds.json` | Ajouter manuellement l'URL dans `seen_feeds.json` ou laisser le premier run le faire |
| **Résumé Gemini = texte original à 100%** | Erreur API en fallback | Vérifier les logs (`WARNING`) — souvent HTTP 500 (surcharge modèle) ou clé invalide |
| **`thinkingLevel` non supporté** | Certains modèles Gemma ne supportent pas `HIGH` | Retirer `thinkingConfig` du body dans `_call_api_sync()` ou changer de modèle |
| **MP3 groupé jamais généré** | La fenêtre temporelle n'est pas encore fermée | Le flush ne se produit que le lendemain (bucket date < aujourd'hui) |
| **Adapter non sélectionné** | `can_handle()` trop permissif ou trop restrictif | Tester avec `--test` et ajouter des logs dans `can_handle()` |
| **Balises Markdown dans le TTS** | Résumé Gemini avec Markdown | `_strip_markdown_for_tts()` est appliqué automatiquement ; vérifier que la méthode est appelée |
| **Texte de raisonnement ("thinking") dans le résumé** | Modèle Gemma expose ses `thought` parts | `_call_api_sync()` filtre `p.get("thought", False)` — vérifier l'endpoint `streamGenerateContent` |

### Lancer les tests

```bash
# Tests unitaires (rapides, sans appel réseau)
python3 -m pytest tests/test_summarizer.py tests/test_grouping.py -v

# Test live Gemini (nécessite gemini_config.json valide)
python3 tests/test_summarizer_live.py --feed "http://www.developpez.com/index/rss" --limit 1
```

### Variables d'environnement utiles

Pas encore de gestion `.env` native. Pour éviter de commiter la clé API :
```bash
# Avant de lancer / dans votre .bashrc
export GEMINI_API_KEY="votre_cle"
```
Et dans `gemini_config.json`, vous pouvez mettre une valeur placeholder puis la surcharger en lisant `os.environ.get("GEMINI_API_KEY")` dans `load_gemini_config()`.

---

## 🔮 Améliorations Futures (Roadmap)

- [ ] **Clé API via variable d'environnement** : remplacer `gemini_config.json` par `GEMINI_API_KEY` env var.
- [ ] **Support Multi-langues** : détection automatique de la langue (`<html lang="en">`) pour basculer sur une voix anglaise.
- [ ] **Fichier de Config Externe** : sortir `INPUT_DIR`, `OUTPUT_DIR`, etc. dans un fichier `.env` ou `config.yaml`.
- [ ] **Parallélisation** : traiter plusieurs articles simultanément pour accélérer le batch processing.
- [ ] **Support PDF/Epub** : étendre le support au-delà du HTML.
- [ ] **Docker** : conteneuriser l'application pour un déploiement plus simple.


## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une Issue ou une Pull Request.

## 📄 Licence

Ce projet est sous licence MIT.