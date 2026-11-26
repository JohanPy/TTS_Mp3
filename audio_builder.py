"""
Moteur d'assemblage audio riche pour TTS_Mp3 (« pseudo-SSML » via edge-tts + ffmpeg).

Fonctionnalités :
- Profils prosodiques par type de bloc (voix principale/secondaire, débit, hauteur, volume)
- Pauses inter-paragraphes précises via les événements SentenceBoundary d'edge-tts (0 appel API en plus)
- Silences et earcons discrets synthétisés localement via ffmpeg et mis en cache
- Normalisation loudness EBU R128 (-16 LUFS)
- Table des matières MP3 (chapitres ID3v2 CHAP / CTOC)
"""

import asyncio
from dataclasses import dataclass
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading

import edge_tts
from mutagen.id3 import CHAP, CTOC, CTOCFlags, ID3, TIT2
from mutagen.mp3 import MP3

from segments import Segment, SynthesisChunk, coalesce_segments

logger = logging.getLogger(__name__)

DEFAULT_AUDIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "tts_mp3_audio_assets_v1")
_asset_lock = threading.Lock()


@dataclass(frozen=True)
class AudioProfile:
    """Paramètres prosodiques et temporels pour un type de segment."""
    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    earcon_before: str | None = None
    earcon_after: str | None = None


@dataclass
class RichAudioConfig:
    """Configuration du moteur d'assemblage audio riche."""
    primary_voice: str = "fr-FR-VivienneMultilingualNeural"
    secondary_voice: str = "fr-FR-RemyMultilingualNeural"
    earcons: bool = True
    loudnorm: bool = True
    inter_paragraph_pause_ms: int = 450
    long_quote_min_chars: int = 180
    max_tts_calls: int = 60


def get_profile(kind: str, cfg: RichAudioConfig) -> AudioProfile:
    """Retourne le profil prosodique associé à un type de segment."""
    p = cfg.primary_voice
    s = cfg.secondary_voice or cfg.primary_voice

    profiles = {
        "intro_meta": AudioProfile(
            voice=s, rate="-4%", pitch="+0Hz", volume="+0%",
            pause_before_ms=0, pause_after_ms=450,
        ),
        "intro_title": AudioProfile(
            voice=p, rate="-6%", pitch="+0Hz", volume="+3%",
            pause_before_ms=250, pause_after_ms=700,
        ),
        "chapo": AudioProfile(
            voice=p, rate="-3%", pitch="-1Hz", volume="+0%",
            pause_before_ms=300, pause_after_ms=900, earcon_after="section",
        ),
        "heading": AudioProfile(
            voice=p, rate="-8%", pitch="-1Hz", volume="+4%",
            pause_before_ms=900, pause_after_ms=550, earcon_before="section",
        ),
        "paragraph": AudioProfile(
            voice=p, rate="+0%", pitch="+0Hz", volume="+0%",
            pause_before_ms=0, pause_after_ms=450,
        ),
        "list_item": AudioProfile(
            voice=p, rate="+0%", pitch="+0Hz", volume="+0%",
            pause_before_ms=0, pause_after_ms=350,
        ),
        "quote_block": AudioProfile(
            voice=s, rate="-4%", pitch="-1Hz", volume="-2%",
            pause_before_ms=350, pause_after_ms=450,
        ),
        "interview_q": AudioProfile(
            voice=p, rate="-2%", pitch="+1Hz", volume="+2%",
            pause_before_ms=600, pause_after_ms=400,
        ),
        "interview_a": AudioProfile(
            voice=s, rate="+0%", pitch="+0Hz", volume="+0%",
            pause_before_ms=150, pause_after_ms=450,
        ),
        "box_title": AudioProfile(
            voice=s, rate="-5%", pitch="+0Hz", volume="+2%",
            pause_before_ms=750, pause_after_ms=400, earcon_before="box",
        ),
        "box_body": AudioProfile(
            voice=p, rate="-3%", pitch="-1Hz", volume="-1%",
            pause_before_ms=0, pause_after_ms=850,
        ),
        "group_intro": AudioProfile(
            voice=s, rate="-4%", pitch="+0Hz", volume="+0%",
            pause_before_ms=0, pause_after_ms=900,
        ),
        "group_item_title": AudioProfile(
            voice=s, rate="-5%", pitch="+0Hz", volume="+3%",
            pause_before_ms=900, pause_after_ms=500, earcon_before="group",
        ),
        "group_item_body": AudioProfile(
            voice=p, rate="+0%", pitch="+0Hz", volume="+0%",
            pause_before_ms=0, pause_after_ms=600,
        ),
        "outro": AudioProfile(
            voice=p, pause_before_ms=800, pause_after_ms=400, earcon_before="outro",
        ),
    }
    return profiles.get(kind, AudioProfile(voice=p, pause_after_ms=450))


def is_ffmpeg_available() -> bool:
    """Vérifie la disponibilité de ffmpeg dans le PATH."""
    return shutil.which("ffmpeg") is not None


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    """Exécute ffmpeg de façon silencieuse et lève RuntimeError en cas d'erreur."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg a échoué ({res.returncode}) : {res.stderr.strip()}")
    return res


def _atomic_ffmpeg_render(target_path: str, build_args_fn) -> str:
    """Génère un fichier audio de manière atomique via un fichier temporaire unique."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    tmp_path = f"{target_path}.tmp.{os.getpid()}.{threading.get_ident()}.mp3"
    try:
        _run_ffmpeg(build_args_fn(tmp_path))
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
    return target_path


def get_silence_path(ms: int, cache_dir: str = DEFAULT_AUDIO_CACHE_DIR) -> str:
    """Retourne le chemin vers un fichier MP3 de silence exact (24kHz mono 48k CBR) mis en cache."""
    ms_clamped = max(50, int(ms))
    target = os.path.join(cache_dir, f"silence_{ms_clamped}ms.mp3")
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target

    with _asset_lock:
        if os.path.exists(target) and os.path.getsize(target) > 0:
            return target
        dur_s = ms_clamped / 1000.0
        _atomic_ffmpeg_render(
            target,
            lambda tmp: [
                "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", f"{dur_s:.3f}",
                "-ar", "24000", "-ac", "1", "-b:a", "48k", "-c:a", "libmp3lame",
                tmp,
            ],
        )
    return target


def get_earcon_path(name: str, cache_dir: str = DEFAULT_AUDIO_CACHE_DIR) -> str:
    """Retourne le chemin vers un earcon doux synthétisé par ffmpeg et mis en cache."""
    if name not in ("section", "box", "group", "outro"):
        raise ValueError(f"Earcon inconnu : {name}")
    target = os.path.join(cache_dir, f"earcon_{name}.mp3")
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target

    with _asset_lock:
        if os.path.exists(target) and os.path.getsize(target) > 0:
            return target

        def _args_for(tmp: str) -> list[str]:
            if name == "section":
                fc = (
                    "sine=frequency=523.25:sample_rate=24000:duration=0.14,"
                    "afade=t=in:st=0:d=0.02,afade=t=out:st=0.04:d=0.10,volume=-20dB"
                )
                return [
                    "-y", "-f", "lavfi", "-i", fc,
                    "-ar", "24000", "-ac", "1", "-b:a", "48k", "-c:a", "libmp3lame",
                    tmp,
                ]

            if name == "box":
                f1, f2, vol = 440.0, 587.33, "-20dB"
                d1, d2 = 0.09, 0.11
            elif name == "group":
                f1, f2, vol = 523.25, 659.25, "-18dB"
                d1, d2 = 0.10, 0.14
            else:  # outro
                f1, f2, vol = 523.25, 392.00, "-22dB"
                d1, d2 = 0.10, 0.16

            fc = (
                f"sine=frequency={f1}:sample_rate=24000:duration={d1},"
                f"afade=t=in:st=0:d=0.015,afade=t=out:st={max(0.02, d1 - 0.05):.3f}:d=0.05[a];"
                f"sine=frequency={f2}:sample_rate=24000:duration={d2},"
                f"afade=t=in:st=0:d=0.015,afade=t=out:st={max(0.02, d2 - 0.07):.3f}:d=0.07[b];"
                f"[a][b]concat=n=2:v=0:a=1,volume={vol}"
            )
            return [
                "-y", "-filter_complex", fc,
                "-ar", "24000", "-ac", "1", "-b:a", "48k", "-c:a", "libmp3lame",
                tmp,
            ]

        _atomic_ffmpeg_render(target, _args_for)
    return target


def get_mp3_duration_ms(path: str) -> int:
    """Retourne la durée réelle d'un fichier MP3 en millisecondes."""
    try:
        info = MP3(path).info
        if info and info.length > 0:
            return int(round(info.length * 1000))
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True,
        )
        return int(round(float(res.stdout.strip()) * 1000))
    except Exception:
        return 0


def _norm_for_align(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def find_paragraph_split_times_ms(
    paragraphs: list[str],
    boundaries: list[tuple[float, float, str]],
) -> list[float]:
    """
    Identifie les instants (en ms) où insérer une pause inter-paragraphes à partir
    des événements SentenceBoundary (offset_ms, duration_ms, text) sans appel API supplémentaire.
    """
    if len(paragraphs) <= 1 or len(boundaries) <= 1:
        return []

    splits: list[float] = []
    cum_target = 0
    cum_bound = 0
    b_idx = 0
    n_bounds = len(boundaries)

    for p_idx in range(len(paragraphs) - 1):
        p_norm = _norm_for_align(paragraphs[p_idx])
        if not p_norm:
            continue
        cum_target += len(p_norm)
        p_tail = p_norm[-10:] if len(p_norm) >= 10 else p_norm

        matched_idx: int | None = None
        while b_idx < n_bounds:
            _, _, b_text = boundaries[b_idx]
            b_norm = _norm_for_align(b_text)
            cum_bound += len(b_norm)

            if cum_bound >= cum_target - 2 or (
                cum_bound >= int(cum_target * 0.90) and p_tail and b_norm.endswith(p_tail)
            ):
                matched_idx = b_idx
                b_idx += 1
                break
            b_idx += 1

        if matched_idx is None or matched_idx + 1 >= n_bounds:
            break

        off_cur, dur_cur, _ = boundaries[matched_idx]
        off_next, _, _ = boundaries[matched_idx + 1]
        end_cur = off_cur + dur_cur
        split_ms = (end_cur + off_next) / 2.0 if off_next > end_cur else end_cur

        if split_ms >= 100.0 and (not splits or (split_ms - splits[-1]) >= 150.0):
            splits.append(round(split_ms, 2))

    return splits


def insert_pauses_ffmpeg(
    raw_mp3: str,
    out_mp3: str,
    split_times_ms: list[float],
    pause_ms: int,
) -> bool:
    """
    Insère des silences de durée pause_ms aux instants split_times_ms dans raw_mp3
    via une seule passe ffmpeg -filter_complex.
    """
    if not split_times_ms or pause_ms <= 0:
        return False

    dur_ms = get_mp3_duration_ms(raw_mp3)
    valid_splits = sorted({
        t for t in split_times_ms
        if 80.0 < t < (dur_ms - 80.0 if dur_ms > 160 else float("inf"))
    })
    if not valid_splits:
        return False

    points_s = [0.0] + [t / 1000.0 for t in valid_splits] + [None]
    pause_s = pause_ms / 1000.0

    filter_parts: list[str] = []
    concat_inputs: list[str] = []

    for i in range(len(points_s) - 1):
        start_s = points_s[i]
        end_s = points_s[i + 1]
        if end_s is None:
            filter_parts.append(f"[0:a]atrim=start={start_s:.3f},asetpts=PTS-STARTPTS[s{i}]")
        else:
            filter_parts.append(f"[0:a]atrim=start={start_s:.3f}:end={end_s:.3f},asetpts=PTS-STARTPTS[s{i}]")
        concat_inputs.append(f"[s{i}]")

        if i < len(points_s) - 2:
            filter_parts.append(
                f"anullsrc=r=24000:cl=mono,atrim=duration={pause_s:.3f},asetpts=PTS-STARTPTS[p{i}]"
            )
            concat_inputs.append(f"[p{i}]")

    n_streams = len(concat_inputs)
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={n_streams}:v=0:a=1[out]")
    filter_complex = ";".join(filter_parts)

    try:
        _run_ffmpeg([
            "-y", "-i", raw_mp3,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", "24000", "-ac", "1", "-b:a", "48k", "-c:a", "libmp3lame",
            out_mp3,
        ])
        return os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 0
    except Exception as e:
        logger.warning(f"Insertion pauses inter-paragraphes échouée (fallback brut) : {e}")
        return False


async def synthesize_chunk(
    chunk: SynthesisChunk,
    profile: AudioProfile,
    out_mp3_path: str,
    limiter,
    *,
    inter_paragraph_pause_ms: int = 450,
    max_retries: int = 3,
    retry_base_delay: float = 3.0,
) -> None:
    """
    Synthétise un SynthesisChunk via edge-tts (stream + SentenceBoundary)
    avec gestion du rate-limiter, retries et insertion des pauses inter-paragraphes.
    """
    text = chunk.text.strip()
    if not text:
        return

    raw_path = out_mp3_path + ".raw.mp3"
    last_exc: Exception = RuntimeError("Aucune tentative effectuée")

    for attempt in range(1, max_retries + 1):
        boundaries: list[tuple[float, float, str]] = []
        try:
            async with limiter:
                communicate = edge_tts.Communicate(
                    text,
                    voice=profile.voice,
                    rate=profile.rate,
                    pitch=profile.pitch,
                    volume=profile.volume,
                    boundary="SentenceBoundary",
                )
                with open(raw_path, "wb") as audio_f:
                    async for event in communicate.stream():
                        etype = event.get("type")
                        if etype == "audio":
                            data = event.get("data")
                            if data:
                                audio_f.write(data)
                        elif etype == "SentenceBoundary":
                            off_ms = float(event.get("offset", 0)) / 10_000.0
                            dur_ms = float(event.get("duration", 0)) / 10_000.0
                            btxt = event.get("text", "")
                            boundaries.append((off_ms, dur_ms, btxt))

            if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
                raise RuntimeError(f"Chunk audio généré vide (0 octet) : {raw_path}")

            if len(chunk.paragraphs) > 1 and inter_paragraph_pause_ms > 0 and boundaries:
                splits = find_paragraph_split_times_ms(chunk.paragraphs, boundaries)
                if splits and insert_pauses_ffmpeg(raw_path, out_mp3_path, splits, inter_paragraph_pause_ms):
                    try:
                        os.remove(raw_path)
                    except OSError:
                        pass
                    return

            os.replace(raw_path, out_mp3_path)
            return

        except Exception as e:
            last_exc = e
            for p in (raw_path, out_mp3_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            if attempt < max_retries:
                wait = retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"TTS chunk tentative {attempt}/{max_retries} échouée ({e}). "
                    f"Nouvelle tentative dans {wait:.0f}s…"
                )
                await asyncio.sleep(wait)

    raise last_exc


def _escape_concat_path(path: str) -> str:
    return path.replace("'", "'\\''")


async def build_rich_audio(
    segments: list[Segment],
    mp3_path: str,
    cfg: RichAudioConfig,
    limiter,
    *,
    cache_dir: str = DEFAULT_AUDIO_CACHE_DIR,
    max_retries: int = 3,
    retry_base_delay: float = 3.0,
) -> list[tuple[str, int, int]]:
    """
    Synthétise et assemble une liste de Segment en un MP3 final normalisé
    avec pauses, earcons et suivi précis des chapitres (title, start_ms, end_ms).
    """
    chunks = coalesce_segments(segments, max_tts_calls=cfg.max_tts_calls)
    if not any(c.is_tts for c in chunks):
        raise ValueError("Aucun segment synthétisable")

    target_dir = os.path.dirname(os.path.abspath(mp3_path))
    os.makedirs(target_dir, exist_ok=True)
    tmp_final = f"{mp3_path}.build.{os.getpid()}.{threading.get_ident()}.mp3"

    try:
        with tempfile.TemporaryDirectory(prefix="tts_mp3_build_") as tmpdir:
            concat_files: list[str] = []
            current_ms = 0
            chapter_starts: list[tuple[str, int]] = []

            def append_audio(path: str) -> None:
                nonlocal current_ms
                dur = get_mp3_duration_ms(path)
                if dur <= 0:
                    return
                concat_files.append(path)
                current_ms += dur

            for idx, chunk in enumerate(chunks):
                profile = get_profile(chunk.kind, cfg)

                if concat_files and profile.pause_before_ms > 0:
                    append_audio(get_silence_path(profile.pause_before_ms, cache_dir=cache_dir))

                if chunk.chapter_title:
                    chapter_starts.append((chunk.chapter_title, current_ms))

                if cfg.earcons and profile.earcon_before:
                    append_audio(get_earcon_path(profile.earcon_before, cache_dir=cache_dir))

                if chunk.is_tts:
                    chunk_mp3 = os.path.join(tmpdir, f"chunk_{idx:03d}.mp3")
                    await synthesize_chunk(
                        chunk,
                        profile,
                        chunk_mp3,
                        limiter,
                        inter_paragraph_pause_ms=cfg.inter_paragraph_pause_ms,
                        max_retries=max_retries,
                        retry_base_delay=retry_base_delay,
                    )
                    append_audio(chunk_mp3)

                if cfg.earcons and profile.earcon_after:
                    append_audio(get_earcon_path(profile.earcon_after, cache_dir=cache_dir))

                if profile.pause_after_ms > 0:
                    append_audio(get_silence_path(profile.pause_after_ms, cache_dir=cache_dir))

            if not concat_files:
                raise RuntimeError("Aucun segment audio produit")

            concat_list_path = os.path.join(tmpdir, "concat.txt")
            with open(concat_list_path, "w", encoding="utf-8") as cf:
                for p in concat_files:
                    cf.write(f"file '{_escape_concat_path(p)}'\n")

            if cfg.loudnorm:
                _run_ffmpeg([
                    "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ar", "24000", "-ac", "1", "-b:a", "48k", "-c:a", "libmp3lame",
                    tmp_final,
                ])
            else:
                _run_ffmpeg([
                    "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
                    "-c", "copy",
                    tmp_final,
                ])

            if not os.path.exists(tmp_final) or os.path.getsize(tmp_final) == 0:
                raise RuntimeError(f"Fichier audio final vide : {mp3_path}")

            os.replace(tmp_final, mp3_path)

            final_dur_ms = get_mp3_duration_ms(mp3_path) or current_ms
            chapters: list[tuple[str, int, int]] = []
            for i, (title, start_ms) in enumerate(chapter_starts):
                end_ms = chapter_starts[i + 1][1] if (i + 1) < len(chapter_starts) else final_dur_ms
                if end_ms <= start_ms:
                    end_ms = start_ms + 100
                chapters.append((title, min(start_ms, final_dur_ms), min(end_ms, final_dur_ms)))

            return chapters

    except Exception:
        for p in (tmp_final, mp3_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        raise


def write_id3_chapters(audio: ID3, chapters: list[tuple[str, int, int]]) -> None:
    """
    Écrit les frames ID3v2 CHAP et CTOC (table des matières) sur un objet ID3.
    N'écrit rien s'il y a moins de 2 chapitres.
    """
    audio.delall("CHAP")
    audio.delall("CTOC")

    if not chapters or len(chapters) < 2:
        return

    child_ids: list[str] = []
    for i, (title, start_ms, end_ms) in enumerate(chapters):
        eid = f"chp{i}"
        child_ids.append(eid)
        audio.add(CHAP(
            element_id=eid,
            start_time=int(start_ms),
            end_time=int(end_ms),
            start_offset=0xFFFFFFFF,
            end_offset=0xFFFFFFFF,
            sub_frames=[TIT2(encoding=3, text=title)],
        ))

    audio.add(CTOC(
        element_id="toc",
        flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
        child_element_ids=child_ids,
        sub_frames=[TIT2(encoding=3, text="Table des matières")],
    ))
