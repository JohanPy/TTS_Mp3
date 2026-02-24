
from bs4 import BeautifulSoup
import logging
from .reader_mode import reader_extract_content

logger = logging.getLogger(__name__)

class BaseAdapter:
    def __init__(self, soup, filename):
        self.soup = soup
        self.filename = filename

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
        """Returns the cleaned text content to be spoken."""
        return ""
    
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
