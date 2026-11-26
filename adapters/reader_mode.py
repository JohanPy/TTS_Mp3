import trafilatura
from trafilatura.settings import use_config
import logging
import re

from segments import Segment, segments_to_plain_text

logger = logging.getLogger(__name__)

# Configure Trafilatura for better readability
config = use_config()
config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "100")
config.set("DEFAULT", "MIN_OUTPUT_SIZE", "1")
config.set("DEFAULT", "MIN_OUTPUT_COMM_SIZE", "1")


def _clean_markdown_line(line: str) -> tuple[str, str, bool]:
    """
    Nettoie une ligne Markdown extraite par Trafilatura et retourne
    (kind, texte_nettoye, is_bold_question).
    """
    is_heading = bool(re.match(r'^#+\s+', line))
    is_quote = bool(re.match(r'^>\s*', line))
    is_list = bool(re.match(r'^[-*+]\s+', line))

    clean = re.sub(r'^#+\s+', '', line)
    clean = re.sub(r'^>\s*', '', clean)
    clean = re.sub(r'^[-*+]\s+', '', clean)
    clean = re.sub(r'\[\s*\d{1,3}\s*\]', '', clean)

    # Détecter si la ligne est majoritairement en gras et se termine par '?' (entretien)
    bold_matches = re.findall(r'\*\*(.+?)\*\*|__(.+?)__', clean)
    bold_len = sum(len(a or b) for a, b in bold_matches)

    # Remove markdown emphasis (bold/italic) cleanly without injecting quotes
    clean = re.sub(r'\*\*(.*?)\*\*', r'\1', clean)
    clean = re.sub(r'\*(.*?)\*', r'\1', clean)
    clean = re.sub(r'__(.*?)__', r'\1', clean)
    clean = re.sub(r'_(.*?)_', r'\1', clean)

    # Clean up any remaining stray asterisks or underscores
    clean = re.sub(r'(?<=\S)\*', '', clean)
    clean = clean.replace('*', ' ')
    clean = clean.replace('_', ' ').strip()

    if is_heading:
        kind = "heading"
    elif is_quote:
        kind = "quote_block"
    elif is_list:
        kind = "list_item"
    else:
        kind = "paragraph"

    is_bold_q = (
        kind == "paragraph"
        and bool(clean)
        and clean.endswith("?")
        and bold_len > 0
        and (bold_len / max(1, len(clean))) >= 0.60
    )
    return kind, clean, is_bold_q


def reader_extract_segments(html_string) -> list[Segment]:
    """
    Extrait les segments structurés d'un article HTML via Trafilatura.
    Distingue titres, citations, listes, questions en gras et paragraphes.
    """
    if not html_string:
        return []

    try:
        extracted_text = trafilatura.extract(
            html_string,
            include_comments=False,
            include_tables=False,
            include_links=False,
            include_images=False,
            include_formatting=True,
            config=config,
        )
        if not extracted_text:
            return []

        segments: list[Segment] = []
        for raw_line in extracted_text.split('\n'):
            line = raw_line.strip()
            if not line:
                continue

            kind, clean, is_bold_q = _clean_markdown_line(line)
            if not clean:
                continue

            if re.match(r'^\d+$', clean) or re.match(r'^\d+\s*vues?\.?$', clean, re.IGNORECASE):
                continue
            if len(clean) < 40 and re.match(
                r'^(?:sources?|bibliographie|notes?|partager|imprimer|articles?\s+en\s+lien|sur\s+le\s+même\s+sujet|ne\s+manquez\s+plus\s+notre\s+newsletter|version\s+raccourcie\s+tract)[s\s:.]*$',
                clean,
                re.IGNORECASE,
            ):
                continue

            if kind == "paragraph" and len(clean) < 100 and not clean.endswith(',') and clean[-1] not in '.!?:;,"\'»*':
                # Ligne courte isolée sans ponctuation finale -> probable intertitre
                kind = "heading"

            segments.append(Segment(kind=kind, text=clean, is_bold_question=is_bold_q))

        return segments
    except Exception as e:
        logger.warning(f"Trafilatura segment extraction failed: {e}")
        return []


def reader_extract_content(html_string):
    """
    Extracts the main content of an article from an HTML string using Trafilatura.
    Formats the output for TTS (adds punctuation, handles headings).
    
    Returns an empty string if extraction fails or is too short.
    """
    segments = reader_extract_segments(html_string)
    if not segments:
        return ""

    result = segments_to_plain_text(segments)
    result = re.sub(r'\.{4,}', '...', result)
    result = re.sub(r'([?!])\s*\.+', r'\1', result)
    result = re.sub(r'([,:;])\s*\.+', r'\1', result)
    result = re.sub(r'(?<!\.)\.{2}(?!\.)', '.', result)
    return result


def reader_extract_metadata(html_string):
    """
    Extracts metadata from an HTML string using Trafilatura.
    
    Returns a dictionary with standard keys, values may be None.
    """
    empty_meta = {
        "title": None,
        "author": None,
        "url": None,
        "date": None,
        "description": None,
        "media": None,
        "image_url": None
    }
    
    if not html_string:
        return empty_meta
        
    try:
        extracted = trafilatura.extract_metadata(html_string)
        if not extracted:
            return empty_meta
            
        return {
            "title": extracted.title,
            "author": extracted.author,
            "url": extracted.url,
            "date": extracted.date,
            "description": extracted.description,
            "media": extracted.sitename,
            "image_url": extracted.image
        }
    except Exception as e:
        logger.warning(f"Trafilatura metadata extraction failed: {e}")
        return empty_meta
