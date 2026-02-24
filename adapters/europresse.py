
from .base import BaseAdapter

class EuropresseAdapter(BaseAdapter):
    def can_handle(self):
        # Europresse often has "Europresse" title or specific structure
        # Check extraction logic from original file
        title = self.soup.find("title")
        if title and "Europresse" in title.get_text():
            return True
        # Original script logic: if meta["title"] == "Europresse" or ... 
        # Here we try to detect before extraction.
        # Often Europresse files are just named "Europresse..." or have it in content
        if self.soup.select_one(".titreArticleVisu, .rdp__articletitle"):
            return True
        return False

    def extract_metadata(self):
        meta = super().extract_metadata()
        
        # Titre
        europresse_title = self.soup.select_one(".titreArticleVisu, .rdp__articletitle")
        if europresse_title:
            meta["title"] = europresse_title.get_text(separator=" ", strip=True)
        else:
            meta["title"] = "Europresse Article"
        
        # Auteur
        europresse_author = self.soup.select_one(".sm-margin-bottomNews")
        if europresse_author:
            meta["author"] = europresse_author.get_text(separator=" ", strip=True)

        # Média
        europresse_media = self.soup.select_one(".DocPublicationName, .rdp__DocPublicationName")
        if europresse_media:
            media_text = europresse_media.get_text(separator="|", strip=True)
            media = media_text.split("|")[0].strip()
            meta["media"] = media.replace("(site web)", "").strip()
        
        # Description - Generate from article content
        meta["description"] = self._generate_long_description()
            
        return meta

    def get_content(self):
        # Specific selector for Europresse
        main_content = self.soup.select_one("div.DocText, div.doc-content, section.doc-content")
        
        if not main_content:
            return ""

        # Pre-process: unwrap
        while True:
            wrapper = main_content.find(lambda t: t.name in ['p', 'div'] and t.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
            if not wrapper: break
            wrapper.unwrap()

        text_parts = []
        for tag in main_content.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
            text = tag.get_text(separator=" ", strip=True)
            if not text: continue
            
            if not text[-1] in '.!?':
                text = text + '.'
            
            if tag.name.startswith('h'):
                text_parts.append(f"{text}...")
            else:
                text_parts.append(f"{text}.")
                
        return " ".join(text_parts)
