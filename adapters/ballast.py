
from .base import BaseAdapter
from bs4 import Tag
import re
import os


class BallastAdapter(BaseAdapter):
    """Adapter for BALLAST articles (revue-ballast.fr)"""
    
    def can_handle(self):
        # Check og:site_name
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "BALLAST" in og_site.get("content", ""):
            return True
        
        # Check URL
        og_url = self.soup.find("meta", property="og:url")
        if og_url and "revue-ballast.fr" in og_url.get("content", ""):
            return True
        
        # Check filename
        if "BALLAST" in self.filename:
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
            # Remove "BALLAST • " prefix if present
            if title.startswith("BALLAST"):
                title = re.sub(r'^BALLAST\s*[•·:]\s*', '', title)
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

        # Author
        # BALLAST often has author in article metadata
        meta_author = soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            meta["author"] = meta_author["content"].strip()
        else:
            # Try to find author in article
            author_el = soup.select_one(".author, .meta-author, .post-author a")
            if author_el:
                meta["author"] = author_el.get_text(strip=True)

        # Media
        meta["media"] = "BALLAST"
        
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
        
        # Find article container
        article = soup.find('article')
        if not article:
            return ""
        
        # Create a copy to avoid modifying original
        container = article.__copy__()
        
        # Remove unwanted elements
        for element in container(["script", "style", "nav", "header", "footer", 
                                   "aside", "form", "iframe", "noscript", "figure", 
                                   "button", "input", "img", "video", "audio"]):
            element.extract()

        # Remove specific junk selectors
        junk_selectors = [
            ".share", ".social", ".sharing", ".sharedaddy",
            ".author", ".post-author", ".author-bio",
            ".tags", ".post-tags", ".category",
            ".comments", ".comment-form",
            ".related", ".related-posts",
            ".navigation", ".nav-links",
            ".meta", ".post-meta", ".entry-meta",
            ".wp-caption", ".wp-caption-text",
            "[class*='share']", "[class*='social']"
        ]
        for selector in junk_selectors:
            for element in container.select(selector):
                element.extract()
        
        # Pre-process: unwrap nested p/div containing other block elements
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
            
            # Skip very short text (likely navigation or metadata)
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
