"""
normalizer.py
-------------
Arabic text normalization engine.
Handles:
  - Arabic-Indic numeral conversion  (٣ → 3)
  - Diacritics (tashkeel) removal
  - Alef variants normalization       (أ إ آ ا → ا)
  - Yaa variants normalization        (ى → ي)
  - Taa marbuta normalization         (ة → ه)
  - Tatweel removal                   (ـ)
  - Whitespace & punctuation cleanup
  - Sub-clause marker normalization   (٢ – / 2. → unified format)

All toggles are driven by config (which reads from .env).
"""

import re
from src.config import config


# ──────────────────────────────────────────────
# Numeral Maps
# ──────────────────────────────────────────────

ARABIC_INDIC_MAP = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩",
    "0123456789"
)

EXTENDED_ARABIC_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹",
    "0123456789"
)


# ──────────────────────────────────────────────
# Core Normalization Functions
# ──────────────────────────────────────────────

def convert_numerals(text: str) -> str:
    """Convert Arabic-Indic and Extended Arabic numerals to Western."""
    text = text.translate(ARABIC_INDIC_MAP)
    text = text.translate(EXTENDED_ARABIC_MAP)
    return text


def remove_diacritics(text: str) -> str:
    """Remove Arabic diacritics (tashkeel/harakat)."""
    return re.sub(r'[\u064B-\u065F\u0670]', '', text)


def normalize_alef(text: str) -> str:
    """Normalize all Alef variants to bare Alef (ا)."""
    return re.sub(r'[أإآٱ]', 'ا', text)


def normalize_yaa(text: str) -> str:
    """Normalize Alef Maqsura (ى) to Yaa (ي)."""
    return text.replace('ى', 'ي')


def normalize_taa_marbuta(text: str) -> str:
    """Normalize Taa Marbuta (ة) to Haa (ه)."""
    return text.replace('ة', 'ه')


def remove_tatweel(text: str) -> str:
    """Remove Tatweel/Kashida (ـ) used for text stretching."""
    return text.replace('\u0640', '')


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/newlines into single space."""
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    return text.strip()


def normalize_punctuation(text: str) -> str:
    """Normalize Arabic punctuation and clause markers."""
    text = text.replace('،', ',')
    text = text.replace('؛', ';')
    text = text.replace('؟', '?')
    text = re.sub(r'[–—]', '-', text)
    return text


def normalize_sub_clauses(text: str) -> str:
    """
    Unify sub-clause markers from both sources.

    Source 1: '1. text'  or  '\n1. text'
    Source 2: '١ - text' or  '١– text'

    Unified output: '[1] text'
    """
    # Source 2 pattern: numeral followed by dash (after numeral conversion)
    text = re.sub(r'(?m)^\s*(\d+)\s*[-–]\s*', r'[\1] ', text)
    # Source 1 pattern: numeral followed by dot
    text = re.sub(r'(?m)^\s*(\d+)\.\s*', r'[\1] ', text)
    return text


# ──────────────────────────────────────────────
# Article Text Flattening
# ──────────────────────────────────────────────

# Patterns that mark the START of a sub-clause inside an article body.
# These are formatting markers, not article identifiers.
# All patterns are stripped before comparison so both sources
# produce identical clean text regardless of how they were formatted.

# Ordinal markers: أولاً: / ثانياً: / ثالثاً: etc.
_RE_ORDINAL = re.compile(
    r"(?:أولاً|ثانياً|ثالثاً|رابعاً|خامساً|سادساً|سابعاً|ثامناً|تاسعاً|عاشراً)"
    r"\s*[:–-]\s*",
    re.UNICODE
)

# Lettered markers: أ- / ب- / ج- / أ) / ب) etc.
_RE_LETTER_MARKER = re.compile(
    r"(?m)^[ 	]*[أبتثجحخدذرزسشصضطظعغفقكلمنهوي]\s*[-–)\]]\s*",
    re.UNICODE
)

# Numbered+lettered compound markers: ١-أ- / 2-أ- / ٢-ب- etc.
_RE_COMPOUND_MARKER = re.compile(
    r"(?m)^[ 	]*\d+\s*-\s*[أبتثجحخدذرزسشصضطظعغفقكلمنهوي]\s*-\s*",
    re.UNICODE
)

# Numbered markers: 1. / ١. / 1- / ١- at line start
_RE_NUMBERED_MARKER = re.compile(
    r"(?m)^[ 	]*\d+\s*[.\-–)\]]\s*",
    re.UNICODE
)

# Page break markers from OCR: --- Page N ---
_RE_PAGE_BREAK = re.compile(
    r"-{2,}\s*Page\s*\d+\s*-{2,}",
    re.IGNORECASE
)

# Standalone page numbers: a line that is only digits (e.g. "٥٣٩٢")
_RE_PAGE_NUMBER = re.compile(
    r"(?m)^\s*\d{3,5}\s*$"
)

# Journal/header lines: الجريدة الرسمية (common OCR artifact in Format B)
_RE_JOURNAL = re.compile(
    r"الجريدة\s+الرسمية\s*",
    re.UNICODE
)


def flatten_article_text(text: str) -> str:
    """
    Flatten an article text body for accurate comparison.

    The problem:
      Source 1 (Format A) stores article bodies with numbered clauses:
        "1. تسري نصوص... 2. فاذا لم تجد... 3. فان لم توجد..."

      Source 2 (Format B) stores the same article with ordinal/lettered clauses:
        "أولاً: تسري نصوص... ثانياً: فاذا لم تجد... ثالثاً: فان لم توجد..."

      Same legal content — different formatting → unfair score penalty.

    The solution:
      Strip ALL sub-clause markers from BOTH sources so the comparator
      sees only the actual legal text. This maximizes similarity scores
      for genuinely matching content and minimizes false mismatches
      caused purely by formatting differences.

    What is stripped:
      - Ordinal markers:          أولاً: / ثانياً: / ثالثاً: ...
      - Lettered markers:         أ- / ب- / ج- ...
      - Compound markers:         ١-أ- / 2-ب- ...
      - Numbered markers:         1. / 2. / ١- / ٢- ...
      - OCR page break markers:   --- Page 7 ---
      - Standalone page numbers:  ٥٣٩٢
      - Journal header lines:     الجريدة الرسمية

    What is NOT stripped:
      - The article header itself (المادة N -) — handled by caller
      - References to other articles: "المادة (٥) من القانون الأصلي"
        → these are CONTENT, not formatting markers
      - Ordinals used mid-sentence: "على أن يكون أولاً..."

    Scalability:
      Works for all Jordanian law formats because it targets
      universal Arabic clause-marking conventions, not
      law-specific patterns.
    """
    if not text or not isinstance(text, str):
        return ""

    # Step 1: Convert numerals so all regex work on Western digits
    text = convert_numerals(text)

    # Step 2: Remove OCR noise (page breaks, page numbers, journal header)
    text = _RE_PAGE_BREAK.sub(" ", text)
    text = _RE_PAGE_NUMBER.sub("", text)
    text = _RE_JOURNAL.sub(" ", text)

    # Step 3: Strip sub-clause markers
    # Order matters: compound (١-أ-) before numbered (١-) before lettered (أ-)
    text = _RE_COMPOUND_MARKER.sub("", text)
    text = _RE_ORDINAL.sub("", text)
    text = _RE_LETTER_MARKER.sub("", text)
    text = _RE_NUMBERED_MARKER.sub("", text)

    # Step 4: Collapse whitespace — multiple newlines/spaces → single space
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    text = text.strip()

    return text


# ──────────────────────────────────────────────
# Master Normalizer
# ──────────────────────────────────────────────

def normalize(text: str, for_comparison: bool = True) -> str:
    """
    Full normalization pipeline driven by config/.env toggles.

    Args:
        text           : Raw input text
        for_comparison : If True  → aggressive normalization for matching accuracy.
                         If False → lighter normalization for display in reports.

    Returns:
        Normalized text string.
    """
    if not text or not isinstance(text, str):
        return ""

    # Always applied
    text = convert_numerals(text)
    text = normalize_punctuation(text)
    text = normalize_sub_clauses(text)

    # Config-driven toggles
    if config.REMOVE_DIACRITICS:
        text = remove_diacritics(text)

    if config.REMOVE_TATWEEL:
        text = remove_tatweel(text)

    if config.NORMALIZE_ALEF:
        text = normalize_alef(text)

    if config.NORMALIZE_YAA:
        text = normalize_yaa(text)

    # Aggressive normalization only for comparison (not display)
    if for_comparison and config.NORMALIZE_TAA_MARBUTA:
        text = normalize_taa_marbuta(text)

    # Always last
    text = normalize_whitespace(text)

    return text


def normalize_number(value: str) -> str:
    """
    Normalize a standalone number string.
    Example: ' ٢٦٤٥ ' → '2645'
    """
    value = str(value).strip()
    value = convert_numerals(value)
    return value.strip()


# ──────────────────────────────────────────────
# Quick Self-Test
# ──────────────────────────────────────────────

if __name__ == "__main__":

    print("=" * 60)
    print("NORMALIZER SELF-TEST")
    print("=" * 60)
    print(f"  Config loaded from : {config.BASE_DIR / '.env'}")
    print(f"  NORMALIZE_ALEF     : {config.NORMALIZE_ALEF}")
    print(f"  NORMALIZE_YAA      : {config.NORMALIZE_YAA}")
    print(f"  NORMALIZE_TAA      : {config.NORMALIZE_TAA_MARBUTA}")
    print(f"  REMOVE_DIACRITICS  : {config.REMOVE_DIACRITICS}")
    print(f"  REMOVE_TATWEEL     : {config.REMOVE_TATWEEL}")
    print("=" * 60)

    samples = [
        (
            "Arabic-Indic numerals",
            "العدد ٢٦٤٥",
            "العدد 2645"
        ),
        (
            "Alef normalization",
            "أحكام إسلامية",
            "احكام اسلاميه" if config.NORMALIZE_TAA_MARBUTA else "احكام اسلامية"
        ),
        (
            "Diacritics removal",
            "القانُونُ المَدَنِي",
            "القانون المدني"
        ),
        (
            "Sub-clause Source2 pattern",
            "٢ - نص المادة",
            "[2] نص الماده" if config.NORMALIZE_TAA_MARBUTA else "[2] نص المادة"
        ),
        (
            "Sub-clause Source1 pattern",
            "2. نص المادة",
            "[2] نص الماده" if config.NORMALIZE_TAA_MARBUTA else "[2] نص المادة"
        ),
        (
            "Tatweel removal",
            "القانـــون",
            "القانون"
        ),
        (
            "normalize_number()",
            "٢٦٤٥",
            "2645"
        ),
    ]

    all_passed = True
    for name, raw, expected in samples:
        result  = normalize(raw) if name != "normalize_number()" else normalize_number(raw)
        passed  = result == expected
        status  = "✓ PASS" if passed else "✗ FAIL"
        if not passed:
            all_passed = False

        print(f"\n  [{status}] {name}")
        print(f"    Input    : {raw}")
        print(f"    Expected : {expected}")
        print(f"    Got      : {result}")

    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED ✓" if all_passed else "  SOME TESTS FAILED ✗ — check .env toggles")
    print("=" * 60)