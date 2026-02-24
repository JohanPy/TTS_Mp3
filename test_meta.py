import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup
from adapters.ucl import UCLAdapter
from adapters.generic import GenericAdapter

def print_meta(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        html = f.read()
    soup = BeautifulSoup(html, 'html.parser')
    filename = os.path.basename(file_path)
    
    ucl = UCLAdapter(soup, filename).extract_metadata()
    gen = GenericAdapter(soup, filename).extract_metadata()
    
    print(f"\n--- {filename} ---")
    for k in ["title", "author", "date", "media"]:
        print(f"[{k}]")
        print(f"  UCL: {ucl.get(k)}")
        print(f"  GEN: {gen.get(k)}")

print_meta("Article-Test/Mark Bray ： « Depuis leur création, les USA sont un pays suprémaciste blanc » (2_19_2026 11：22：47 AM).html")
print_meta("Article-Test/Anarchisme au Soudan ： Revendiquer la liberté par temps de guerre et de révolution (2_11_2026 7：34：48 PM).html")
