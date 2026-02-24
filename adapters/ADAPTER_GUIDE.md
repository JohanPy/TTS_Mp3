# Guide de Création d'Adapters TTS

> Ce guide fournit toutes les informations nécessaires pour créer un nouvel adapter compatible avec `html_to_mp3.py` et le système de podcast FolderCast.

## Architecture

```
adapters/
├── __init__.py      # Factory - enregistre les adapters
├── base.py          # Classe de base abstraite
├── generic.py       # Fallback par défaut
├── mediapart.py     # Exemple d'adapter spécifique
├── ballast.py       # Exemple récent
└── [votre_adapter].py
```

---

## Structure d'un Adapter

```python
from .base import BaseAdapter
import re
import os

class MonSiteAdapter(BaseAdapter):
    """Adapter pour MonSite.com"""
    
    def can_handle(self):
        """Retourne True si cet adapter peut traiter ce HTML"""
        # Implémenter la détection
        pass
    
    def extract_metadata(self):
        """Retourne un dict avec les métadonnées de l'article"""
        # Implémenter l'extraction
        pass
    
    def get_content(self):
        """Retourne le texte de l'article nettoyé pour TTS"""
        # Implémenter l'extraction du contenu
        pass
```

---

## Méthode `can_handle()`

**But** : Identifier si ce HTML provient de votre source.

### Stratégies de détection (par ordre de fiabilité)

```python
def can_handle(self):
    # 1. META og:site_name (le plus fiable)
    og_site = self.soup.find("meta", property="og:site_name")
    if og_site and "MonSite" in og_site.get("content", ""):
        return True
    
    # 2. URL dans og:url
    og_url = self.soup.find("meta", property="og:url")
    if og_url and "monsite.com" in og_url.get("content", ""):
        return True
    
    # 3. Nom de fichier (fallback)
    if "MonSite" in self.filename:
        return True
    
    return False
```

> ⚠️ **PIÈGE** : Évitez les sélecteurs CSS trop génériques comme `.entry-content` qui peuvent matcher plusieurs sources.

---

## Méthode `extract_metadata()`

**But** : Extraire les métadonnées pour les tags ID3 du MP3.

### Champs requis pour FolderCast

| Champ | Tag ID3 | Usage FolderCast | Obligatoire |
|-------|---------|------------------|-------------|
| `title` | TIT2 | Titre épisode | ✅ Oui |
| `author` | TPE1 | `<itunes:author>` | ⚠️ Important |
| `media` | TALB | Album (non utilisé RSS) | ⚠️ Important |
| `url` | COMM | `<link>` dans RSS | Recommandé |
| `description` | USLT | `<description>` + `<itunes:summary>` | Recommandé |
| `date` | TDRC | Date publication | Recommandé |
| `image_url` | APIC | Artwork | Optionnel |

### Template complet

```python
def extract_metadata(self):
    meta = super().extract_metadata()  # Valeurs par défaut
    soup = self.soup
    
    # === TITLE ===
    # Priorité: og:title > <title> > <h1> > filename
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
        # Nettoyer suffixes comme " - MonSite"
        title = re.sub(r'\s*[-–|]\s*MonSite.*$', '', title, flags=re.IGNORECASE)
        meta["title"] = title
    
    if not meta["title"]:
        if soup.title and soup.title.string:
            meta["title"] = soup.title.string.strip()
    
    if not meta["title"]:
        h1 = soup.find("h1")
        if h1:
            meta["title"] = h1.get_text(separator=" ", strip=True)
    
    if not meta["title"]:
        meta["title"] = os.path.splitext(self.filename)[0]
    
    # === AUTHOR ===
    # Sources possibles (ordre de priorité):
    # 1. <meta name="author">
    # 2. <meta property="article:author">
    # 3. JSON-LD schema
    # 4. Sélecteurs CSS spécifiques
    
    author = None
    
    # Meta name="author"
    meta_author = soup.find("meta", attrs={"name": "author"})
    if meta_author and meta_author.get("content"):
        author = meta_author["content"].strip()
    
    # Meta property="article:author"
    if not author:
        meta_author = soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()
    
    # JSON-LD (sites modernes)
    if not author:
        import json
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if '@graph' in data:
                        for item in data['@graph']:
                            if item.get('@type') == 'Article' and 'author' in item:
                                author_data = item['author']
                                if isinstance(author_data, dict):
                                    author = author_data.get('name', '')
                                elif isinstance(author_data, str):
                                    author = author_data
                                break
            except:
                pass
    
    # Sélecteur CSS spécifique au site
    if not author:
        author_el = soup.select_one(".author-name, .post-author, .byline")
        if author_el:
            author = author_el.get_text(strip=True)
    
    if author:
        meta["author"] = author
    
    # === MEDIA (nom de la source) ===
    meta["media"] = "MonSite"  # Toujours hardcoder
    
    # === URL ===
    meta_url = soup.find("meta", property="og:url") or soup.find("link", rel="canonical")
    if meta_url:
        meta["url"] = meta_url.get("href", meta_url.get("content", "")).strip()
    
    # === DATE ===
    # ⚠️ Le script html_to_mp3 extrait uniquement l'année (YYYY)
    meta_date = soup.find("meta", property="article:published_time")
    if meta_date and meta_date.get("content"):
        meta["date"] = meta_date["content"].strip()
    
    # === DESCRIPTION ===
    meta_desc = soup.find("meta", property="og:description")
    if meta_desc and meta_desc.get("content"):
        og_desc = meta_desc["content"].strip()
        if len(og_desc) < 300:
            # Générer une description plus longue
            long_desc = self._generate_long_description()
            meta["description"] = long_desc if long_desc else og_desc
        else:
            meta["description"] = og_desc
    else:
        meta["description"] = self._generate_long_description()
    
    # === IMAGE ===
    meta_image = soup.find("meta", property="og:image")
    if meta_image and meta_image.get("content"):
        meta["image_url"] = meta_image["content"].strip()
    
    return meta
```

---

## Méthode `get_content()`

**But** : Extraire le texte de l'article, nettoyé pour la synthèse vocale.

### Principes essentiels

1. **Cibler le conteneur principal** de l'article
2. **Supprimer les éléments parasites** (nav, ads, auteur, partage...)
3. **Éviter les doublons** (chapeau répété dans le corps)
4. **Ajouter une ponctuation** pour les pauses TTS

### Template complet

```python
def get_content(self):
    soup = self.soup
    
    # 1. TROUVER LE CONTENEUR PRINCIPAL
    # Adapter ces sélecteurs à votre site
    container = soup.select_one("article, .entry-content, .post-content, main")
    
    if not container:
        return ""
    
    # 2. SUPPRIMER LES ÉLÉMENTS PARASITES
    # Scripts et styles
    for element in container(["script", "style", "noscript", "iframe"]):
        element.extract()
    
    # Navigation et UI
    for element in container(["nav", "header", "footer", "aside", "button", "form"]):
        element.extract()
    
    # Médias (sauf si vous voulez les décrire)
    for element in container(["figure", "img", "video", "audio"]):
        element.extract()
    
    # Sélecteurs spécifiques au site
    junk_selectors = [
        # Partage social
        ".share", ".social", ".sharing", "[class*='share']",
        # Auteur/bio
        ".author", ".author-box", ".post-author", ".byline",
        # Tags et catégories
        ".tags", ".post-tags", ".categories",
        # Commentaires
        ".comments", "#comments",
        # Articles liés
        ".related", ".related-posts",
        # Navigation inter-articles
        ".navigation", ".nav-links", ".post-navigation",
        # Métadonnées
        ".meta", ".post-meta", ".entry-meta",
        # Publicités
        ".ad", ".ads", ".advertisement",
        # Newsletter/abonnement
        ".newsletter", ".subscribe",
    ]
    for selector in junk_selectors:
        for element in container.select(selector):
            element.extract()
    
    # 3. PRÉ-TRAITEMENT: Déballer les éléments imbriqués
    # Évite de manquer du contenu dans des div wrapper
    while True:
        wrapper = container.find(lambda t: t.name in ['div', 'span'] and 
                                 t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
        if not wrapper:
            break
        wrapper.unwrap()
    
    # 4. EXTRAIRE LE TEXTE
    text_parts = []
    seen_texts = set()  # Pour éviter les doublons
    
    for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'li']):
        # Ignorer les éléments imbriqués (déjà traités par parent)
        if tag.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote']):
            continue
        
        text = tag.get_text(separator=" ", strip=True)
        
        # Filtrer textes trop courts (métadonnées résiduelles)
        if not text or len(text) < 15:
            continue
        
        # Éviter les doublons
        text_hash = text[:50]
        if text_hash in seen_texts:
            continue
        seen_texts.add(text_hash)
        
        # 5. AJOUTER PONCTUATION POUR TTS
        if not text[-1] in '.!?':
            text = text + '.'
        
        # Formatage selon type d'élément
        if tag.name.startswith('h'):
            text_parts.append(f"{text}...")  # Pause après titre
        elif tag.name == 'blockquote':
            text_parts.append(f"Citation: {text}")
        elif tag.name == 'li':
            text_parts.append(f"{text},")  # Pause légère entre items
        else:
            text_parts.append(f"{text}.")
    
    # 6. NETTOYAGE FINAL
    result = " ".join(text_parts)
    result = re.sub(r'\.{5,}', '...', result)  # Trop de points
    result = re.sub(r'\.{2}', '.', result)      # Points doubles
    result = re.sub(r',\.', '.', result)        # Virgule-point
    
    return result
```

### Le Mode "Reader" (Trafilatura)

La classe `BaseAdapter` fournit désormais une méthode `self._reader_extract()` qui utilise la bibliothèque d'extraction de contenu Trafilatura. 

**Pourquoi l'utiliser ?** Ce mode est extrêmement robuste et intègre des filtres spécifiques au TTS que vous n'aurez pas à recoder :
- Nettoyage automatique des notes de bas de page académiques (ex: `[1]`, `[ 24 ]`).
- Suppression des résidus de métadonnées (mots isolés comme "Sources :", "1.", etc).
- Forçage de **vraies pauses respiratoires** (` ... `) entre chaque paragraphe extrait pour Edge-TTS.
- Formatage garantissant un texte brut pur, prêt à être dicté.

C'est particulièrement utile si le site a un markup imprévisible ou si l'extraction par défaut de BeautifulSoup demande trop d'efforts. Vous pouvez l'utiliser de deux façons :

1. **Extraction de tout le document (fallback)**
```python
def get_content(self):
    # Logique spécifique...
    if not article:
        # Fallback automatique sur l'extracteur Trafilatura
        return self._reader_extract()
```

2. **Extraction sur un conteneur spécifique**
```python
def get_content(self):
    article = self.soup.select_one('.main-article-content')
    if article:
        # Laisse Trafilatura nettoyer et parser ce conteneur précis
        return self._reader_extract(str(article))
    return ""
```

---

## Enregistrement de l'Adapter

### Dans `adapters/__init__.py`

```python
# Imports
from .monsite import MonSiteAdapter

def get_adapter(soup, filename):
    adapters = [
        # Adapters spécifiques d'abord
        MediapartAdapter,
        BallastAdapter,
        MonSiteAdapter,      # <- Ajouter ici
        # ...
        UCLAdapter,          # Adapters génériques en dernier
        GenericAdapter,      # Toujours en dernier
    ]
```

> ⚠️ **PIÈGE CRITIQUE** : L'ordre compte ! Les adapters sont testés dans l'ordre.
> Si un adapter avec des sélecteurs génériques est placé avant le vôtre, il peut "voler" vos articles.

---

## Tests et Validation

### Script de test rapide

```python
from bs4 import BeautifulSoup
from adapters import get_adapter
import os

filepath = "chemin/vers/article.html"
with open(filepath, 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

adapter = get_adapter(soup, os.path.basename(filepath))

# Vérifier adapter sélectionné
print(f"Adapter: {type(adapter).__name__}")

# Vérifier métadonnées
meta = adapter.extract_metadata()
for key, value in meta.items():
    status = "✅" if value and value not in ["Unknown Author", "Unknown Media"] else "⚠️"
    print(f"{status} {key}: {value[:50] if value else 'ABSENT'}...")

# Vérifier contenu
content = adapter.get_content()
print(f"\nContenu: {len(content)} caractères")
print(f"Début: {content[:200]}...")
print(f"Fin: ...{content[-200:]}")
```

### Checklist de validation

- [ ] `can_handle()` retourne `True` uniquement pour les bons articles
- [ ] `title` extrait sans suffixe du site (ex: " - MonSite")
- [ ] `author` ≠ "Unknown Author" (chercher dans meta, JSON-LD, HTML)
- [ ] `media` est hardcodé au nom du site
- [ ] `url` commence par `http`
- [ ] `description` a > 50 caractères
- [ ] `date` est présent (format quelconque, l'année sera extraite)
- [ ] `image_url` pointe vers une image valide
- [ ] `get_content()` ne contient pas de métadonnées au début
- [ ] `get_content()` ne contient pas d'URLs ou de code
- [ ] Pas de texte dupliqué

### Vérification du MP3 généré

```bash
# Générer le MP3
python3 html_to_mp3.py

# Vérifier les tags ID3
ffprobe -v quiet -print_format json -show_format "fichier.mp3" | grep -E '"(title|artist|album|date|comment)"'
```

---

## Pièges Courants et Solutions

### 1. Auteur "Unknown Author"

**Cause** : Le meta tag `property="article:author"` n'existe pas.

**Solution** : Chercher dans plusieurs sources :
```python
# 1. <meta name="author">
# 2. <meta property="article:author">
# 3. JSON-LD schema
# 4. Sélecteur CSS spécifique
```

### 2. Contenu dupliqué

**Cause** : Le chapeau (intro) est répété dans le corps de l'article.

**Solution** : Tracker les textes déjà vus :
```python
seen_texts = set()
text_hash = text[:50]
if text_hash in seen_texts:
    continue
seen_texts.add(text_hash)
```

### 3. Métadonnées dans le contenu

**Cause** : Date, auteur ou tags non filtrés au début.

**Solution** : Filtrer les paragraphes courts au début :
```python
for p in container.find_all('p')[:5]:
    text = p.get_text(strip=True)
    if len(text) < 30:
        p.extract()
```

### 4. Adapter non sélectionné

**Cause** : Un autre adapter avec des sélecteurs génériques le capture avant.

**Solution** : Réorganiser l'ordre dans `__init__.py` :
```python
adapters = [
    MonSiteAdapter,  # Spécifique - tester avant
    UCLAdapter,      # Générique - tester après
]
```

### 5. Date au format ISO rejettée par podcast

**Cause** : Le tag TDRC contenait `2024-03-14T15:32` au lieu de `2024`.

**Solution** : Déjà corrigé dans `html_to_mp3.py` - seule l'année est extraite.

---

## Exemple Complet : BallastAdapter

```python
from .base import BaseAdapter
import re
import os

class BallastAdapter(BaseAdapter):
    """Adapter for BALLAST articles (revue-ballast.fr)"""
    
    def can_handle(self):
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "BALLAST" in og_site.get("content", ""):
            return True
        
        og_url = self.soup.find("meta", property="og:url")
        if og_url and "revue-ballast.fr" in og_url.get("content", ""):
            return True
            
        if "BALLAST" in self.filename:
            return True
            
        return False

    def extract_metadata(self):
        meta = super().extract_metadata()
        soup = self.soup

        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r'\s*[-–]\s*BALLAST\s*$', '', title, flags=re.IGNORECASE)
            meta["title"] = title

        # Author
        author_el = soup.select_one(".author-name, .entry-author")
        if author_el:
            meta["author"] = author_el.get_text(strip=True)

        # Media (hardcoded)
        meta["media"] = "BALLAST"
        
        # URL
        meta_url = soup.find("meta", property="og:url")
        if meta_url:
            meta["url"] = meta_url.get("content", "").strip()

        # Date
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date:
            meta["date"] = meta_date.get("content", "").strip()

        # Description
        meta_desc = soup.find("meta", property="og:description")
        if meta_desc:
            meta["description"] = meta_desc.get("content", "").strip()

        # Image
        meta_image = soup.find("meta", property="og:image")
        if meta_image:
            meta["image_url"] = meta_image.get("content", "").strip()

        return meta
        
    def get_content(self):
        article = self.soup.find('article')
        if not article:
            return ""

        # Remove junk
        for el in article(["script", "style", "nav", "figure", "img"]):
            el.extract()
        
        for selector in [".share", ".social", ".author", ".tags", ".related"]:
            for el in article.select(selector):
                el.extract()

        # Extract text
        text_parts = []
        seen = set()
        
        for tag in article.find_all(['h2', 'h3', 'p', 'blockquote', 'li']):
            if tag.find(['p', 'h2', 'h3']):
                continue
            
            text = tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 15:
                continue
            
            if text[:50] in seen:
                continue
            seen.add(text[:50])
            
            if not text[-1] in '.!?':
                text += '.'
            
            text_parts.append(text)

        return " ".join(text_parts)
```

---

## Ressources

- **BaseAdapter** : `adapters/base.py`
- **GenericAdapter** (fallback) : `adapters/generic.py`
- **Exemples existants** : `mediapart.py`, `ballast.py`, `multitudes.py`
- **Script principal** : `html_to_mp3.py`
- **Spec FolderCast** : Tags ID3 requis dans le README du projet podcast
