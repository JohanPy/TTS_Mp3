# Tests Directory

This directory contains test scripts used during development and validation of the TTS_Mp3 core functions.

## Test Scripts

- **test_exact_reproduction.py** - Test script that reproduces the exact content generation approach
- **test_final.py** - Final test for plain text approach (no SSML)
- **test_quotes.py** - Test comparing single vs double quotes in content
- **test_ssml_support.py** - Comprehensive SSML element support testing

## Usage

To run the full test suite manually:

```bash
python3 tests/test_final.py
```
