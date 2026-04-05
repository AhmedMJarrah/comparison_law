import sys
import json
sys.path.insert(0, '.')
from src.ingestion import _extract_article_after_toc

json_path = (
    "data/source1/"
    "قانون_معدل_رقم_31_لسنة_2017_"
    "قانون_معدل_لقانون_أصول_المحاكمات_المدنية_لسنة_2017_ocr.json"
)

with open(json_path, encoding="utf-8-sig") as f:
    data = json.load(f)

result = _extract_article_after_toc(str(data["1"]), "1")

print("=" * 60)
print("Result of _extract_article_after_toc for key [1]:")
print("=" * 60)
print(repr(result[:300]))
print()
print("Readable:")
print(result[:300])
print("=" * 60)
