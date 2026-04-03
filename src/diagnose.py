"""
diagnose.py
-----------
Diagnostic tool to investigate extraction gaps.

Runs:
  1. Shows which article numbers are in JSON but missing from TXT
  2. Shows which article numbers are in TXT but missing from JSON
  3. Scans TXT for variant article header patterns that RE_ARTICLE missed
  4. Shows sample lines around missing articles for manual inspection

Usage:
    python -m src.diagnose --json <file.json> --txt <file.txt> --law-index 0
"""

import re
import sys
import argparse
import logging
from pathlib import Path
from collections import Counter

from src.ingestion import load_pair
from src.extractor import extract, build_article_index
from src.normalizer import convert_numerals

logging.basicConfig(
    level  = logging.WARNING,       # Suppress info noise during diagnosis
    format = "%(levelname)-8s %(message)s"
)

SEP  = "=" * 65
SEP2 = "-" * 65


def load_txt(path: str) -> str:
    for enc in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            return Path(path).read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def diagnose(json_path: str, txt_path: str, law_index: int = 0):

    print()
    print(SEP)
    print("  LAW COMPARISON DIAGNOSTIC")
    print(SEP)

    # ── Load both sources ──────────────────────
    pair   = load_pair(json_path, txt_path, law_index=law_index)
    raw    = load_txt(txt_path)
    result = extract(raw)

    json_numbers = {a.article_number for a in pair.source1.articles}
    txt_numbers  = {a.article_number for a in result.articles}

    missing_in_txt  = sorted(json_numbers - txt_numbers,  key=lambda x: int(x))
    extra_in_txt    = sorted(txt_numbers  - json_numbers, key=lambda x: int(x))
    matched         = json_numbers & txt_numbers

    print(f"\n  JSON articles     : {len(json_numbers)}")
    print(f"  TXT  articles     : {len(txt_numbers)}")
    print(f"  Matched           : {len(matched)}")
    print(f"  Missing in TXT    : {len(missing_in_txt)}  ← needs investigation")
    print(f"  Extra in TXT      : {len(extra_in_txt)}   ← possible false positives")

    # ── Report 1: Missing articles ─────────────
    print()
    print(SEP2)
    print(f"  MISSING IN TXT ({len(missing_in_txt)} articles)")
    print(SEP2)
    if missing_in_txt:
        # Show in ranges for readability
        ranges = []
        start = prev = int(missing_in_txt[0])
        for n in missing_in_txt[1:]:
            curr = int(n)
            if curr == prev + 1:
                prev = curr
            else:
                ranges.append((start, prev))
                start = prev = curr
        ranges.append((start, prev))

        for s, e in ranges:
            if s == e:
                print(f"    Article {s}")
            else:
                print(f"    Articles {s} → {e}  ({e - s + 1} consecutive)")
    else:
        print("    None ✓")

    # ── Report 2: Extra articles ───────────────
    print()
    print(SEP2)
    print(f"  EXTRA IN TXT (possible false positives: {len(extra_in_txt)})")
    print(SEP2)
    if extra_in_txt:
        print(f"    {extra_in_txt[:30]}")
        if len(extra_in_txt) > 30:
            print(f"    ... and {len(extra_in_txt) - 30} more")
    else:
        print("    None ✓")

    # ── Report 3: Header pattern variants ─────
    print()
    print(SEP2)
    print("  ARTICLE HEADER PATTERN VARIANTS FOUND IN TXT")
    print(SEP2)
    print("  (These are all lines containing 'المادة' — helps spot missed patterns)")
    print()

    normalized_txt = convert_numerals(raw)
    all_madda_lines = []

    for i, line in enumerate(normalized_txt.split("\n"), 1):
        if "المادة" in line:
            all_madda_lines.append((i, line.strip()))

    # Classify each line by its pattern
    pattern_counter = Counter()
    RE_CURRENT = re.compile(
        r'(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?[ \t]*-?[ \t]*المادة[ \t]*-?[ \t]*[(\[]?[ \t]*(\d+)(?:-\d+)?[ \t]*[)\]]?(?:\*{0,2})[ \t]*[-–]?(?![ \t]*من)'
    )

    unmatched_samples = []
    for lineno, line in all_madda_lines:
        if RE_CURRENT.search("\n" + line):
            pattern_counter["matched_by_current_regex"] += 1
        else:
            pattern_counter["NOT matched"] += 1
            if len(unmatched_samples) < 20:
                unmatched_samples.append((lineno, line))

    for pattern, count in pattern_counter.most_common():
        status = "✓" if pattern == "matched_by_current_regex" else "✗"
        print(f"    {status}  {pattern:<35} : {count}")

    # ── Report 4: Unmatched header samples ────
    if unmatched_samples:
        print()
        print(SEP2)
        print(f"  UNMATCHED 'المادة' LINES (sample of up to 20)")
        print("  These lines contain 'المادة' but were NOT caught by the regex")
        print("  → Use these to improve RE_ARTICLE in extractor.py")
        print(SEP2)
        for lineno, line in unmatched_samples:
            print(f"    Line {lineno:>5} | {repr(line[:100])}")

    # ── Report 5: Context around first 5 missing ──
    if missing_in_txt:
        print()
        print(SEP2)
        print(f"  CONTEXT AROUND FIRST 5 MISSING ARTICLES")
        print("  (Searching TXT for these article numbers to see how they appear)")
        print(SEP2)

        lines = normalized_txt.split("\n")
        for art_num in missing_in_txt[:5]:
            print(f"\n  Looking for Article {art_num}:")
            found = False
            for i, line in enumerate(lines):
                if f"المادة" in line and art_num in line:
                    # Show surrounding context
                    start = max(0, i - 1)
                    end   = min(len(lines), i + 3)
                    for j in range(start, end):
                        marker = ">>>" if j == i else "   "
                        print(f"    {marker} Line {j+1:>5} | {repr(lines[j][:100])}")
                    found = True
                    break
            if not found:
                print(f"    Article {art_num} not found anywhere in TXT")

    # ── Report 6: Coverage summary ───────────
    total_json   = len(json_numbers)
    coverage_pct = (len(matched) / total_json * 100) if total_json > 0 else 0

    print()
    print(SEP)
    print("  COVERAGE SUMMARY")
    print(SEP)
    print(f"  Match rate        : {coverage_pct:.1f}%")
    if coverage_pct >= 95:
        verdict = "EXCELLENT - ready for comparison"
    elif coverage_pct >= 85:
        verdict = "GOOD - minor gaps, acceptable for comparison"
    elif coverage_pct >= 70:
        verdict = "FAIR - notable gaps, flag in report"
    else:
        verdict = "POOR - TXT may be significantly incomplete"
    print(f"  Verdict           : {verdict}")
    print()
    print(f"  Matched           : {len(matched)}")
    print(f"  Missing (OCR gap) : {len(missing_in_txt)}  → will be flagged in report")
    print(f"  Extra (unmatched) : {len(extra_in_txt)}  → will be flagged in report")
    print()
    print(SEP)
    print("  DIAGNOSTIC COMPLETE")
    print(SEP)
    print()


# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Diagnostic tool — find extraction gaps between JSON and TXT."
    )
    parser.add_argument("--json",      type=str, required=True)
    parser.add_argument("--txt",       type=str, required=True)
    parser.add_argument("--law-index", type=int, default=0)
    args = parser.parse_args()

    diagnose(args.json, args.txt, law_index=args.law_index)