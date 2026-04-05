"""
extractor.py
------------
Responsible for parsing Source 2 (raw TXT) into structured data
that mirrors Source 1 (JSON) format.

Extracts:
  1. Magazine number   → العدد ٢٦٤٥
  2. Law number + year → قانون رقم (٤٣) لسنة ١٩٧٦
  3. Articles          → المادة ١ ... المادة ٢ ...
  4. Sub-clauses       → ١ - ... ٢ - ...

Output: ExtractedLaw object that feeds directly into comparator.py
"""

import re
import logging
from dataclasses import dataclass, field

from src.config import config
from src.normalizer import normalize, normalize_number, convert_numerals

# ── Logger ─────────────────────────────────────
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────

@dataclass
class ExtractedArticle:
    """
    A single article extracted from Source 2 TXT.
    Mirrors the Article dataclass from ingestion.py.
    """
    article_number: str
    text: str           # raw text (for display)
    text_normalized: str  # normalized text (for comparison)


@dataclass
class ExtractedLaw:
    """
    Full structured result of TXT extraction.
    Ready to be compared against LawSource1.
    """
    magazine_number: str
    law_number: str
    year: str
    articles: list[ExtractedArticle] = field(default_factory=list)
    warnings: list[str]              = field(default_factory=list)

    def __repr__(self):
        return (
            f"<ExtractedLaw law={self.law_number}/{self.year} "
            f"magazine={self.magazine_number} "
            f"articles={len(self.articles)}>"
        )


# ──────────────────────────────────────────────
# Regex Patterns
# ──────────────────────────────────────────────

# Magazine number:  العدد ٢٦٤٥  or  العدد 2645
RE_MAGAZINE = re.compile(
    r'العدد\s*([\d٠-٩]+)'
)

# Law number + year:  قانون رقم (٤٣) لسنة ١٩٧٦
#                     قانون مؤقت رقم (٤٣) لسنة ١٩٧٦
RE_LAW_HEADER = re.compile(
    r'قانون\s+(?:مؤقت\s+)?رقم\s*[(\[]?\s*([\d٠-٩]+)\s*[)\]]?\s+لسنة\s+([\d٠-٩]+)'
)

# Article header patterns handled:
#   المادة ١              plain
#   المادة (١)            bracketed
#   ### المادة ١          markdown heading prefix (### or ####)
#   **المادة ١** -        bold markdown with closing **
#   **المادة ٨٩-1** -     bold + compound number (89-1)
#   **المادة ٩٢-          bold with no closing ** (broken OCR)
#   - المادة ٧٣ -         leading dash prefix
#   المادة - ١١٣٠ -       dash between المادة and number
# Constraints to avoid false positives:
#   - Must NOT be followed by "من"   (blocks: المادة 31 من الدستور)
#   - Must be at line start           (blocks: والمادة التي in mid-sentence)
RE_ARTICLE = re.compile(
    r'(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?[ \t]*-?[ \t]*المادة[ \t]*-?[ \t]*[(\[]?[ \t]*(\d+)(?:-\d+)?[ \t]*[)\]]?(?:\*{0,2})[ \t]*[-–]?(?![ \t]*من)'
)


# ──────────────────────────────────────────────
# Extraction Helpers
# ──────────────────────────────────────────────

def _extract_magazine_number(text: str) -> tuple[str, list[str]]:
    """
    Extract magazine (journal) number from raw TXT.
    Returns (magazine_number, warnings).
    """
    warnings = []

    # Convert numerals first for reliable matching
    normalized = convert_numerals(text)
    match = RE_MAGAZINE.search(normalized)

    if not match:
        warnings.append(
            "Could not extract magazine number (العدد) from TXT. "
            "It may be missing or formatted differently."
        )
        return "", warnings

    magazine_number = match.group(1).strip()
    logger.debug(f"Magazine number extracted: {magazine_number}")
    return magazine_number, warnings


def _extract_law_header(text: str) -> tuple[str, str, list[str]]:
    """
    Extract law number and year from raw TXT.
    Returns (law_number, year, warnings).
    """
    warnings = []

    normalized = convert_numerals(text)
    match = RE_LAW_HEADER.search(normalized)

    if not match:
        warnings.append(
            "Could not extract law number/year from TXT. "
            "Pattern expected: قانون رقم (XX) لسنة XXXX"
        )
        return "", "", warnings

    law_number = match.group(1).strip()
    year       = match.group(2).strip()
    logger.debug(f"Law header extracted: Law {law_number}/{year}")
    return law_number, year, warnings


def _split_into_articles(text: str) -> list[tuple[str, str]]:
    """
    Split raw TXT into a list of (article_number, article_text) tuples.

    Strategy:
      - Find all article headers using RE_ARTICLE
      - The text between article N and article N+1 is article N's body
      - Convert Arabic-Indic numerals in article numbers to Western

    Returns:
        List of (article_number: str, raw_text: str) tuples
    """
    # Convert numerals globally so article numbers are consistent
    text = convert_numerals(text)

    # Find all article header positions
    matches = list(RE_ARTICLE.finditer(text))

    if not matches:
        logger.warning("No article headers found in TXT.")
        return []

    articles = []

    # Build list of valid (number, body) pairs
    # Use deduplication: if same article number appears twice,
    # keep the one with more content (longer body)
    seen: dict[str, tuple[int, str]] = {}   # number -> (body_length, body_text)

    for i, match in enumerate(matches):
        # group(1) captures the base number only (e.g. "89" from "89-1")
        article_number = match.group(1).strip()

        try:
            int(article_number)     # Validate it is a real integer
        except ValueError:
            logger.debug(f"Non-integer article number skipped: {article_number}")
            continue

        # Text starts right after this header
        body_start = match.end()

        # Text ends at the start of the next article header (or end of file)
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        raw_body = text[body_start:body_end].strip()

        # Skip empty articles
        if not raw_body:
            logger.debug(f"Article {article_number} has empty body - skipping.")
            continue

        # Minimum body length filter:
        # Real articles have substantial content.
        # References like "المادة (83) من القانون" produce near-empty bodies.
        # 20 chars minimum filters out false positives from inline references.
        if len(raw_body.strip()) < 20:
            logger.debug(
                f"Article {article_number} skipped — "
                f"body too short ({len(raw_body)} chars), likely a reference."
            )
            continue

        # Deduplication: keep the richer (longer) version
        if article_number in seen:
            existing_len, _ = seen[article_number]
            if len(raw_body) > existing_len:
                logger.debug(
                    f"Article {article_number} duplicate - "
                    f"replacing with longer version ({len(raw_body)} > {existing_len})."
                )
                seen[article_number] = (len(raw_body), raw_body)
        else:
            seen[article_number] = (len(raw_body), raw_body)

    # Reconstruct ordered list preserving TXT order
    articles = [(num, body) for num, (_, body) in seen.items()]

    logger.debug(f"Split into {len(articles)} articles from TXT.")
    return articles


def _clean_article_text(text: str) -> str:
    """
    Clean raw article body text:
      - Remove page headers/footers (lines with only numbers)
      - Remove markdown headings (### Title, ## Title)
      - Remove markdown bold/italic (**text**, *text*)
      - Remove separator lines (---, ***, ===)
      - Remove OCR punctuation noise
      - Collapse excessive blank lines
    """
    lines = text.split("\n")
    cleaned = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines (will re-add controlled spacing)
        if not stripped:
            cleaned.append("")
            continue

        # Skip pure page number lines (just digits, 1-4 chars)
        if re.match(r'^\d{1,4}$', stripped):
            continue

        # Skip markdown section headings (## Title, ### Title)
        if re.match(r'^#{1,6}\s+', stripped):
            continue

        # Skip separator lines (---, ***, ===, ___)
        if re.match(r'^[-*=_#]{2,}$', stripped):
            continue

        # Skip OCR artifacts that are just punctuation noise
        if re.match(r'^[،,;:\-–—.]{1,3}$', stripped):
            continue

        # Strip markdown bold/italic markers (**text** or *text*)
        # but keep the text content inside them
        stripped = re.sub(r'\*{1,2}(.*?)\*{1,2}', r'\1', stripped)

        # Strip markdown heading prefix from article lines
        # e.g. "### المادة 53" leftover after split
        stripped = re.sub(r'^#{1,6}\s*', '', stripped)

        cleaned.append(stripped)

    # Collapse multiple blank lines into one
    result = re.sub(r'\n{3,}', '\n\n', "\n".join(cleaned))
    return result.strip()


# ──────────────────────────────────────────────
# Main Extractor
# ──────────────────────────────────────────────

def extract(raw_text: str) -> ExtractedLaw:
    """
    Main extraction pipeline.
    Parses a raw TXT string into a fully structured ExtractedLaw object.

    Args:
        raw_text : Raw content of Source 2 TXT file

    Returns:
        ExtractedLaw with magazine number, law info, and articles list
    """
    all_warnings = []

    logger.info("Extraction started...")

    # ── Step 1: Extract magazine number ───────
    magazine_number, w1 = _extract_magazine_number(raw_text)
    all_warnings.extend(w1)

    # ── Step 2: Extract law header ─────────────
    law_number, year, w2 = _extract_law_header(raw_text)
    all_warnings.extend(w2)

    # ── Step 3: Split into articles ────────────
    raw_articles = _split_into_articles(raw_text)

    if not raw_articles:
        all_warnings.append(
            "No articles were extracted from TXT. "
            "Check that article headers follow the pattern: المادة ١"
        )

    # ── Step 4: Build ExtractedArticle objects ─
    articles = []
    for article_number, raw_body in raw_articles:

        # Clean the raw text (remove page numbers, separators etc.)
        cleaned_text = _clean_article_text(raw_body)

        # Normalize for comparison
        normalized_text = normalize(cleaned_text, for_comparison=True)

        articles.append(ExtractedArticle(
            article_number  = article_number,
            text            = cleaned_text,
            text_normalized = normalized_text,
        ))

    # ── Step 5: Log summary ────────────────────
    logger.info(
        f"Extraction complete: "
        f"{len(articles)} articles | "
        f"magazine={magazine_number} | "
        f"law={law_number}/{year}"
    )

    if all_warnings:
        for w in all_warnings:
            logger.warning(f"  ⚠  {w}")

    return ExtractedLaw(
        magazine_number = magazine_number,
        law_number      = law_number,
        year            = year,
        articles        = articles,
        warnings        = all_warnings,
    )


def build_article_index(extracted: ExtractedLaw) -> dict[str, ExtractedArticle]:
    """
    Build a lookup dictionary for fast article access by number.

    Args:
        extracted : ExtractedLaw from extract()

    Returns:
        dict mapping article_number (str) → ExtractedArticle
        Example: {"1": ExtractedArticle(...), "2": ExtractedArticle(...)}
    """
    index = {a.article_number: a for a in extracted.articles}
    logger.debug(f"Article index built: {len(index)} entries")
    return index


# ──────────────────────────────────────────────
# Quick Self-Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import argparse
    import logging

    logging.basicConfig(
        level  = logging.INFO,
        format = "%(levelname)-8s %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Extractor module — parse a TXT law file into structured articles."
    )
    parser.add_argument("--txt",      type=str, help="Path to Source 2 (.txt) file")
    parser.add_argument("--show",     type=int, default=3,
                        help="Number of sample articles to display (default: 3)")
    parser.add_argument("--article",  type=str, default=None,
                        help="Show a specific article by number")

    args = parser.parse_args()

    sep = "=" * 60

    # ── Built-in mini test ─────────────────────
    if not args.txt:
        print(sep)
        print("EXTRACTOR BUILT-IN TEST")
        print(sep)

        sample_txt = """
عمان : الاحد ٥ شعبان سنة ١٣٩٦ م. الموافق ١ آب سنة ١٩٧٦ م. العدد ٢٦٤٥

قانون مؤقت رقم (٤٣) لسنة ١٩٧٦
القانون المدني

المادة ١ - يسمى هذا القانون ( القانون المدني لسنة ١٩٧٦) ويعمل به من ١/١/١٩٧٧.

المادة ٢ - ١ - تسري نصوص هذا القانون على المسائل التي تتناولها هذه النصوص.
٢ - فاذا لم تجد المحكمة نصا في هذا القانون حكمت بأحكام الفقه الاسلامي.
٣ - فان لم توجد حكمت بمقتضى العرف.

المادة ٣ - يرجع في فهم النص وتفسيره الى قواعد اصول الفقه الاسلامي.
"""
        result = extract(sample_txt)

        print(f"\n  Magazine №  : {result.magazine_number}")
        print(f"  Law         : {result.law_number}/{result.year}")
        print(f"  Articles    : {len(result.articles)}")

        for article in result.articles:
            print(f"\n  --- Article {article.article_number} ---")
            print(f"  Raw text   : {article.text[:120]}...")
            print(f"  Normalized : {article.text_normalized[:120]}...")

        if result.warnings:
            print(f"\n  Warnings:")
            for w in result.warnings:
                print(f"    ⚠  {w}")

        print(f"\n  {'✓ Built-in test passed' if len(result.articles) == 3 else '✗ Check extraction logic'}")
        print(sep)
        print("\nTo test with your file:")
        print("  python -m src.extractor --txt data\\source2\\ocr_1.txt")
        sys.exit(0)

    # ── Live file test ─────────────────────────
    txt_path = args.txt
    from pathlib import Path

    if not Path(txt_path).exists():
        print(f"X File not found: {txt_path}")
        sys.exit(1)

    for encoding in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            raw = Path(txt_path).read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue

    result = extract(raw)

    print()
    print(sep)
    print("EXTRACTOR RESULTS")
    print(sep)
    print(f"  File        : {Path(txt_path).name}")
    print(f"  Magazine №  : {result.magazine_number or 'NOT FOUND'}")
    print(f"  Law         : {result.law_number}/{result.year}")
    print(f"  Articles    : {len(result.articles)}")
    print(sep)

    # Show specific article
    if args.article:
        index = build_article_index(result)
        art = index.get(args.article)
        if art:
            print(f"\n  Article {art.article_number}:")
            print(f"  {art.text}")
            print(f"\n  Normalized:")
            print(f"  {art.text_normalized}")
        else:
            print(f"  Article {args.article} not found.")
            print(f"  Available: {[a.article_number for a in result.articles[:10]]}...")

    # Show sample articles
    else:
        sample_count = min(args.show, len(result.articles))
        print(f"\n  First {sample_count} articles extracted:")
        for article in result.articles[:sample_count]:
            print(f"\n  --- Article {article.article_number} ---")
            preview = article.text[:150].replace("\n", " ")
            print(f"  {preview}...")

    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    ⚠  {w}")

    print()
    print(sep)