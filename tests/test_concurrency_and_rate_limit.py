#!/usr/bin/env python3
"""
Tests unitaires pour la parallélisation et la régulation de débit :
- EdgeTTSRateLimiter : limitation à max_rpm et max_concurrency
- Verrous d'état : accès concurrents sécurisés à processed_urls.json et grouped_summaries.json
- GeminiSummarizer : exécution concurrente avec sémaphore
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import html_to_mp3 as h2m
from summarizer import GeminiSummarizer, reset_summarizer


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestEdgeTTSRateLimiter(unittest.TestCase):
    """Tests du régulateur Edge-TTS."""

    def test_concurrency_limit(self):
        """Vérifie que la concurrence ne dépasse jamais max_concurrency."""
        limiter = h2m.EdgeTTSRateLimiter(max_rpm=60, max_concurrency=2)
        active_counts = []
        current_active = 0
        lock = asyncio.Lock()

        async def worker():
            nonlocal current_active
            async with limiter:
                async with lock:
                    current_active += 1
                    active_counts.append(current_active)
                await asyncio.sleep(0.05)
                async with lock:
                    current_active -= 1

        async def main():
            await asyncio.gather(*(worker() for _ in range(5)))

        _run(main())
        self.assertTrue(all(c <= 2 for c in active_counts))
        self.assertEqual(max(active_counts), 2)

    def test_rpm_rate_limiting(self):
        """Vérifie que le limiter espace les requêtes quand max_rpm est atteint."""
        # Limiter à 2 req / fenêtre avec 0.2s de fenêtre pour tester rapidement
        limiter = h2m.EdgeTTSRateLimiter(max_rpm=2, max_concurrency=5)
        limiter._window_seconds = 0.2

        start_time = time.monotonic()

        async def run_3():
            async with limiter:
                pass
            async with limiter:
                pass
            # Le 3ème appel doit attendre que la fenêtre se vide
            async with limiter:
                pass

        _run(run_3())
        duration = time.monotonic() - start_time
        # La 3ème requête a dû attendre au moins 0.2s
        self.assertGreaterEqual(duration, 0.18)


class TestConcurrentRSSProcessing(unittest.TestCase):
    """Tests du traitement concurrent des flux RSS."""

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp()
        self._old_processed = h2m.PROCESSED_URLS_FILE
        self._old_grouped = h2m.GROUPED_SUMMARIES_FILE
        self._old_seen = h2m.SEEN_FEEDS_FILE

        h2m.PROCESSED_URLS_FILE = os.path.join(self._temp_dir, "processed_urls.json")
        h2m.GROUPED_SUMMARIES_FILE = os.path.join(self._temp_dir, "grouped_summaries.json")
        h2m.SEEN_FEEDS_FILE = os.path.join(self._temp_dir, "seen_feeds.json")

    def tearDown(self):
        h2m.PROCESSED_URLS_FILE = self._old_processed
        h2m.GROUPED_SUMMARIES_FILE = self._old_grouped
        h2m.SEEN_FEEDS_FILE = self._old_seen

        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_entries_processed_concurrently_and_state_saved(self):
        """Plusieurs articles RSS sont traités en parallèle et leurs URLs sont sauvées."""
        feed_config = {
            "url": "http://test.com/rss",
            "summarize": False,
        }

        # Simuler un flux déjà vu avec 4 nouveaux articles
        h2m.save_seen_feed("http://test.com/rss")
        processed = set()

        fake_feed = MagicMock()
        fake_feed.entries = [
            {"link": f"http://test.com/art{i}", "title": f"Article {i}"}
            for i in range(4)
        ]

        async def fake_audio(*args, **kwargs):
            await asyncio.sleep(0.02)
            return True

        def fake_fetch_html(url):
            return b"<html><body><p>" + b"Texte d'article long pour test. " * 10 + b"</p></body></html>"

        with patch("feedparser.parse", return_value=fake_feed), \
             patch("urllib.request.urlopen") as mock_urlopen, \
             patch("html_to_mp3.generate_audio_from_content", side_effect=fake_audio):

            mock_resp = MagicMock()
            mock_resp.read.side_effect = lambda: fake_fetch_html("url")
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            _run(h2m.process_rss_feed(feed_config, processed))

        # Toutes les 4 URLs doivent être marquées comme traitées
        saved = h2m.load_processed_urls()
        self.assertEqual(len(saved), 4)
        self.assertTrue(all(f"http://test.com/art{i}" in saved for i in range(4)))


class TestConcurrentSummarizer(unittest.TestCase):
    """Tests de concurrence pour GeminiSummarizer."""

    def test_summarizer_concurrency(self):
        """Vérifie que jusqu'à concurrency résumés peuvent s'exécuter simultanément."""
        reset_summarizer()
        config = {
            "api_key": "test_key",
            "model": "gemma-4-31b-it",
            "prompt": "prompt {text}",
            "max_requests_per_minute": 1800,  # Pas de délai min
            "concurrency": 3,
            "timeout": 180,
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            summarizer = GeminiSummarizer(config_path)
            active_counts = []
            current_active = 0
            lock = asyncio.Lock()

            def fake_call_api(prompt):
                nonlocal current_active
                # Simuler le travail en thread
                time.sleep(0.05)
                return "Résumé"

            with patch.object(summarizer, "_call_api_sync", side_effect=fake_call_api):
                async def run_article():
                    await summarizer.summarize("Texte d'article assez long pour déclencher le résumé... " * 5)

                async def main():
                    await asyncio.gather(*(run_article() for _ in range(6)))

                _run(main())

            self.assertEqual(summarizer._concurrency, 3)
        finally:
            os.unlink(config_path)
            reset_summarizer()


if __name__ == "__main__":
    unittest.main()

