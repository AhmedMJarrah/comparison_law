"""
test_format_b.py
----------------
Tests Format B detection and parsing against the real JSON file.
Run: python test_format_b.py
"""
import sys, json, os
sys.path.insert(0, ".")

from src.ingestion import detect_json_format, _parse_format_b, _extract_articles_from_chunk

SEP  = "=" * 65
SEP2 = "-" * 65

json_path = (
    "data/source1/"
    "قانون_معدل_رقم_31_لسنة_2017_"
    "قانون_معدل_لقانون_أصول_المحاكمات_المدنية_لسنة_2017_ocr.json"
)

if not os.path.exists(json_path):
    print(f"File not found: {json_path}")
    sys.exit(1)

print()
print(SEP)
print("  FORMAT B TEST — LIVE FILE")
print(SEP)

# Load file
for enc in ["utf-8-sig", "utf-8", "cp1256"]:
    try:
        with open(json_path, encoding=enc) as f:
            data = json.load(f)
        print(f"  Encoding         : {enc}")
        break
    except UnicodeDecodeError:
        continue

print(f"  JSON keys count  : {len(data)}")
print(f"  First 5 keys     : {list(data.keys())[:5]}")

# Detect format
fmt = detect_json_format(data)
print(f"  Detected format  : {fmt}")
print(SEP2)

# Show first 3 chunks raw
print("  SAMPLE VALUES (first 3 keys)")
print(SEP2)
for i, (k, v) in enumerate(list(data.items())[:3]):
    preview = str(v)[:120].replace("\n", " / ")
    print(f"  Key [{k}]: {preview}...")
    print()

print(SEP2)
print("  PARSING RESULT")
print(SEP2)

# Parse
law, warnings = _parse_format_b(data)

print(f"  Articles found   : {len(law.articles)}")
print(f"  Law number       : '{law.leg_number}'")
print(f"  Year             : '{law.year}'")
print(f"  Warnings         : {len(warnings)}")

if warnings:
    print()
    for w in warnings:
        print(f"  ⚠  {w}")

print()
print("  FIRST 5 ARTICLES:")
print(SEP2)
for art in law.articles[:5]:
    print(f"  Article {art.article_number:>4} : {art.text[:80]}...")

print()
print("  LAST 3 ARTICLES:")
print(SEP2)
for art in law.articles[-3:]:
    print(f"  Article {art.article_number:>4} : {art.text[:80]}...")

print()
print(SEP)
if law.articles:
    print(f"  STATUS: OK — {len(law.articles)} articles extracted")
else:
    print("  STATUS: FAILED — 0 articles extracted")
    print("  Check sample values above for article header patterns")
print(SEP)
print()

# ── Extra: debug Article 1 chunk ──────────────────────────────
print()
print(SEP)
print("  DEBUG: Article 1 chunk analysis")
print(SEP)

import re as _re
from src.normalizer import convert_numerals as _cv

chunk1 = str(data.get("1", ""))
t      = _cv(chunk1)
lines  = t.split("\n")

print(f"  Total lines in key[1]: {len(lines)}")
print()

# Find المادة 1 pattern
art_pattern = _re.compile(r"المادة\s*[([]?\s*1\s*[)\]]?\s*[-\u2013]")
print("  Lines containing 'المادة 1':")
found_any = False
for i, line in enumerate(lines):
    if art_pattern.search(line):
        print(f"    Line {i:>3}: {repr(line[:100])}")
        found_any = True
if not found_any:
    print("    NOT FOUND — article 1 header not in this chunk")

print()
print("  Lines containing law header (قانون رقم):")
found_any = False
for i, line in enumerate(lines):
    if _re.search(r"قانون\s+(?:معدل\s+)?رقم\s*[([]?\s*\d+", line):
        print(f"    Line {i:>3}: {repr(line[:100])}")
        found_any = True
if not found_any:
    print("    NOT FOUND")

print()
print("  Lines 25-40 (likely where real content starts):")
for i, line in enumerate(lines[25:40], start=25):
    print(f"    {i:>3}: {repr(line[:90])}")
print(SEP)