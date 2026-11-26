
from .base import BaseAdapter
from bs4 import Tag
from segments import Segment, segments_to_plain_text
import re
import os


class ManifestoAdapter(BaseAdapter):
    """Adapter for Manifesto XXI articles (manifesto-21.com)"""
    
    def can_handle(self):
        # Check og:site_name
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site and "Manifesto" in og_site.get("content", ""):
            return True
        
        # Check URL
        og_url = self.soup.find("meta", property="og:url")
        if og_url and "manifesto-21.com" in og_url.get("content", ""):
            return True
        
        # Check filename
        if "Manifesto" in self.filename:
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
            # Clean " - Manifesto XXI" suffix
            title = re.sub(r'\s*[-–]\s*Manifesto\s*(XXI|21)?\s*$', '', title, flags=re.IGNORECASE)
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

        # Author - Check multiple sources
        author = None
        
        # 1. Check meta name="author" (most common for Manifesto XXI)
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            author = meta_author["content"].strip()
        
        # 2. Check meta property="article:author"
        if not author:
            meta_author = soup.find("meta", property="article:author")
            if meta_author and meta_author.get("content"):
                author = meta_author["content"].strip()
        
        # 3. Try JSON-LD schema
        if not author:
            import json
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if '@graph' in data:
                            for item in data['@graph']:
                                if item.get('@type') == 'Article' and 'author' in item:
                                    author_data = item['author']
                                    if isinstance(author_data, dict):
                                        author = author_data.get('name', '')
                                    elif isinstance(author_data, str):
                                        author = author_data
                                    break
                        elif 'author' in data:
                            author_data = data['author']
                            if isinstance(author_data, dict):
                                author = author_data.get('name', '')
                            elif isinstance(author_data, str):
                                author = author_data
                except:
                    pass
        
        # 4. Try HTML elements
        if not author:
            author_el = soup.select_one(".author-name, .post-author, .elementor-author-box__name")
            if author_el:
                author = author_el.get_text(strip=True)
        
        if author:
            meta["author"] = author

        # Media
        meta["media"] = "Manifesto XXI"
        
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
        
    def _extract_segments(self) -> list[Segment]:
        soup = self.soup
        article = soup.find('article') or soup.find('main') or soup.body
        if not article:
            return []

        container = article.__copy__()
        for element in container(["script", "style", "nav", "header", "footer",
                                   "aside", "form", "iframe", "noscript", "figure",
                                   "button", "input", "img", "video", "audio"]):
            element.extract()

        junk_selectors = [
            ".share", ".social", ".sharing",
            ".author", ".post-author", ".elementor-author-box",
            ".tags", ".post-tags",
            ".comments", ".related", ".jet-smart-listing",
            ".navigation", ".nav-links",
            ".meta", ".post-meta", ".elementor-post-info",
            ".elementor-widget-jet-woo-builder-archive-sale-badge",
            ".elementor-widget-theme-post-featured-image",
            ".elementor-widget-post-navigation",
            "[class*='share']", "[class*='social']",
            ".jet-listing-dynamic-link", ".elementor-icon-list",
            ".elementor-widget-form", ".footnotes", "a[href^='#fn']", "sup.footnote"
        ]
        for selector in junk_selectors:
            for element in container.select(selector):
                element.extract()

        paragraphs = container.find_all('p')
        for p in paragraphs[:5]:
            text = p.get_text(strip=True)
            if len(text) < 30:
                if re.match(r'^\d{1,2}\s+\w+\s+\d{4}$', text):
                    p.extract()
                elif len(text.split()) <= 3:
                    p.extract()

        while True:
            wrapper = container.find(lambda t: t.name in ['p', 'div'] and
                                     t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper:
                break
            wrapper.unwrap()

        return self._extract_segments_from_container(
            container,
            min_len=15,
            seen_dedup=True,
            skip_patterns=(r'^(?:Ne manquez plus notre Newsletter|Articles en lien|Image à la Une\s*:)',),
        )

    def _extract_content(self):
        return segments_to_plain_text(self._extract_segments())
