#!/usr/bin/env python3
"""
Test guillemets simples vs doubles dans SSML
"""
import asyncio
import edge_tts

VOICE = "fr-FR-VivienneNeural"

async def test_quotes():
    # Test avec guillemets simples (comme dans votre code)
    text_simple = "Test un<break time='1s'/>Test deux<break time='500ms'/>Test trois"
    
    # Test avec guillemets doubles (XML standard)
    text_double = 'Test un<break time="1s"/>Test deux<break time="500ms"/>Test trois'
    
    print("Test avec guillemets simples:")
    print(text_simple)
    comm1 = edge_tts.Communicate(text_simple, VOICE)
    await comm1.save("quote_test_simple.mp3")
    print("✅ Généré: quote_test_simple.mp3\n")
    
    print("Test avec guillemets doubles:")
    print(text_double)
    comm2 = edge_tts.Communicate(text_double, VOICE)
    await comm2.save("quote_test_double.mp3")
    print("✅ Généré: quote_test_double.mp3\n")

if __name__ == "__main__":
    asyncio.run(test_quotes())
