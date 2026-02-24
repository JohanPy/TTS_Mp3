#!/usr/bin/env python3
import os
import subprocess
import asyncio
import edge_tts
from datetime import datetime

# --- CONFIGURATION ---
VOICE = "fr-FR-VivienneNeural" # Une excellente voix, très naturelle
# Autres choix : "fr-FR-HenriNeural" (Homme), "fr-FR-RemyMultilingualNeural"
OUTPUT_DIR = os.path.expanduser("~/Musique/Articles_Audio")
# ---------------------

async def main():
    # 1. Récupérer le contenu du presse-papiers via xclip
    # xclip -o -selection clipboard récupère ce que vous venez de copier (Ctrl+C)
    try:
        process = subprocess.run(['xclip', '-o', '-selection', 'clipboard'], capture_output=True, text=True)
        text = process.stdout.strip()
    except FileNotFoundError:
        notify("Erreur", "xclip n'est pas installé.")
        return

    if not text or len(text) < 50:
        notify("Erreur", "Presse-papiers vide ou texte trop court.")
        return

    # 2. Préparer le nom du fichier
    # On prend les 30 premiers caractères pour le nom ou un timestamp
    safe_title = "".join([c for c in text[:30] if c.isalnum() or c in (' ', '_')]).strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_title}.mp3"
    filepath = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 3. Génération Audio via Edge-TTS
    notify("Génération en cours...", f"Création de {filename}")
    
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(filepath)

    # 4. Notification finale
    notify("Terminé !", f"Fichier sauvegardé : {filename}")
    
    # Optionnel : Lancer la lecture directement (décommenter si voulu)
    # subprocess.Popen(['xdg-open', filepath])

def notify(title, message):
    # Envoie une notification système Ubuntu
    subprocess.run(['notify-send', title, message])

if __name__ == "__main__":
    asyncio.run(main())