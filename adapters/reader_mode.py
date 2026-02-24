import trafilatura
from trafilatura.settings import use_config
import logging
import re

logger = logging.getLogger(__name__)

# Configure Trafilatura for better readability
config = use_config()
config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
config.set("DEFAULT", "MIN_EXTRACTED_SIZE", "100")
config.set("DEFAULT", "MIN_OUTPUT_SIZE", "1")
config.set("DEFAULT", "MIN_OUTPUT_COMM_SIZE", "1")


def reader_extract_content(html_string):
    """
    Extracts the main content of an article from an HTML string using Trafilatura.
    Formats the output for TTS (adds punctuation, handles headings).
    
    Returns an empty string if extraction fails or is too short.
    """
    if not html_string:
        return ""
        
    try:
        # Extract text with focus on readability and keeping structure
        extracted_text = trafilatura.extract(
            html_string,
            include_comments=False,
            include_tables=False,
            include_links=False,
            include_images=False,
            include_formatting=True, # Keep basic formatting to identify headings/paragraphs
            config=config
        )
        
        if not extracted_text:
            return ""
            
        # Format for TTS: Trafilatura output is usually markdown-like
        # Headers are usually prefixed with # or are on their own line
        text_parts = []
        
        lines = extracted_text.split('\n')
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            # Remove Markdown header markers (e.g. "## Title")
            line = re.sub(r'^#+\s+', '', line)
            
            # Remove academic footnotes (e.g., [1], [ 2 ], [12]) safely anywhere in the text
            line = re.sub(r'\[\s*\d{1,3}\s*\]', '', line)
            
            # Remove standalone numbers or very short standalone references
            if re.match(r'^\d+$', line) or (len(line) < 20 and re.match(r'^(sources?|bibliographie|notes?)[s\s:.]*$', line, re.IGNORECASE)):
                continue
            
            # Remove list item markers but keep the content and add a pause
            line = re.sub(r'^[-*+]\s+', '', line)
            
            # Add punctuation if missing for TTS pauses
            if not line[-1] in '.!?:;,"\'»*':
                # If it's a short line, it might be a header
                if len(line) < 100 and not line.endswith(','):
                    line = f"{line}..."
                else:
                    line = f"{line}."
                    
            text_parts.append(line)
            
        # Join with explicitly long pauses between distinct paragraphs/lines
        # The ' ... ' ensures the TTS engine breathes between blocks
        result = " ... ".join(text_parts)
        
        # Clean up excessive punctuation that might have been created
        result = re.sub(r'\.{5,}', '...', result)
        result = re.sub(r'\.{2}', '.', result)
        result = re.sub(r' \.\.\. \.', ' ... ', result)
        result = re.sub(r',\.', '.', result)
        
        return result
        
    except Exception as e:
        logger.warning(f"Trafilatura content extraction failed: {e}")
        return ""


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
