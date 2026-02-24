#!/usr/bin/env python3
"""
Compare adapter output vs reader_mode output for each test article.
Generates _ADAPTER_<name>.txt and _READER.txt for each HTML file,
then reports differences.
"""
import os
import sys
import re
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adapters import get_adapter
from adapters.reader_mode import reader_extract_content, reader_extract_metadata

ARTICLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Article-Test")

def load_html(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()

def get_adapter_content(soup, filename):
    """Get content using the standard adapter pipeline."""
    adapter = get_adapter(soup, filename)
    adapter_name = adapter.__class__.__name__
    content = adapter.get_content()
    return adapter_name, content

def get_reader_content(html_string):
    """Get content using reader_mode directly."""
    return reader_extract_content(html_string)

def compare_texts(adapter_text, reader_text):
    """Compare two texts and return similarity ratio and diff summary."""
    # Similarity ratio
    ratio = SequenceMatcher(None, adapter_text, reader_text).ratio()
    
    # Word-level diff for readability
    adapter_words = adapter_text.split()
    reader_words = reader_text.split()
    
    diff_lines = []
    
    # Count additions and removals
    added = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
    removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
    
    return ratio, added, removed, diff_lines

def main():
    html_files = [f for f in os.listdir(ARTICLE_DIR) if f.endswith('.html')]
    
    if not html_files:
        print("No HTML files found in Article-Test/")
        return
    
    print(f"Found {len(html_files)} HTML files to compare\n")
    print("=" * 100)
    
    results = []
    
    for html_file in sorted(html_files):
        filepath = os.path.join(ARTICLE_DIR, html_file)
        short_name = html_file[:60] + "..." if len(html_file) > 60 else html_file
        
        print(f"\n📄 {short_name}")
        print("-" * 80)
        
        html_string = load_html(filepath)
        soup = BeautifulSoup(html_string, 'html.parser')
        
        # Get adapter output
        adapter_name, adapter_content = get_adapter_content(soup, html_file)
        
        # Skip GenericAdapter (it already uses reader_mode)
        if adapter_name == "GenericAdapter":
            print(f"   ⏭️  Uses GenericAdapter (already reader_mode) — skipping")
            continue
        
        # Get reader_mode output (need fresh soup since adapter may have modified it)
        reader_content = get_reader_content(html_string)
        
        # Save files
        base = os.path.splitext(html_file)[0]
        adapter_file = os.path.join(ARTICLE_DIR, f"{base}_ADAPTER_{adapter_name}.txt")
        reader_file = os.path.join(ARTICLE_DIR, f"{base}_READER.txt")
        
        with open(adapter_file, 'w', encoding='utf-8') as f:
            f.write(adapter_content)
        with open(reader_file, 'w', encoding='utf-8') as f:
            f.write(reader_content)
        
        # Compare
        ratio, added, removed, diff_lines = compare_texts(adapter_content, reader_content)
        
        adapter_len = len(adapter_content)
        reader_len = len(reader_content)
        diff_pct = abs(adapter_len - reader_len) / max(adapter_len, 1) * 100
        
        print(f"   Adapter: {adapter_name}")
        print(f"   Adapter length: {adapter_len:,} chars ({len(adapter_content.split()):,} words)")
        print(f"   Reader length:  {reader_len:,} chars ({len(reader_content.split()):,} words)")
        print(f"   Similarity: {ratio:.1%}")
        print(f"   Length diff: {diff_pct:.1f}% {'(adapter longer)' if adapter_len > reader_len else '(reader longer)'}")
        print(f"   Words added in reader: {added}, Words removed from adapter: {removed}")
        
        if ratio > 0.95:
            print(f"   ✅ VERY SIMILAR — adapter may be removable")
        elif ratio > 0.85:
            print(f"   ⚠️  MOSTLY SIMILAR — check differences carefully")
        else:
            print(f"   ❌ SIGNIFICANTLY DIFFERENT — adapter likely needed")
        
        results.append({
            'file': html_file,
            'adapter': adapter_name,
            'ratio': ratio,
            'adapter_len': adapter_len,
            'reader_len': reader_len,
            'added': added,
            'removed': removed
        })
        
        # Show first few differences for context
        if ratio < 0.99:
            print(f"\n   📋 Sample differences (first 500 chars of adapter-only text):")
            # Find sentences in adapter but not in reader
            adapter_sentences = set(s.strip() for s in re.split(r'[.!?]+', adapter_content) if len(s.strip()) > 20)
            reader_sentences = set(s.strip() for s in re.split(r'[.!?]+', reader_content) if len(s.strip()) > 20)
            
            only_in_adapter = adapter_sentences - reader_sentences
            only_in_reader = reader_sentences - adapter_sentences
            
            if only_in_adapter:
                sample_adapter = list(only_in_adapter)[:3]
                print(f"      Only in ADAPTER ({len(only_in_adapter)} unique sentences):")
                for s in sample_adapter:
                    print(f"        - {s[:120]}...")
            
            if only_in_reader:
                sample_reader = list(only_in_reader)[:3]
                print(f"      Only in READER ({len(only_in_reader)} unique sentences):")
                for s in sample_reader:
                    print(f"        - {s[:120]}...")
    
    # Summary
    print("\n" + "=" * 100)
    print("\n📊 SUMMARY")
    print("-" * 80)
    print(f"{'Adapter':<25} {'Similarity':>12} {'Adapter':>10} {'Reader':>10} {'Verdict':<20}")
    print("-" * 80)
    for r in results:
        verdict = "REMOVE?" if r['ratio'] > 0.95 else ("CHECK" if r['ratio'] > 0.85 else "KEEP")
        print(f"{r['adapter']:<25} {r['ratio']:>11.1%} {r['adapter_len']:>10,} {r['reader_len']:>10,} {verdict:<20}")

if __name__ == "__main__":
    main()
