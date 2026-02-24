from .base import BaseAdapter
import re
import os

class LMSIAdapter(BaseAdapter):
    """Adapter for lmsi.net articles"""
    
    def can_handle(self):
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "lmsi.net" in og_site.get("content", ""):
            return True
            
        og_url = self.soup.find("meta", property="og:url")
        if og_url and "lmsi.net" in og_url.get("content", ""):
            return True
        
        if "lmsi.net" in self.filename:
            return True
            
        return False

    def extract_metadata(self):
        meta = super().extract_metadata()
        soup = self.soup
        
        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r'\s*[-–|]\s*Les mots sont importants.*$', '', title, flags=re.IGNORECASE)
            meta["title"] = title
            
        if not meta["title"] or meta["title"] == "Unknown Title":
            title_el = soup.select_one("h1.article-titre-2091, h1")
            if title_el:
                meta["title"] = title_el.get_text(separator=" ", strip=True)

        # Author
        author_el = soup.select_one(".vcard.author, .auteurs")
        if author_el:
            author_text = author_el.get_text(separator=", ", strip=True)
            author_text = re.sub(r'^par[\s,]+', '', author_text, flags=re.IGNORECASE)
            meta["author"] = author_text

        # Media
        meta["media"] = "LMSI"
        
        # URL
        meta_url = soup.find("meta", property="og:url") or soup.find("link", rel="canonical")
        if meta_url:
            meta["url"] = meta_url.get("content", meta_url.get("href", "")).strip()

        # Date
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date and meta_date.get("content"):
            meta["date"] = meta_date["content"].strip()
        else:
            abbr_date = soup.find("abbr", class_="published")
            if abbr_date and abbr_date.get("title"):
                meta["date"] = abbr_date["title"].strip()

        # Description
        meta_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            meta["description"] = meta_desc["content"].strip()

        # Image
        meta_image = soup.find("meta", property="og:image")
        if meta_image and meta_image.get("content"):
            meta["image_url"] = meta_image["content"].strip()

        return meta
        
    def get_content(self):
        # The main container
        container = self.soup.select_one(".contenu-principal")
        if not container:
            return ""

        # Remove junk
        for el in container(["script", "style", "nav", "figure", "img", "iframe"]):
            el.extract()
            
        junk_selectors = [
            ".info-publi", ".spip_note_ref", ".notes", ".portfolio", 
            ".share", ".social", ".author", ".tags", ".related", "#forum",
            ".cartouche h1"
        ]
        for selector in junk_selectors:
            for el in container.select(selector):
                el.extract()

        # Unwrap wrappers to avoid missing text
        while True:
            wrapper = container.find(lambda t: t.name in ['div', 'span'] and 
                                     t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper:
                break
            wrapper.unwrap()

        # Extract text
        text_parts = []
        seen = set()
        
        for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'li']):
            # Skip nested tags that have block children
            if tag.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote']):
                continue
                
            text = tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 15:
                continue
                
            text_hash = text[:50]
            if text_hash in seen:
                continue
            seen.add(text_hash)
            
            if not text[-1] in '.!?':
                text = text + '.'
                
            if tag.name.startswith('h'):
                text_parts.append(f"{text}...")
            elif tag.name == 'blockquote':
                text_parts.append(f"Citation: {text}")
            elif tag.name == 'li':
                text_parts.append(f"{text},")
            else:
                text_parts.append(f"{text}.")

        result = " ".join(text_parts)
        result = re.sub(r'\.{5,}', '...', result)
        result = re.sub(r'\.{2}', '.', result)
        result = re.sub(r',\.', '.', result)
        
        return result
