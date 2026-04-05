import sys
import json
sys.path.insert(0, '.')

# Force reload — bypass any cache
import importlib
import src.ingestion
importlib.reload(src.ingestion)
from src.ingestion import _parse_format_b

json_path = (
    "data/source1/"
    "قانون_معدل_رقم_31_لسنة_2017_"
    "قانون_معدل_لقانون_أصول_المحاكمات_المدنية_لسنة_2017_ocr.json"
)

with open(json_path, encoding="utf-8-sig") as f:
    data = json.load(f)

law, warnings = _parse_format_b(data)

print("=" * 60)
print(f"Total articles: {len(law.articles)}")
print("=" * 60)

art1 = next((a for a in law.articles if a.article_number == "1"), None)
if art1:
    print(f"\nArticle 1 text (first 300 chars):")
    print(repr(art1.text[:300]))
    print()
    print("Readable:")
    print(art1.text[:300])
else:
    print("Article 1 NOT FOUND in parsed results")

print("=" * 60)
print(f"\nWarnings: {len(warnings)}")
for w in warnings:
    print(f"  - {w}")
