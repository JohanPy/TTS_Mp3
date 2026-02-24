# 🎙️ HTML to Podcast Converter

![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

> **Automatisez la transformation de vos articles web en épisodes de podcast audio de haute qualité.**
> Ce script convertit des fichiers HTML (sauvegardés via SingleFile) en fichiers MP3 enrichis, prêts à être diffusés sur votre flux RSS personnel (Nextcloud, Audiobookshelf, etc.).

---

## ✨ Fonctionnalités

- **🗣️ Synthèse Vocale Neurale (TTS)** : Utilise le moteur `edge-tts` (Voix *Vivienne Neural*) pour une qualité audio quasi-humaine.
- **📰 Mode "Reader" Robuste & Pauses Naturelles** : Génère un texte ultra-propre et structuré pour la lecture :
    - Extraction puissante via `Trafilatura` avec filtrage automatique du bruit (notes de bas de page académiques `[1]`, résidus de menus).
    - Points de suspension ` ... ` forcés entre les paragraphes pour garantir la respiration du TTS.
    - Points `.` et Virgules `,` préservés pour les pauses moyennes et courtes.
    - **Intro Scriptée** : *"Article de [Média]... [Titre]... Par [Auteur]"*.
- **🏷️ Métadonnées Enrichies (ID3)** :
    - **Titre & Auteur** : Directement extraits de l'article.
    - **Image de Couverture** : Récupère automatiquement l'image principale (`og:image`) et l'intègre au MP3.
    - **Description** : Ajoute le chapô/résumé dans les tags `USLT` (Lyrics).
    - **URL Source** : Ajoutée dans les commentaires `COMM`.

- **✨ Architecture Modulaire (Adapters)** : Le système détecte automatiquement la source de l'article pour appliquer l'extraction la plus précise :
    - **Générique (Reader Mode)** : Fallback surpuissant utilisant Trafilatura, fonctionnant parfaitement sur 95% des sites web.
    - **Gemini** : Support des exports HTML de l'IA (Markdown rendu).
    - **Europresse** : Gestion des articles de presse agrégés.
    - **Adapters Sur-mesure** : Conservation de règles spécifiques de nettoyage profond pour certains sites (ex: *Cairn, Mediapart*).
- **clean_filename** : Renommage automatique des fichiers pour une compatibilité maximale.
- **Archivage** : Déplace automatiquement les fichiers traités pour garder votre dossier de "Lu" propre.


## 🚀 Installation

### Pré-requis
- Python 3.12 ou supérieur
- Un environnement Linux (recommandé) ou macOS/Windows.

### Installation des dépendances

```bash
pip install -r requirements.txt
```

*Dépendances principales : `edge-tts`, `beautifulsoup4`, `mutagen`, `trafilatura`.*

## ⚙️ Configuration

Les chemins d'accès sont définis en haut du script `html_to_mp3.py`. Vous devez les adapter à votre environnement :

```python
INPUT_DIR = "/chemin/vers/vos/articles/html"     # Dossier surveillé
OUTPUT_DIR = "/chemin/vers/votre/dossier/podcast" # Dossier de sortie MP3
ARCHIVE_DIR = "/chemin/vers/archives"            # Dossier d'archivage
VOICE = "fr-FR-VivienneNeural"                   # Voix utilisée
```

## � Utilisation

Le script est conçu pour être lancé manuellement ou via une tâche planifiée (CRON).

### Lancement manuel
```bash
python3 html_to_mp3.py
```

### Automatisation (CRON)
Pour scanner le dossier toutes les heures :
```bash
0 * * * * /usr/bin/python3 /chemin/vers/html_to_mp3.py >> /var/log/tts_mp3.log 2>&1
```

## 📋 Workflow Recommandé

1.  **Sur votre navigateur** : Utilisez l'extension [SingleFile](https://github.com/gildas-lormeau/SingleFile) pour sauvegarder un article dans votre dossier `INPUT_DIR` (synchronisé via Nextcloud/Syncthing).
2.  **Sur le serveur** : Le script détecte le fichier `.html`.
3.  **Traitement** : 
    - Extraction intelligente du contenu (suppression des pubs/menus).
    - Génération du texte avec ponctuation naturelle pour créer des pauses.
    - Téléchargement de la cover.
    - Tagging ID3 complet.
4.  **Résultat** : Un fichier MP3 apparaît dans `OUTPUT_DIR`, prêt à être écouté.


## 🛠️ Développement (Ajouter une source)

L'architecture repose sur des **Adapters** situés dans `adapters/`. Pour supporter un nouveau site :

1.  Créez un fichier `adapters/monsite.py`.
2.  Héritez de `BaseAdapter`.
3.  Implémentez `can_handle`, `extract_metadata` et `get_content`.
4.  Enregistrez votre classe dans `adapters/__init__.py`.

Exemple :
```python
class MonSiteAdapter(BaseAdapter):
    def can_handle(self):
        return "monsite.com" in self.soup.text
```
Une documentation détaillée des adapters est disponible dans le dossier `adapters/`.

### Test des adapters
```bash
python3 html_to_mp3.py --test
```
Des fichiers txt seront générés dans le dossier `Article-Test/` avec le contenu que le script enverrait au TTS.

## 🔮 Améliorations Futures (Roadmap)


- [ ] **Support Multi-langues** : Détection automatique de la langue (`<html lang="en">`) pour basculer sur une voix anglaise/espagnole.
- [ ] **Fichier de Config Externe** : Sortir les variables `INPUT_DIR` etc. dans un fichier `.env` ou `config.yaml`.
- [ ] **Parallélisation** : Traiter plusieurs articles simultanément pour accélérer le batch processing.
- [ ] **Support PDF/Epub** : Étendre le support au-delà du HTML.
- [ ] **Docker** : Conteneuriser l'application pour un déploiement plus simple.

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une Issue ou une Pull Request.

## 📄 Licence

Ce projet est sous licence MIT.