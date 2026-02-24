#!/usr/bin/env python3
"""
Test final: comparer texte plain vs l'ancienne approche avec SSML
"""
import asyncio
import edge_tts

VOICE = "fr-FR-VivienneNeural"

async def final_test():
    test_text = "Article de Union Communiste Libertaire... Attaque antisémite en Australie : faisons front contre tous les racismes !... Par Union communiste libertaire... Suite au terrible crime antisémite. Face à tous les racismes. Un front antiraciste."
    
    print("Test FINAL - Texte plain (SANS balises SSML)")
    print("="*60)
    print(f"Contenu: {test_text}")
    print(f"Longueur: {len(test_text)} caractères")
    print("="*60)
    
    comm = edge_tts.Communicate(test_text, VOICE)
    await comm.save("final_test_plain_text.mp3")
    print("✅ Généré: final_test_plain_text.mp3")
    print("\nÉcoutez ce fichier - il ne devrait PAS prononcer de balises!")

if __name__ == "__main__":
    asyncio.run(final_test())
