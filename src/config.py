"""
config.py
---------
Central configuration loader.
Reads all settings from .env file.
Every module imports from here — never hardcode values directly.

Usage:
    from src.config import config
    print(config.SIMILARITY_THRESHOLD)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env file ─────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent   # project root
load_dotenv(BASE_DIR / ".env")


# ──────────────────────────────────────────────
# Configuration Class
# ──────────────────────────────────────────────

class Config:

    # ── Project ────────────────────────────────
    PROJECT_NAME: str   = os.getenv("PROJECT_NAME", "comparison_law")
    VERSION: str        = os.getenv("VERSION", "1.0.0")
    ENV: str            = os.getenv("ENV", "development")

    # ── Paths ──────────────────────────────────
    BASE_DIR: Path      = BASE_DIR
    SOURCE1_DIR: Path   = BASE_DIR / os.getenv("SOURCE1_DIR", "data/source1")
    SOURCE2_DIR: Path   = BASE_DIR / os.getenv("SOURCE2_DIR", "data/source2")
    OUTPUT_DIR: Path    = BASE_DIR / os.getenv("OUTPUT_DIR", "output")
    REPORTS_DIR: Path   = BASE_DIR / os.getenv("REPORTS_DIR", "output/reports")
    SUMMARIES_DIR: Path = BASE_DIR / os.getenv("SUMMARIES_DIR", "output/summaries")
    LOGS_DIR: Path      = BASE_DIR / os.getenv("LOGS_DIR", "logs")

    # ── Comparison Settings ────────────────────
    SIMILARITY_THRESHOLD: float  = float(os.getenv("SIMILARITY_THRESHOLD", 95))
    FUZZY_MATCH_THRESHOLD: float = float(os.getenv("FUZZY_MATCH_THRESHOLD", 80))

    # ── Normalization Settings ─────────────────
    NORMALIZE_TAA_MARBUTA: bool = os.getenv("NORMALIZE_TAA_MARBUTA", "true").lower() == "true"
    NORMALIZE_YAA: bool         = os.getenv("NORMALIZE_YAA",          "true").lower() == "true"
    NORMALIZE_ALEF: bool        = os.getenv("NORMALIZE_ALEF",         "true").lower() == "true"
    REMOVE_DIACRITICS: bool     = os.getenv("REMOVE_DIACRITICS",      "true").lower() == "true"
    REMOVE_TATWEEL: bool        = os.getenv("REMOVE_TATWEEL",         "true").lower() == "true"

    # ── Report Settings ────────────────────────
    REPORT_LANGUAGE: str        = os.getenv("REPORT_LANGUAGE", "ar")
    REPORT_SHOW_DIFFS: bool     = os.getenv("REPORT_SHOW_DIFFS", "true").lower() == "true"
    REPORT_COMPANY_NAME: str    = os.getenv("REPORT_COMPANY_NAME", "")
    REPORT_LOGO_PATH: str       = os.getenv("REPORT_LOGO_PATH", "")

    # ── Logging ────────────────────────────────
    LOG_LEVEL: str      = os.getenv("LOG_LEVEL", "INFO")
    LOG_TO_FILE: bool   = os.getenv("LOG_TO_FILE", "true").lower() == "true"

    def __repr__(self) -> str:
        return (
            f"<Config ENV={self.ENV} "
            f"SIMILARITY_THRESHOLD={self.SIMILARITY_THRESHOLD} "
            f"LOG_LEVEL={self.LOG_LEVEL}>"
        )


# ── Singleton instance ─────────────────────────
config = Config()


# ── Ensure output directories exist ───────────
def ensure_dirs():
    """Create all output/log directories if they don't exist."""
    dirs = [
        config.SOURCE1_DIR,
        config.SOURCE2_DIR,
        config.OUTPUT_DIR,
        config.REPORTS_DIR,
        config.SUMMARIES_DIR,
        config.LOGS_DIR,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


# ── Quick self-test ────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("CONFIG LOADER SELF-TEST")
    print("=" * 50)
    print(f"  Project      : {config.PROJECT_NAME} v{config.VERSION}")
    print(f"  Environment  : {config.ENV}")
    print(f"  Base dir     : {config.BASE_DIR}")
    print(f"  Source1 dir  : {config.SOURCE1_DIR}")
    print(f"  Source2 dir  : {config.SOURCE2_DIR}")
    print(f"  Reports dir  : {config.REPORTS_DIR}")
    print(f"  Threshold    : {config.SIMILARITY_THRESHOLD}%")
    print(f"  Log level    : {config.LOG_LEVEL}")
    print("=" * 50)
    print("✓ Config loaded successfully")