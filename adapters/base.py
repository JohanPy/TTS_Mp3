
from bs4 import BeautifulSoup
import logging
import re
from .reader_mode import reader_extract_content, reader_extract_segments
from segments import Segment, segments_to_plain_text, split_paragraphs_from_text

logger = logging.getLogger(__name__)

class BaseAdapter:
    def __init__(self, soup, filename):
        self.soup = soup
        self.filename = filename
        self._content_cache = None
        self._segments_cache = None

    def can_handle(self):
        """Returns True if this adapter can handle the given soup/filename."""
        return False

    def extract_metadata(self):
        """
        Returns a dictionary with:
        title, author, media, url, date, description, image_url
        """
        return {
            "title": "",
            "author": "Unknown Author",
            "media": "Unknown Media",
            "url": "",
            "date": "",
            "description": "",
            "image_url": ""
        }

    def get_content(self):
        """Returns the cleaned text content to be spoken, using cache if available."""
        if self._content_cache is not None:
            return self._content_cache
        
        self._content_cache = self._extract_content()
        return self._content_cache

    def _extract_content(self):
        """Returns the cleaned text content to be spoken. To be overridden by subclasses."""
        return ""

    def get_segments(self) -> list[Segment]:
        """Retourne la liste des segments structurés de l'article (avec cache)."""
        if self._segments_cache is not None:
            return self._segments_cache
        self._segments_cache = self._extract_segments()
        return self._segments_cache

    def _extract_segments(self) -> list[Segment]:
        """Fallback générique à partir de _extract_content()."""
        content = self.get_content()
        if not content:
            return []
        return split_paragraphs_from_text(content)

    @staticmethod
    def _is_bold_question_tag(tag, text: str) -> bool:
        """Détermine si un paragraphe <p> est une question mise en gras (entretien)."""
        if not text or not text.endswith("?"):
            return False
        bold_parts = [b.get_text(" ", strip=True) for b in tag.find_all(["strong", "b"])]
        if not bold_parts:
            return False
        bold_len = sum(len(b) for b in bold_parts)
        return (bold_len / max(1, len(text))) >= 0.65

    def _extract_segments_from_container(
        self,
        container,
        *,
        min_len: int = 10,
        seen_dedup: bool = False,
        skip_patterns: tuple[str, ...] = (),
    ) -> list[Segment]:
        """
        Helper partagé pour extraire des Segment typés depuis un conteneur DOM
        (headings, blockquotes, listes, paragraphes).
        """
        all_tags = container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'li'])
        all_tags_set = set(all_tags)
        segments: list[Segment] = []
        seen_texts: set[str] = set()

        for tag in all_tags:
            is_nested = False
            for parent in tag.parents:
                if parent == container:
                    break
                if parent in all_tags_set:
                    is_nested = True
                    break
            if is_nested:
                continue

            text = re.sub(r'\s+([.,;:!?])', r'\1', tag.get_text(separator=" ", strip=True))
            if not text or len(text) < min_len:
                continue
            if any(re.match(pat, text, re.IGNORECASE) for pat in skip_patterns):
                continue

            if seen_dedup:
                text_hash = text[:50]
                if text_hash in seen_texts:
                    continue
                seen_texts.add(text_hash)

            if tag.name.startswith('h'):
                segments.append(Segment("heading", text))
            elif tag.name == 'blockquote':
                segments.append(Segment("quote_block", text))
            elif tag.name == 'li':
                segments.append(Segment("list_item", text))
            else:
                is_bq = self._is_bold_question_tag(tag, text)
                segments.append(Segment("paragraph", text, is_bold_question=is_bq))

        return segments
    
    def _generate_long_description(self, target_length=1200):
        """
        Generate a long description from article content for USLT tag.
        Extracts the first paragraphs up to target_length characters.
        
        Args:
            target_length: Target character count (default 1200, ~4x typical og:description)
        
        Returns:
            String containing article preview
        """
        content = self.get_content()
        if not content:
            return ""
        
        # Split by sentence-ending patterns to get clean breaks
        # Take content up to target length
        if len(content) <= target_length:
            return content
        
        # Find a good breaking point (end of sentence near target)
        truncated = content[:target_length]
        
        # Look for the last sentence-ending punctuation
        for delimiter in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
            last_pos = truncated.rfind(delimiter)
            if last_pos > target_length * 0.7:  # At least 70% of target
                return truncated[:last_pos + 1].strip()
        
        # Fallback: just cut at target length
        return truncated.strip() + "..."
        
    def _reader_extract(self, html_string=None):
        """
        Helper method to extract content using internal Trafilatura reader mode.
        Can be called by specific adapters if their target text structure is too
        complex, or to extract specific sub-trees by passing html_string.
        
        Args:
            html_string: Optional HTML string to process. If None, uses str(self.soup).
        
        Returns:
            String containing the cleaned article text.
        """
        if html_string is None:
            html_string = str(self.soup)
        return reader_extract_content(html_string)

    def _reader_extract_segments(self, html_string=None) -> list[Segment]:
        """Extrait des segments typés via Trafilatura reader mode."""
        if html_string is None:
            html_string = str(self.soup)
        return reader_extract_segments(html_string)
