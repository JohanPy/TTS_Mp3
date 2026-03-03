import sys
import os
import glob

# Add parent directory to path to import adapters
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.reader_mode import reader_extract_content

def test_directory(directory_path):
    files = glob.glob(os.path.join(directory_path, "*.html"))
    for filepath in files:
        print(f"Testing {os.path.basename(filepath)}")
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()
        
        text = reader_extract_content(html)
        print("EXTRACTED TEXT START:")
        print(text[:1500])  # Print just the first 1500 chars to avoid huge console output
        print("...\nEXTRACTED TEXT END\n")

if __name__ == "__main__":
    test_directory("/home/killersky4/Documents/IUT/code/TTS_Mp3/Article-Test")
