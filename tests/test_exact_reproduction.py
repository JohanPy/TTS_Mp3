#!/usr/bin/env python3
"""
Reproduction EXACTE de ce que fait html_to_mp3.py actuellement
pour vérifier si le problème persiste
"""
import asyncio
import edge_tts
from xml.sax.saxutils import escape

VOICE = "fr-FR-VivienneNeural"

async def test_current_approach():
    """Test exact de l'approche actuelle dans html_to_mp3.py"""
    
    # Simul metadata
    title = "Attaque antisémite en Australie : faisons front contre tous les racismes !"
    media = "Union Communiste Libertaire"
    author = "Union communiste libertaire"
    
    # Escape comme dans le code
    safe_title_xml = escape(title, entities={'"': "&quot;", "'": "&apos;"})
    safe_media_xml = escape(media, entities={'"': "&quot;", "'": "&apos;"})
    safe_author_xml = escape(author, entities={'"': "&quot;", "'": "&apos;"})

    ssml_intro = (
        f"<p>Article de {safe_media_xml}.</p>"
        f"<break time='800ms'/>"
        f"<p>{safe_title_xml}</p>"
        f"<break time='1000ms'/>"
        f"<p>Par {safe_author_xml}.</p>"
        f"<break time='1500ms'/>"
    )
    
    # Simuler content
    ssml_body = (
        f"<p>Suite au terrible crime antisémite qui a récemment frappé l'Australie.</p>"
        f"<break time='500ms'/>"
        f"<p>Face à tous les racismes, nous affirmons le besoin de construire un front antiraciste.</p>"
    )
    
    full_content = f"{ssml_intro}{ssml_body}"
    full_content = full_content.strip()
    
    print("="*60)
    print("Contenu exact passé à edge-tts:")
    print("="*60)
    print(full_content)
    print("="*60)
    print(f"\nLongueur: {len(full_content)} caractères")
    print(f"Nombre de <break>: {full_content.count('<break')}")
    print(f"Nombre de <p>: {full_content.count('<p>')}")
    
    output_file = "test_exact_current.mp3"
    print(f"\nGénération: {output_file}...")
    
    communicate = edge_tts.Communicate(full_content, VOICE)
    await communicate.save(output_file)
    
    print(f"✅ SUCCESS: {output_file}")
    
    # Also test what would happen if we READ the tags
    print("\n" + "="*60)
    print("COMPARAISON: Si les balises étaient lues à voix haute:")
    print("="*60)
    
    # Simuler la lecture des balises
    broken_text = full_content.replace("<", " balise ouvrant ").replace(">", " balise fermant ")
    print(f"Texte si balises lues: {broken_text[:200]}...")
    print(f"Longueur du texte cassé: {len(broken_text)} caractères")
    
    communicate_broken = edge_tts.Communicate(broken_text, VOICE)
    await communicate_broken.save("test_if_tags_were_read.mp3")
    print(f"✅ Généré: test_if_tags_were_read.mp3 (pour comparaison)")

if __name__ == "__main__":
    asyncio.run(test_current_approach())
