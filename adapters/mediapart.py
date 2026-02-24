
from .base import BaseAdapter
from bs4 import Tag
import re
import os

class MediapartAdapter(BaseAdapter):
    def can_handle(self):
        if "Mediapart" in self.filename:
            return True
        if self.soup.select_one("div.news__rich-text-content, div.content-page__full"):
            # Strong signal for Mediapart structure
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
            if soup.title and soup.title.string:
                meta["title"] = soup.title.string.strip()

        if not meta["title"]:
            h1_tag = soup.find("h1")
            if h1_tag:
                meta["title"] = h1_tag.get_text(separator=" ", strip=True)
                
        if not meta["title"]:
            meta["title"] = filename_title

        # Clean title (remove " | Mediapart" suffix)
        title = meta["title"]
        for separator in [" | ", " - "]:
            if separator in title:
                parts = title.split(separator)
                if len(parts) > 1 and "Mediapart" in parts[-1]:
                    title = separator.join(parts[:-1])
        meta["title"] = title

        # Author
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            meta["author"] = meta_author["content"].strip()

        # Media
        meta["media"] = "Mediapart"
        
        # URL
        meta_url = soup.find("meta", property="og:url") or soup.find("link", rel="canonical")
        if meta_url:
            meta["url"] = meta_url.get("href", meta_url.get("content", "")).strip()

        # Date
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date and meta_date.get("content"):
            meta["date"] = meta_date["content"].strip()

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
        main_content = self.soup.select_one("div.news__rich-text-content, div.content-page__full")
        
        if not main_content:
            return ""

        # Remove "À lire aussi" blocks, accessibility hidden text, and other noise
        # Note: Do NOT remove dropcap-wrapper as it contains the first paragraph text
        for node in main_content.select(".lire-aussi, .r-interne, .read-also, .screen-reader-only, figure"): 
            node.extract()
            
        # Identify paragraphs and headings
        # Handling nested paragraphs: Mediapart HTML can be very messy with <p> inside <p>.
        # Strategy: Find all interesting tags, then filter out those that are descendants of another interesting tag.
        # This keeps the outermost container and avoids duplication.
        
        all_tags = main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li'])
        top_level_tags = []
        all_tags_set = set(all_tags)
        
        for tag in all_tags:
            is_nested = False
            for parent in tag.parents:
                if parent == main_content: break # Don't go beyond main container
                if parent in all_tags_set:
                    is_nested = True
                    break
            if not is_nested:
                top_level_tags.append(tag)
        
        text_parts = []
        
        for tag in top_level_tags:
            text = tag.get_text(separator=" ", strip=True)
             
            if "À lire aussi" in text and len(text) < 50:
                continue
                
            if not text: continue
            
            if not text[-1] in '.!?':
                text = text + '.'
                
            if tag.name.startswith('h'):
                text_parts.append(f"{text}...")
            elif tag.name == 'li':
                 text_parts.append(f"{text},")
            else:
                text_parts.append(f"{text}.")
                
        return " ".join(text_parts)


