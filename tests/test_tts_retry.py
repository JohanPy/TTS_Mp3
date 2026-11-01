#!/usr/bin/env python3
"""
Tests unitaires pour le mécanisme de retry TTS de generate_tts_file.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import html_to_mp3 as h2m


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestGenerateTTSFile(unittest.TestCase):
    """Tests du helper generate_tts_file avec retry."""

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp()
        self._mp3_path = os.path.join(self._temp_dir, "test.mp3")

    def tearDown(self):
        if os.path.exists(self._mp3_path):
            os.remove(self._mp3_path)
        os.rmdir(self._temp_dir)

    def test_tts_success_first_try(self):
        """Si la première tentative réussit, le fichier est conservé sans retry."""
        async def fake_save(path):
            with open(path, "wb") as f:
                f.write(b"AUDIO_DATA")

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save

        with patch("edge_tts.Communicate", return_value=mock_communicate):
            _run(h2m.generate_tts_file("Texte", "voice", self._mp3_path, max_retries=3))

        self.assertTrue(os.path.exists(self._mp3_path))
        self.assertEqual(os.path.getsize(self._mp3_path), 10)

    def test_tts_retry_on_failure_then_succeed(self):
        """Si la tentative 1 échoue avec NoAudioReceived, la tentative 2 réussit."""
        call_count = 0

        async def fake_save(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                with open(path, "wb") as f:
                    f.write(b"")
                raise RuntimeError("No audio was received. Please verify that your parameters are correct.")
            with open(path, "wb") as f:
                f.write(b"SUCCESS_AUDIO")

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save

        with patch("edge_tts.Communicate", return_value=mock_communicate), \
             patch("asyncio.sleep") as mock_sleep:
            _run(h2m.generate_tts_file("Texte", "voice", self._mp3_path, max_retries=3))

        self.assertEqual(call_count, 2)
        mock_sleep.assert_called_once_with(h2m.TTS_RETRY_BASE_DELAY)
        self.assertTrue(os.path.exists(self._mp3_path))
        self.assertEqual(os.path.getsize(self._mp3_path), 13)

    def test_tts_all_retries_fail_raises_and_cleans_up(self):
        """Si toutes les tentatives échouent, lève l'exception et supprime le fichier résiduel."""
        async def fake_save_fail(path):
            with open(path, "wb") as f:
                f.write(b"partiel")
            raise RuntimeError("No audio was received")

        mock_communicate = MagicMock()
        mock_communicate.save = fake_save_fail

        with patch("edge_tts.Communicate", return_value=mock_communicate), \
             patch("asyncio.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                _run(h2m.generate_tts_file("Texte", "voice", self._mp3_path, max_retries=3))
            self.assertIn("No audio was received", str(ctx.exception))

        self.assertFalse(os.path.exists(self._mp3_path))


if __name__ == "__main__":
    unittest.main()

