"""
ingestion.py
------------
Responsible for:
  1. Accepting explicit --json and --txt file paths from CLI
  2. Validating both files (existence, extension, content)
  3. Parsing Source 1 (.json) into a clean LawDocument object
  4. Parsing Source 2 (.txt) into raw text ready for extraction
  5. Cross-validating that both files belong to the same law
  6. Returning a unified PairedLaw object to the pipeline

Usage (from main.py):
    from src.ingestion import load_pair
    pair = load_pair(json_path, txt_path)
"""

import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from src.config import config
from src.normalizer import normalize_number, convert_numerals

# ── Logger ─────────────────────────────────────
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────

@dataclass
class Article:
    """Represents a single article from Source 1 (JSON)."""
    article_number: str
    title: str
    enforcement_date: str
    text: str


@dataclass
class LawSource1:
    """
    Parsed representation of a Source 1 JSON file.
    Contains structured metadata + list of articles.
    """
    leg_name: str
    leg_number: str
    year: str
    magazine_number: str
    magazine_page: str
    magazine_date: str
    articles: list[Article] = field(default_factory=list)

    def __repr__(self):
        return (
            f"<LawSource1 leg_number={self.leg_number} "
            f"year={self.year} "
            f"articles={len(self.articles)}>"
        )


@dataclass
class LawSource2:
    """
    Parsed representation of a Source 2 TXT file.
    Holds raw text for the extractor to process.
    """
    raw_text: str
    file_path: str

    def __repr__(self):
        return (
            f"<LawSource2 file={Path(self.file_path).name} "
            f"chars={len(self.raw_text)}>"
        )


@dataclass
class PairedLaw:
    """
    Final output of ingestion.
    Carries both sources validated and paired,
    ready to flow into extraction → comparison → reporting.
    """
    law_id: str                         # e.g. "law_43_1976"
    source1: LawSource1
    source2: LawSource2
    cross_validated: bool = False       # True if law numbers matched across sources
    warnings: list[str] = field(default_factory=list)

    def __repr__(self):
        return (
            f"<PairedLaw id={self.law_id} "
            f"cross_validated={self.cross_validated} "
            f"warnings={len(self.warnings)}>"
        )


# ──────────────────────────────────────────────
# Validation Helpers
# ──────────────────────────────────────────────

def _validate_path(path: str, expected_ext: str) -> Path:
    """
    Validate that a file path:
      - Is not empty
      - Has the correct extension
      - Exists on disk
      - Is a file (not a directory)

    Returns a resolved Path object.
    Raises ValueError or FileNotFoundError on failure.
    """
    if not path or not path.strip():
        raise ValueError(f"File path cannot be empty.")

    p = Path(path.strip())

    if p.suffix.lower() != expected_ext.lower():
        raise ValueError(
            f"Expected a '{expected_ext}' file, got '{p.suffix}' → {p.name}"
        )

    if not p.exists():
        raise FileNotFoundError(
            f"File not found: {p.resolve()}"
        )

    if not p.is_file():
        raise ValueError(
            f"Path is a directory, not a file: {p.resolve()}"
        )

    return p.resolve()


def _validate_json_structure(data: dict) -> list[str]:
    """
    Validate that a parsed JSON dict has the expected
    top-level keys and at least one article.

    Returns a list of warning strings (empty = all good).
    """
    warnings = []
    required_keys = ["Leg_Name", "Leg_Number", "Year", "Magazine_Number", "Articles"]

    for key in required_keys:
        if key not in data:
            warnings.append(f"Missing expected JSON key: '{key}'")

    if "Articles" in data:
        if not isinstance(data["Articles"], list):
            warnings.append("'Articles' field is not a list.")
        elif len(data["Articles"]) == 0:
            warnings.append("'Articles' list is empty — no articles to compare.")
        else:
            # Spot-check first article structure
            first = data["Articles"][0]
            for akey in ["article_number", "text"]:
                if akey not in first:
                    warnings.append(f"Article is missing expected key: '{akey}'")

    return warnings


# ──────────────────────────────────────────────
# JSON Format Detection
# ──────────────────────────────────────────────

def detect_json_format(data) -> str:
    """
    Detect which JSON format the data uses.

    Format A (old structured):
      {"Leg_Number": "43", "Year": "1976", "Articles": [...]}
      OR a list of such objects

    Format B (new pre-segmented):
      {"1": "المادة 1 - ...", "2": "المادة 2 - ...", ...}
      Keys are article numbers (numeric strings), values are article texts.

    Returns: "A" or "B"
    """
    # If it is a list, check the first element
    check = data[0] if isinstance(data, list) else data

    if not isinstance(check, dict):
        return "A"

    # Format B signature: ALL keys are numeric strings
    # and values are strings (article texts)
    keys = list(check.keys())
    if not keys:
        return "A"

    numeric_keys = sum(1 for k in keys[:20] if str(k).strip().isdigit())
    string_values = sum(
        1 for k in keys[:20]
        if isinstance(check.get(k), str)
    )

    # If >80% of sample keys are numeric and values are strings → Format B
    sample = min(20, len(keys))
    if numeric_keys / sample >= 0.8 and string_values / sample >= 0.8:
        return "B"

    return "A"


def _strip_article_header(text: str, article_number: str) -> str:
    """
    Remove the article header from Format B article text.

    The text contains the header inside it, e.g.:
      "المادة 1 - يسمى هذا القانون..."
      "المادة ١ - يسمى هذا القانون..."

    We strip the header to get just the body — consistent
    with how Format A stores articles (body only in 'text' field).
    """
    from src.normalizer import convert_numerals

    # Convert Arabic-Indic numerals in text for matching
    text_converted = convert_numerals(text.strip())
    num_converted  = convert_numerals(str(article_number).strip())

    # Pattern: المادة {number} followed by optional brackets, dashes, spaces
    pattern = re.compile(
        r"^[\s\-–]*المادة[\s\-–]*[([]?"
        + re.escape(num_converted)
        + r"[)\]]?[\s\-–]*",
        re.UNICODE | re.MULTILINE
    )

    cleaned = pattern.sub("", text_converted).strip()

    # If nothing was stripped, return original (header may vary)
    return cleaned if cleaned else text_converted


def _clean_format_b_text(text: str) -> str:
    """
    Clean a Format B JSON value:
    - Remove OCR page break markers: --- Page X ---
    - Remove markdown headings: # Title, ## Title
    - Remove table-of-contents lines (contain | characters)
    - Collapse excessive whitespace
    """
    lines         = text.split("\n")
    cleaned        = []
    past_header    = False   # True once we've seen an article header (المادة N)

    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append("")
            continue
        # Skip page break markers always
        if re.match(r"^-{2,}\s*Page\s*\d+\s*-{2,}$", s, re.IGNORECASE):
            continue
        # Skip pure page number lines always
        if re.match(r"^\d{1,4}$", s):
            continue
        # Skip pure markdown section headings (not article headers) always
        if re.match(r"^#{1,6}\s+[^0-9]", s) and "المادة" not in s:
            continue
        # Detect article header — once we pass it, tables become content
        if re.search(r"المادة\s*[([]?\s*\d+", s):
            past_header = True
        # Skip pipe-separated lines ONLY if we haven't reached the article header yet
        # (those are TOC lines). After the header, pipes are table content — keep them.
        if s.count("|") >= 2 and not past_header:
            continue
        cleaned.append(line)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned))
    return result.strip()


def _extract_articles_from_chunk(
    chunk_text: str,
    hint_key: str,
) -> list[tuple[str, str]]:
    """
    Extract one or more articles from a Format B JSON value.

    Strategy:
      1. Clean the chunk (remove page markers, TOC lines etc.)
      2. Run the article header regex to find all المادة N headers
      3. If headers found  → split on them and return list of (number, body)
      4. If NO header found → use hint_key as article number, entire text as body

    Returns: list of (article_number: str, body_text: str)
    """
    from src.normalizer import convert_numerals as _cv

    text = _clean_format_b_text(chunk_text)
    text = _cv(text)

    # Regex: same pattern as extractor.py RE_ARTICLE
    RE = re.compile(
        r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?[ \t]*-?[ \t]*"
        r"المادة[ \t]*-?[ \t]*[(\[]?[ \t]*(\d+)(?:-\d+)?"
        r"[ \t]*[)\]]?(?:\*{0,2})[ \t]*[-–]?(?![ \t]*\u0645\u0646)"
    )

    matches = list(RE.finditer(text))

    if not matches:
        # No article header found in this chunk
        # Use hint_key as the article number if it looks numeric
        hint = str(hint_key).strip()
        body = text.strip()
        if body and hint.isdigit():
            return [(hint, body)]
        return []

    results = []
    seen    = set()

    for i, m in enumerate(matches):
        art_num    = m.group(1).strip()
        body_start = m.end()
        body_end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body       = text[body_start:body_end].strip()

        if not body or art_num in seen:
            continue
        seen.add(art_num)
        results.append((art_num, body))

    return results


def _is_article_chunk(text: str, key: str) -> bool:
    """
    Determine if a Format B chunk is a real article or non-article content.

    A chunk is considered NOT a pure article if:
      - Its dominant content is a table of contents (many | characters)
      - It has no meaningful Arabic text after cleaning

    NOTE: even if a chunk fails this check, _parse_format_b will still
    attempt to extract article content from it using _extract_article_after_toc()
    so no content is lost.
    """
    from src.normalizer import convert_numerals as _cv
    t = _cv(text.strip())

    # Check meaningful content after stripping noise
    lines        = t.split("\n")
    meaningful   = []
    toc_lines    = 0
    past_header  = False   # True once we pass an article header

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^-{2,}\s*Page\s*\d+", s, re.IGNORECASE):
            continue
        if re.match(r"^\d{1,4}$", s):
            continue
        if re.match(r"^#", s) and "المادة" not in s:
            continue
        # Detect article header
        if re.search(r"المادة\s*[([]?\s*\d+", s):
            past_header = True
        # Count pipe lines as TOC only before the article header
        if s.count("|") >= 2:
            if not past_header:
                toc_lines += 1
            else:
                # Post-header table → treat as meaningful content
                meaningful.append(s)
            continue
        meaningful.append(s)

    total_content = " ".join(meaningful)

    # Pure TOC/header with no meaningful text → not an article chunk
    if len(total_content) < 10:
        return False

    # Mostly TOC (more TOC lines than content lines) → not a pure article
    # but may still contain an article embedded after the TOC
    if toc_lines > len(meaningful):
        return False

    return True


def _extract_article_after_toc(text: str, expected_num: str) -> str:
    """
    For mixed chunks (TOC + article), find the article content
    that appears AFTER the table of contents section.

    Strategy: find the law header line or first المادة N line,
    then take everything from there onwards.
    """
    from src.normalizer import convert_numerals as _cv
    t = _cv(text)
    lines = t.split("\n")

    # Find where the actual law content starts
    # Either: "قانون رقم (N) لسنة YYYY" or "المادة N -"
    start_idx = None
    for i, line in enumerate(lines):
        s = line.strip()
        # Law header line
        if re.search(r"قانون\s+(?:معدل\s+)?رقم\s*[([]?\s*\d+", s):
            start_idx = i
            break
        # Article header line matching expected number (dash optional)
        art_pattern = re.compile(
            r"المادة\s*[([]?\s*" + re.escape(expected_num) + r"\s*[)\]]?\s*[-–]?"
        )
        if art_pattern.search(s):
            start_idx = i
            break

    if start_idx is None:
        return ""

    # Search the ENTIRE chunk for the article header
    # (not just from start_idx — the article may be anywhere after TOC)
    art_start_idx = None
    num_conv      = convert_numerals(expected_num)
    art_pattern   = re.compile(
        r"المادة\s*[([]?\s*" + re.escape(num_conv) + r"\s*[)\]]?\s*[-–]?"
    )
    for i, line in enumerate(lines):
        if art_pattern.search(convert_numerals(line)):
            art_start_idx = i
            break

    # If article header found anywhere → use that (most precise)
    # If not found → fall back to law header position
    actual_start = art_start_idx if art_start_idx is not None else start_idx

    # Take content from actual_start onwards
    content_lines = []
    for line in lines[actual_start:]:
        s = line.strip()
        # Skip page markers
        if re.match(r"^-{{2,}}\s*Page\s*\d+", s, re.IGNORECASE):
            continue
        content_lines.append(line)

    result = "\n".join(content_lines).strip()
    # Strip the article header from the result
    result = _strip_article_header(result, expected_num)
    return result.strip()


def _parse_format_b(data: dict) -> tuple[LawSource1, list[str]]:
    """
    Parse a Format B JSON into a LawSource1 object.

    Format B structure:
      {
        "1": "القسم الثاني ... (table of contents)",
        "2": "المادة ٢ - تعدل المادة (٥) ...",
        "3": "المادة ٣ - يلغى ...",
        ...
      }

    Strategy: USE THE KEY as the article number (keys are reliable).
    Strip the article header from the value to get the body.
    Skip non-article chunks (TOC, page headers).

    This avoids false positives from article number references
    that appear inside article body text.

    Returns: (LawSource1, warnings_list)
    """
    warnings = []

    # Sort keys numerically
    try:
        sorted_keys = sorted(data.keys(), key=lambda k: int(str(k).strip()))
    except (ValueError, TypeError):
        sorted_keys = list(data.keys())
        warnings.append("Could not sort keys numerically — using original order.")

    articles   = []
    skipped    = 0

    for key in sorted_keys:
        raw_value = str(data[key]).strip()
        if not raw_value:
            continue

        art_num = str(key).strip()

        if not _is_article_chunk(raw_value, key):
            # Chunk is not a pure article (e.g. TOC + article mixed)
            # Attempt to rescue the article content from after the TOC
            rescued = _extract_article_after_toc(raw_value, art_num)
            if rescued:
                logger.info(
                    f"Format B: rescued article {art_num} from mixed chunk (key [{key}])"
                )
                articles.append(Article(
                    article_number   = art_num,
                    title            = f"المادة {art_num}",
                    enforcement_date = "",
                    text             = rescued,
                ))
            else:
                skipped += 1
                logger.debug(f"Format B: skipped key [{key}] — no article content found")
            continue

        # For any chunk — use _extract_article_after_toc first
        # This precisely finds the article header and takes only what follows
        # Works for both pure article chunks AND mixed TOC+article chunks
        body = _extract_article_after_toc(raw_value, art_num)

        if not body.strip():
            # Fallback: clean and strip header manually
            body = _clean_format_b_text(raw_value)
            body = convert_numerals(body)
            body = _strip_article_header(body, art_num)

        if not body.strip():
            skipped += 1
            continue

        articles.append(Article(
            article_number   = art_num,
            title            = f"المادة {art_num}",
            enforcement_date = "",
            text             = body.strip(),
        ))

    if skipped > 0:
        logger.info(f"Format B: skipped {skipped} non-article chunks (no content found)")

    if not articles:
        warnings.append(
            "Format B: no articles extracted after filtering. "
            "Check that JSON values contain article text."
        )

    # Extract law number + year from the first few chunks
    leg_number = ""
    year       = ""
    all_text   = convert_numerals(" ".join(str(v) for v in list(data.values())[:5]))

    m = re.search(
        r"قانون\s+(?:معدل\s+)?(?:مؤقت\s+)?رقم\s*[([]?\s*(\d+)\s*[)\]]?\s+لسنة\s+(\d+)",
        all_text
    )
    if m:
        leg_number = m.group(1).strip()
        year       = m.group(2).strip()
        logger.info(f"Format B: extracted law {leg_number}/{year}")
    else:
        warnings.append(
            "Format B: could not extract law number/year. "
            "Cross-validation will be skipped."
        )

    law = LawSource1(
        leg_name       = "",
        leg_number     = leg_number,
        year           = year,
        magazine_number= "",
        magazine_page  = "",
        magazine_date  = "",
        articles       = articles,
    )

    logger.info(
        f"Format B parsed: {len(articles)} articles "
        f"({skipped} skipped), law={leg_number}/{year}"
    )
    return law, warnings


# ──────────────────────────────────────────────
# Parsers
# ──────────────────────────────────────────────

def list_laws_in_json(json_path: str) -> None:
    """
    Utility: print all laws available inside a multi-law JSON file.
    Helps user identify the correct --law-index to pass.

    Usage:
        python -m src.ingestion --list data/source1/qistas_ext.json
    """
    p = Path(json_path.strip())
    if not p.exists():
        print(f"X File not found: {p}")
        return

    raw = None
    for encoding in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            raw = p.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue

    if raw is None:
        print("X Could not decode file — try saving as UTF-8.")
        return

    data = json.loads(raw)

    if not isinstance(data, list):
        data = [data]

    sep = "=" * 60
    print()
    print(sep)
    print(f"  Laws found in: {p.name}  ({len(data)} total)")
    print(sep)
    for i, law in enumerate(data):
        leg_num  = normalize_number(str(law.get("Leg_Number", "?")))
        year     = normalize_number(str(law.get("Year", "?")))
        name     = law.get("Leg_Name", "N/A")
        articles = len(law.get("Articles", []))
        print(f"  [{i}]  Law {leg_num}/{year}  |  {articles} articles  |  {name}")
    print(sep)
    print(f"  Tip: python main.py --json {p.name} --txt <file.txt> --law-index <N>")
    print()


def _parse_source1(json_path: Path, law_index: int = 0) -> tuple[LawSource1, list[str]]:
    """
    Parse a validated JSON file into a LawSource1 object.
    Auto-detects JSON format (A or B) and routes accordingly.

    Format A: {"Leg_Number":..., "Articles":[...]}  — structured metadata
    Format B: {"1": "المادة 1 -...", "2": "..."}    — pre-segmented articles

    Args:
        json_path : Path to the JSON file
        law_index : Index of the law to load (0-based) — only used for Format A

    Returns:
        (LawSource1, warnings_list)
    """
    warnings = []

    # Encoding fallback chain:
    # utf-8-sig → handles UTF-8 with BOM (common in Windows-generated files)
    # utf-8     → standard UTF-8
    # cp1256    → Arabic Windows encoding (last resort)
    encoding_chain = ["utf-8-sig", "utf-8", "cp1256"]
    raw = None

    for encoding in encoding_chain:
        try:
            raw = json_path.read_text(encoding=encoding)
            if encoding != "utf-8":
                logger.info(f"'{json_path.name}' read successfully using '{encoding}'.")
                if encoding == "cp1256":
                    warnings.append("File was not UTF-8 encoded — read as cp1256.")
            break
        except UnicodeDecodeError:
            continue

    if raw is None:
        raise ValueError(
            f"Could not decode '{json_path.name}' — tried: {encoding_chain}. "
            f"Please re-save the file as UTF-8."
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{json_path.name}': {e}")

    # ── Auto-detect JSON format ────────────────
    fmt = detect_json_format(data)
    logger.info(f"Detected JSON format: {fmt} for '{json_path.name}'")

    # ── Format B: pre-segmented articles ──────
    if fmt == "B":
        # Format B is always a single dict — law_index not applicable
        law, fmt_warnings = _parse_format_b(data)
        warnings.extend(fmt_warnings)
        warnings.append("Format B detected: pre-segmented JSON (no metadata).")
        logger.info(f"Source1 parsed (Format B): {law}")
        return law, warnings

    # ── Format A: structured with metadata ────
    # JSON may be a list (multiple laws) or a dict (single law object)
    if isinstance(data, list):
        if len(data) == 0:
            raise ValueError(f"JSON file '{json_path.name}' contains an empty array.")

        total = len(data)

        if law_index < 0 or law_index >= total:
            raise ValueError(
                f"--law-index {law_index} is out of range. "
                f"'{json_path.name}' contains {total} law(s), "
                f"valid indices are 0 to {total - 1}. "
                f"Tip: run with --list to see all available laws."
            )

        if total > 1:
            warnings.append(
                f"JSON file contains {total} law objects — "
                f"loading index [{law_index}] as requested."
            )

        data = data[law_index]

    struct_warnings = _validate_json_structure(data)
    warnings.extend(struct_warnings)

    # Build articles list
    articles = []
    for raw_article in data.get("Articles", []):
        articles.append(Article(
            article_number   = str(raw_article.get("article_number", "")).strip(),
            title            = str(raw_article.get("title", "")).strip(),
            enforcement_date = str(raw_article.get("enforcement_date", "")).strip(),
            text             = str(raw_article.get("text", "")).strip(),
        ))

    law = LawSource1(
        leg_name       = str(data.get("Leg_Name", "")).strip(),
        leg_number     = normalize_number(str(data.get("Leg_Number", ""))),
        year           = normalize_number(str(data.get("Year", ""))),
        magazine_number= normalize_number(str(data.get("Magazine_Number", ""))),
        magazine_page  = normalize_number(str(data.get("Magazine_Page", ""))),
        magazine_date  = str(data.get("Magazine_Date", "")).strip(),
        articles       = articles,
    )

    logger.info(f"Source1 parsed (Format A): {law}")
    return law, warnings


def _parse_source2(txt_path: Path) -> tuple[LawSource2, list[str]]:
    """
    Parse a validated TXT file into a LawSource2 object.

    Returns:
        (LawSource2, warnings_list)
    """
    warnings = []

    encoding_chain = ["utf-8-sig", "utf-8", "cp1256"]
    raw_text = None

    for encoding in encoding_chain:
        try:
            raw_text = txt_path.read_text(encoding=encoding)
            if encoding != "utf-8":
                logger.info(f"'{txt_path.name}' read successfully using '{encoding}'.")
                if encoding == "cp1256":
                    warnings.append("File was not UTF-8 encoded — read as cp1256.")
            break
        except UnicodeDecodeError:
            continue

    if raw_text is None:
        raise ValueError(
            f"Could not decode '{txt_path.name}' — tried: {encoding_chain}. "
            f"Please re-save the file as UTF-8."
        )

    if not raw_text.strip():
        raise ValueError(f"TXT file '{txt_path.name}' is empty.")

    if len(raw_text.strip()) < 50:
        warnings.append(
            f"TXT file '{txt_path.name}' is very short ({len(raw_text)} chars) "
            f"— it may be incomplete."
        )

    law = LawSource2(
        raw_text  = raw_text,
        file_path = str(txt_path),
    )

    logger.info(f"Source2 parsed: {law}")
    return law, warnings


# ──────────────────────────────────────────────
# Cross-Validation
# ──────────────────────────────────────────────

def _cross_validate(source1: LawSource1, source2: LawSource2) -> tuple[bool, list[str]]:
    """
    Cross-check that both files appear to belong to the same law.

    Format A: compare Leg_Number + Year from JSON against TXT content.
    Format B: JSON has no metadata — attempt to extract from TXT and
              compare against what was parsed from article text.
              If nothing to compare, skip validation gracefully.

    Returns:
        (is_valid: bool, warnings: list[str])
    """
    warnings = []

    # If Format B had no metadata, skip cross-validation
    if not source1.leg_number and not source1.year:
        warnings.append(
            "Format B JSON has no metadata — cross-validation skipped. "
            "Make sure the JSON and TXT files belong to the same law."
        )
        logger.info("Cross-validation skipped (Format B — no metadata).")
        return False, warnings

    # Pattern: قانون رقم (43) لسنة 1976  (after numeral conversion)
    txt_normalized = convert_numerals(source2.raw_text)

    pattern = re.search(
        r'قانون\s+(?:معدل\s+)?(?:مؤقت\s+)?رقم\s*[(\[]?\s*(\d+)\s*[)\]]?\s+لسنة\s+(\d+)',
        txt_normalized
    )

    if not pattern:
        warnings.append(
            "Could not extract law number/year from TXT file for cross-validation. "
            "Proceeding without verification — make sure you paired the correct files."
        )
        return False, warnings

    txt_leg_number = pattern.group(1).strip()
    txt_year       = pattern.group(2).strip()

    number_match = (txt_leg_number == source1.leg_number)
    year_match   = (txt_year       == source1.year)

    if not number_match:
        warnings.append(
            f"Law number MISMATCH: JSON says '{source1.leg_number}', "
            f"TXT says '{txt_leg_number}'. Are you sure these files belong together?"
        )

    if not year_match:
        warnings.append(
            f"Year MISMATCH: JSON says '{source1.year}', "
            f"TXT says '{txt_year}'. Are you sure these files belong together?"
        )

    is_valid = number_match and year_match

    if is_valid:
        logger.info(
            f"Cross-validation passed: Law {source1.leg_number}/{source1.year}"
        )
    else:
        logger.warning("Cross-validation FAILED — possible wrong file pairing.")

    return is_valid, warnings


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def load_pair(json_path: str, txt_path: str, law_index: int = 0) -> PairedLaw:
    """
    Main entry point for ingestion.

    Args:
        json_path  : Path to Source 1 (.json) file
        txt_path   : Path to Source 2 (.txt) file
        law_index  : Which law to load from JSON (0-based, default=0)
                     Use list_laws_in_json() to preview available laws.

    Returns:
        PairedLaw object ready for the pipeline.

    Raises:
        ValueError        : Bad file type, empty file, invalid structure, bad index
        FileNotFoundError : File does not exist
    """
    all_warnings = []

    logger.info("=" * 50)
    logger.info("INGESTION STARTED")
    logger.info(f"  JSON       : {json_path}")
    logger.info(f"  TXT        : {txt_path}")
    logger.info(f"  Law index  : {law_index}")
    logger.info("=" * 50)

    # ── Step 1: Validate paths ─────────────────
    validated_json = _validate_path(json_path, ".json")
    validated_txt  = _validate_path(txt_path,  ".txt")

    # ── Step 2: Parse files ────────────────────
    source1, w1 = _parse_source1(validated_json, law_index=law_index)
    source2, w2 = _parse_source2(validated_txt)
    all_warnings.extend(w1)
    all_warnings.extend(w2)

    # ── Step 3: Cross-validate ─────────────────
    is_valid, w3 = _cross_validate(source1, source2)
    all_warnings.extend(w3)

    # ── Step 4: Build law_id ───────────────────
    law_id = f"law_{source1.leg_number}_{source1.year}"

    # ── Step 5: Log warnings ───────────────────
    if all_warnings:
        logger.warning(f"Ingestion completed with {len(all_warnings)} warning(s):")
        for w in all_warnings:
            logger.warning(f"  ⚠  {w}")
    else:
        logger.info("Ingestion completed with no warnings ✓")

    paired = PairedLaw(
        law_id           = law_id,
        source1          = source1,
        source2          = source2,
        cross_validated  = is_valid,
        warnings         = all_warnings,
    )

    logger.info(f"PairedLaw created: {paired}")
    return paired


# ──────────────────────────────────────────────
# JSON vs JSON Pair Loader
# ──────────────────────────────────────────────

def _format_b_to_extracted_law(source1_b: "LawSource1") -> "ExtractedLaw":
    """
    Convert a Format B LawSource1 (parsed from JSON) into an ExtractedLaw
    so it can flow into comparator.py exactly like a TXT-extracted source.

    Why this conversion is needed:
      comparator.py expects source 2 as ExtractedLaw (list of ExtractedArticle).
      Format B JSON articles are stored as LawSource1.articles (list of Article).
      By converting here, ALL downstream code (comparator, reporter, app)
      works identically regardless of whether source 2 came from TXT or JSON.

    The text_normalized field uses flatten_article_text() + normalize()
    so sub-clause markers are stripped before comparison — same treatment
    as TXT articles.
    """
    from src.extractor import ExtractedLaw, ExtractedArticle
    from src.normalizer import normalize, flatten_article_text

    extracted_articles = []
    for art in source1_b.articles:
        raw_text  = art.text or ""
        norm_text = normalize(flatten_article_text(raw_text), for_comparison=True)
        extracted_articles.append(ExtractedArticle(
            article_number  = art.article_number,
            text            = raw_text,       # raw — for display in reports
            text_normalized = norm_text,      # normalized — for comparison
        ))

    return ExtractedLaw(
        magazine_number = source1_b.magazine_number or "",
        law_number      = source1_b.leg_number      or "",
        year            = source1_b.year            or "",
        articles        = extracted_articles,
        warnings        = [],
    )


def load_json_pair(
    json1_path: str,
    json2_path: str,
    law1_index: int = 0,
) -> "PairedLaw":
    """
    Load and pair two JSON files for JSON-vs-JSON comparison.

    Source 1: Format A JSON  (structured, with metadata)
              e.g. qistas_ext.json — law 43/1976
    Source 2: Format B JSON  (pre-segmented, key=article_number, value=text)
              e.g. قانون_معدل_رقم_31_لسنة_2017_ocr.json

    The function:
      1. Validates both paths as .json files
      2. Auto-detects and parses each (Format A or B)
      3. Converts Source 2 into ExtractedLaw so comparator.py
         receives the same types as the TXT workflow
      4. Cross-validates law number + year if metadata is available
      5. Returns a PairedLaw ready for compare() + generate_report()

    Args:
        json1_path  : Path to Source 1 JSON (Format A — structured)
        json2_path  : Path to Source 2 JSON (Format B — pre-segmented)
        law1_index  : Which law to load from Source 1 (default 0)
                      Use list_laws_in_json() to see available laws.

    Returns:
        PairedLaw object — identical structure to load_pair() output.
    """
    all_warnings = []

    logger.info("=" * 50)
    logger.info("INGESTION STARTED (JSON vs JSON)")
    logger.info(f"  JSON 1 : {json1_path}")
    logger.info(f"  JSON 2 : {json2_path}")
    logger.info(f"  Index  : {law1_index}")
    logger.info("=" * 50)

    # ── Step 1: Validate both paths ──────────────
    validated_j1 = _validate_path(json1_path, ".json")
    validated_j2 = _validate_path(json2_path, ".json")

    # ── Step 2: Parse Source 1 (Format A expected) ─
    source1, w1 = _parse_source1(validated_j1, law_index=law1_index)
    all_warnings.extend(w1)

    logger.info(f"Source 1 parsed: {len(source1.articles)} articles")

    # ── Step 3: Parse Source 2 (Format B expected) ─
    source2_raw, w2 = _parse_source1(validated_j2, law_index=0)
    all_warnings.extend(w2)

    logger.info(f"Source 2 parsed: {len(source2_raw.articles)} articles")

    # ── Step 4: Convert Source 2 → ExtractedLaw ──
    # This makes comparator.py receive identical types
    # regardless of whether source 2 came from TXT or JSON
    extracted = _format_b_to_extracted_law(source2_raw)

    # ── Step 5: Cross-validate (best effort) ──────
    is_valid   = False
    cv_warnings = []

    s1_num  = source1.leg_number.strip()
    s1_year = source1.year.strip()
    s2_num  = source2_raw.leg_number.strip()
    s2_year = source2_raw.year.strip()

    if s1_num and s1_year and s2_num and s2_year:
        num_match  = (s1_num  == s2_num)
        year_match = (s1_year == s2_year)
        if num_match and year_match:
            is_valid = True
            logger.info(f"Cross-validation passed: {s1_num}/{s1_year}")
        else:
            if not num_match:
                cv_warnings.append(
                    f"Law number mismatch: Source1={s1_num}, Source2={s2_num}"
                )
            if not year_match:
                cv_warnings.append(
                    f"Year mismatch: Source1={s1_year}, Source2={s2_year}"
                )
            logger.warning("Cross-validation FAILED — possible wrong file pairing.")
    else:
        cv_warnings.append(
            "JSON-vs-JSON: one or both sources have no metadata — "
            "cross-validation skipped. Verify files belong to the same law."
        )

    all_warnings.extend(cv_warnings)

    # ── Step 6: Wrap in a LawSource2 for PairedLaw ─
    # PairedLaw.source2 expects LawSource2 (raw text holder)
    # We embed the ExtractedLaw in it via a sentinel path
    # so the pipeline can detect JSON-vs-JSON mode
    source2_wrapper = LawSource2(
        raw_text  = "__JSON_SOURCE__",   # sentinel — signals no TXT
        file_path = str(validated_j2),
    )

    # ── Step 7: Build law_id ──────────────────────
    law_id = f"law_{source1.leg_number}_{source1.year}"

    # ── Step 8: Log warnings ──────────────────────
    if all_warnings:
        logger.warning(f"Ingestion completed with {len(all_warnings)} warning(s):")
        for w in all_warnings:
            logger.warning(f"  ⚠  {w}")
    else:
        logger.info("Ingestion completed with no warnings ✓")

    paired = PairedLaw(
        law_id          = law_id,
        source1         = source1,
        source2         = source2_wrapper,
        cross_validated = is_valid,
        warnings        = all_warnings,
    )

    # Attach the ExtractedLaw directly so comparator can use it
    # without needing to run the TXT extractor
    paired._extracted = extracted

    logger.info(f"PairedLaw created (JSON-vs-JSON): {paired}")
    return paired


# ──────────────────────────────────────────────
# Quick Self-Test
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import argparse

    logging.basicConfig(
        level  = logging.INFO,
        format = "%(levelname)-8s %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Ingestion module — load and validate a JSON+TXT law pair."
    )
    parser.add_argument("--json",       type=str, help="Path to Source 1 (.json) file")
    parser.add_argument("--txt",        type=str, help="Path to Source 2 (.txt) file")
    parser.add_argument("--law-index",  type=int, default=0,
                        help="Index of law to load from JSON (default: 0)")
    parser.add_argument("--list",       type=str, metavar="JSON_FILE",
                        help="List all laws inside a JSON file and exit")

    args = parser.parse_args()

    print("=" * 60)
    print("INGESTION MODULE")
    print("=" * 60)

    # ── --list mode ────────────────────────────
    if args.list:
        list_laws_in_json(args.list)
        sys.exit(0)

    # ── --json + --txt mode ────────────────────
    if not args.json or not args.txt:
        print("Usage:")
        print("  List laws in JSON  : python -m src.ingestion --list <file.json>")
        print("  Load a pair        : python -m src.ingestion --json <file.json> --txt <file.txt> [--law-index N]")
        sys.exit(0)

    try:
        pair = load_pair(args.json, args.txt, law_index=args.law_index)
        print(f"\n✓ PairedLaw      : {pair}")
        print(f"  Law ID         : {pair.law_id}")
        print(f"  Cross-validated: {pair.cross_validated}")
        print(f"  Articles       : {len(pair.source1.articles)}")
        print(f"  Magazine №     : {pair.source1.magazine_number}")
        print(f"  Law name       : {pair.source1.leg_name}")
        print(f"  TXT chars      : {len(pair.source2.raw_text)}")
        if pair.warnings:
            print(f"\n  Warnings ({len(pair.warnings)}):")
            for w in pair.warnings:
                print(f"    ⚠  {w}")
        else:
            print("\n  No warnings ✓")
    except (ValueError, FileNotFoundError) as e:
        print(f"\n✗ ERROR: {e}")

    print("\n" + "=" * 60)