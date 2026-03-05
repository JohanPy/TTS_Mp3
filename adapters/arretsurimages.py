from .base import BaseAdapter
import re
import os

class ArretSurImagesAdapter(BaseAdapter):
    """Adapter for Arrêt sur images (arretsurimages.net)"""
    
    def can_handle(self):
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "Arrêt sur images" in og_site.get("content", ""):
            return True
            
        og_url = self.soup.find("meta", property="og:url")
        if og_url and "arretsurimages.net" in og_url.get("content", ""):
            return True
            
        if "Arrêt sur images" in self.filename or "Arr_t sur images" in self.filename:
            return True
            
        return False

    def extract_metadata(self):
        meta = super().extract_metadata()
        soup = self.soup
        
        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r'\s*\|\s*Arrêt sur images\s*$', '', title, flags=re.IGNORECASE)
            meta["title"] = title

        # Author
        author = None
        # Meta name="author" or article:author doesn't exist on all pages, but we check just in case
        meta_author = soup.find("meta", attrs={"name": "author"}) or soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()
            
        if not author:
            # Often the author is in .author-name
            author_el = soup.select_one(".author-name, .chronic-author")
            if author_el:
                # E.g. "Pauline Bock@PaulineBock" -> "Pauline Bock", but we can just clean the @
                text = author_el.get_text(separator=" ", strip=True)
                # Split at @ in case there's a Twitter handle appended
                text = text.split("@")[0].strip()
                author = text
                
        if author:
            meta["author"] = author

        # Media (hardcoded)
        meta["media"] = "Arrêt sur images"
        
        # URL
        meta_url = soup.find("meta", property="og:url")
        if meta_url:
            meta["url"] = meta_url.get("content", "").strip()

        # Date
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date:
            meta["date"] = meta_date.get("content", "").strip()

        # Description
        meta_desc = soup.find("meta", property="og:description")
        if meta_desc:
            meta["description"] = meta_desc.get("content", "").strip()

        # Image
        meta_image = soup.find("meta", property="og:image")
        if meta_image:
            meta["image_url"] = meta_image.get("content", "").strip()

        return meta

    def get_content(self):
        """Extract the main article content specifically avoiding comments panel."""
        soup = self.soup
        
        # 1. Target the primary article containers
        # .article is typically the main article container, .article-body is the inner one
        article = soup.find('article', class_='article') 
        if not article:
            article = soup.find('div', class_='article-body')
            
        if not article:
            # Fallback
            return self._reader_extract()

        # Use Trafilatura reader extraction on just the specific article container
        # This gives us pristine results and avoids reader_mode accidentally targeting comments
        return self._reader_extract(str(article))
