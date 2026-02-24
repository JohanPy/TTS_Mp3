#!/usr/bin/env python3
"""
Test different SSML approaches with edge-tts to find what works.
"""
import asyncio
import edge_tts
import os

VOICE = "fr-FR-VivienneNeural"

async def test_approach(name, text, filename):
    """Test a specific approach and save to file."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"Content: {text[:200]}...")
    print(f"Output: {filename}")
    
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(filename)
        print(f"✅ SUCCESS - Generated {filename}")
        return True
    except Exception as e:
        print(f"❌ FAILED - {e}")
        return False

async def main():
    """Run all tests."""
    
    # Test 1: Plain text (baseline)
    await test_approach(
        "Test 1: Plain text with punctuation",
        "Bonjour. Ceci est un test. Pause courte, pause longue... Et voilà!",
        "test1_plain_text.mp3"
    )
    
    # Test 2: Text with <break/> tags
    await test_approach(
        "Test 2: Text with <break/> tags",
        "Bonjour<break time='1s'/> Ceci est un test<break time='500ms'/> Avec des pauses.",
        "test2_with_breaks.mp3"
    )
    
    # Test 3: Text with <p> tags
    await test_approach(
        "Test 3: Text with <p> tags",
        "<p>Bonjour</p><p>Ceci est un test</p><p>Avec des paragraphes</p>",
        "test3_with_paragraphs.mp3"
    )
    
    # Test 4: Text with <s> tags (sentence)
    await test_approach(
        "Test 4: Text with <s> tags",
        "<s>Première phrase.</s><s>Deuxième phrase.</s><s>Troisième phrase.</s>",
        "test4_with_sentences.mp3"
    )
    
    # Test 5: Text with prosody (rate change)
    await test_approach(
        "Test 5: Text with <prosody> rate",
        "Vitesse normale. <prosody rate='slow'>Vitesse lente.</prosody> <prosody rate='fast'>Vitesse rapide.</prosody>",
        "test5_with_prosody.mp3"
    )
    
    # Test 6: Mixed SSML elements
    await test_approach(
        "Test 6: Mixed SSML",
        "<p>Article de test.</p><break time='800ms'/><p>Titre principal.</p><break time='1000ms'/><p>Contenu de l'article.</p>",
        "test6_mixed_ssml.mp3"
    )
    
    # Test 7: Only breaks (no other tags)
    await test_approach(
        "Test 7: Only <break/> elements",
        "Première partie.<break time='1s'/>Deuxième partie.<break time='500ms'/>Troisième partie.",
        "test7_only_breaks.mp3"
    )
    
    print(f"\n{'='*60}")
    print("Tests completed!")
    print("\nÉcoutez les fichiers MP3 générés pour voir lesquels")
    print("interprètent correctement le SSML.")

if __name__ == "__main__":
    asyncio.run(main())
