import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup
from adapters.lmsi import LMSIAdapter
from adapters.generic import GenericAdapter

def print_meta(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        html = f.read()
    soup = BeautifulSoup(html, 'html.parser')
    filename = os.path.basename(file_path)
    
    adapter = LMSIAdapter(soup, filename).extract_metadata()
    gen = GenericAdapter(soup, filename).extract_metadata()
    
    print(f"\n--- {filename} ---")
    for k in ["title", "author", "date", "media"]:
        print(f"[{k}]")
        print(f"  ADAPTER: {adapter.get(k)}")
        print(f"  GENERIC: {gen.get(k)}")

for f in os.listdir("Article-Test"):
    if "lmsi" in f.lower() and f.endswith(".html"):
        print_meta(f"Article-Test/{f}")
