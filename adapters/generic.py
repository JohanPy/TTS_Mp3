
from .base import BaseAdapter
from .reader_mode import reader_extract_content, reader_extract_metadata
from bs4 import Tag, NavigableString
import json
import re
import os

class GenericAdapter(BaseAdapter):
    def can_handle(self):
        return True # Fallback

    def extract_metadata(self):
        soup = self.soup
        filename = self.filename
        meta = super().extract_metadata()
        
        filename_title = os.path.splitext(filename)[0]

        # --- Titre ---
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

        # Nettoyage
        title = meta["title"]
        for separator in [" | ", " - ", " : "]:
            if separator in title:
                parts = title.split(separator)
                if len(parts) > 1 and len(parts[-1]) < 30: 
                    title = separator.join(parts[:-1])
        meta["title"] = title

        # --- Auteur (JSON-LD & Meta) ---
        # (Simplified extraction for generic)
        author = "Unknown Author"
        meta_author = soup.find("meta", attrs={"name": "author"}) or \
                      soup.find("meta", property="article:author")
        if meta_author and meta_author.get("content"):
             author = meta_author["content"].strip()
        meta["author"] = author

        # --- URL ---
        meta_url = soup.find("meta", property="og:url") or soup.find("link", rel="canonical")
        if meta_url:
            if meta_url.name == "link":
                meta["url"] = meta_url.get("href", "").strip()
            else:
                meta["url"] = meta_url.get("content", "").strip()

        # --- Date ---
        meta_date = soup.find("meta", property="article:published_time") or \
                    soup.find("meta", attrs={"name": "date"})
        if meta_date and meta_date.get("content"):
            meta["date"] = meta_date["content"].strip()

        # --- Description ---
        # Try og:description first, but generate a longer one from content
        meta_desc = soup.find("meta", property="og:description") or \
                    soup.find("meta", attrs={"name": "description"})
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

        # --- Image ---
        meta_image = soup.find("meta", property="og:image")
        if meta_image and meta_image.get("content"):
            meta["image_url"] = meta_image["content"].strip()

        # --- Média ---
        og_site_name = soup.find("meta", property="og:site_name")
        if og_site_name and og_site_name.get("content"):
            meta["media"] = og_site_name["content"].strip()
        else:
            app_name = soup.find("meta", attrs={"name": "application-name"})
            if app_name and app_name.get("content"):
                meta["media"] = app_name["content"].strip()
                
        # --- Trafilatura Reader Mode Fallback ---
        # Si certains champs importants sont vides, essayons Reader Mode
        reader_meta = None
        if not meta["title"] or not meta["author"] or not meta["date"]:
            reader_meta = reader_extract_metadata(str(soup))
            
            if not meta["title"] and reader_meta.get("title"):
                meta["title"] = reader_meta["title"]
            
            if (not meta["author"] or meta["author"] == "Unknown Author") and reader_meta.get("author"):
                meta["author"] = reader_meta["author"]
                
            if not meta["date"] and reader_meta.get("date"):
                meta["date"] = reader_meta["date"]

        # Ensure title default again if reader mode didn't find it
        if not meta["title"]:
            meta["title"] = filename_title

        return meta

    def get_content(self):
        soup = self.soup
        html_string = str(soup)
        
        # 0. Essai via Reader Mode (Trafilatura) en priorité pour le Generic
        reader_content = reader_extract_content(html_string)
        if reader_content and len(reader_content) > 100:
            return reader_content

        # 1. Cleaning Fallback (si Reader Mode a échoué)
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe", "noscript", "figure", "button", "input"]):
            element.extract()

        junk_selectors = [
            ".share", ".social", ".comment", ".meta", ".tags", ".banner", ".promo", ".newsletter",
            ".navigation", ".sidebar", ".related", ".breadcrumbs", ".author-bio", ".date", 
            "#cookie-banner", "#subscribe-modal", ".paywall", ".teaser", ".recruitment",
            ".noprint", ".hidden", ".visually-hidden", ".feed"
        ]
        for selector in junk_selectors:
            for element in soup.select(selector):
                element.extract()
        
        # 2. Main Content Detection
        main_content = soup.find('article')
        if not main_content:
            main_content = soup.find('main')
        if not main_content:
            main_content = soup.find('div', role='main')
            
        if not main_content:
            max_p_count = 0
            best_div = None
            for div in soup.find_all('div'):
                p_count = len(div.find_all('p', recursive=False))
                if p_count > max_p_count:
                    max_p_count = p_count
                    best_div = div
            if best_div and max_p_count > 3:
                main_content = best_div

        if not main_content:
            main_content = soup.body

        if not main_content:
            return ""

        # 3. Text Generation
        text_parts = []
        relevant_tags = main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li'])
        
        for tag in relevant_tags:
            text = tag.get_text(separator=" ", strip=True)
            if not text: continue
            
            if not text[-1] in '.!?':
                text = text + '.'
            
            if tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                text_parts.append(f"{text}...")
            elif tag.name == 'p':
                text_parts.append(f"{text}.")
            elif tag.name == 'li':
                text_parts.append(f"{text},")

        result = " ".join(text_parts)
        result = re.sub(r'\.{5,}', '...', result)
        result = re.sub(r'\.{2}', '.', result)
        result = re.sub(r',\.', '.', result)
        
        return result
