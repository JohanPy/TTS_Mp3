
from .base import BaseAdapter
from bs4 import Tag
import re
import os


class MultitudesAdapter(BaseAdapter):
    """Adapter for Multitudes articles (multitudes.net)"""
    
    def can_handle(self):
        # Check og:site_name
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "multitudes" in og_site.get("content", "").lower():
            return True
        
        # Check URL
        og_url = self.soup.find("meta", property="og:url")
        if og_url and "multitudes.net" in og_url.get("content", ""):
            return True
        
        # Check filename
        if "multitudes" in self.filename.lower():
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
            title = og_title["content"].strip()
            # Clean " - multitudes" suffix
            title = re.sub(r'\s*[-–]\s*multitudes\s*$', '', title, flags=re.IGNORECASE)
            meta["title"] = title
        
        if not meta["title"]:
            if soup.title and soup.title.string:
                meta["title"] = soup.title.string.strip()

        if not meta["title"]:
            h1_tag = soup.find("h1")
            if h1_tag:
                meta["title"] = h1_tag.get_text(separator=" ", strip=True)
                
        if not meta["title"]:
            meta["title"] = filename_title

        # Author - Multitudes has multiple authors in h3 tags
        authors = []
        article = soup.find('article')
        if article:
            # Authors are often in h3 tags within article
            for h3 in article.find_all('h3', limit=5):
                text = h3.get_text(strip=True)
                # Skip if it looks like a section title (too long)
                if len(text) < 50 and not any(c in text for c in [':', '.', '?']):
                    authors.append(text)
        
        if authors:
            meta["author"] = ", ".join(authors[:3])  # Limit to 3 authors
        else:
            meta_author = soup.find("meta", property="article:author")
            if meta_author and meta_author.get("content"):
                meta["author"] = meta_author["content"].strip()

        # Media
        meta["media"] = "Multitudes"
        
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
            if len(og_desc) < 300:
                long_desc = self._generate_long_description()
                meta["description"] = long_desc if long_desc else og_desc
            else:
                meta["description"] = og_desc
        else:
            meta["description"] = self._generate_long_description()

        # Image
        meta_image = soup.find("meta", property="og:image")
        if meta_image and meta_image.get("content"):
            meta["image_url"] = meta_image["content"].strip()

        return meta
        
    def get_content(self):
        soup = self.soup
        
        # Find .entry-content which is the main content container
        entry_content = soup.select_one('.entry-content')
        if not entry_content:
            # Fallback to article
            entry_content = soup.find('article')
        
        if not entry_content:
            return ""
        
        # Create a copy to avoid modifying original
        container = entry_content.__copy__()
        
        # Remove unwanted elements
        for element in container(["script", "style", "nav", "header", "footer", 
                                   "aside", "form", "iframe", "noscript", "figure", 
                                   "button", "input", "img", "video", "audio"]):
            element.extract()

        # Remove author headers (h3 tags that are just author names)
        for h3 in container.find_all('h3'):
            text = h3.get_text(strip=True)
            # If it's a short name-like h3, remove it
            if len(text) < 50 and not any(c in text for c in [':', '.', '?', '!']):
                h3.extract()

        # Remove specific junk selectors
        junk_selectors = [
            ".share", ".social", ".sharing",
            ".author", ".post-author",
            ".tags", ".post-tags",
            ".comments",
            ".related",
            ".navigation",
            ".meta", ".post-meta"
        ]
        for selector in junk_selectors:
            for element in container.select(selector):
                element.extract()
        
        # Pre-process: unwrap nested elements
        while True:
            wrapper = container.find(lambda t: t.name in ['p', 'div'] and 
                                     t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper:
                break
            wrapper.unwrap()
            
        # Extract text from relevant tags
        text_parts = []
        for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'li']):
            text = tag.get_text(separator=" ", strip=True)
            if not text:
                continue
            
            # Skip very short text
            if len(text) < 10:
                continue
                
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
        # Clean up multiple dots
        result = re.sub(r'\.{5,}', '...', result)
        result = re.sub(r'\.{2}', '.', result)
        result = re.sub(r',\.', '.', result)
        
        return result
