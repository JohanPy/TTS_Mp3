#!/usr/bin/env python3
import os
import shutil
import asyncio
import edge_tts
from bs4 import BeautifulSoup

# CONFIG
INPUT_DIR = os.path.expanduser("~/Nextcloud/To_Audio")
OUTPUT_DIR = os.path.expanduser("~/Nextcloud/Podcasts") # Votre dossier plugin
ARCHIVE_DIR = os.path.expanduser("~/Nextcloud/To_Audio/Archived")
VOICE = "fr-FR-VivienneNeural"

async def process_html_file(filepath):
    filename = os.path.basename(filepath)
    print(f"Traitement de : {filename}")

    # 1. Extraction propre du texte via BeautifulSoup
    with open(filepath, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
        
    # On supprime les scripts et styles pour ne pas les lire
    for script in soup(["script", "style", "header", "footer", "nav"]):
        script.extract()

    # On récupère le texte. get_text avec separator=' ' évite de coller les mots
    text = soup.get_text(separator='. ', strip=True)
    
    if len(text) < 100:
        print("Fichier trop court ou vide.")
        return

    # 2. Génération MP3
    mp3_name = os.path.splitext(filename)[0] + ".mp3"
    mp3_path = os.path.join(OUTPUT_DIR, mp3_name)
    
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(mp3_path)
    
    # 3. Nettoyage
    shutil.move(filepath, os.path.join(ARCHIVE_DIR, filename))
    # Si Firefox a créé un dossier de fichiers liés (images etc), on le vire
    files_dir = os.path.splitext(filepath)[0] + "_files"
    if os.path.exists(files_dir):
        shutil.rmtree(files_dir)

async def main():
    if not os.path.exists(ARCHIVE_DIR): os.makedirs(ARCHIVE_DIR)
    
    # On cherche tous les fichiers .html
    for file in os.listdir(INPUT_DIR):
        if file.endswith(".html") or file.endswith(".htm"):
            await process_html_file(os.path.join(INPUT_DIR, file))

if __name__ == "__main__":
    asyncio.run(main())