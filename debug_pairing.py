import re
import sys
import json
sys.path.insert(0, '.')
from src.normalizer import convert_numerals

print("=" * 60)
print("DEBUG: Auto-pairing test")
print("=" * 60)

# ── Test 1: Filename regex ─────────────────────────────────────
filename = "قانون_معدل_رقم_31_لسنة_2017_قانون_معدل_لقانون_أصول_المحاكمات_المدنية_لسنة_2017_ocr.txt"
fname = convert_numerals(filename)
print(f"\nOriginal filename : {filename}")
print(f"After convert     : {fname}")

m = re.search(r'رقم[_\s]+(\d+)[_\s]+لسنة[_\s]+(\d+)', fname)
if m:
    print(f"\nRegex result      : FOUND ✓")
    print(f"  number = {m.group(1)}")
    print(f"  year   = {m.group(2)}")
else:
    print(f"\nRegex result      : NOT FOUND ✗")

# ── Test 2: JSON content ───────────────────────────────────────
print("\n" + "=" * 60)
print("DEBUG: JSON file content")
print("=" * 60)

json_path = "data/source1/قانون_معدل_رقم_31_لسنة_2017_قانون_معدل_لقانون_أصول_المحاكمات_المدنية_لسنة_2017_ocr.json"

try:
    for enc in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            with open(json_path, encoding=enc) as f:
                raw = f.read()
            print(f"Encoding used     : {enc}")
            break
        except UnicodeDecodeError:
            continue

    data = json.loads(raw)
    if isinstance(data, list):
        print(f"Laws in JSON      : {len(data)}")
        data = data[0]
    else:
        print(f"Laws in JSON      : 1 (single object)")

    leg_num = str(data.get("Leg_Number", "NOT FOUND"))
    year    = str(data.get("Year",       "NOT FOUND"))
    name    = str(data.get("Leg_Name",   "NOT FOUND"))

    print(f"Leg_Number        : {leg_num}")
    print(f"Year              : {year}")
    print(f"Leg_Name          : {name[:60]}")

    # ── Test 3: Do they match? ─────────────────────────────────
    print("\n" + "=" * 60)
    print("DEBUG: Match check")
    print("=" * 60)

    from src.normalizer import normalize_number
    json_num  = normalize_number(leg_num)
    json_year = normalize_number(year)

    if m:
        file_num  = m.group(1)
        file_year = m.group(2)
        print(f"From filename → number={file_num}, year={file_year}")
        print(f"From JSON     → number={json_num}, year={json_year}")
        if file_num == json_num and file_year == json_year:
            print("\nRESULT: MATCH ✓ — pairing should work")
        elif file_year == json_year:
            print("\nRESULT: Year matches but number differs!")
            print(f"  filename number : {file_num}")
            print(f"  JSON number     : {json_num}")
        else:
            print("\nRESULT: NO MATCH ✗ — numbers/years differ")
    else:
        print("Cannot compare — regex failed on filename")

except FileNotFoundError:
    print(f"ERROR: File not found: {json_path}")
    print("Make sure you run this from inside comparison_law folder")

print("\n" + "=" * 60)
print("Also check: is app.py updated? Run:")
print('  findstr "Strategy 1" app.py')
print("=" * 60)
