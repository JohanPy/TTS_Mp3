#!/usr/bin/env python3
"""
Tests unitaires pour le module summarizer.py

Couvre :
- Chargement de la configuration
- Rate limiting
- Appel API réussi
- Fallback sur erreur API
- Comportement du singleton
"""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# Ajouter la racine du projet au path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import summarizer as summarizer_module
from summarizer import (
    GeminiSummarizer,
    get_summarizer,
    load_gemini_config,
    reset_summarizer,
)

VALID_CONFIG = {
    "api_key": "test_api_key_123",
    "model": "gemma-4-31b-it",
    "prompt": "Résume cet article : {text}",
    "max_requests_per_minute": 15,
}

VALID_API_RESPONSE = {
    "candidates": [
        {
            "content": {
                "parts": [{"text": "Ceci est un résumé de test."}]
            }
        }
    ]
}


def _run(coro):
    """Helper pour exécuter une coroutine dans les tests synchrones."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLoadConfig(unittest.TestCase):
    """Tests du chargement de configuration."""

    def setUp(self):
        reset_summarizer()

    def test_load_valid_config(self):
        """Charge un fichier de configuration valide."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(VALID_CONFIG, f)
            path = f.name
        try:
            config = load_gemini_config(path)
            self.assertEqual(config["api_key"], "test_api_key_123")
            self.assertEqual(config["model"], "gemma-4-31b-it")
            self.assertEqual(config["max_requests_per_minute"], 15)
        finally:
            os.unlink(path)

    def test_load_missing_file(self):
        """Lève FileNotFoundError si le fichier est absent."""
        with self.assertRaises(FileNotFoundError):
            load_gemini_config("/tmp/inexistant_config_xyz.json")

    def test_load_missing_keys(self):
        """Lève ValueError si des clés obligatoires manquent."""
        incomplete = {"api_key": "key", "model": "model"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(incomplete, f)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                load_gemini_config(path)
            self.assertIn("manquantes", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_load_rpm_too_high(self):
        """Lève ValueError si max_requests_per_minute > 15."""
        bad_config = {**VALID_CONFIG, "max_requests_per_minute": 20}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad_config, f)
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                load_gemini_config(path)
            self.assertIn("15", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_load_rpm_zero(self):
        """Lève ValueError si max_requests_per_minute = 0."""
        bad_config = {**VALID_CONFIG, "max_requests_per_minute": 0}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad_config, f)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_gemini_config(path)
        finally:
            os.unlink(path)


class TestRateLimiting(unittest.TestCase):
    """Tests du rate limiter."""

    def setUp(self):
        reset_summarizer()

    def _make_summarizer(self, rpm=15) -> GeminiSummarizer:
        config = {**VALID_CONFIG, "max_requests_per_minute": rpm}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            self._config_path = f.name
        return GeminiSummarizer(self._config_path)

    def tearDown(self):
        if hasattr(self, "_config_path") and os.path.exists(self._config_path):
            os.unlink(self._config_path)
        reset_summarizer()

    def test_first_call_no_delay(self):
        """Le premier appel ne doit pas attendre."""
        s = self._make_summarizer(rpm=15)
        sleep_calls = []

        async def fake_sleep(duration):
            sleep_calls.append(duration)

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                await s._enforce_rate_limit()

        _run(run())
        self.assertEqual(len(sleep_calls), 0, "Le premier appel ne doit pas attendre")

    def test_second_call_immediate_triggers_sleep(self):
        """Deux appels très rapprochés → le deuxième doit attendre."""
        s = self._make_summarizer(rpm=15)
        sleep_calls = []

        async def fake_sleep(duration):
            sleep_calls.append(duration)

        async def run():
            with patch("asyncio.sleep", side_effect=fake_sleep):
                s._last_request_time = time.monotonic()  # simuler un appel récent
                await s._enforce_rate_limit()

        _run(run())
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreater(sleep_calls[0], 0)
        self.assertLessEqual(sleep_calls[0], 60.0 / 15)

    def test_min_interval_calculation(self):
        """L'intervalle minimum est bien 60 / max_rpm."""
        s = self._make_summarizer(rpm=10)
        self.assertAlmostEqual(s._min_interval, 6.0, places=5)


class TestSummarizeSuccess(unittest.TestCase):
    """Tests d'un appel API réussi."""

    def setUp(self):
        reset_summarizer()
        config = VALID_CONFIG.copy()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            self._config_path = f.name
        self._summarizer = GeminiSummarizer(self._config_path)

    def tearDown(self):
        os.unlink(self._config_path)
        reset_summarizer()

    def test_summarize_returns_summary(self):
        """summarize() retourne le texte de la réponse API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = VALID_API_RESPONSE

        article = "Ceci est un long article sur la technologie. " * 20

        with patch("requests.post", return_value=mock_resp):
            result = _run(self._summarizer.summarize(article))

        self.assertEqual(result, "Ceci est un résumé de test.")

    def test_summarize_uses_prompt_template(self):
        """Le prompt envoyé à l'API contient bien le texte de l'article."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = VALID_API_RESPONSE

        article = "Article de test unique sur la technologie et le développement logiciel, un sujet très important à analyser en détail."
        captured_body = {}

        def capture_post(url, params=None, json=None, timeout=None):
            captured_body.update(json or {})
            return mock_resp

        with patch("requests.post", side_effect=capture_post):
            _run(self._summarizer.summarize(article))

        sent_text = captured_body["contents"][0]["parts"][0]["text"]
        self.assertIn(article[:40], sent_text)

    def test_text_truncated_at_max_length(self):
        """Un texte très long est tronqué à MAX_TEXT_LENGTH avant envoi."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = VALID_API_RESPONSE

        long_article = "A" * 20000
        captured_body = {}

        def capture_post(url, params=None, json=None, timeout=None):
            captured_body.update(json or {})
            return mock_resp

        with patch("requests.post", side_effect=capture_post):
            _run(self._summarizer.summarize(long_article))

        sent_text = captured_body["contents"][0]["parts"][0]["text"]
        # Le texte envoyé doit être tronqué (le prompt contient le texte)
        self.assertLessEqual(len(sent_text), 20000 + len(VALID_CONFIG["prompt"]))
        # La partie article ne dépasse pas MAX_TEXT_LENGTH
        self.assertIn("A" * summarizer_module.MAX_TEXT_LENGTH, sent_text)
        self.assertNotIn("A" * (summarizer_module.MAX_TEXT_LENGTH + 1), sent_text)


class TestSummarizeFallback(unittest.TestCase):
    """Tests du fallback silencieux en cas d'erreur API."""

    def setUp(self):
        reset_summarizer()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(VALID_CONFIG, f)
            self._config_path = f.name
        self._summarizer = GeminiSummarizer(self._config_path)

    def tearDown(self):
        os.unlink(self._config_path)
        reset_summarizer()

    def test_api_error_returns_original_text(self):
        """En cas d'erreur HTTP, retourne le texte original."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        article = "Texte original de l'article."
        with patch("requests.post", return_value=mock_resp):
            result = _run(self._summarizer.summarize(article))

        self.assertEqual(result, article)

    def test_network_error_returns_original_text(self):
        """En cas d'erreur réseau, retourne le texte original."""
        import requests as req_module

        article = "Texte original de l'article."
        with patch("requests.post", side_effect=req_module.ConnectionError("Network down")):
            result = _run(self._summarizer.summarize(article))

        self.assertEqual(result, article)

    def test_short_text_returned_as_is(self):
        """Un texte trop court (< 50 chars) est retourné sans appel API."""
        short = "Court."
        with patch("requests.post") as mock_post:
            result = _run(self._summarizer.summarize(short))
        mock_post.assert_not_called()
        self.assertEqual(result, short)

    def test_empty_candidates_returns_original(self):
        """Si l'API renvoie des candidates vides, retourne le texte original."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"candidates": []}

        article = "Texte original de l'article assez long pour être traité correctement."
        with patch("requests.post", return_value=mock_resp):
            result = _run(self._summarizer.summarize(article))

        self.assertEqual(result, article)


class TestSingleton(unittest.TestCase):
    """Tests du singleton get_summarizer()."""

    def setUp(self):
        reset_summarizer()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(VALID_CONFIG, f)
            self._config_path = f.name

    def tearDown(self):
        os.unlink(self._config_path)
        reset_summarizer()

    def test_singleton_returns_same_instance(self):
        """Deux appels à get_summarizer() retournent la même instance."""
        s1 = get_summarizer(self._config_path)
        s2 = get_summarizer(self._config_path)
        self.assertIs(s1, s2)

    def test_reset_clears_singleton(self):
        """reset_summarizer() force la création d'une nouvelle instance."""
        s1 = get_summarizer(self._config_path)
        reset_summarizer()
        s2 = get_summarizer(self._config_path)
        self.assertIsNot(s1, s2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
