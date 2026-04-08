import sys, json
sys.path.insert(0, ".")
from src.ingestion import _clean_format_b_text, _extract_article_after_toc
from src.normalizer import convert_numerals

SEP = "=" * 60

# Simulate Article 2 with table content
raw = """المادة ٢
يكون للكلمات والعبارات التالية المعاني المخصصة لها ادناه ما لم تدل القرينة على خلاف ذلك.

|  المملكة | المملكة الاردنية الهاشمية  |
| --- | --- |
|  الحكومة | حكومة المملكة الاردنية الهاشمية  |
|  البنك | بنك الاسكان المؤسس بمقتضى هذا القانون  |
|  المجلس | مجلس ادارة البنك  |
|  المدير العام | مدير عام البنك  |

مؤسسات الاسكان وجمعيات الاسكان التعاونية وصناديق الاسكان.

--- Page 2 ---
٤٣٣"""

print(SEP)
print("INPUT (first 200 chars):")
print(raw[:200])
print()

cleaned = _clean_format_b_text(raw)
print(SEP)
print("AFTER _clean_format_b_text:")
print(cleaned)
print()
print(f"Length: {len(cleaned)} chars")
print()

# Check table lines preserved
table_lines = [l for l in cleaned.split("\n") if "|" in l]
print(f"Table lines preserved: {len(table_lines)}")
for l in table_lines[:3]:
    print(f"  {l[:80]}")

print(SEP)
result = _extract_article_after_toc(raw, "2")
print("AFTER _extract_article_after_toc:")
print(result[:300])
print(f"\nLength: {len(result)} chars")
print("STATUS:", "OK — table content preserved ✅" if len(result) > 50 else "FAIL — too short ❌")
print(SEP)
