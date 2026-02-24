# Tests Directory

This directory contains test scripts used during development and debugging.

## Test Scripts

- **debug_full_execution.py** - Debug script to test the full processing pipeline on a specific HTML file
- **debug_extraction.py** - Debug script for testing metadata extraction
- **test_exact_reproduction.py** - Test script that reproduces the exact content generation approach
- **test_final.py** - Final test for plain text approach (no SSML)
- **test_quotes.py** - Test comparing single vs double quotes in content
- **test_ssml_support.py** - Comprehensive SSML element support testing

## Test HTML Files

- **test_article.html** - Simple test article
- **test_complex_article.html** - More complex article for testing

## Debug Output

- **debug_output.txt** - Debug output from testing sessions

## Usage

To run the debug script on a specific article:

```bash
python3 tests/debug_full_execution.py
```

Note: You may need to adjust file paths in the scripts to match your setup.
