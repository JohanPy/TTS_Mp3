
from .base import BaseAdapter
import re
import os

class UCLAdapter(BaseAdapter):
    def can_handle(self):
        # Union Communiste Libertaire
        if "Union communiste libertaire" in self.soup.get_text():
            return True
        if self.soup.select_one(".entry-title") and self.soup.select_one(".vcard.author"):
            return True
        return False

    def extract_metadata(self):
        meta = super().extract_metadata()
        soup = self.soup
        filename = self.filename
        filename_title = os.path.splitext(filename)[0]

        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            meta["title"] = og_title["content"].strip()
        
        if not meta["title"]:
            entry_title = soup.select_one(".entry-title")
            if entry_title:
                meta["title"] = entry_title.get_text(separator=" ", strip=True)
        
        if not meta["title"]:
            if soup.title and soup.title.string:
                meta["title"] = soup.title.string.strip()

        if not meta["title"]:
            h1_tag = soup.find("h1")
            if h1_tag:
                meta["title"] = h1_tag.get_text(separator=" ", strip=True)
                
        if not meta["title"]:
            meta["title"] = filename_title

        # Clean title
        title = meta["title"]
        for separator in [" - Union communiste libertaire", " | "]:
            if separator in title:
                parts = title.split(separator)
                if len(parts) > 1:
                    title = parts[0].strip()
        meta["title"] = title

        # Author
        author_span = soup.select_one(".vcard.author .fn")
        if author_span:
            meta["author"] = author_span.get_text(strip=True)
        else:
            meta["author"] = "Union communiste libertaire"

        # Media
        meta["media"] = "Union Communiste Libertaire"
        
        # URL
        meta_url = soup.find("meta", property="og:url") or soup.find("link", rel="canonical")
        if meta_url:
            meta["url"] = meta_url.get("href", meta_url.get("content", "")).strip()

        # Date
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date and meta_date.get("content"):
            meta["date"] = meta_date["content"].strip()
        else:
            # Try specific UCL date selector
            date_el = soup.select_one(".date-publication")
            if date_el:
                meta["date"] = date_el.get_text(strip=True)

        # Description
        meta_desc = soup.find("meta", property="og:description")
        if meta_desc and meta_desc.get("content"):
            og_desc = meta_desc["content"].strip()
            # If og:description is short (< 300 chars), supplement with article content
            if len(og_desc) < 300:
                long_desc = self._generate_long_description()
                meta["description"] = long_desc if long_desc else og_desc
            else:
                meta["description"] = og_desc
        else:
            # No meta description, generate from content
            meta["description"] = self._generate_long_description()

        # Image
        meta_image = soup.find("meta", property="og:image")
        if meta_image and meta_image.get("content"):
            meta["image_url"] = meta_image["content"].strip()

        return meta
        
    def get_content(self):
        # reader_mode (Trafilatura) provides an excellent extraction for UCL articles.
        # It successfully captures all text, formats headers correctly, and avoids duplicates.
        # We rely entirely on it for content extraction while keeping this adapter
        # for its accurate Custom Metadata logic (like specific media name and author location).
        return self._reader_extract()
