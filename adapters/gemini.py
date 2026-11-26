
from .base import BaseAdapter
from segments import Segment, segments_to_plain_text
import os
import re
import logging
from bs4 import Comment

logger = logging.getLogger(__name__)

class GeminiAdapter(BaseAdapter):
    def can_handle(self):
        # Check title or specific meta tags
        # Gemini export often has "Gemini" in title or specific filename pattern
        if "Gemini" in self.filename:
            return True
        if self.soup.find("meta", property="og:site_name", content="Gemini"):
            return True
        return False

    def extract_metadata(self):
        meta = super().extract_metadata()
        meta["author"] = "Gemini"
        meta["media"] = "Google Deepmind"
        
        # 1. Titre: Chercher le H1 dans le bloc markdown
        markdown_div = self.soup.find("div", class_="markdown")
        if markdown_div:
            h1 = markdown_div.find("h1")
            if h1:
                meta["title"] = h1.get_text(separator=" ", strip=True)
                
        # Fallback Titre
        if not meta["title"]:
            clean_name = os.path.splitext(self.filename)[0]
            clean_name = re.sub(r'\(\d+_\d+_\d+.*\)', '', clean_name)
            meta["title"] = clean_name.replace("_", " ").strip()

        # 2. Date
        date_match = re.search(r'\((\d{1,2})_(\d{1,2})_(\d{4})', self.filename)
        if date_match:
            month, day, year = date_match.groups()
            meta["date"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        # 3. URL
        for comment in self.soup.find_all(string=lambda text: isinstance(text, Comment)):
             if "url:" in comment:
                 try:
                     meta["url"] = comment.split("url:")[1].strip().split()[0]
                 except:
                     pass
                 break
        
        # 4. Description - Generate from article content
        meta["description"] = self._generate_long_description()

        return meta


    def _extract_segments(self) -> list[Segment]:
        raw_div = self.soup.find("div", class_="markdown")
        if not raw_div:
            raw_div = self.soup.find("div", class_="message-content")
        if not raw_div:
            return []

        markdown_div = raw_div.__copy__()
        block_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'blockquote', 'ul', 'ol', 'li']
        while True:
            wrapper = markdown_div.find(lambda t: t.name in ['p', 'div', 'blockquote', 'li'] and t.find(block_tags))
            if not wrapper:
                break
            wrapper.unwrap()

        new_contents = []
        buffer = []

        def flush_buffer():
            if not buffer:
                return
            is_empty = True
            for item in buffer:
                if isinstance(item, str):
                    if item.strip():
                        is_empty = False
                        break
                else:
                    is_empty = False
                    break
            if not is_empty:
                new_p = self.soup.new_tag("p")
                for item in buffer:
                    new_p.append(item)
                new_contents.append(new_p)
            buffer.clear()

        original_contents = list(markdown_div.contents)
        markdown_div.clear()
        block_tags_set = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'blockquote', 'ul', 'ol', 'li'}

        for node in original_contents:
            if isinstance(node, str):
                buffer.append(node)
                continue
            if node.name in block_tags_set:
                flush_buffer()
                new_contents.append(node)
            else:
                buffer.append(node)

        flush_buffer()
        for node in new_contents:
            markdown_div.append(node)

        return self._extract_segments_from_container(markdown_div, min_len=1)

    def _extract_content(self):
        return segments_to_plain_text(self._extract_segments())
