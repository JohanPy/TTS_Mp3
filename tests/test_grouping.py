#!/usr/bin/env python3
"""
Tests unitaires pour le mécanisme de regroupement de résumés IA.

Couvre :
- store_pending_summary : stockage dans grouped_summaries.json
- flush_grouped_summaries : fenêtre ouverte (aucun MP3) vs fermée (MP3 généré)
- _build_grouped_text : format du texte combiné
- Nettoyage du pending après flush
- Nom de fichier du MP3 groupé
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

# Ajouter la racine du projet au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# On importe le module complet pour pouvoir patcher ses globals
import html_to_mp3 as h2m


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TODAY = date.today().isoformat()

SAMPLE_ENTRY = {
    "feed_url": "http://www.developpez.com/index/rss",
    "media": "Developpez.com",
    "title": "Python 4 annoncé",
    "article_url": "http://www.developpez.com/article/1",
    "summary": "Python 4 vient d'être annoncé avec de nouvelles fonctionnalités majeures.",
    "date_bucket": YESTERDAY,
    "window_hours": 24,
    "voice": "fr-FR-VivienneNeural",
}


class TestStorePendingSummary(unittest.TestCase):
    """Tests de store_pending_summary."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self._tmp.close()
        # Rediriger le fichier grouped_summaries vers un fichier temporaire
        self._original_file = h2m.GROUPED_SUMMARIES_FILE
        h2m.GROUPED_SUMMARIES_FILE = self._tmp.name

    def tearDown(self):
        h2m.GROUPED_SUMMARIES_FILE = self._original_file
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)
        for ext in [".tmp"]:
            path = self._tmp.name + ext
            if os.path.exists(path):
                os.unlink(path)

    def test_store_creates_entry(self):
        """store_pending_summary crée bien une entrée dans le JSON."""
        # Fichier vide au départ
        with open(self._tmp.name, "w") as f:
            json.dump({"pending": []}, f)

        h2m.store_pending_summary(
            feed_url="http://example.com/rss",
            media="ExMedia",
            title="Mon article",
            article_url="http://example.com/art/1",
            summary="Un résumé court.",
            window_hours=24,
            voice="fr-FR-VivienneNeural",
        )

        data = h2m.load_grouped_summaries()
        self.assertEqual(len(data["pending"]), 1)
        entry = data["pending"][0]
        self.assertEqual(entry["media"], "ExMedia")
        self.assertEqual(entry["title"], "Mon article")
        self.assertEqual(entry["summary"], "Un résumé court.")
        self.assertEqual(entry["date_bucket"], TODAY)

    def test_store_multiple_entries(self):
        """Plusieurs appels accumulent plusieurs entrées."""
        with open(self._tmp.name, "w") as f:
            json.dump({"pending": []}, f)

        for i in range(3):
            h2m.store_pending_summary(
                feed_url="http://example.com/rss",
                media="ExMedia",
                title=f"Article {i}",
                article_url=f"http://example.com/art/{i}",
                summary=f"Résumé {i}.",
                window_hours=24,
                voice="fr-FR-VivienneNeural",
            )

        data = h2m.load_grouped_summaries()
        self.assertEqual(len(data["pending"]), 3)

    def test_store_preserves_existing_entries(self):
        """Un nouvel ajout ne supprime pas les entrées existantes."""
        existing = [SAMPLE_ENTRY.copy()]
        with open(self._tmp.name, "w") as f:
            json.dump({"pending": existing}, f)

        h2m.store_pending_summary(
            feed_url="http://other.com/rss",
            media="Other",
            title="Nouveau",
            article_url="http://other.com/1",
            summary="Résumé.",
            window_hours=24,
            voice="fr-FR-VivienneNeural",
        )

        data = h2m.load_grouped_summaries()
        self.assertEqual(len(data["pending"]), 2)


class TestBuildGroupedText(unittest.TestCase):
    """Tests du formatage du texte groupé."""

    def test_single_article_format(self):
        """Un seul article : l'intro mentionne '1 article' et 'Premier article sur 1'."""
        entries = [{"title": "Mon titre", "summary": "Mon résumé."}]
        text = h2m._build_grouped_text("Developpez.com", "2026-05-26", entries)

        self.assertIn("1 article", text)
        self.assertIn("Premier article sur 1", text)
        self.assertIn("Mon titre", text)
        self.assertIn("Mon résumé.", text)
        self.assertIn("Developpez.com", text)
        self.assertIn("2026-05-26", text)

    def test_multiple_articles_format(self):
        """Trois articles : numérotation ordinale correcte."""
        entries = [
            {"title": f"Titre {i}", "summary": f"Résumé {i}."}
            for i in range(3)
        ]
        text = h2m._build_grouped_text("Source", "2026-05-26", entries)

        self.assertIn("3 articles", text)
        self.assertIn("Premier article sur 3", text)
        self.assertIn("Deuxième article sur 3", text)
        self.assertIn("Troisième article sur 3", text)

    def test_text_contains_all_titles(self):
        """Le texte groupé contient tous les titres."""
        entries = [
            {"title": f"Article spécial {i}", "summary": f"Résumé {i}."}
            for i in range(5)
        ]
        text = h2m._build_grouped_text("Media", "2026-05-26", entries)

        for i in range(5):
            self.assertIn(f"Article spécial {i}", text)

    def test_beyond_ten_articles_fallback(self):
        """Au-delà de 10 articles, le label devient 'Article N sur M'."""
        entries = [
            {"title": f"T{i}", "summary": f"R{i}."}
            for i in range(12)
        ]
        text = h2m._build_grouped_text("Media", "2026-05-26", entries)
        # Le 11ème article (index 10) doit être "Article 11 sur 12"
        self.assertIn("Article 11 sur 12", text)


class TestFlushGroupedSummaries(unittest.TestCase):
    """Tests de flush_grouped_summaries."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self._tmp.close()
        self._original_file = h2m.GROUPED_SUMMARIES_FILE
        self._original_output = h2m.OUTPUT_DIR
        h2m.GROUPED_SUMMARIES_FILE = self._tmp.name

        # Dossier output temporaire
        self._out_dir = tempfile.mkdtemp()
        h2m.OUTPUT_DIR = self._out_dir

    def tearDown(self):
        h2m.GROUPED_SUMMARIES_FILE = self._original_file
        h2m.OUTPUT_DIR = self._original_output
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)
        for ext in [".tmp"]:
            path = self._tmp.name + ext
            if os.path.exists(path):
                os.unlink(path)
        import shutil
        shutil.rmtree(self._out_dir, ignore_errors=True)

    def _write_pending(self, entries):
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({"pending": entries}, f)

    def test_open_window_no_mp3_generated(self):
        """Une fenêtre encore ouverte (date_bucket = today) ne génère pas de MP3."""
        entry = {**SAMPLE_ENTRY, "date_bucket": TODAY}
        self._write_pending([entry])

        with patch("edge_tts.Communicate") as mock_tts:
            _run(h2m.flush_grouped_summaries())
            mock_tts.assert_not_called()

        # L'entrée reste dans le pending
        data = h2m.load_grouped_summaries()
        self.assertEqual(len(data["pending"]), 1)

    def test_closed_window_generates_mp3(self):
        """Une fenêtre fermée (date_bucket = yesterday) génère un MP3."""
        entry = {**SAMPLE_ENTRY, "date_bucket": YESTERDAY}
        self._write_pending([entry])

        mock_communicate = MagicMock()
        mock_communicate.save = AsyncMock()

        with patch("edge_tts.Communicate", return_value=mock_communicate) as mock_tts:
            _run(h2m.flush_grouped_summaries())
            mock_tts.assert_called_once()
            mock_communicate.save.assert_awaited_once()

    def test_flush_cleans_pending_after_success(self):
        """Après un flush réussi, les entrées traitées sont retirées du JSON."""
        entry = {**SAMPLE_ENTRY, "date_bucket": YESTERDAY}
        self._write_pending([entry])

        mock_communicate = MagicMock()
        mock_communicate.save = AsyncMock()

        with patch("edge_tts.Communicate", return_value=mock_communicate):
            with patch("mutagen.id3.ID3"):
                _run(h2m.flush_grouped_summaries())

        data = h2m.load_grouped_summaries()
        self.assertEqual(len(data["pending"]), 0)

    def test_flush_keeps_open_window_in_pending(self):
        """Après flush, les entrées dont la fenêtre est encore ouverte restent."""
        old_entry = {**SAMPLE_ENTRY, "date_bucket": YESTERDAY}
        new_entry = {**SAMPLE_ENTRY, "date_bucket": TODAY, "title": "Nouveau"}
        self._write_pending([old_entry, new_entry])

        mock_communicate = MagicMock()
        mock_communicate.save = AsyncMock()

        with patch("edge_tts.Communicate", return_value=mock_communicate):
            with patch("mutagen.id3.ID3"):
                _run(h2m.flush_grouped_summaries())

        data = h2m.load_grouped_summaries()
        self.assertEqual(len(data["pending"]), 1)
        self.assertEqual(data["pending"][0]["title"], "Nouveau")

    def test_grouped_mp3_filename(self):
        """Le nom du MP3 groupé suit le format Resumes_{media}_{date}.mp3."""
        entry = {**SAMPLE_ENTRY, "date_bucket": YESTERDAY}
        self._write_pending([entry])

        saved_paths = []

        async def fake_save(path):
            saved_paths.append(path)

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save

        with patch("edge_tts.Communicate", return_value=mock_communicate):
            with patch("mutagen.id3.ID3"):
                _run(h2m.flush_grouped_summaries())

        self.assertEqual(len(saved_paths), 1)
        filename = os.path.basename(saved_paths[0])
        self.assertTrue(
            filename.startswith("Resumes_"),
            f"Le nom devrait commencer par 'Resumes_', obtenu : {filename}"
        )
        self.assertIn(YESTERDAY, filename)
        self.assertTrue(filename.endswith(".mp3"))

    def test_empty_pending_no_op(self):
        """Si le pending est vide, flush ne fait rien et ne crashe pas."""
        self._write_pending([])
        with patch("edge_tts.Communicate") as mock_tts:
            _run(h2m.flush_grouped_summaries())
            mock_tts.assert_not_called()

    def test_multiple_feeds_separate_mp3s(self):
        """Deux flux différents avec date_bucket = yesterday → deux MP3 distincts."""
        entry1 = {**SAMPLE_ENTRY, "date_bucket": YESTERDAY, "feed_url": "http://feed1.com/rss"}
        entry2 = {
            **SAMPLE_ENTRY,
            "date_bucket": YESTERDAY,
            "feed_url": "http://feed2.com/rss",
            "media": "AutreMedia",
        }
        self._write_pending([entry1, entry2])

        saved_paths = []

        async def fake_save(path):
            saved_paths.append(path)

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save

        with patch("edge_tts.Communicate", return_value=mock_communicate):
            with patch("mutagen.id3.ID3"):
                _run(h2m.flush_grouped_summaries())

        self.assertEqual(len(saved_paths), 2, "Deux flux → deux MP3 groupés distincts")


class TestLoadSaveGroupedSummaries(unittest.TestCase):
    """Tests des fonctions d'I/O pour grouped_summaries.json."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self._tmp.close()
        self._original_file = h2m.GROUPED_SUMMARIES_FILE
        h2m.GROUPED_SUMMARIES_FILE = self._tmp.name

    def tearDown(self):
        h2m.GROUPED_SUMMARIES_FILE = self._original_file
        if os.path.exists(self._tmp.name):
            os.unlink(self._tmp.name)

    def test_load_absent_file_returns_empty(self):
        """Si le fichier est absent, load retourne {"pending": []}."""
        h2m.GROUPED_SUMMARIES_FILE = "/tmp/inexistant_grouped_summaries_xyz.json"
        data = h2m.load_grouped_summaries()
        self.assertEqual(data, {"pending": []})
        h2m.GROUPED_SUMMARIES_FILE = self._tmp.name

    def test_save_and_load_roundtrip(self):
        """save puis load retourne les mêmes données."""
        original = {"pending": [SAMPLE_ENTRY]}
        h2m.save_grouped_summaries(original)
        loaded = h2m.load_grouped_summaries()
        self.assertEqual(loaded["pending"][0]["title"], SAMPLE_ENTRY["title"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
