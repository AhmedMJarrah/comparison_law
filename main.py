"""
main.py
-------
Unified entrypoint for the Law Comparison Pipeline.

Usage:
    # Compare a law pair
    python main.py --json data/source1/law.json --txt data/source2/law.txt

    # Specify which law to load from a multi-law JSON
    python main.py --json data/source1/laws.json --txt data/source2/law.txt --law-index 2

    # List all laws inside a JSON file
    python main.py --list data/source1/laws.json

    # Run in quiet mode (no INFO logs, just final summary)
    python main.py --json ... --txt ... --quiet
"""

import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime

from src.config import config, ensure_dirs
from src.ingestion import load_pair, list_laws_in_json
from src.extractor import extract
from src.comparator import compare, MatchStatus
from src.reporter import generate_report


# ──────────────────────────────────────────────
# Logger Setup
# ──────────────────────────────────────────────

def setup_logging(quiet: bool = False) -> None:
    """
    Configure logging to console and optionally to file.
    quiet=True → only WARNING+ shown on console.
    """
    ensure_dirs()

    level   = logging.WARNING if quiet else getattr(logging, config.LOG_LEVEL, logging.INFO)
    handlers = []

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
    handlers.append(console)

    # File handler (always full INFO regardless of quiet mode)
    if config.LOG_TO_FILE:
        log_file = config.LOGS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
        )
        handlers.append(file_handler)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)


# ──────────────────────────────────────────────
# CLI Banner
# ──────────────────────────────────────────────

def print_banner() -> None:
    SEP = "=" * 60
    print()
    print(SEP)
    print(f"  Law Comparison Pipeline  v{config.VERSION}")
    print(f"  Environment : {config.ENV}")
    print(f"  Thresholds  : match={config.SIMILARITY_THRESHOLD}%  fuzzy={config.FUZZY_MATCH_THRESHOLD}%")
    print(SEP)
    print()


def print_summary(report, paths: dict) -> None:
    SEP  = "=" * 60
    SEP2 = "-" * 60

    verdict_colors = {
        "ممتاز":          "\033[92m",   # green
        "جيد":            "\033[94m",   # blue
        "مقبول":          "\033[93m",   # yellow
        "يحتاج مراجعة":  "\033[91m",   # red
    }
    RESET = "\033[0m"
    color = verdict_colors.get(report.overall_verdict, "")

    print()
    print(SEP)
    print("  PIPELINE COMPLETE ✓")
    print(SEP)
    print(f"  Law             : {report.law_name}")
    print(f"  Law number      : {report.law_number}/{report.year}")
    print(f"  Magazine №      : {report.metadata.json_magazine} "
          f"{'✅' if report.metadata.match else '❌'}")
    print(SEP2)
    print(f"  Total JSON      : {report.total_json:>6} articles")
    print(f"  Total TXT       : {report.total_txt:>6} articles")
    print(f"  Coverage        : {report.coverage_pct:>6.1f}%")
    print(f"  Match rate      : {report.match_pct:>6.1f}%")
    print(f"  Verdict         : {color}{report.overall_verdict}{RESET}")
    print(SEP2)
    print(f"  ✅  Match        : {report.count_match:>6}")
    print(f"  ⚠️   Near match   : {report.count_near_match:>6}")
    print(f"  ❌  Mismatch     : {report.count_mismatch:>6}")
    print(f"  🔍  Missing      : {report.count_missing:>6}")
    print(f"  ➕  Extra        : {report.count_extra:>6}")
    print(SEP2)
    print(f"  HTML report     : {paths['html']}")
    print(f"  Excel summary   : {paths['excel']}")
    print(SEP)
    print()


# ──────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────

def run_pipeline(json_path: str, txt_path: str, law_index: int) -> int:
    """
    Execute the full comparison pipeline:
      1. Ingest  → validate & parse both files
      2. Extract → parse TXT into structured articles
      3. Compare → score every article pair
      4. Report  → generate HTML + Excel outputs

    Returns exit code: 0 = success, 1 = error
    """
    logger = logging.getLogger(__name__)

    try:
        # ── Step 1: Ingest ─────────────────────
        print("  [1/4] Loading and validating files...")
        pair = load_pair(json_path, txt_path, law_index=law_index)

        if pair.warnings:
            for w in pair.warnings:
                print(f"        ⚠  {w}")

        print(f"        ✓ JSON: {len(pair.source1.articles)} articles loaded")
        print(f"        ✓ TXT : {len(pair.source2.raw_text):,} characters loaded")
        print(f"        ✓ Cross-validated: {pair.cross_validated}")

        # ── Step 2: Extract ────────────────────
        print("  [2/4] Extracting articles from TXT...")

        raw_txt = None
        for enc in ["utf-8-sig", "utf-8", "cp1256"]:
            try:
                raw_txt = Path(txt_path).read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue

        if raw_txt is None:
            raise ValueError(f"Cannot decode TXT file: {txt_path}")

        extracted = extract(raw_txt)
        print(f"        ✓ Extracted: {len(extracted.articles)} articles")
        print(f"        ✓ Magazine №: {extracted.magazine_number}")

        # ── Step 3: Compare ────────────────────
        print("  [3/4] Comparing articles (this may take a moment)...")
        report = compare(pair.source1, extracted, pair.law_id)

        print(f"        ✓ Coverage  : {report.coverage_pct:.1f}%")
        print(f"        ✓ Match rate: {report.match_pct:.1f}%")
        print(f"        ✓ Verdict   : {report.overall_verdict}")

        # ── Step 4: Report ─────────────────────
        print("  [4/4] Generating reports...")
        paths = generate_report(report)
        print(f"        ✓ HTML  → {paths['html'].name}")
        print(f"        ✓ Excel → {paths['excel'].name}")

        # ── Final summary ──────────────────────
        print_summary(report, paths)
        return 0

    except FileNotFoundError as e:
        print(f"\n  ✗ FILE ERROR: {e}\n")
        logger.error(e)
        return 1

    except ValueError as e:
        print(f"\n  ✗ VALIDATION ERROR: {e}\n")
        logger.error(e)
        return 1

    except Exception as e:
        print(f"\n  ✗ UNEXPECTED ERROR: {e}\n")
        logger.exception(e)
        return 1


# ──────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "main.py",
        description = "Law Comparison Pipeline — compare JSON and TXT law sources.",
        formatter_class = argparse.RawTextHelpFormatter,
        epilog = """
Examples:
  python main.py --json data/source1/law.json --txt data/source2/law.txt
  python main.py --json data/source1/laws.json --txt data/source2/law.txt --law-index 2
  python main.py --list data/source1/laws.json
  python main.py --json ... --txt ... --quiet
        """
    )

    parser.add_argument(
        "--json",
        type    = str,
        help    = "Path to Source 1 (.json) file"
    )
    parser.add_argument(
        "--txt",
        type    = str,
        help    = "Path to Source 2 (.txt) file"
    )
    parser.add_argument(
        "--law-index",
        type    = int,
        default = 0,
        help    = "Index of law to load from JSON (default: 0). Use --list to preview."
    )
    parser.add_argument(
        "--list",
        type    = str,
        metavar = "JSON_FILE",
        help    = "List all laws in a JSON file and exit"
    )
    parser.add_argument(
        "--quiet",
        action  = "store_true",
        help    = "Suppress INFO logs — only show progress and final summary"
    )
    parser.add_argument(
        "--version",
        action  = "version",
        version = f"Law Comparison Pipeline v{config.VERSION}"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    # ── --list mode ────────────────────────────
    if args.list:
        setup_logging(quiet=True)
        list_laws_in_json(args.list)
        return 0

    # ── Validate required args ─────────────────
    if not args.json or not args.txt:
        print()
        print("  ✗ ERROR: Both --json and --txt are required.\n")
        parser.print_help()
        return 1

    # ── Run pipeline ───────────────────────────
    setup_logging(quiet=args.quiet)
    print_banner()
    return run_pipeline(args.json, args.txt, args.law_index)


if __name__ == "__main__":
    sys.exit(main())