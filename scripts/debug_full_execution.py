import asyncio
import os
import sys
import edge_tts
import re
from html_to_mp3 import process_html_file, generate_text_content, extract_metadata, clean_filename
from bs4 import BeautifulSoup

# Configuration from html_to_mp3.py
VOICE = "fr-FR-VivienneNeural"

async def debug_execution():
    # Target specific file
    filename = "Attaque antisémite en Australie ： faisons front contre tous les racismes ! (12_21_2025 9：32：38 PM).html"
    filepath = os.path.join("Article-Test", filename)
    
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return

    print(f"Processing: {filename}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    # 1. Metadata extraction
    meta = extract_metadata(soup, filename)
    title = meta['title']
    author = meta['author']
    media = meta['media']
    
    print(f"Metadata: {title} | {media} | {author}")

    # 2. Content Generation (plain text, no SSML)
    text_body = generate_text_content(soup)
    
    # 3. Intro construction with punctuation for pauses
    text_intro = (
        f"Article de {media}... "
        f"{title}... "
        f"Par {author}... "
    )

    # Full content is plain text
    full_content = f"{text_intro}{text_body}"
    full_content = re.sub(r'\s+', ' ', full_content).strip()
    
    print("\n--- DEBUG INFO ---")
    print(f"VOICE ARG: {VOICE}")
    print(f"Content (first 500 chars):\n{full_content[:500]}")
    print(f"\nTotal length: {len(full_content)} characters")
    print("------------------\n")

    output_file = "debug_execution_output.mp3"
    print(f"Attempting generation to {output_file}...")
    
    try:
        # Pass plain text (no SSML tags)
        communicate = edge_tts.Communicate(full_content, VOICE)
        await communicate.save(output_file)
        print(f"SUCCESS: Generated {output_file}")
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    asyncio.run(debug_execution())
