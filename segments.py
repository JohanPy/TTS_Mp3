"""
Modèle de segments structurés pour la synthèse vocale riche (« pseudo-SSML »).

Chaque article est découpé en blocs typés (intro, chapô, intertitre, paragraphe,
citation longue, question/réponse d'entretien, encadré, liste) puis regroupé en
chunks optimisés pour respecter le quota d'edge-tts tout en variant voix,
prosodie, pauses et chapitres ID3.
"""

from dataclasses import dataclass, field
import re
from typing import Iterable

from text_utils import (
    format_list_item_for_tts,
    prepare_text_for_tts,
    strip_leading_duplicate_title,
)


MERGEABLE_KINDS = frozenset({
    "paragraph",
    "interview_a",
    "box_body",
    "list_item",
    "chapo",
    "quote_block",
})

_KNOWN_INTERVIEWERS = (
    r"Basta!|Alternative libertaire|RFI|Mediapart|BALLAST|Reporterre|Acrimed|"
    r"Le Monde|L'Humanité|Politis|Regards|La Horde|Question|Q"
)
_EXCLUDED_COLON_PREFIXES = frozenset({
    "note", "encadré", "source", "sources", "mise à jour", "erratum",
    "précision", "avertissement", "rappel", "citation", "exemple", "nb",
})
_INTERVIEW_COLON_RE = re.compile(
    r"^([A-ZÀ-Ÿ][\w\s!\.'’\-]{1,28})\s*:\s+(.+\?)\s*$"
)
_KNOWN_PREFIX_STRIP_RE = re.compile(
    rf"^(?:{_KNOWN_INTERVIEWERS})\s*:\s*",
    re.IGNORECASE,
)


@dataclass
class Segment:
    """Bloc sémantique d'un document à synthétiser."""
    kind: str
    text: str
    chapter_title: str | None = None
    is_bold_question: bool = False


@dataclass
class SynthesisChunk:
    """Unité d'appel TTS regroupant un ou plusieurs paragraphes de même profil."""
    kind: str
    paragraphs: list[str] = field(default_factory=list)
    chapter_title: str | None = None

    @property
    def is_tts(self) -> bool:
        return bool(self.paragraphs)

    @property
    def text(self) -> str:
        return " ".join(self.paragraphs)


def _ensure_terminal_punct(text: str, *, kind: str = "paragraph") -> str:
    """Garantit une ponctuation finale propre selon le type de segment."""
    t = text.strip()
    if not t:
        return ""
    if kind == "list_item":
        return format_list_item_for_tts(t)
    if t[-1] in ".!?:;…":
        return t
    return f"{t}."


def segments_to_plain_text(segments: Iterable[Segment]) -> str:
    """
    Convertit une liste de segments en texte plat compatible avec le pipeline
    existant (mode rapide, résumeur IA, rétrocompatibilité adapters).
    """
    parts: list[str] = []
    for seg in segments:
        t = (seg.text or "").strip()
        if not t:
            continue
        if seg.kind == "heading":
            if t[-1] not in ".!?:;…":
                t = f"{t}..."
            elif t[-1] == ".":
                t = t if t.endswith("...") else f"{t.rstrip('.')}..."
        elif seg.kind == "list_item":
            t = format_list_item_for_tts(t)
        else:
            if t[-1] not in ".!?:;…":
                t = f"{t}."
        parts.append(t)

    result = " ".join(parts)
    result = re.sub(r"\.{5,}", "...", result)
    result = re.sub(r"(?<!\.)\.{2}(?!\.)", ".", result)
    result = re.sub(r",\.", ".", result)
    return result.strip()


def split_paragraphs_from_text(text: str) -> list[Segment]:
    """Découpe un texte brut (ex. résumé IA) en segments paragraph."""
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n{2,}", text.strip()) if b.strip()]
    if len(blocks) == 1:
        # Si pas de double saut de ligne, découper sur saut de ligne simple si pertinent
        lines = [ln.strip() for ln in blocks[0].splitlines() if ln.strip()]
        if len(lines) > 1:
            blocks = lines
    return [Segment("paragraph", b) for b in blocks]


def detect_interview_segments(segments: list[Segment]) -> tuple[list[Segment], bool]:
    """
    Détecte si un article est un entretien (au moins 3 questions structurées)
    et bascule les questions en 'interview_q' et les réponses en 'interview_a'.
    Supprime les préfixes d'interviewer répétitifs à partir de la 2e question.
    """
    question_indices: list[int] = []
    detected_prefixes: list[str | None] = []

    for idx, seg in enumerate(segments):
        if seg.kind != "paragraph":
            continue
        t = seg.text.strip()
        m = _INTERVIEW_COLON_RE.match(t)
        prefix: str | None = None
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in _EXCLUDED_COLON_PREFIXES:
                prefix = cand
        if seg.is_bold_question or prefix is not None:
            if t.endswith("?") or prefix is not None:
                question_indices.append(idx)
                detected_prefixes.append(prefix)

    if len(question_indices) < 3:
        return segments, False

    q_set = set(question_indices)
    first_prefix = next((p for p in detected_prefixes if p), None)
    out: list[Segment] = []
    in_answer = False
    seen_q_count = 0

    for idx, seg in enumerate(segments):
        if idx in q_set:
            q_text = seg.text.strip()
            if seen_q_count >= 1:
                # Retirer un préfixe média/interviewer répété à partir de la 2e question
                stripped = _KNOWN_PREFIX_STRIP_RE.sub("", q_text)
                if stripped == q_text and first_prefix:
                    pat = re.compile(rf"^{re.escape(first_prefix)}\s*:\s*", re.IGNORECASE)
                    stripped = pat.sub("", q_text)
                if stripped and len(stripped) >= 10:
                    q_text = stripped[0].upper() + stripped[1:] if stripped[0].islower() else stripped
            seen_q_count += 1
            in_answer = True
            out.append(Segment(
                kind="interview_q",
                text=q_text,
                chapter_title=seg.chapter_title,
            ))
        elif seg.kind in ("heading", "box_title", "box_body"):
            in_answer = False
            out.append(seg)
        elif in_answer and seg.kind in ("paragraph", "list_item"):
            out.append(Segment(
                kind="interview_a",
                text=seg.text,
                chapter_title=seg.chapter_title,
            ))
        else:
            out.append(seg)

    return out, True


def split_long_quotes(segments: list[Segment], min_quote_chars: int = 180) -> list[Segment]:
    """
    Extrait les très longues citations françaises (« … » >= min_quote_chars)
    hors des paragraphes narratifs pour leur appliquer une voix/prosodie dédiée.
    """
    if min_quote_chars <= 0:
        return segments

    quote_re = re.compile(rf"«\s*([^»]{{{min_quote_chars},}}?)\s*»")
    out: list[Segment] = []

    for seg in segments:
        if seg.kind != "paragraph":
            out.append(seg)
            continue

        text = seg.text
        matches = list(quote_re.finditer(text))
        if not matches:
            out.append(seg)
            continue

        cursor = 0
        pending_chapter = seg.chapter_title
        for m in matches:
            before = text[cursor:m.start()].strip()
            quote_inner = m.group(1).strip()

            if before and len(re.sub(r"[\W_]+", "", before)) >= 3:
                out.append(Segment("paragraph", before, chapter_title=pending_chapter))
                pending_chapter = None

            if quote_inner:
                out.append(Segment("quote_block", quote_inner, chapter_title=pending_chapter))
                pending_chapter = None

            cursor = m.end()

        after = text[cursor:].strip()
        # Nettoyer un reste d'incise de type ", explique le chercheur."
        after_clean = re.sub(r"^[,;:\s]+", "", after).strip()
        if after_clean and len(re.sub(r"[\W_]+", "", after_clean)) >= 4:
            if after_clean[0].islower():
                after_clean = after_clean[0].upper() + after_clean[1:]
            out.append(Segment("paragraph", after_clean, chapter_title=pending_chapter))

    return out


def _clean_meta_fields(meta: dict) -> tuple[str, str, str]:
    """Normalise title, author et media comme build_article_intro."""
    clean_media = (meta.get("media") or "").strip()
    if not clean_media or clean_media == "Unknown Media":
        clean_media = ""
    elif "|" in clean_media:
        clean_media = clean_media.split("|", 1)[0].strip()

    clean_author = (meta.get("author") or "").strip()
    if not clean_author or clean_author == "Unknown Author":
        clean_author = ""
    elif clean_media and clean_author.lower() == clean_media.lower():
        clean_author = ""

    clean_title = (meta.get("title") or "").strip()
    if not clean_title or clean_title == "Unknown Title":
        clean_title = ""

    return clean_title, clean_author, clean_media


def enrich_article_segments(
    body_segments: list[Segment],
    meta: dict,
    *,
    long_quote_min_chars: int = 180,
    enable_interview_detection: bool = True,
) -> list[Segment]:
    """
    Construit la séquence complète et nettoyée de segments d'un article :
    intro structurée + chapô/corps nettoyé + détection d'entretien + citations longues + outro.
    """
    clean_title, clean_author, clean_media = _clean_meta_fields(meta)

    working = [
        Segment(
            kind=s.kind,
            text=(s.text or "").strip(),
            chapter_title=s.chapter_title,
            is_bold_question=s.is_bold_question,
        )
        for s in body_segments
        if (s.text or "").strip()
    ]

    # Retirer le titre dupliqué au début du premier bloc non-intro
    if working and clean_title:
        stripped = strip_leading_duplicate_title(clean_title, working[0].text)
        if not stripped or len(stripped.strip()) < 15:
            if stripped != working[0].text:
                working.pop(0)
        else:
            working[0].text = stripped

    if enable_interview_detection:
        working, _ = detect_interview_segments(working)

    working = split_long_quotes(working, min_quote_chars=long_quote_min_chars)

    intro_segments: list[Segment] = []
    if clean_media:
        intro_segments.append(Segment("intro_meta", prepare_text_for_tts(f"Article de {clean_media}.")))
    if clean_title:
        title_clean = prepare_text_for_tts(_ensure_terminal_punct(clean_title, kind="intro_title"))
        if title_clean:
            intro_segments.append(Segment("intro_title", title_clean, chapter_title="Introduction"))
    if clean_author:
        author_clean = prepare_text_for_tts(f"Par {clean_author}.")
        if author_clean:
            chap = "Introduction" if not any(s.chapter_title for s in intro_segments) else None
            intro_segments.append(Segment("intro_meta", author_clean, chapter_title=chap))

    if intro_segments and not any(s.chapter_title for s in intro_segments):
        intro_segments[0].chapter_title = "Introduction"

    cleaned_body: list[Segment] = []
    prev_norm: str | None = None
    chapo_norm: str | None = None

    for seg in working:
        raw_t = seg.text
        if seg.kind == "quote_block":
            raw_t = re.sub(r"^Citation\s*:\s*", "", raw_t, flags=re.IGNORECASE).strip()

        prepared = prepare_text_for_tts(raw_t)
        if not prepared:
            continue

        if seg.kind == "box_title" and not re.match(r"^Encadré\b", prepared, re.IGNORECASE):
            chap_label = f"Encadré : {prepared[:70]}"
            prepared = f"Encadré : {prepared}"
        elif seg.kind == "box_title":
            chap_label = prepared[:75]
        elif seg.kind == "heading":
            chap_label = prepared.rstrip(".")[:80]
        else:
            chap_label = seg.chapter_title

        prepared = _ensure_terminal_punct(prepared, kind=seg.kind)
        if not prepared:
            continue

        norm = re.sub(r"[\W_]+", " ", prepared.lower()).strip()
        if len(norm) > 40 and norm == prev_norm:
            continue
        if seg.kind == "chapo" and len(norm) > 30:
            chapo_norm = norm
        elif chapo_norm and seg.kind == "paragraph" and norm == chapo_norm:
            continue

        if len(norm) > 40:
            prev_norm = norm

        cleaned_body.append(Segment(
            kind=seg.kind,
            text=prepared,
            chapter_title=chap_label,
        ))

    if not cleaned_body:
        return []

    result = intro_segments + cleaned_body
    result.append(Segment("outro", ""))
    return result


def build_grouped_summary_segments(media: str, date_bucket: str, entries: list[dict]) -> list[Segment]:
    """Construit les segments structurés d'un MP3 de résumés groupés."""
    n = len(entries)
    ordinals = [
        "Premier", "Deuxième", "Troisième", "Quatrième", "Cinquième",
        "Sixième", "Septième", "Huitième", "Neuvième", "Dixième",
    ]

    segments: list[Segment] = []
    intro_text = prepare_text_for_tts(
        f"Résumés {media} du {date_bucket}. {n} article{'s' if n > 1 else ''}."
    )
    if intro_text:
        segments.append(Segment(
            kind="group_intro",
            text=_ensure_terminal_punct(intro_text),
            chapter_title="Introduction",
        ))

    for i, entry in enumerate(entries):
        title = (entry.get("title") or "Sans titre").strip()
        summary = (entry.get("summary") or "").strip()
        label = f"{ordinals[i]} article sur {n}" if i < len(ordinals) else f"Article {i + 1} sur {n}"

        clean_title = prepare_text_for_tts(f"{label} : {title}.")
        if clean_title:
            segments.append(Segment(
                kind="group_item_title",
                text=_ensure_terminal_punct(clean_title),
                chapter_title=f"{i + 1}. {prepare_text_for_tts(title)[:70]}",
            ))

        clean_summary = prepare_text_for_tts(summary)
        if clean_summary:
            segments.append(Segment(
                kind="group_item_body",
                text=_ensure_terminal_punct(clean_summary),
            ))

    if segments:
        segments.append(Segment("outro", ""))
    return segments


def _coalesce_pass(segments: list[Segment], max_chunk_chars: int) -> list[SynthesisChunk]:
    """Regroupe les segments consécutifs compatibles jusqu'à max_chunk_chars."""
    chunks: list[SynthesisChunk] = []

    for seg in segments:
        if seg.kind == "outro" and not seg.text:
            chunks.append(SynthesisChunk(kind="outro", paragraphs=[], chapter_title=seg.chapter_title))
            continue

        t = (seg.text or "").strip()
        if not t:
            continue

        if (
            chunks
            and chunks[-1].is_tts
            and chunks[-1].kind == seg.kind
            and seg.kind in MERGEABLE_KINDS
            and seg.chapter_title is None
            and (sum(len(p) for p in chunks[-1].paragraphs) + len(chunks[-1].paragraphs) + len(t)) <= max_chunk_chars
        ):
            chunks[-1].paragraphs.append(t)
        else:
            chunks.append(SynthesisChunk(
                kind=seg.kind,
                paragraphs=[t],
                chapter_title=seg.chapter_title,
            ))

    return chunks


def _tts_count(chunks: list[SynthesisChunk]) -> int:
    return sum(1 for c in chunks if c.is_tts)


def coalesce_segments(
    segments: list[Segment],
    max_chunk_chars: int = 3200,
    max_tts_calls: int = 60,
) -> list[SynthesisChunk]:
    """
    Regroupe les segments consécutifs de même profil et applique un garde-fou
    pour garantir que le nombre d'appels TTS ne dépasse jamais max_tts_calls.
    """
    chunks = _coalesce_pass(segments, max_chunk_chars)
    if _tts_count(chunks) <= max_tts_calls:
        return chunks

    # Passe 1 : replier les quote_block en paragraph
    folded = [
        Segment("paragraph", s.text, s.chapter_title) if s.kind == "quote_block" else s
        for s in segments
    ]
    chunks = _coalesce_pass(folded, max_chunk_chars)
    if _tts_count(chunks) <= max_tts_calls:
        return chunks

    # Passe 2 : replier list_item et box_body en paragraph
    folded = [
        Segment("paragraph", s.text, s.chapter_title)
        if s.kind in ("list_item", "box_body") else s
        for s in folded
    ]
    chunks = _coalesce_pass(folded, max_chunk_chars)
    if _tts_count(chunks) <= max_tts_calls:
        return chunks

    # Passe 3 : fusionner les plus petits chunks adjacents (en préservant les chapitres)
    tts_only = [c for c in chunks if c.is_tts]
    outro = [c for c in chunks if not c.is_tts]
    while len(tts_only) > max_tts_calls and len(tts_only) > 1:
        # Trouver la paire adjacente de taille combinée minimale
        best_idx = 0
        best_len = float("inf")
        for i in range(len(tts_only) - 1):
            # Ne pas fusionner les intro_* si autre choix existe
            pair_len = len(tts_only[i].text) + len(tts_only[i + 1].text)
            if tts_only[i].kind.startswith("intro_") or tts_only[i + 1].kind.startswith("intro_"):
                pair_len += 50000
            if pair_len < best_len:
                best_len = pair_len
                best_idx = i

        a = tts_only[best_idx]
        b = tts_only[best_idx + 1]
        merged_kind = a.kind if a.kind == b.kind else "paragraph"
        merged = SynthesisChunk(
            kind=merged_kind,
            paragraphs=a.paragraphs + b.paragraphs,
            chapter_title=a.chapter_title or b.chapter_title,
        )
        tts_only[best_idx:best_idx + 2] = [merged]

    return tts_only + outro
