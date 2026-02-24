
from .base import BaseAdapter
from bs4 import Tag
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
        
    def get_content(self):
        soup = self.soup
        
        # Find main content container
        main_content = soup.find('main', class_='main-content')
        if not main_content:
            main_content = soup.find('main')
        if not main_content:
            main_content = soup.find('article')
        if not main_content:
            main_content = soup.body
        
        if not main_content:
            return ""
        
        # Create a copy to avoid modifying original
        container = main_content.__copy__()
        
        # Remove unwanted elements
        for element in container(["script", "style", "nav", "header", "footer", 
                                   "aside", "form", "iframe", "noscript", "figure", 
                                   "button", "input", "img", "video", "audio"]):
            element.extract()

        # Remove specific junk selectors - Academic articles have footnotes
        junk_selectors = [
            ".share", ".social",
            ".footnotes", ".notes", "[class*='footnote']", "[class*='note-']",
            ".references", ".bibliography", ".biblio",
            ".author", ".authors", ".author-info",
            ".doi", "[class*='doi']",
            ".comments",
            ".related",
            ".navigation",
            ".meta", ".article-meta",
            ".sidebar", ".widget"
        ]
        for selector in junk_selectors:
            for element in container.select(selector):
                element.extract()

        # Remove short metadata paragraphs at the beginning
        paragraphs = container.find_all('p')
        for p in paragraphs[:5]:  # Only check first 5
            text = p.get_text(strip=True)
            # Skip DOI, author names, etc.
            if len(text) < 50:
                if "DOI" in text or re.match(r'^[A-Z][a-zéèàù]+\s*[A-Z]', text):
                    p.extract()
                elif len(text.split()) <= 3:
                    p.extract()
        
        # Pre-process: unwrap nested elements
        while True:
            wrapper = container.find(lambda t: t.name in ['p', 'div'] and 
                                     t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper:
                break
            wrapper.unwrap()
            
        # Extract text from relevant tags
        text_parts = []
        seen_texts = set()  # Avoid duplicates
        
        for tag in container.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote', 'li']):
            text = tag.get_text(separator=" ", strip=True)
            if not text:
                continue
            
            # Skip very short text
            if len(text) < 15:
                continue
            
            # Skip footnote references (numbers in brackets)
            if re.match(r'^\[\d+\]$', text) or re.match(r'^\d+\.$', text):
                continue
            
            # === DÉTECTION DE BIBLIOGRAPHIE PAR CONTENU ===
            # Arrêter si on rencontre une référence bibliographique typique
            # Pattern: "Auteur, A. (YYYY)." ou "Auteur, A. & Coauteur, B. (YYYY)."
            # Note: les années peuvent être tronquées par le nettoyage, donc \d{2,4}
            if re.match(r'^[A-Z][a-zéèàùâêîôûç\-]+,\s*[A-Z]\.?\s*(?:[,&]\s*[A-Z][a-zéèàùâêîôûç\-]+,\s*[A-Z]\.?\s*)*\(\d{2,4}\)', text):
                break  # Stop processing - we've hit the bibliography
            
            # Pattern alternatif: "Auteur, Prénom." en début
            if re.match(r'^[A-Z][a-zéèàùâêîôûç\-]+,\s*[A-Z][a-zéèàùâêîôûç]+\.', text) and '(' in text and ')' in text:
                break
            
            # Arrêter si "Conflits d'intérêts" ou fin d'article typique
            if re.match(r'^Conflits?\s+d.intérêt', text, re.IGNORECASE):
                break
            
            # Arrêter si on rencontre "Référence électronique"
            if re.match(r'^Référence électronique', text, re.IGNORECASE):
                break
            
            # Arrêter si le texte ressemble à une note numérotée (1, 2, 3...)
            # Pattern: numéro suivi d'un texte explicatif
            if re.match(r'^\d{1,2}\s+[A-Z]', text) and len(text) < 300:
                # C'est probablement une note de bas de page
                continue
            
            # Skip duplicates
            text_hash = text[:50]
            if text_hash in seen_texts:
                continue
            seen_texts.add(text_hash)
                
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
