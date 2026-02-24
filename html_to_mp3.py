#!/usr/bin/env python3
import os
import shutil
import asyncio
import edge_tts
import logging
import re
import json
import glob
import argparse
from bs4 import BeautifulSoup, Tag, NavigableString
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, COMM, USLT, TDRC, APIC
import urllib.request
import urllib.error


# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
INPUT_DIR = os.path.expanduser("/home/killersky4/Téléchargements/versaudio")
OUTPUT_DIR = os.path.expanduser("/home/killersky4/Documents/Perso/Podcasts/ArtcleTTS")
ARCHIVE_DIR = os.path.expanduser("/home/killersky4/Téléchargements/versaudio/Archived")
VOICE = "fr-FR-VivienneNeural"

# --- HELPER FUNCTIONS ---

def clean_filename(text):
    """Cleans a string to be used as a filename."""
    if not text: return "Audio_Article"
    # Keep alphanumeric, spaces, hyphens and underscores
    safe_text = "".join([c for c in text if c.isalnum() or c in (' ', '-', '_')]).strip()
    safe_text = re.sub(r'[\s_-]+', '_', safe_text)
    return safe_text

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
        
        # Limit length
        if len(txt_name) > 200:
            txt_name = txt_name[:200] + ".txt"

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
        
        # Limit length
        if len(mp3_name) > 200:
            mp3_name = mp3_name[:200] + ".mp3"

        mp3_path = os.path.join(OUTPUT_DIR, mp3_name)

        # Generate content
        text_body = adapter.get_content()
            
        if len(text_body) < 50:
            logger.warning(f"Skipping {filename}: content too short or empty.")
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
        full_content = clean_text_for_tts(full_content)  # Remove URLs, notes, references

        # Generate Audio
        logger.info(f"Generating MP3: {mp3_name}")
        logger.debug(f"Content Preview: {full_content[:100]}...")
        
        communicate = edge_tts.Communicate(full_content, VOICE)
        await communicate.save(mp3_path)
        
        # Add ID3 Tags
        try:
            audio = ID3(mp3_path)
        except Exception:
            audio = ID3()
            
        audio.add(TIT2(encoding=3, text=title))
        audio.add(TPE1(encoding=3, text=author))
        
        album = media if media != "Unknown Media" else "Audio Articles"
        audio.add(TALB(encoding=3, text=album))
        
        if meta['url']:
            audio.add(COMM(encoding=3, lang='eng', desc='', text=meta['url']))
        
        if meta['description']:
            audio.add(USLT(encoding=3, lang='eng', desc='Description', text=meta['description']))
            
        if meta['date']:
            # Extract year only for TDRC tag (full ISO format like "2024-03-14T15:32" 
            # can cause issues with podcast readers)
            date_str = str(meta['date'])
            # Try to extract just the year
            year_match = re.match(r'^(\d{4})', date_str)
            if year_match:
                audio.add(TDRC(encoding=3, text=year_match.group(1)))

        if meta['image_url']:
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


async def main():
    # Ensure directories exist
    for directory in [INPUT_DIR, OUTPUT_DIR, ARCHIVE_DIR]:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                logger.error(f"Could not create directory {directory}: {e}")
                return

    logger.info("Starting scan...")
    files_found = False
    
    try:
        files = sorted(os.listdir(INPUT_DIR))
    except FileNotFoundError:
        logger.error(f"Input directory not found: {INPUT_DIR}")
        return

    for file in files:
        filepath = os.path.join(INPUT_DIR, file)
        
        if os.path.isdir(filepath): continue
        if file.startswith('.'): continue
        if file.endswith('.part') or file.endswith('.tmp') or file.endswith('.crdownload'): continue
        
        if file.lower().endswith(".html") or file.lower().endswith(".htm"):
            files_found = True
            await process_html_file(filepath)
    
    if not files_found:
        logger.info("No new HTML files found.")

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
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
