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

    Args:
        json_path : Path to the JSON file
        law_index : Index of the law to load (0-based) when JSON has multiple laws

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

    logger.info(f"Source1 parsed: {law}")
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

    Strategy:
      - Extract law number and year from Source 2 raw text
        using Arabic pattern: قانون رقم (٤٣) لسنة ١٩٧٦
      - Compare with Source 1 Leg_Number and Year

    Returns:
        (is_valid: bool, warnings: list[str])
    """
    warnings = []

    # Pattern: قانون رقم (43) لسنة 1976  (after numeral conversion)
    txt_normalized = convert_numerals(source2.raw_text)

    pattern = re.search(
        r'قانون\s+(?:مؤقت\s+)?رقم\s*[(\[]?\s*(\d+)\s*[)\]]?\s+لسنة\s+(\d+)',
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