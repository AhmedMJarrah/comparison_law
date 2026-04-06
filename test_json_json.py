"""
test_json_json.py
-----------------
Tests the JSON-vs-JSON comparison pipeline end to end.
Run: python test_json_json.py
"""
import sys, os
sys.path.insert(0, ".")

SEP  = "=" * 65
SEP2 = "-" * 65

JSON1 = (
    "data/source1/"
    "قانون_معدل_رقم_31_لسنة_2017_"
    "قانون_معدل_لقانون_أصول_المحاكمات_المدنية_لسنة_2017_ocr.json"
)
JSON2 = JSON1   # same file for self-test (should give ~100% match)

print()
print(SEP)
print("  JSON-vs-JSON PIPELINE TEST")
print(SEP)

# ── Step 1: load_json_pair ────────────────────────────────────
print("\n[1/3] Testing load_json_pair()...")
from src.ingestion import load_json_pair

if not os.path.exists(JSON1):
    print(f"  File not found: {JSON1}")
    print("  Copy your JSON files to data/source1/ and re-run")
    sys.exit(1)

pair = load_json_pair(JSON1, JSON2, law1_index=0)
print(f"  Source 1 articles : {len(pair.source1.articles)}")
print(f"  Source 2 articles : {len(pair._extracted.articles)}")
print(f"  Law ID            : {pair.law_id}")
print(f"  Cross-validated   : {pair.cross_validated}")
print(f"  Warnings          : {len(pair.warnings)}")
for w in pair.warnings:
    print(f"    ⚠  {w}")

# ── Step 2: compare ───────────────────────────────────────────
print(f"\n[2/3] Testing compare()...")
from src.comparator import compare

report = compare(pair.source1, pair._extracted, pair.law_id)
print(f"  Coverage   : {report.coverage_pct:.1f}%")
print(f"  Match rate : {report.match_pct:.1f}%")
print(f"  Verdict    : {report.overall_verdict}")
print(f"  Match      : {report.count_match}")
print(f"  Near match : {report.count_near_match}")
print(f"  Mismatch   : {report.count_mismatch}")
print(f"  Missing    : {report.count_missing}")
print(f"  Extra      : {report.count_extra}")

# ── Step 3: generate_report ───────────────────────────────────
print(f"\n[3/3] Testing generate_report()...")
from src.reporter import generate_report

paths = generate_report(report)
print(f"  HTML  → {paths['html']}")
print(f"  Excel → {paths['excel']}")

print()
print(SEP)
if report.match_pct >= 90:
    print(f"  STATUS: OK — self-test passed ({report.match_pct:.1f}% match)")
else:
    print(f"  STATUS: WARN — self-test score lower than expected ({report.match_pct:.1f}%)")
print(SEP)
print()
