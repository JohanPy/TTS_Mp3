#!/usr/bin/env python3
import os
import shutil
import asyncio
import edge_tts
import feedparser
import logging
import re
import json
import glob
import argparse
from datetime import date
from bs4 import BeautifulSoup, Tag, NavigableString
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, COMM, USLT, TDRC, APIC
import urllib.request
import urllib.error
from summarizer import get_summarizer


# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
INPUT_DIR = os.path.expanduser("~/Téléchargements/versaudio")
OUTPUT_DIR = os.path.expanduser("~/Documents/Perso/Podcasts/ArtcleTTS")
ARCHIVE_DIR = os.path.expanduser("~/Téléchargements/versaudio/Archived")
VOICE = "fr-FR-VivienneNeural"
CONCURRENCY_LIMIT = 3  # Safe parallel requests limit to avoid Microsoft ban/throttle

# RSS configuration
PROCESSED_URLS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_urls.json")
SEEN_FEEDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_feeds.json")
GROUPED_SUMMARIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grouped_summaries.json")
RSS_FEEDS = [
    "https://www.acrimed.org/spip.php?page=backend",
    "https://www.unioncommunistelibertaire.org/spip.php?page=backend&",
    # Exemple de flux avec résumé IA et regroupement par jour :
    # {
    #     "url": "http://www.developpez.com/index/rss",
    #     "voice": "fr-FR-VivienneNeural",
    #     "summarize": True,       # Active le résumé IA (gemini_config.json)
    #     "group_window_hours": 24 # Regroupe tous les résumés du jour en 1 MP3
    # }
    {
        "url": "http://www.developpez.com/index/rss",
        "voice": "fr-FR-VivienneNeural",
        "summarize": True,
        "group_window_hours": 24
    }
]

# --- HELPER FUNCTIONS ---

def clean_filename(text):
    """Cleans a string to be used as a filename."""
    if not text: return "Audio_Article"
    # Keep alphanumeric, spaces, hyphens and underscores
    safe_text = "".join([c for c in text if c.isalnum() or c in (' ', '-', '_')]).strip()
    safe_text = re.sub(r'[\s_-]+', '_', safe_text)
    return safe_text

def limit_filename(filename, max_length=120):
    """Truncates a filename to not exceed max_length while preserving its extension."""
    if len(filename) <= max_length:
        return filename
    name, ext = os.path.splitext(filename)
    ext_len = len(ext)
    max_name_len = max_length - ext_len
    if max_name_len <= 0:
        return filename[:max_length]
    return name[:max_name_len] + ext

def is_hidden(element):
    """Checks if an element is likely hidden via inline style."""
    if isinstance(element, Tag):
        style = element.get('style', '')
        if style and 'display: none' in style.lower():
            return True
        if element.has_attr('hidden'):
            return True
    return False


# ... (imports)
from adapters import get_adapter

# ... (logging setup, config, clean_filename, is_hidden remain)

# Helper functions extract_metadata, download_image, generate_text_content 
# will be removed/replaced or moved to adapters if not already done.
# download_image is general, can stay or move to utils. Ideally stay for now.

def download_image(url):
    """Downloads image to memory returns bytes or None."""
    if not url: return None
    try:
        # Basic validation
        if not url.startswith("http"): return None
        
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read()
    except Exception as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None

# --- INCLUSIVE WRITING HANDLER ---

# Homophones: mots qui s'écrivent différemment au masculin/féminin mais sonnent pareil
# Le masculin suffit à l'oral
HOMOPHONES_RACINES = {
    # Terminaisons en -é (ami/amie, salarié/salariée)
    "ami", "amie", "salari", "déput", "charg", "employ", "invit", "concern",
    "abonn", "engag", "fatigu", "motiv", "détermin", "passionn", "diplôm",
    "qualifi", "expériment", "intéress", "touch", "affect", "impliqu",
    "préoccup", "inform", "consult", "réuni", "assembl", "group", "rassembl",
    "marqu", "salu", "accompagn", "guid", "orient", "form", "sensibilis",
    "mobilis", "organis", "structur", "coordonn", "délég", "mandaté",
    "autoris", "habilit", "certifi", "agré", "reconnu", "validé",
    # Autres terminaisons muettes
    "auteur", "lecteur", "acteur", "directeur", "professeur"
}

def _sonnent_pareil(masculin: str, feminin: str) -> bool:
    """
    Détermine si le masculin et le féminin sonnent pareil à l'oral.
    Utilise des règles phonétiques françaises + liste d'exceptions.
    """
    # Normaliser
    masc = masculin.lower().strip()
    fem = feminin.lower().strip()
    
    # Identiques
    if masc == fem:
        return True
    
    # Retirer le 's' final pour comparer les racines
    masc_base = masc.rstrip('s')
    fem_base = fem.rstrip('s')
    
    # Vérifier dans les homophones connus
    for racine in HOMOPHONES_RACINES:
        if masc_base.endswith(racine) or masc_base == racine:
            return True
    
    # Règle: si le féminin = masculin + "e" ou "es"
    # et que le masculin finit par une voyelle accentuée, ils sonnent pareil
    if fem_base.startswith(masc_base):
        suffixe = fem_base[len(masc_base):]
        if suffixe in ['e', 'es', '']:
            # Dernière lettre du masculin (sans 's')
            if masc_base and masc_base[-1] in 'éèêëiîïuûüoôaàâ':
                return True
    
    # Règle: terminaisons en -eur/-euse, -teur/-trice -> différent
    if masc.endswith('eur') and fem.endswith('euse'):
        return False
    if masc.endswith('teur') and fem.endswith('trice'):
        return False
    
    # Règle: terminaisons en -if/-ive -> différent
    if masc.endswith('if') and fem.endswith('ive'):
        return False
    
    # Règle: terminaisons en -eux/-euse -> différent
    if masc.endswith('eux') and fem.endswith('euse'):
        return False
    
    # Par défaut: différent (on dédouble)
    return False


def _generer_forme_parlee(masculin: str, feminin: str) -> str:
    """
    Génère la forme parlée d'un mot en écriture inclusive.
    Retourne soit le masculin seul (si homophone), soit "féminin et masculin".
    """
    if _sonnent_pareil(masculin, feminin):
        return masculin
    else:
        # Ordre: féminin d'abord (convention courante à l'oral)
        return f"{feminin} et {masculin}"


def process_inclusive_writing(text: str) -> str:
    """
    Convertit l'écriture inclusive en forme parlée pour TTS.
    
    Gère les patterns:
    - client·e·s → "clientes et clients" ou "clients" si homophone
    - client·es → "clientes et clients"
    - chacun·e → "chacune et chacun"
    - celleux → "celles et ceux"
    - iel/iels → "elle ou il" / "elles ou ils"
    
    Nettoie aussi les points médians orphelins.
    """
    result = text
    
    # 1. Remplacer les néologismes inclusifs courants
    neologismes = {
        r'\bcelleux\b': 'celles et ceux',
        r'\bceuxlles\b': 'ceux et celles',
        r'\biels\b': 'elles et ils',
        r'\biel\b': 'elle ou il',
        r'\bae\b': 'a ou e',  # rare mais existe
    }
    for pattern, replacement in neologismes.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # 2. Pattern complet: mot·e·s ou mot·es·s (pluriel avec double suffixe)
    # Ex: "client·e·s", "citoyen·ne·s", "lecteur·rice·s"
    def replace_full_pattern(match):
        base = match.group(1)      # "client"
        suffix1 = match.group(2)   # "e" ou "ne" ou "rice"
        suffix2 = match.group(3)   # "s" (optionnel)
        
        # Construire masculin et féminin
        if suffix2:
            masculin = base + suffix2  # "clients"
            feminin = base + suffix1 + suffix2  # "clientes"
        else:
            masculin = base  # "client"
            feminin = base + suffix1  # "cliente"
        
        return _generer_forme_parlee(masculin, feminin)
    
    # Pattern: mot·suffixe·s ou mot·suffixe (avec point médian ou tiret ou parenthèses)
    # Séparateurs: · (point médian), - (tiret), . (point), ( )
    separateurs = r'[·\-\.\(\)]'
    
    # Pattern pluriel: base·suffix·s
    pattern_pluriel = rf'(\w+){separateurs}(\w+){separateurs}([s])\b'
    result = re.sub(pattern_pluriel, replace_full_pattern, result)
    
    # Pattern singulier/court: base·suffix (ex: "chacun·e", "client·es")
    def replace_short_pattern(match):
        base = match.group(1)
        suffix = match.group(2)
        
        # Détecter si c'est un pluriel court (suffix = "es" ou "s")
        if suffix.endswith('s'):
            masculin = base + 's'
            feminin = base + suffix
        else:
            masculin = base
            feminin = base + suffix
        
        return _generer_forme_parlee(masculin, feminin)
    
    pattern_court = rf'(\w+){separateurs}([eé]s?|ne|rice|euse|ive|se)\b'
    result = re.sub(pattern_court, replace_short_pattern, result, flags=re.IGNORECASE)
    
    # 3. Nettoyer les points médians orphelins
    result = re.sub(r'·', ' ', result)
    
    # 4. Nettoyer les espaces multiples
    result = re.sub(r'\s+', ' ', result)
    
    return result


def convertir_chiffres_romains(texte):
    """
    Convertit les chiffres romains (I, V, X) en chiffres arabes dans des contextes spécifiques
    (siècles, arrondissements, noms de souverains) pour faciliter la lecture par le TTS.
    """
    # Dictionnaire de base pour la conversion (limité aux I, V, X pour limiter les faux positifs)
    def roman_to_int(s):
        rom_val = {'I': 1, 'V': 5, 'X': 10}
        int_val = 0
        s = s.upper()
        for i in range(len(s)):
            # Ignore les caractères non romains qui auraient pu se glisser
            if s[i] not in rom_val:
                continue

            if i > 0 and rom_val[s[i]] > rom_val[s[i - 1]]:
                int_val += rom_val[s[i]] - 2 * rom_val[s[i - 1]]
            else:
                int_val += rom_val[s[i]]
        return int_val

    # 1. Règle pour les Siècles (ex: XIXe siècle, XXème siècle)
    def replace_siecle(match):
        roman = match.group(1)
        mot_siecle = match.group(3)
        val = roman_to_int(roman)

        # Gestion du "premier"
        if val == 1:
            return f"1er {mot_siecle}"
        return f"{val}ème {mot_siecle}"

    texte = re.sub(r'\b([IVX]+)(e|ème|eme|er)?\s+(siècle|siecles|siècles)\b',
                   replace_siecle, texte, flags=re.IGNORECASE)

    # 2. Règle pour les Arrondissements (ex: XVe arrondissement, Paris XX)
    def replace_arrond(match):
        roman = match.group(1)
        mot_arrond = match.group(3)
        val = roman_to_int(roman)

        if val == 1:
            return f"1er {mot_arrond}"
        return f"{val}ème {mot_arrond}"

    texte = re.sub(r'\b([IVX]+)(e|ème|eme|er)?\s+(arrondissement|arrondissements)\b',
                   replace_arrond, texte, flags=re.IGNORECASE)

    # Cas spécifique "Paris XV" ou "Lyon III"
    def replace_ville_arrond(match):
        ville = match.group(1)
        roman = match.group(2)
        val = roman_to_int(roman)
        return f"{ville} {val}"

    texte = re.sub(r'\b(Paris|Lyon|Marseille)\s+([IVX]+)(e|ème)?\b',
                   replace_ville_arrond, texte)

    # 3. Règle pour les Rois / Papes (ex: Louis XIV, Jean-Paul II)
    def replace_souverain(match):
        nom = match.group(1)
        roman = match.group(2)
        val = roman_to_int(roman)

        if val == 1:
            return f"{nom} 1er"
        return f"{nom} {val}"

    # Liste fermée de noms courants pour éviter tout faux positif
    noms_rois = r"(Louis|Charles|Henri|Jean|Philippe|François|Guillaume|Benoît|Paul|Pie|Jean-Paul|Napoléon|Léopold)"
    texte = re.sub(r'\b' + noms_rois + r'\s+([IVX]+)(er|e)?\b',
                   replace_souverain, texte)

    return texte


def clean_text_for_tts(text: str) -> str:
    """
    Nettoie le texte pour la synthèse vocale en supprimant:
    - URLs
    - Numéros de notes de bas de page [1], [2], etc.
    - Références bibliographiques
    - DOI et identifiants
    - Mentions de licence
    - Métadonnées résiduelles
    """
    result = text
    
    # 1. Supprimer les URLs (http://, https://, www.)
    result = re.sub(r'https?://[^\s\)]+', '', result)
    result = re.sub(r'www\.[^\s\)]+', '', result)
    
    # 2. Supprimer les DOI
    result = re.sub(r'doi\.org/[^\s\)]+', '', result)
    result = re.sub(r'https?://doi\.org/[^\s]+', '', result)
    result = re.sub(r'\bdoi\s*:\s*[^\s]+', '', result, flags=re.IGNORECASE)
    
    # 3. Supprimer les numéros de notes entre crochets [1], [2], etc.
    result = re.sub(r'\[\d+\]', '', result)
    
    # 4. Supprimer les appels de notes (numéros seuls en exposant ou après un mot)
    # Pattern original trop agressif: "texte1" ou "texte 1" en fin de phrase avant ponctuation
    # On limite aux chiffres collés directement à un mot (sans espace) avant une ponctuation forte
    # Ex: "mot1." ou "mot12," mais pas "le 20 janvier"
    result = re.sub(r'(?<=[a-zA-Zà-ÿ])\d{1,2}(?=[\.,;:!?])', '', result)
    # 5. Supprimer les références bibliographiques typiques
    # Pattern: "Auteur, A. (YYYY). Titre..."
    result = re.sub(r'\b[A-Z][a-zà-ÿ]+,\s*[A-Z]\.\s*(?:&\s*[A-Z][a-zà-ÿ]+,\s*[A-Z]\.\s*)*\(\d{4}\)\.\s*[^\.]+\.[^\.]*(?:Presses|Éditions|University|Press|Gallimard|Seuil)[^\.]*\.', '', result)
    
    # 6. Supprimer les mentions de licence Creative Commons
    result = re.sub(r'(CC\s+BY[-\w]*|Creative\s+Commons|Tous\s+droits\s+réservés)[^\.]*\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Le texte seul est utilisable sous licence[^\.]+\.', '', result, flags=re.IGNORECASE)
    
    # 7. Supprimer les références électroniques
    result = re.sub(r'Référence électronique[^\.]*\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'\[En ligne\][^,]*,', '', result, flags=re.IGNORECASE)
    result = re.sub(r'mis en ligne le[^,\.]+[,\.]', '', result, flags=re.IGNORECASE)
    result = re.sub(r'consulté le \d+[^\.]+\.', '', result, flags=re.IGNORECASE)
    result = re.sub(r'URL\s*:', '', result, flags=re.IGNORECASE)
    
    # 8. Supprimer les mentions "Paru dans..." "Articles du même auteur"
    result = re.sub(r'Paru dans[^\.]+\.', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Articles? du même auteur\.?', '', result, flags=re.IGNORECASE)

    # 9. Supprimer les sections interactives et boilerplate des sites d'actu
    #    (développez.com, presse générale…)
    # Couper au premier marqueur de section parasite
    noise_cutoff_patterns = [
        r'"Et vous\s*\?"',          # developpez.com forum
        r'"Et vous aussi"',
        r'"Voir aussi"',            # liens connexes
        r'Voir aussi\s*:',
        r'Vous avez lu gratuitement',  # paywall/abonnement
        r'Soutenez le club',
        r'en souscrivant un abonnement',
        r'Donnez votre avis',
        r'Réagissez à cet article',
        r'Laisser un commentaire',
    ]
    for pattern in noise_cutoff_patterns:
        m = re.search(pattern, result, flags=re.IGNORECASE)
        if m:
            result = result[:m.start()]
    
    # 9. Supprimer les notes numérotées en début de phrase
    # Pattern: "1 Texte de la note..." "2 Autre note..."
    # On supprime les lignes qui commencent par un numéro suivi d'un espace et peu de contexte
    result = re.sub(r'\.\s+\d{1,2}\s+[A-Z][^\.]{10,150}(?:\.\.\.|\.\s)', '. ', result)
    
    # 10. Nettoyer les doubles espaces et ponctuation orpheline
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'\s+([.,;:!?])', r'\1', result)
    result = re.sub(r'([.,;:!?])\s*\1+', r'\1', result)  # Ponctuation doublée
    result = re.sub(r'\(\s*\)', '', result)  # Parenthèses vides
    result = re.sub(r'\[\s*\]', '', result)  # Crochets vides
    
    # 11. Nettoyer les espaces avant ponctuation
    result = re.sub(r'\s+\.', '.', result)
    result = re.sub(r'\s+,', ',', result)
    
    return result.strip()


# Old extract_metadata and generate_text_content Removed

def process_html_file_test(filepath, test_output_dir):
    """Process HTML file in test mode: extract and save text content only."""
    filename = os.path.basename(filepath)
    logger.info(f"[TEST MODE] Processing: {filename}")

    try:
        # Read file
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f:
                soup = BeautifulSoup(f, 'html.parser')

        # Get Adapter
        adapter = get_adapter(soup, filename)
        
        # Metadata
        meta = adapter.extract_metadata()
        title = meta['title']
        author = meta['author']
        media = meta['media']
        
        logger.info(f"[TEST MODE] Metadata - Title: {title}, Author: {author}, Media: {media}")

        safe_title = clean_filename(title)
        if len(safe_title) < 3:
             safe_title = clean_filename(os.path.splitext(filename)[0])
        
        # Format filename for text output
        safe_media = clean_filename(media)
        
        if safe_media and safe_media != "Unknown_Media" and safe_media != "Europresse": 
            txt_name = f"{safe_title} - {safe_media}.txt"
        else:
            txt_name = f"{safe_title}.txt"
        
        # Limit length to 120 characters to avoid sync issues (e.g. with Nextcloud)
        txt_name = limit_filename(txt_name, 120)

        txt_path = os.path.join(test_output_dir, txt_name)

        # Generate content
        text_body = adapter.get_content()
            
        if len(text_body) < 50:
            logger.warning(f"[TEST MODE] Skipping {filename}: content too short or empty.")
            return 

        # Construct intro
        text_intro = (
            f"Article de {media}... "
            f"{title}... "
            f"Par {author}... "
        )

        full_content = f"{text_intro}{text_body}"
        full_content = re.sub(r'\s+', ' ', full_content).strip()
        full_content = process_inclusive_writing(full_content)  # Handle écriture inclusive
        full_content = convertir_chiffres_romains(full_content)  # Convert Roman numerals
        full_content = clean_text_for_tts(full_content)  # Remove URLs, notes, references

        # Save text content to file
        with open(txt_path, 'w', encoding='utf-8') as f:
            # Write metadata header
            f.write("=" * 80 + "\n")
            f.write(f"TITRE: {title}\n")
            f.write(f"AUTEUR: {author}\n")
            f.write(f"MÉDIA: {media}\n")
            if meta['url']:
                f.write(f"URL: {meta['url']}\n")
            if meta['date']:
                f.write(f"DATE: {meta['date']}\n")
            f.write("=" * 80 + "\n\n")
            
            # Write content that would be sent to TTS
            f.write("CONTENU POUR EDGE-TTS:\n")
            f.write("-" * 80 + "\n")
            f.write(full_content)
            f.write("\n" + "-" * 80 + "\n")
            
            # Write statistics
            f.write(f"\nSTATISTIQUES:\n")
            f.write(f"  - Nombre de caractères: {len(full_content)}\n")
            f.write(f"  - Nombre de mots (approximatif): {len(full_content.split())}\n")
        
        logger.info(f"[TEST MODE] Text saved to: {txt_path}")
        logger.info(f"[TEST MODE] Content length: {len(full_content)} characters")

    except Exception as e:
        logger.error(f"[TEST MODE] Error processing {filename}: {e}", exc_info=True)


def load_processed_urls():
    """Loads the set of already processed RSS article URLs."""
    if os.path.exists(PROCESSED_URLS_FILE):
        try:
            with open(PROCESSED_URLS_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load processed URLs: {e}")
    return set()


def save_processed_url(url):
    """Saves a processed RSS article URL to the history file."""
    save_processed_urls([url])


def save_processed_urls(new_urls):
    """Saves multiple processed RSS article URLs to the history file at once."""
    urls = load_processed_urls()
    urls.update(new_urls)
    try:
        temp_file = PROCESSED_URLS_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(list(urls), f, indent=4)
        os.replace(temp_file, PROCESSED_URLS_FILE)
    except Exception as e:
        logger.error(f"Failed to save processed URLs: {e}")


def load_seen_feeds():
    """Loads the set of already initialized RSS feed URLs."""
    if os.path.exists(SEEN_FEEDS_FILE):
        try:
            with open(SEEN_FEEDS_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load seen feeds: {e}")
    return set()


def save_seen_feed(feed_url):
    """Saves an initialized RSS feed URL to the history file."""
    feeds = load_seen_feeds()
    feeds.add(feed_url)
    try:
        temp_file = SEEN_FEEDS_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(list(feeds), f, indent=4)
        os.replace(temp_file, SEEN_FEEDS_FILE)
    except Exception as e:
        logger.error(f"Failed to save seen feeds: {e}")


async def generate_audio_from_content(meta, text_body, mp3_path, voice=VOICE):
    """
    Generates an MP3 file from clean text and metadata, and sets ID3 tags.
    Returns True if generation was successful, False otherwise.
    """
    title = meta.get('title') or 'Unknown Title'
    author = meta.get('author') or 'Unknown Author'
    media = meta.get('media') or 'Unknown Media'
    
    # Construct intro
    text_intro = (
        f"Article de {media}... "
        f"{title}... "
        f"Par {author}... "
    )

    full_content = f"{text_intro}{text_body}"
    full_content = re.sub(r'\s+', ' ', full_content).strip()
    full_content = process_inclusive_writing(full_content)  # Handle écriture inclusive
    full_content = convertir_chiffres_romains(full_content)  # Convert Roman numerals
    full_content = clean_text_for_tts(full_content)  # Remove URLs, notes, references

    if len(full_content) < 50:
        logger.warning(f"Skipping generation for '{title}': content too short or empty.")
        return False

    # Generate Audio
    logger.info(f"Generating MP3: {os.path.basename(mp3_path)}")
    logger.debug(f"Content Preview: {full_content[:100]}...")
    
    try:
        communicate = edge_tts.Communicate(full_content, voice)
        await communicate.save(mp3_path)
    except Exception as e:
        logger.error(f"Failed to generate TTS audio for '{title}': {e}")
        return False
    
    # Add ID3 Tags
    try:
        try:
            audio = ID3(mp3_path)
        except Exception:
            audio = ID3()
            
        audio.add(TIT2(encoding=3, text=title))
        audio.add(TPE1(encoding=3, text=author))
        
        album = media if media != "Unknown Media" else "Audio Articles"
        audio.add(TALB(encoding=3, text=album))
        
        if meta.get('url'):
            audio.add(COMM(encoding=3, lang='eng', desc='', text=meta['url']))
        
        if meta.get('description'):
            audio.add(USLT(encoding=3, lang='eng', desc='Description', text=meta['description']))
            
        if meta.get('date'):
            # Extract year only for TDRC tag
            date_str = str(meta['date'])
            year_match = re.match(r'^(\d{4})', date_str)
            if year_match:
                audio.add(TDRC(encoding=3, text=year_match.group(1)))

        if meta.get('image_url'):
            img_data = download_image(meta['image_url'])
            if img_data:
                mime = 'image/jpeg'
                if meta['image_url'].lower().endswith('.png'):
                    mime = 'image/png'
                audio.add(APIC(
                    encoding=3,
                    mime=mime,
                    type=3, 
                    desc=u'Cover',
                    data=img_data
                ))
        
        audio.save(mp3_path)
        return True
    except Exception as e:
        logger.warning(f"Failed to write ID3 tags to {mp3_path}: {e}")
        # Return True because the audio file was successfully generated
        return True


# --- GROUPED SUMMARIES (résumés IA regroupés en 1 MP3 par fenêtre calendaire) ---

def load_grouped_summaries() -> dict:
    """Charge le fichier grouped_summaries.json. Retourne {"pending": []} si absent."""
    if os.path.exists(GROUPED_SUMMARIES_FILE):
        try:
            with open(GROUPED_SUMMARIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Impossible de lire grouped_summaries.json : {e}")
    return {"pending": []}


def save_grouped_summaries(data: dict) -> None:
    """Sauvegarde grouped_summaries.json de façon atomique."""
    try:
        temp_file = GROUPED_SUMMARIES_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(temp_file, GROUPED_SUMMARIES_FILE)
    except Exception as e:
        logger.error(f"Impossible de sauvegarder grouped_summaries.json : {e}")


def store_pending_summary(
    feed_url: str,
    media: str,
    title: str,
    article_url: str,
    summary: str,
    window_hours: int,
    voice: str,
) -> None:
    """
    Ajoute un résumé dans la liste d'attente grouped_summaries.json.
    Le date_bucket est la date courante ISO (ex. "2026-05-27").
    """
    data = load_grouped_summaries()
    entry = {
        "feed_url": feed_url,
        "media": media,
        "title": title,
        "article_url": article_url,
        "summary": summary,
        "date_bucket": date.today().isoformat(),
        "window_hours": window_hours,
        "voice": voice,
    }
    data["pending"].append(entry)
    save_grouped_summaries(data)
    logger.debug(f"Résumé mis en attente de regroupement : {title[:60]}")


def _build_grouped_text(media: str, date_bucket: str, entries: list) -> str:
    """Construit le texte complet du MP3 groupé à partir de la liste de résumés."""
    n = len(entries)
    ordinals = [
        "Premier", "Deuxième", "Troisième", "Quatrième", "Cinquième",
        "Sixième", "Septième", "Huitième", "Neuvième", "Dixième",
    ]

    parts = [f"Résumés {media} du {date_bucket}. {n} article{'s' if n > 1 else ''}. "]
    for i, entry in enumerate(entries):
        title = entry.get("title", "Sans titre")
        summary = entry.get("summary", "")
        if i < len(ordinals):
            label = f"{ordinals[i]} article sur {n}"
        else:
            label = f"Article {i + 1} sur {n}"
        parts.append(f"{label} : {title}. {summary}")

    return " ".join(parts)


async def flush_grouped_summaries() -> None:
    """
    Génère les MP3 groupés pour toutes les fenêtres calendaires fermées
    (date_bucket strictement antérieure à aujourd'hui).

    Les entrées traitées sont retirées de grouped_summaries.json.
    """
    data = load_grouped_summaries()
    pending = data.get("pending", [])
    if not pending:
        return

    today_str = date.today().isoformat()

    # Grouper les entrées par (feed_url, date_bucket)
    groups: dict = {}
    remaining: list = []

    for entry in pending:
        bucket = entry.get("date_bucket", "")
        if bucket < today_str:
            key = (entry["feed_url"], bucket)
            groups.setdefault(key, []).append(entry)
        else:
            remaining.append(entry)

    if not groups:
        logger.debug("flush_grouped_summaries : aucune fenêtre fermée à traiter.")
        return

    for (feed_url, date_bucket), entries in groups.items():
        media = entries[0].get("media", "Unknown Media")
        voice = entries[0].get("voice", VOICE)

        safe_media = clean_filename(media)
        mp3_name = f"Resumes_{safe_media}_{date_bucket}.mp3"
        mp3_name = limit_filename(mp3_name, 120)
        mp3_path = os.path.join(OUTPUT_DIR, mp3_name)

        logger.info(
            f"Génération du MP3 groupé : {mp3_name} ({len(entries)} article(s))"
        )

        combined_text = _build_grouped_text(media, date_bucket, entries)
        combined_text = clean_text_for_tts(combined_text)

        if len(combined_text) < 20:
            logger.warning(f"Texte groupé trop court pour {mp3_name}, ignoré.")
            remaining.extend(entries)
            continue

        try:
            communicate = edge_tts.Communicate(combined_text, voice)
            await communicate.save(mp3_path)
        except Exception as e:
            logger.error(f"Erreur TTS pour le MP3 groupé {mp3_name} : {e}")
            remaining.extend(entries)
            continue

        # Tags ID3 du MP3 groupé
        try:
            try:
                audio = ID3(mp3_path)
            except Exception:
                audio = ID3()
            audio.add(TIT2(encoding=3, text=f"Résumés {media} du {date_bucket}"))
            audio.add(TPE1(encoding=3, text="IA Résumé"))
            audio.add(TALB(encoding=3, text=media))
            audio.save(mp3_path)
        except Exception as e:
            logger.warning(f"Impossible d'écrire les tags ID3 pour {mp3_name} : {e}")

        logger.info(f"MP3 groupé généré avec succès : {mp3_path}")

    # Sauvegarder uniquement les entrées non traitées
    data["pending"] = remaining
    save_grouped_summaries(data)


async def process_rss_feed(feed_config, processed_urls, limit=None):
    """
    Processes an RSS feed, downloading new articles and converting them to MP3.
    """
    if isinstance(feed_config, str):
        feed_url = feed_config
        feed_voice = VOICE
        should_summarize = False
        group_window_hours = None
    elif isinstance(feed_config, dict):
        feed_url = feed_config.get("url")
        feed_voice = feed_config.get("voice", VOICE)
        should_summarize = bool(feed_config.get("summarize", False))
        group_window_hours = feed_config.get("group_window_hours")
    else:
        logger.error(f"Invalid feed configuration: {feed_config}")
        return

    logger.info(f"Checking RSS Feed: {feed_url}")
    try:
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
    except Exception as e:
        logger.error(f"Failed to parse RSS feed {feed_url}: {e}")
        return

    entries = feed.entries
    if not entries:
        logger.info(f"No entries found in feed {feed_url}")
        return

    # Check if this feed is new to initialize it by marking all current items as read
    seen_feeds = load_seen_feeds()
    if feed_url not in seen_feeds:
        logger.info(f"New RSS Feed detected: {feed_url}. Initializing feed by marking all current entries as read...")
        links_to_save = []
        for entry in entries:
            link = entry.get("link")
            if link:
                links_to_save.append(link)
                processed_urls.add(link)
        if links_to_save:
            save_processed_urls(links_to_save)
        logger.info(f"Marked {len(links_to_save)} existing articles from {feed_url} as read.")
        save_seen_feed(feed_url)
        return

    # Filter out already processed entries
    new_entries = []
    for entry in entries:
        link = entry.get("link")
        if not link:
            continue
        if link not in processed_urls:
            new_entries.append(entry)

    if not new_entries:
        logger.info(f"No new entries in feed {feed_url}")
        return

    # If limit is set, we only keep the N latest entries
    if limit is not None:
        new_entries = new_entries[:limit]
        logger.info(f"Limiting to {len(new_entries)} latest articles for RSS feed.")

    logger.info(f"Found {len(new_entries)} new entries to process from {feed_url}")

    # Process each new entry
    for entry in new_entries:
        link = entry.get("link")
        title = entry.get("title", "Untitled Article")
        
        logger.info(f"Processing RSS Entry: {title} ({link})")
        
        try:
            # Download article HTML
            def fetch_html(url):
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    return response.read()
            
            html_bytes = await loop.run_in_executor(None, fetch_html, link)
            soup = BeautifulSoup(html_bytes, 'html.parser')
            
            # Use article title as filename hint
            filename_hint = clean_filename(title) + ".html"
            
            # Get Adapter
            adapter = get_adapter(soup, filename_hint)
            
            # Extract metadata and merge/override with RSS data
            meta = adapter.extract_metadata()
            
            if title:
                meta["title"] = title
            if link:
                meta["url"] = link
                
            # If date is missing, try to extract from entry
            if not meta.get("date") and entry.get("published_parsed"):
                tm = entry.published_parsed
                meta["date"] = f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}"
                
            # If description is missing, use summary
            if not meta.get("description") and entry.get("summary"):
                summary_soup = BeautifulSoup(entry.summary, 'html.parser')
                meta["description"] = summary_soup.get_text()

            # Clean name for output file
            safe_title = clean_filename(meta["title"])
            media = meta.get("media", "Unknown Media")
            safe_media = clean_filename(media)
            
            if safe_media and safe_media != "Unknown_Media":
                mp3_name = f"{safe_title} - {safe_media}.mp3"
            else:
                mp3_name = f"{safe_title}.mp3"
                
            # Limit length to 120 characters to avoid sync issues (e.g. with Nextcloud)
            mp3_name = limit_filename(mp3_name, 120)
                
            mp3_path = os.path.join(OUTPUT_DIR, mp3_name)
            
            # Generate body content
            text_body = adapter.get_content()
            if len(text_body) < 50:
                logger.warning(f"Skipping RSS entry '{title}': content too short or empty.")
                save_processed_url(link)
                processed_urls.add(link)
                continue

            # --- RÉSUMÉ IA (optionnel, configuré par flux) ---
            if should_summarize:
                logger.info(f"Résumé IA activé pour '{title[:60]}' ({len(text_body)} chars)")
                summarizer = get_summarizer()
                text_body = await summarizer.summarize(text_body)

                if group_window_hours:
                    # Accumuler dans grouped_summaries.json, pas de MP3 individuel
                    store_pending_summary(
                        feed_url=feed_url,
                        media=meta.get("media", "Unknown Media"),
                        title=meta["title"],
                        article_url=link,
                        summary=text_body,
                        window_hours=group_window_hours,
                        voice=feed_voice,
                    )
                    save_processed_url(link)
                    processed_urls.add(link)
                    logger.info(
                        f"Résumé mis en attente (groupe {group_window_hours}h) : {title[:60]}"
                    )
                    continue
                # else : text_body est maintenant le résumé → génération MP3 individuelle normale
            # --- FIN RÉSUMÉ IA ---

            # Generate MP3 and save tags
            success = await generate_audio_from_content(meta, text_body, mp3_path, feed_voice)
            if success:
                logger.info(f"Successfully converted RSS article to MP3: {mp3_path}")
                save_processed_url(link)
                processed_urls.add(link)
            else:
                logger.error(f"Failed to generate MP3 for RSS article: {title}")
                
        except Exception as e:
            logger.error(f"Error processing RSS entry '{title}': {e}", exc_info=True)


async def process_html_file(filepath):
    filename = os.path.basename(filepath)
    logger.info(f"Processing: {filename}")

    try:
        # Read file
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='latin-1') as f:
                soup = BeautifulSoup(f, 'html.parser')

        # Get Adapter
        adapter = get_adapter(soup, filename)
        
        # Metadata
        meta = adapter.extract_metadata()
        title = meta['title']
        author = meta['author']
        media = meta['media']
        
        logger.info(f"Metadata - Title: {title}, Author: {author}, Media: {media}")

        safe_title = clean_filename(title)
        if len(safe_title) < 3:
             safe_title = clean_filename(os.path.splitext(filename)[0])
        
        # Format filename
        safe_media = clean_filename(media)
        
        if safe_media and safe_media != "Unknown_Media" and safe_media != "Europresse": 
            mp3_name = f"{safe_title} - {safe_media}.mp3"
        else:
            mp3_name = f"{safe_title}.mp3"
        
        # Limit length to 120 characters to avoid sync issues (e.g. with Nextcloud)
        mp3_name = limit_filename(mp3_name, 120)

        mp3_path = os.path.join(OUTPUT_DIR, mp3_name)

        # Generate content
        text_body = adapter.get_content()
            
        if len(text_body) < 50:
            logger.warning(f"Skipping {filename}: content too short or empty.")
            return 

        # Generate Audio and tags
        success = await generate_audio_from_content(meta, text_body, mp3_path, VOICE)
        if not success:
            return

        logger.info(f"Generated successfully with tags: {mp3_path}")

        # Archive and Cleanup
        if not os.path.exists(ARCHIVE_DIR):
            os.makedirs(ARCHIVE_DIR)
        
        archive_path = os.path.join(ARCHIVE_DIR, filename)
        if os.path.exists(archive_path):
            base, ext = os.path.splitext(filename)
            timestamp = 0 
            while os.path.exists(archive_path):
                timestamp += 1
                archive_path = os.path.join(ARCHIVE_DIR, f"{base}_{timestamp}{ext}")

        shutil.move(filepath, archive_path)
        logger.info(f"Archived to: {archive_path}")

        files_dir_name = os.path.splitext(filename)[0] + "_files"
        files_dir_path = os.path.join(INPUT_DIR, files_dir_name)
        if os.path.exists(files_dir_path) and os.path.isdir(files_dir_path):
            shutil.rmtree(files_dir_path)
            logger.info(f"Removed artifacts directory: {files_dir_name}")

    except Exception as e:
        logger.error(f"Error processing {filename}: {e}", exc_info=True)


def main_test(test_dir):
    """Main function for test mode - no async needed as we're not generating audio."""
    logger.info("=" * 80)
    logger.info("MODE TEST ACTIVÉ")
    logger.info(f"Répertoire source: {test_dir}")
    logger.info(f"Répertoire de sortie: {test_dir}")
    logger.info("=" * 80)
    
    if not os.path.exists(test_dir):
        logger.error(f"Test directory does not exist: {test_dir}")
        return
    
    files_found = False
    
    try:
        files = sorted(os.listdir(test_dir))
    except FileNotFoundError:
        logger.error(f"Test directory not found: {test_dir}")
        return

    for file in files:
        filepath = os.path.join(test_dir, file)
        
        if os.path.isdir(filepath): continue
        if file.startswith('.'): continue
        if file.endswith('.part') or file.endswith('.tmp') or file.endswith('.crdownload'): continue
        if file.endswith('.txt'): continue  # Skip existing text files
        
        if file.lower().endswith(".html") or file.lower().endswith(".htm"):
            files_found = True
            process_html_file_test(filepath, test_dir)
    
    if not files_found:
        logger.info("[TEST MODE] No HTML files found in test directory.")
    else:
        logger.info("=" * 80)
        logger.info("[TEST MODE] Traitement terminé. Vérifiez les fichiers .txt générés.")
        logger.info("=" * 80)


async def main(rss_limit=None):
    # Ensure directories exist
    for directory in [INPUT_DIR, OUTPUT_DIR, ARCHIVE_DIR]:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except OSError as e:
                logger.error(f"Could not create directory {directory}: {e}")
                return

    # --- PROCESS LOCAL HTML FILES ---
    logger.info("Starting scan for local HTML files...")
    try:
        files = sorted(os.listdir(INPUT_DIR))
    except FileNotFoundError:
        logger.error(f"Input directory not found: {INPUT_DIR}")
        files = []

    html_files = []
    for file in files:
        filepath = os.path.join(INPUT_DIR, file)
        
        if os.path.isdir(filepath): continue
        if file.startswith('.'): continue
        if file.endswith('.part') or file.endswith('.tmp') or file.endswith('.crdownload'): continue
        
        if file.lower().endswith(".html") or file.lower().endswith(".htm"):
            html_files.append(filepath)
    
    if html_files:
        logger.info(f"Found {len(html_files)} HTML file(s) to process.")
        # Use a semaphore to process multiple files in parallel safely
        sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
        
        async def safe_process(filepath):
            async with sem:
                await process_html_file(filepath)
                
        tasks = [safe_process(filepath) for filepath in html_files]
        await asyncio.gather(*tasks)
        logger.info("All local HTML files processed.")
    else:
        logger.info("No new local HTML files found.")

    # --- PROCESS RSS FEEDS ---
    if RSS_FEEDS:
        logger.info("Starting RSS feeds processing...")
        processed_urls = load_processed_urls()
        for feed_config in RSS_FEEDS:
            await process_rss_feed(feed_config, processed_urls, limit=rss_limit)
        logger.info("All RSS feeds processed.")

        # Générer les MP3 groupés pour les fenêtres calendaires fermées
        await flush_grouped_summaries()
    else:
        logger.info("No RSS feeds configured.")

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Convert HTML articles to MP3 audio files using edge-TTS',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  Normal mode:  python3 html_to_mp3.py
  Test mode:    python3 html_to_mp3.py --test
        """
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Mode test: extrait le texte sans générer de fichiers audio. '
             'Les fichiers HTML sont lus depuis Article-Test/ et les fichiers '
             'texte sont créés dans le même dossier.'
    )
    parser.add_argument(
        '--rss-limit',
        type=int,
        default=None,
        help='Limite le nombre de nouveaux articles à traiter par flux RSS (utile pour les tests).'
    )
    
    args = parser.parse_args()
    
    try:
        if args.test:
            # Test mode: use Article-Test directory
            test_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "Article-Test"
            )
            main_test(test_dir)
        else:
            # Normal mode: async execution
            asyncio.run(main(rss_limit=args.rss_limit))
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
