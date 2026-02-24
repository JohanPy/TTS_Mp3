from bs4 import BeautifulSoup
import re

filepath = "Article-Test/La zone du cador - Les mots sont importants (lmsi.net) (2_21_2026 1：13：00 PM).html"
with open(filepath, 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("--- META ---")
for meta in soup.find_all('meta'):
    print(meta)
    
print("\n--- CONTAINER ---")
container = soup.select_one(".contenu-principal")
if container:
    print("Container .contenu-principal found.")
    for junk in container.select(".info-publi, .spip_note, .notes, .portfolio"):
        print("Extracting junk:", junk.get('class'))
else:
    print("Container not found!")
