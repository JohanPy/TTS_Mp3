
from .base import BaseAdapter
from bs4 import BeautifulSoup, NavigableString, Tag
from segments import Segment, segments_to_plain_text
import re
import os

class MediapartAdapter(BaseAdapter):
    def can_handle(self):
        if "Mediapart" in self.filename:
            return True
        if self.soup.select_one("div.news__rich-text-content, div.content-page__full"):
            # Strong signal for Mediapart structure
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

        # Clean title (remove " | Mediapart" suffix)
        title = meta["title"]
        for separator in [" | ", " - "]:
            if separator in title:
                parts = title.split(separator)
                if len(parts) > 1 and "Mediapart" in parts[-1]:
                    title = separator.join(parts[:-1])
        meta["title"] = title

        # Author
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            meta["author"] = meta_author["content"].strip()

        # Media
        meta["media"] = "Mediapart"
        
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
            # If og:description is short (< 300 chars), supplement with article content
            if len(og_desc) < 300:
                long_desc = self._generate_long_description()
                meta["description"] = long_desc if long_desc else og_desc
            else:
                meta["description"] = og_desc
        else:
            # No meta description, generate from content
            meta["description"] = self._generate_long_description()

        # Image
        meta_image = soup.find("meta", property="og:image")
        if meta_image and meta_image.get("content"):
            meta["image_url"] = meta_image["content"].strip()

        return meta
        
    def _extract_segments(self) -> list[Segment]:
        segments: list[Segment] = []

        # 1. Chapô Mediapart (situé hors de news__rich-text-content)
        chapo_el = self.soup.select_one(
            ".news__heading__top__intro, .content-page__intro, .news__intro"
        )
        if chapo_el:
            chapo_text = re.sub(r'\s+([.,;:!?])', r'\1', chapo_el.get_text(separator=" ", strip=True))
            if chapo_text and len(chapo_text) >= 25:
                segments.append(Segment("chapo", chapo_text))

        raw_main = self.soup.select_one("div.news__rich-text-content, div.content-page__full")
        if not raw_main:
            return segments

        main_content = BeautifulSoup(str(raw_main), 'html.parser')

        # Handle dropcaps: keep reader part, remove visual part
        for dropcap_wrapper in main_content.select(".dropcap-wrapper"):
            visual_part = dropcap_wrapper.select_one('[aria-hidden="true"]')
            if visual_part:
                visual_part.extract()
            reader_part = dropcap_wrapper.select_one(".screen-reader-only")
            if reader_part:
                reader_part.unwrap()

        # Remove "À lire aussi" blocks, accessibility hidden text, pull-quotes (highlight), footnotes and newsletter inserts
        for node in main_content.select(
            ".lire-aussi, .r-interne, .read-also, .screen-reader-only, .newsletter-insert, "
            "figure, aside.highlight, span.spip_note_ref, a.spip_note, sup.footnote"
        ):
            node.extract()

        for aside in main_content.find_all("aside"):
            aside_classes = aside.get("class") or []
            if "box" in aside_classes:
                continue
            aside_text = aside.get_text(" ", strip=True)
            if "highlight" in aside_classes or not aside_classes or re.search(r'inscrivez-vous|newsletter|lettre enquête', aside_text, re.IGNORECASE):
                aside.extract()

        # Supprimer les paragraphes newsletter feuille insérés hors <aside>
        for p in main_content.find_all("p"):
            if p.find(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'aside', 'blockquote']):
                continue
            p_txt = p.get_text(" ", strip=True)
            if len(p_txt) < 350 and re.search(
                r'Voulez-vous plonger dans les\s+secrets de\s+fabrication|Rejoignez la\s+[«"].*?lettre enquête',
                p_txt,
                re.IGNORECASE,
            ):
                p.extract()

        block_names = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'blockquote', 'ul', 'ol', 'div', 'aside', 'section'}

        def _clean_inline_text(raw: str) -> str:
            t = re.sub(r'\s+', ' ', raw).strip()
            return re.sub(r'\s+([.,;:!?])', r'\1', t)

        def _is_box_tag(tag: Tag) -> bool:
            return 'box' in (tag.get('class') or [])

        def _emit_paragraph(text: str, tag: Tag | None, para_kind: str) -> None:
            cleaned = _clean_inline_text(text)
            if not cleaned:
                return
            if "À lire aussi" in cleaned and len(cleaned) < 50:
                return
            is_bq = (para_kind == "paragraph" and tag is not None and self._is_bold_question_tag(tag, cleaned))
            segments.append(Segment(para_kind, cleaned, is_bold_question=is_bq))

        def _walk_node(node: Tag, para_kind: str = "paragraph") -> None:
            if not isinstance(node, Tag):
                return

            if _is_box_tag(node):
                header = node.select_one('.box__header')
                if header:
                    h_txt = _clean_inline_text(header.get_text(separator=" ", strip=True))
                    if h_txt:
                        segments.append(Segment("box_title", h_txt))
                content_box = node.select_one('.box__content') or node
                for child in content_box.children:
                    if isinstance(child, Tag) and child is not header:
                        _walk_node(child, para_kind="box_body")
                return

            name = node.name or ""
            if name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                txt = _clean_inline_text(node.get_text(separator=" ", strip=True))
                if txt:
                    segments.append(Segment("heading", txt))
                return

            if name == 'blockquote':
                txt = _clean_inline_text(node.get_text(separator=" ", strip=True))
                if txt:
                    segments.append(Segment("quote_block", txt))
                return

            if name == 'li':
                txt = _clean_inline_text(node.get_text(separator=" ", strip=True))
                if txt:
                    segments.append(Segment("list_item" if para_kind == "paragraph" else para_kind, txt))
                return

            if name == 'p':
                has_nested_block = node.find(
                    lambda t: isinstance(t, Tag) and (
                        t.name in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'li')
                        or _is_box_tag(t)
                    )
                )
                if not has_nested_block:
                    _emit_paragraph(node.get_text(separator=" ", strip=True), node, para_kind)
                    return

                # <p> contenant des blocs imbriqués : flusher les inline par morceaux entre blocs
                buf: list[str] = []

                def _flush_buf() -> None:
                    if not buf:
                        return
                    joined = _clean_inline_text(" ".join(buf))
                    buf.clear()
                    if joined:
                        _emit_paragraph(joined, None, para_kind)

                for child in node.children:
                    if isinstance(child, NavigableString):
                        if str(child).strip():
                            buf.append(str(child).strip())
                    elif isinstance(child, Tag):
                        if child.name in block_names or _is_box_tag(child):
                            _flush_buf()
                            _walk_node(child, para_kind=para_kind)
                        else:
                            t_inline = child.get_text(separator=" ", strip=True)
                            if t_inline:
                                buf.append(t_inline)
                _flush_buf()
                return

            for child in node.children:
                if isinstance(child, Tag):
                    _walk_node(child, para_kind=para_kind)

        _walk_node(main_content)
        return segments

    def _extract_content(self):
        return segments_to_plain_text(self._extract_segments())


