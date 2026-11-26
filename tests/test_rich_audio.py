#!/usr/bin/env python3
"""
Tests unitaires et d'intégration ffmpeg pour le pipeline audio riche :
- segments.py : extraction structurée, détection entretiens 2 voix, longues citations, plafond max_tts_calls
- audio_builder.py : alignement SentenceBoundary, insertion pauses ffmpeg, earcons/silences, loudnorm, chapitres ID3 CHAP/CTOC
- html_to_mp3.py : mode riche vs mode rapide (--fast)
"""

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from mutagen.id3 import ID3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import html_to_mp3 as h2m
from adapters.reader_mode import reader_extract_segments
from audio_builder import (
    RichAudioConfig,
    build_rich_audio,
    find_paragraph_split_times_ms,
    get_earcon_path,
    get_mp3_duration_ms,
    get_silence_path,
    insert_pauses_ffmpeg,
    is_ffmpeg_available,
    write_id3_chapters,
)
from segments import (
    Segment,
    coalesce_segments,
    detect_interview_segments,
    enrich_article_segments,
    split_long_quotes,
)


def _run(coro):
    return asyncio.run(coro)


def _make_sample_mp3(path: str, duration_s: float = 0.6, freq: float = 330.0) -> bytes:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=24000:duration={duration_s}",
            "-ar", "24000", "-ac", "1", "-b:a", "48k", "-c:a", "libmp3lame",
            path,
        ],
        check=True,
    )
    with open(path, "rb") as f:
        return f.read()


class TestSegmentsPipeline(unittest.TestCase):
    def test_detect_interview_and_strip_repeated_prefix(self):
        segs = [
            Segment("paragraph", "Présentation de la personne invitée aujourd'hui."),
            Segment("paragraph", "Basta! : Pourquoi cette loi pose-t-elle problème ?", is_bold_question=True),
            Segment("paragraph", "Première réponse détaillée de la personne invitée."),
            Segment("paragraph", "Basta! : Que répondez-vous aux critiques ?", is_bold_question=True),
            Segment("paragraph", "Deuxième réponse développée."),
            Segment("paragraph", "Basta! : Quelles perspectives pour la suite ?", is_bold_question=True),
            Segment("paragraph", "Troisième réponse finale."),
        ]
        out, is_interview = detect_interview_segments(segs)
        self.assertTrue(is_interview)
        kinds = [s.kind for s in out]
        self.assertEqual(
            kinds,
            ["paragraph", "interview_q", "interview_a", "interview_q", "interview_a", "interview_q", "interview_a"],
        )
        # 1re question conserve le préfixe, les suivantes le suppriment
        self.assertTrue(out[1].text.startswith("Basta! :"))
        self.assertFalse(out[3].text.startswith("Basta!"))
        self.assertFalse(out[5].text.startswith("Basta!"))

    def test_split_long_quotes_only_above_threshold(self):
        short_q = "Elle déclare « ceci est court » puis continue."
        long_inner = "Ceci est une citation suffisamment longue pour déclencher une lecture par une voix dédiée et posée sans aucun problème de segmentation dans notre pipeline audio"
        long_q = f"Dans son rapport, il écrit : « {long_inner}. », ce qui confirme l'analyse."

        res = split_long_quotes(
            [Segment("paragraph", short_q), Segment("paragraph", long_q)],
            min_quote_chars=120,
        )
        self.assertEqual(res[0].kind, "paragraph")
        self.assertEqual(res[0].text, short_q)
        self.assertEqual([s.kind for s in res[1:]], ["paragraph", "quote_block", "paragraph"])
        self.assertIn("Ceci est une citation suffisamment longue", res[2].text)

    def test_coalesce_respects_max_tts_calls_cap(self):
        segs = [Segment("intro_title", "Titre principal.", chapter_title="Introduction")]
        for i in range(45):
            segs.append(Segment("heading", f"Section {i}.", chapter_title=f"Section {i}"))
            segs.append(Segment("quote_block", "Une longue citation de test suffisamment étoffée pour être comptée comme bloc distinct."))
            segs.append(Segment("paragraph", f"Paragraphe de contenu numéro {i} avec suffisamment de texte."))
        segs.append(Segment("outro", ""))

        chunks = coalesce_segments(segs, max_tts_calls=20)
        tts_calls = sum(1 for c in chunks if c.is_tts)
        self.assertLessEqual(tts_calls, 20)
        self.assertEqual(chunks[-1].kind, "outro")

    def test_reader_extract_segments_identifies_structures(self):
        html = """
        <html><body><article>
            <h2>Un sous-titre clair</h2>
            <p>Premier vrai paragraphe d'introduction de l'article avec assez de matière pour Trafilatura.</p>
            <ul>
                <li>Premier point d'une liste très claire dans le corps du texte.</li>
                <li>Deuxième point de la liste pour vérifier l'extraction structurée.</li>
            </ul>
            <p><strong>Basta! : Pourquoi cette question en gras est-elle détectée comme question d'entretien ?</strong></p>
            <p>Réponse de l'invité suffisamment développée pour que l'extraction reste fidèle au texte d'origine.</p>
        </article></body></html>
        """
        segs = reader_extract_segments(html)
        kinds = [s.kind for s in segs]
        self.assertIn("heading", kinds)
        self.assertIn("list_item", kinds)
        self.assertTrue(any(s.is_bold_question for s in segs))

    def test_enrich_article_segments_adds_intro_chapters_box_and_outro(self):
        body = [
            Segment("chapo", "Un chapô introductif très clair."),
            Segment("heading", "Première section"),
            Segment("paragraph", "Un premier paragraphe normal."),
            Segment("box_title", "Chiffres clés"),
            Segment("box_body", "Quarante-deux pour cent de hausse."),
        ]
        meta = {"title": "Grand titre", "author": "Alice", "media": "Mediapart"}
        enriched = enrich_article_segments(body, meta)
        self.assertEqual(enriched[0].kind, "intro_meta")
        self.assertEqual(enriched[1].kind, "intro_title")
        self.assertEqual(enriched[1].chapter_title, "Introduction")
        self.assertEqual(enriched[-1].kind, "outro")
        box_title = next(s for s in enriched if s.kind == "box_title")
        self.assertTrue(box_title.text.startswith("Encadré :"))
        self.assertTrue(box_title.chapter_title.startswith("Encadré :"))


class TestAudioBuilderAndFFmpeg(unittest.TestCase):
    def test_find_paragraph_split_times_ms(self):
        paragraphs = [
            "Premier paragraphe court. Deuxième phrase du premier.",
            "Deuxième paragraphe qui suit.",
            "Troisième paragraphe final.",
        ]
        boundaries = [
            (50.0, 900.0, "Premier paragraphe court."),
            (1050.0, 1100.0, "Deuxième phrase du premier."),
            (2350.0, 1000.0, "Deuxième paragraphe qui suit."),
            (3550.0, 950.0, "Troisième paragraphe final."),
        ]
        splits = find_paragraph_split_times_ms(paragraphs, boundaries)
        self.assertEqual(len(splits), 2)
        # Entre fin boundary 1 (2150) et début boundary 2 (2350) -> 2250.0
        self.assertAlmostEqual(splits[0], 2250.0, places=1)
        # Entre fin boundary 2 (3350) et début boundary 3 (3550) -> 3450.0
        self.assertAlmostEqual(splits[1], 3450.0, places=1)

        self.assertEqual(find_paragraph_split_times_ms(["Un seul paragraphe."], boundaries), [])
        self.assertEqual(find_paragraph_split_times_ms(paragraphs, []), [])

    @unittest.skipUnless(is_ffmpeg_available(), "ffmpeg requis pour ce test")
    def test_ffmpeg_assets_pauses_and_full_build_with_id3_chapters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache")
            sil = get_silence_path(500, cache_dir=cache_dir)
            self.assertTrue(os.path.exists(sil))
            self.assertGreaterEqual(get_mp3_duration_ms(sil), 400)

            for earcon_name in ("section", "box", "group", "outro"):
                ep = get_earcon_path(earcon_name, cache_dir=cache_dir)
                self.assertTrue(os.path.exists(ep))
                self.assertGreater(get_mp3_duration_ms(ep), 80)

            # Vérifier insert_pauses_ffmpeg allonge bien la durée
            raw_mp3 = os.path.join(tmpdir, "raw.mp3")
            paused_mp3 = os.path.join(tmpdir, "paused.mp3")
            _make_sample_mp3(raw_mp3, duration_s=1.0)
            ok = insert_pauses_ffmpeg(raw_mp3, paused_mp3, [450.0], pause_ms=500)
            self.assertTrue(ok)
            self.assertGreaterEqual(get_mp3_duration_ms(paused_mp3), get_mp3_duration_ms(raw_mp3) + 350)

            # Test complet de build_rich_audio avec mock de edge_tts.Communicate
            sample_bytes = _make_sample_mp3(os.path.join(tmpdir, "sample_tts.mp3"), duration_s=0.5)

            class FakeCommunicate:
                def __init__(self, text, **kwargs):
                    self.text = text

                async def stream(self):
                    yield {"type": "SentenceBoundary", "offset": 50 * 10_000, "duration": 400 * 10_000, "text": self.text}
                    yield {"type": "audio", "data": sample_bytes}

            segs = [
                Segment("intro_title", "Mon article test.", chapter_title="Introduction"),
                Segment("paragraph", "Premier paragraphe."),
                Segment("paragraph", "Deuxième paragraphe."),
                Segment("heading", "Partie deux.", chapter_title="Partie deux"),
                Segment("quote_block", "Une citation importante."),
                Segment("outro", ""),
            ]
            out_mp3 = os.path.join(tmpdir, "final_rich.mp3")
            cfg = RichAudioConfig(earcons=True, loudnorm=True, max_tts_calls=20)
            limiter = h2m.EdgeTTSRateLimiter(max_rpm=100, max_concurrency=2)

            with patch("audio_builder.edge_tts.Communicate", FakeCommunicate):
                chapters = _run(build_rich_audio(segs, out_mp3, cfg, limiter, cache_dir=cache_dir))

            self.assertTrue(os.path.exists(out_mp3))
            self.assertGreater(get_mp3_duration_ms(out_mp3), 2500)
            self.assertEqual([c[0] for c in chapters], ["Introduction", "Partie deux"])
            self.assertLess(chapters[0][1], chapters[0][2])
            self.assertEqual(chapters[0][2], chapters[1][1])

            # Écriture et relecture ID3 CHAP / CTOC
            audio = ID3(out_mp3)
            write_id3_chapters(audio, chapters)
            audio.save(out_mp3)

            reloaded = ID3(out_mp3)
            self.assertIn("CTOC:toc", reloaded)
            self.assertIn("CHAP:chp0", reloaded)
            self.assertIn("CHAP:chp1", reloaded)
            self.assertEqual(reloaded["CHAP:chp0"].sub_frames["TIT2"].text[0], "Introduction")
            self.assertEqual(reloaded["CHAP:chp1"].sub_frames["TIT2"].text[0], "Partie deux")

    def test_fast_mode_uses_single_generate_tts_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp3_path = os.path.join(tmpdir, "fast.mp3")
            called_with = []

            async def fake_gen(text, voice, path, **kwargs):
                called_with.append((text, voice, path))
                with open(path, "wb") as f:
                    f.write(b"ID3" + b"\x00" * 32)

            meta = {"title": "Titre test", "author": "Auteur", "media": "Mediapart"}
            with patch("html_to_mp3.generate_tts_file", side_effect=fake_gen), \
                 patch("html_to_mp3.build_rich_audio") as mock_rich, \
                 patch("html_to_mp3.ID3"):
                ok = _run(h2m.generate_audio_from_content(
                    meta,
                    "Corps de texte suffisamment long pour déclencher la synthèse vocale rapide.",
                    mp3_path,
                    voice="fr-FR-VivienneMultilingualNeural",
                    segments=[Segment("paragraph", "Corps de texte suffisamment long pour déclencher la synthèse vocale rapide.")],
                    fast_mode=True,
                ))

            self.assertTrue(ok)
            self.assertEqual(len(called_with), 1)
            mock_rich.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
