import os
import sys
from bs4 import BeautifulSoup
import glob
from unittest.mock import MagicMock

# Mock dependencies
sys.modules['edge_tts'] = MagicMock()
sys.modules['mutagen'] = MagicMock()
sys.modules['mutagen.id3'] = MagicMock()

# Import local module
sys.path.append('/home/killersky4/Documents/IUT/code/TTS_Mp3')
from html_to_mp3 import generate_ssml_content, extract_metadata, clean_filename

def debug_extraction():
    test_dir = '/home/killersky4/Documents/IUT/code/TTS_Mp3/Article-Test'
    html_files = glob.glob(os.path.join(test_dir, "*.html"))
    output_file = "debug_output.txt"
    
    with open(output_file, "w", encoding="utf-8") as out:
        for filepath in html_files:
            filename = os.path.basename(filepath)
            out.write(f"\n{'='*80}\n")
            out.write(f"FILE: {filename}\n")
            out.write(f"{'='*80}\n")
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f, 'html.parser')
                
                # We want to check what generate_ssml_content returns
                # But it modifies soup in place, so let's rely on that
                ssml = generate_ssml_content(soup)
                
                out.write(ssml)
                out.write("\n")
                
            except Exception as e:
                out.write(f"ERROR: {e}\n")

    print(f"Debug output written to {output_file}")

if __name__ == "__main__":
    debug_extraction()
