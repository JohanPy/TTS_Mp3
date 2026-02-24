
from .base import BaseAdapter
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


    def get_content(self):
        markdown_div = self.soup.find("div", class_="markdown")
        if not markdown_div:
            markdown_div = self.soup.find("div", class_="message-content")
            
        if not markdown_div:
            return ""

        # 1. Flatten structure: Unwrap block tags that contain other block tags
        # This fixes issues where <p> contains <h2> or other <p> (invalid but possible)
        block_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'blockquote', 'ul', 'ol', 'li']
        while True:
            # Find a tag that is in block_tags AND contains another tag from block_tags
            # We explicitly exclude 'div' from being unwrapped if it's the root container, but find searches descendants.
            # We want to unwrap P, DIV, BLOCKQUOTE if they have block children.
            wrapper = markdown_div.find(lambda t: t.name in ['p', 'div', 'blockquote', 'li'] and t.find(block_tags))
            if not wrapper: 
                break
            wrapper.unwrap()


        # 2. Re-group inline elements into <p>
        # Unwrapping might have left text nodes and inline tags (em, strong, a) as direct children.
        # We need to wrap them in <p> so they are caught by find_all('p').
        # Using a grouping approach.
        
        new_contents = []
        buffer = []
        
        def flush_buffer():
            if not buffer: return
            # Check if buffer has only whitespace
            is_empty = True
            for item in buffer:
                if isinstance(item, str):
                    if item.strip():
                        is_empty = False
                        break
                else:
                    # Tags are content
                    is_empty = False
                    break
            
            if not is_empty:
                new_p = self.soup.new_tag("p")
                for item in buffer:
                    new_p.append(item)
                new_contents.append(new_p)
            else:
                 # If whitespace, just append? No, discard whitespace between blocks
                 pass
            buffer.clear()

        # Iterate over a copy of children to avoiding modification issues during iteration?
        # Actually we will rebuild the children list.
        original_contents = list(markdown_div.contents)
        markdown_div.clear() # We will refill it
        
        block_tags_set = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'blockquote', 'ul', 'ol', 'li'}
        
        for node in original_contents:
            if isinstance(node, str):
                buffer.append(node)
                continue
                
            if node.name in block_tags_set:
                flush_buffer()
                new_contents.append(node)
            else:
                # Inline tag (em, strong, a, span, br...)
                buffer.append(node)
                
        flush_buffer()
        
        # Refill markdown_div
        for node in new_contents:
            markdown_div.append(node)

        # 3. Extract content linearly
        text_parts = []
        tags_of_interest = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'blockquote']
        
        found_tags = markdown_div.find_all(tags_of_interest)

        
        for element in found_tags:
            # Skip if this element still contains block tags (shouldn't happen due to step 1, but safety first)
            # Exception: blockquote might contain p, we might want to read p inside blockquote.
            # If element is blockquote, we let it pass?
            # Actually, if we stick to the plan: if we unwrap blockquote because it had p, then blockquote is GONE.
            # That might be bad if we want to extract blockquote semantics.
            # But for TTS, reading the text is priority.
            
            # Anti-doublon: If this tag is inside another tag we are also processing?
            # If we flattened, there shouldn't be much nesting.
            # But assume <p><b>Text</b></p>. <b> is not in tags_of_interest. Safe.
            # Assume <ul><li>Text</li></ul>. <ul> unwrapped (if in list). <li> remains.
            
            # Check if this tag is a descendant of another tag in the found list?
            # This is O(N^2).
            # Easier: just check if parent is in tags_of_interest.
            if element.parent and element.parent in found_tags:
                continue

            text = element.get_text(separator=" ", strip=True)
            if not text: continue
            
            if text[-1] not in '.!?:;"':
                text = text + '.'
            
            if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                text_parts.append(f"{text}...")
            elif element.name == 'li':
                text_parts.append(f"{text}") 
            else:
                text_parts.append(text)
        
        result = " ".join(text_parts)
        result = re.sub(r'\.{4,}', '...', result)
        result = re.sub(r'\.\.', '.', result)
        result = re.sub(r'\s+', ' ', result).strip()
        
        return result
