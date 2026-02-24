
from .base import BaseAdapter
from bs4 import Tag
import re
import os

class LeMondeDiplomatiqueAdapter(BaseAdapter):
    def can_handle(self):
        # Check specific LMD meta or structure
        # Often "Le Monde diplomatique" is in the title or footer
        if "Le Monde diplomatique" in self.filename:
            return True
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "Le Monde diplomatique" in og_site.get("content", ""):
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

        # Clean title
        title = meta["title"]
        for separator in [" | ", " - ", ", par "]:
            if separator in title:
                parts = title.split(separator)
                if len(parts) > 1 and len(parts[-1]) < 30:
                    title = separator.join(parts[:-1])
        meta["title"] = title

        # Author
        # LMD often has author in og:article:author or specific class
        meta_author = soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            meta["author"] = meta_author["content"].strip()
        else:
            author_span = soup.select_one(".auteurs a")
            if author_span:
                meta["author"] = author_span.get_text(strip=True)

        # Media
        meta["media"] = "Le Monde diplomatique"
        
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
        # Logic from original script
        main_content = self.soup.select_one("div.texte")
        chapo = self.soup.select_one("div.chapo")
        
        container = self.soup.new_tag("div")
        
        if chapo:
             container.append(chapo)
        
        if main_content:
            container.append(main_content)
            
        if not main_content and not chapo:
            return ""
            
        # Clean-up inside the specific content
        # (Generic cleanup might have already been done if we called a shared helper, 
        # but here we do adapter specific stuff)
        
        # Pre-process: unwrap
        while True:
            wrapper = container.find(lambda t: t.name in ['p', 'div'] and t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper: break
            wrapper.unwrap()
            
        text_parts = []
        for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
            text = tag.get_text(separator=" ", strip=True)
            if not text: continue
            
            if not text[-1] in '.!?':
                text = text + '.'
                
            if tag.name.startswith('h'):
                text_parts.append(f"{text}...")
            else:
                text_parts.append(f"{text}.")
                
        return " ".join(text_parts)
