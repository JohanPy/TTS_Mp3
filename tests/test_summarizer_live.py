#!/usr/bin/env python3
"""
Script de test en conditions réelles pour observer :
  - Le texte extrait d'un article RSS (via l'adapter générique)
  - Le résumé produit par l'IA Gemini/Gemma
  - Les métriques de réduction

Usage :
    python3 scripts/test_summarizer_live.py [--feed URL] [--limit N]

Exemple :
    python3 scripts/test_summarizer_live.py --feed http://www.developpez.com/index/rss --limit 2
"""

import argparse
import asyncio
import os
import sys
import urllib.request
from bs4 import BeautifulSoup
import feedparser

# Racine du projet dans le path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import get_adapter
from summarizer import get_summarizer

SEPARATOR = "=" * 80
SUBSEP = "-" * 80


def fetch_html(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def _truncate(text: str, max_chars: int = 2000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n  [...tronqué — {len(text)} chars au total]"


async def test_feed(feed_url: str, limit: int):
    print(SEPARATOR)
    print(f"FLUX RSS : {feed_url}")
    print(f"Limite   : {limit} article(s)")
    print(SEPARATOR)

    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(None, feedparser.parse, feed_url)

    if not feed.entries:
        print("Aucune entrée dans ce flux.")
        return

    entries = feed.entries[:limit]
    summarizer = get_summarizer()

    for idx, entry in enumerate(entries, 1):
        title = entry.get("title", "Sans titre")
        link = entry.get("link", "")

        print(f"\n{'#' * 80}")
        print(f"ARTICLE {idx}/{len(entries)} : {title}")
        print(f"URL : {link}")
        print(SEPARATOR)

        # --- Extraction HTML ---
        try:
            html_bytes = await loop.run_in_executor(None, fetch_html, link)
        except Exception as e:
            print(f"[ERREUR] Téléchargement échoué : {e}")
            continue

        soup = BeautifulSoup(html_bytes, "html.parser")
        filename_hint = title.replace(" ", "_")[:60] + ".html"
        adapter = get_adapter(soup, filename_hint)
        meta = adapter.extract_metadata()

        print(f"\nMÉTADONNÉES EXTRAITES :")
        print(f"  Titre  : {meta.get('title', '—')}")
        print(f"  Auteur : {meta.get('author', '—')}")
        print(f"  Média  : {meta.get('media', '—')}")
        print(f"  Date   : {meta.get('date', '—')}")

        raw_text = adapter.get_content()
        print(f"\n{SUBSEP}")
        print(f"TEXTE BRUT EXTRAIT ({len(raw_text)} chars, ~{len(raw_text.split())} mots) :")
        print(SUBSEP)
        print(_truncate(raw_text, 3000))

        # --- Résumé IA ---
        print(f"\n{SUBSEP}")
        print("APPEL API GEMINI...")
        print(SUBSEP)
        try:
            summary = await summarizer.summarize(raw_text)
        except Exception as e:
            print(f"  ❌  ÉCHEC DU RÉSUMÉ IA : {e}")
            continue

        ratio = round(100 * len(summary) / len(raw_text)) if raw_text else 0
        print(f"\nRÉSUMÉ IA ({len(summary)} chars, {ratio}% du texte original) :")
        print(SUBSEP)
        print(summary)
        print(SUBSEP)

        # --- Analyse ---
        print(f"\nANALYSE :")
        print(f"  Texte original : {len(raw_text):>6} chars  |  {len(raw_text.split()):>5} mots")
        print(f"  Résumé IA      : {len(summary):>6} chars  |  {len(summary.split()):>5} mots")
        print(f"  Réduction      : {100 - ratio:>5}%")

    print(f"\n{SEPARATOR}")
    print("Test terminé.")
    print(SEPARATOR)


async def main():
    parser = argparse.ArgumentParser(
        description="Test en live du summarizer Gemini sur un flux RSS"
    )
    parser.add_argument(
        "--feed",
        default="http://www.developpez.com/index/rss",
        help="URL du flux RSS (défaut : developpez.com)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Nombre d'articles à tester (défaut : 2)",
    )
    args = parser.parse_args()
    await test_feed(args.feed, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
