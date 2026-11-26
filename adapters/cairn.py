
from .base import BaseAdapter
from bs4 import Tag
from segments import Segment, segments_to_plain_text
import re
import os


class CairnAdapter(BaseAdapter):
    """Adapter for Cairn/Psychologies academic articles (psygenresociete.org and similar)"""
    
    def can_handle(self):
        # Check og:site_name
        og_site = self.soup.find("meta", property="og:site_name")
        if og_site:
            site_name = og_site.get("content", "").lower()
            if "psychologies" in site_name or "cairn" in site_name:
                return True
        
        # Check URL
        og_url = self.soup.find("meta", property="og:url")
        if og_url:
            url = og_url.get("content", "")
            if "psygenresociete.org" in url or "cairn.info" in url:
                return True
        
        # Check filename
        filename_lower = self.filename.lower()
        if "psychologies" in filename_lower or "cairn" in filename_lower:
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
            # Clean " – Psychologies, Genre et Société" suffix
            title = re.sub(r'\s*[-–]\s*Psychologies.*$', '', title, flags=re.IGNORECASE)
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

        # Author - Academic articles often have author in specific format
        meta_author = soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
            meta["author"] = meta_author["content"].strip()
        else:
            # Try to find author in first paragraph or specific classes
            author_el = soup.select_one(".author, .authors, .meta-author")
            if author_el:
                meta["author"] = author_el.get_text(strip=True)
            else:
                # Try first paragraph if it looks like an author name
                main = soup.find('main')
                if main:
                    first_p = main.find('p')
                    if first_p:
                        text = first_p.get_text(strip=True)
                        # Check if it's a name-like short text
                        if len(text) < 50 and len(text.split()) <= 4:
                            meta["author"] = text

        # Media - Extract from og:site_name
        og_site = soup.find("meta", property="og:site_name")
        if og_site and og_site.get("content"):
            meta["media"] = og_site["content"].strip()
        else:
            meta["media"] = "Psychologies, Genre et Société"
        
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
        main_content = soup.find('main', class_='main-content') or soup.find('main') or soup.find('article') or soup.body
        if not main_content:
            return []

        container = main_content.__copy__()
        for element in container(["script", "style", "nav", "header", "footer",
                                   "aside", "form", "iframe", "noscript", "figure",
                                   "button", "input", "img", "video", "audio"]):
            element.extract()

        junk_selectors = [
            ".share", ".social",
            ".footnotes", ".notes", "[class*='footnote']", "[class*='note-']",
            ".references", ".bibliography", ".biblio",
            ".author", ".authors", ".author-info",
            ".doi", "[class*='doi']",
            ".comments", ".related", ".navigation",
            ".meta", ".article-meta", ".sidebar", ".widget"
        ]
        for selector in junk_selectors:
            for element in container.select(selector):
                element.extract()

        paragraphs = container.find_all('p')
        for p in paragraphs[:5]:
            text = p.get_text(strip=True)
            if len(text) < 50:
                if "DOI" in text or re.match(r'^[A-Z][a-zéèàù]+\s*[A-Z]', text):
                    p.extract()
                elif len(text.split()) <= 3:
                    p.extract()

        while True:
            wrapper = container.find(lambda t: t.name in ['p', 'div'] and
                                     t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper:
                break
            wrapper.unwrap()

        segments: list[Segment] = []
        seen_texts: set[str] = set()

        for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'li']):
            if tag.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote']):
                continue
            text = tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 15:
                continue
            if re.match(r'^\[\d+\]$', text) or re.match(r'^\d+\.$', text):
                continue

            if re.match(r'^[A-Z][a-zéèàùâêîôûç\-]+,\s*[A-Z]\.?\s*(?:[,&]\s*[A-Z][a-zéèàùâêîôûç\-]+,\s*[A-Z]\.?\s*)*\(\d{2,4}\)', text):
                break
            if re.match(r'^[A-Z][a-zéèàùâêîôûç\-]+,\s*[A-Z][a-zéèàùâêîôûç]+\.', text) and '(' in text and ')' in text:
                break
            if re.match(r'^Conflits?\s+d.intérêt', text, re.IGNORECASE):
                break
            if re.match(r'^Référence électronique', text, re.IGNORECASE):
                break
            if re.match(r'^\d{1,2}\s+[A-Z]', text) and len(text) < 300:
                continue

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
                segments.append(Segment("paragraph", text, is_bold_question=self._is_bold_question_tag(tag, text)))

        return segments

    def _extract_content(self):
        return segments_to_plain_text(self._extract_segments())
