import os
import unittest
from unittest.mock import patch
import html_to_mp3


class TestOutputDirForSource(unittest.TestCase):
    def test_default_fallback(self):
        with patch.object(html_to_mp3, '_cfg', {}):
            with patch.object(html_to_mp3, 'OUTPUT_DIR', '/base/output'):
                self.assertEqual(html_to_mp3.get_output_dir_for_source('html'), '/base/output')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('rss'), '/base/output')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('summary'), '/base/output')

    def test_relative_output_dirs_dict(self):
        cfg = {
            "output_dirs": {
                "html": "HTML_Files",
                "rss": "RSS_Feeds",
                "summary": "Resumes"
            }
        }
        with patch.object(html_to_mp3, '_cfg', cfg):
            with patch.object(html_to_mp3, 'OUTPUT_DIR', '/base/output'):
                self.assertEqual(html_to_mp3.get_output_dir_for_source('html'), '/base/output/HTML_Files')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('rss'), '/base/output/RSS_Feeds')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('summary'), '/base/output/Resumes')

    def test_absolute_output_dirs(self):
        cfg = {
            "output_dir_html": "/custom/html",
            "output_dir_rss": "/custom/rss",
            "output_dir_summary": "/custom/summary"
        }
        with patch.object(html_to_mp3, '_cfg', cfg):
            with patch.object(html_to_mp3, 'OUTPUT_DIR', '/base/output'):
                self.assertEqual(html_to_mp3.get_output_dir_for_source('html'), '/custom/html')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('rss'), '/custom/rss')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('summary'), '/custom/summary')

    def test_aliases(self):
        cfg = {
            "output_dirs": {
                "resume": "MesResumes"
            }
        }
        with patch.object(html_to_mp3, '_cfg', cfg):
            with patch.object(html_to_mp3, 'OUTPUT_DIR', '/base/output'):
                self.assertEqual(html_to_mp3.get_output_dir_for_source('summary'), '/base/output/MesResumes')
                self.assertEqual(html_to_mp3.get_output_dir_for_source('resumes'), '/base/output/MesResumes')


if __name__ == '__main__':
    unittest.main()
