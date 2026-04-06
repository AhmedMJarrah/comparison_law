"""
comparator.py
-------------
Compares Source 1 (JSON) against Source 2 (TXT extracted) at three levels:

  Level 1 — Metadata     : Magazine number match
  Level 2 — Coverage     : Which articles exist in both / missing / extra
  Level 3 — Content      : Article text similarity using rapidfuzz

Output: ComparisonReport object consumed by reporter.py

Similarity scoring:
  >= SIMILARITY_THRESHOLD (default 95%)  → MATCH       ✅
  >= FUZZY_MATCH_THRESHOLD (default 80%) → NEAR MATCH  ⚠️
  <  FUZZY_MATCH_THRESHOLD               → MISMATCH    ❌
  Article missing from TXT               → MISSING     🔍
  Article extra in TXT                   → EXTRA       ➕
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz

from src.config import config
from src.normalizer import normalize, normalize_number, flatten_article_text
from src.ingestion import LawSource1, Article
from src.extractor import ExtractedLaw, ExtractedArticle, build_article_index

# ── Logger ─────────────────────────────────────
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Enums & Constants
# ──────────────────────────────────────────────

class MatchStatus(str, Enum):
    MATCH      = "MATCH"        # >= SIMILARITY_THRESHOLD
    NEAR_MATCH = "NEAR_MATCH"   # >= FUZZY_MATCH_THRESHOLD
    MISMATCH   = "MISMATCH"     # < FUZZY_MATCH_THRESHOLD
    MISSING    = "MISSING"      # in JSON, not in TXT
    EXTRA      = "EXTRA"        # in TXT, not in JSON


STATUS_EMOJI = {
    MatchStatus.MATCH:      "✅",
    MatchStatus.NEAR_MATCH: "⚠️",
    MatchStatus.MISMATCH:   "❌",
    MatchStatus.MISSING:    "🔍",
    MatchStatus.EXTRA:      "➕",
}

STATUS_LABEL = {
    MatchStatus.MATCH:      "تطابق",
    MatchStatus.NEAR_MATCH: "تطابق جزئي",
    MatchStatus.MISMATCH:   "تعارض",
    MatchStatus.MISSING:    "غائب عن المصدر الثاني",
    MatchStatus.EXTRA:      "زائد في المصدر الثاني",
}


# ──────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────

@dataclass
class MetadataResult:
    """Result of magazine number comparison."""
    json_magazine:  str
    txt_magazine:   str
    match:          bool

    @property
    def status(self) -> MatchStatus:
        return MatchStatus.MATCH if self.match else MatchStatus.MISMATCH


@dataclass
class ArticleResult:
    """
    Comparison result for a single article.
    Contains both raw texts for display and score for logic.
    """
    article_number:   str
    status:           MatchStatus
    similarity_score: float             # 0.0 - 100.0

    # Source 1 (JSON) content
    json_text:        str = ""

    # Source 2 (TXT) content
    txt_text:         str = ""

    # Normalized versions (used for scoring, shown in debug)
    json_normalized:  str = ""
    txt_normalized:   str = ""

    # Character-level diff hints (populated for MISMATCH / NEAR_MATCH)
    diff_hint:        str = ""

    def __repr__(self):
        return (
            f"<ArticleResult #{self.article_number} "
            f"{self.status.value} "
            f"score={self.similarity_score:.1f}%>"
        )


@dataclass
class ComparisonReport:
    """
    Full comparison report for one law pair.
    Fed directly into reporter.py.
    """
    law_id:           str
    law_name:         str
    law_number:       str
    year:             str

    metadata:         MetadataResult
    articles:         list[ArticleResult] = field(default_factory=list)

    # Summary counts (computed after comparison)
    total_json:       int = 0
    total_txt:        int = 0
    count_match:      int = 0
    count_near_match: int = 0
    count_mismatch:   int = 0
    count_missing:    int = 0
    count_extra:      int = 0

    @property
    def coverage_pct(self) -> float:
        """% of JSON articles found in TXT."""
        if self.total_json == 0:
            return 0.0
        return ((self.total_json - self.count_missing) / self.total_json) * 100

    @property
    def match_pct(self) -> float:
        """% of matched articles that are exact/near matches."""
        compared = self.count_match + self.count_near_match + self.count_mismatch
        if compared == 0:
            return 0.0
        return ((self.count_match + self.count_near_match) / compared) * 100

    @property
    def overall_verdict(self) -> str:
        if self.match_pct >= 95 and self.coverage_pct >= 95:
            return "ممتاز"           # Excellent
        elif self.match_pct >= 85 and self.coverage_pct >= 85:
            return "جيد"             # Good
        elif self.match_pct >= 70:
            return "مقبول"           # Acceptable
        else:
            return "يحتاج مراجعة"   # Needs review

    def __repr__(self):
        return (
            f"<ComparisonReport {self.law_id} "
            f"coverage={self.coverage_pct:.1f}% "
            f"match={self.match_pct:.1f}%>"
        )


# ──────────────────────────────────────────────
# Diff Helper
# ──────────────────────────────────────────────

def _build_diff_hint(text1: str, text2: str, max_len: int = 200) -> str:
    """
    Build a human-readable diff hint showing where two texts diverge.
    Finds the first position where they differ and shows context.
    """
    if not text1 or not text2:
        return ""

    # Truncate for performance
    t1 = text1[:500]
    t2 = text2[:500]

    # Find first differing character
    min_len = min(len(t1), len(t2))
    first_diff = min_len  # default: texts match up to min_len

    for i in range(min_len):
        if t1[i] != t2[i]:
            first_diff = i
            break

    if first_diff == min_len and len(t1) == len(t2):
        return ""   # identical

    # Show context around first difference
    context_start = max(0, first_diff - 20)
    context_end   = min(min_len, first_diff + 40)

    snippet1 = t1[context_start:context_end].replace("\n", " ")
    snippet2 = t2[context_start:context_end].replace("\n", " ")

    return f'JSON: "...{snippet1}..." | TXT: "...{snippet2}..."'


# ──────────────────────────────────────────────
# Comparison Engine
# ──────────────────────────────────────────────

def _compare_metadata(source1: LawSource1, extracted: ExtractedLaw) -> MetadataResult:
    """Compare magazine numbers from both sources."""
    json_mag = normalize_number(source1.magazine_number)
    txt_mag  = normalize_number(extracted.magazine_number)
    match    = (json_mag == txt_mag) and bool(json_mag)

    if match:
        logger.info(f"Magazine number match: {json_mag} ✅")
    else:
        logger.warning(
            f"Magazine number MISMATCH: JSON={json_mag} TXT={txt_mag} ❌"
        )

    return MetadataResult(
        json_magazine = json_mag,
        txt_magazine  = txt_mag,
        match         = match,
    )


def _score_articles(
    json_article: Article,
    txt_article:  ExtractedArticle,
) -> ArticleResult:
    """
    Compare a single article pair and return a scored ArticleResult.

    Uses rapidfuzz token_sort_ratio for word-order-tolerant matching
    combined with partial_ratio for substring matching (handles truncated OCR).
    Final score = weighted average of both.
    """
    # Normalize both texts for comparison
    # flatten_article_text strips sub-clause markers (1. 2. / أولاً: / أ- ب-)
    # and OCR noise (page breaks, page numbers) from BOTH sources
    # so scoring reflects actual content differences not formatting differences
    json_norm = normalize(flatten_article_text(json_article.text), for_comparison=True)
    txt_norm  = normalize(flatten_article_text(txt_article.text_normalized), for_comparison=True)

    # Score 1: token sort ratio (order-independent word matching)
    score_token = fuzz.token_sort_ratio(json_norm, txt_norm)

    # Score 2: partial ratio (handles one text being substring of other)
    score_partial = fuzz.partial_ratio(json_norm, txt_norm)

    # Weighted final score: favor token_sort but consider partial
    final_score = (score_token * 0.7) + (score_partial * 0.3)

    # Determine status
    if final_score >= config.SIMILARITY_THRESHOLD:
        status = MatchStatus.MATCH
    elif final_score >= config.FUZZY_MATCH_THRESHOLD:
        status = MatchStatus.NEAR_MATCH
    else:
        status = MatchStatus.MISMATCH

    # Build diff hint only for non-matches (saves computation)
    diff_hint = ""
    if status in (MatchStatus.NEAR_MATCH, MatchStatus.MISMATCH):
        diff_hint = _build_diff_hint(json_norm, txt_norm)

    return ArticleResult(
        article_number   = json_article.article_number,
        status           = status,
        similarity_score = round(final_score, 2),
        json_text        = json_article.text,
        txt_text         = txt_article.text,
        json_normalized  = json_norm,
        txt_normalized   = txt_norm,
        diff_hint        = diff_hint,
    )


def compare(
    source1:   LawSource1,
    extracted: ExtractedLaw,
    law_id:    str,
) -> ComparisonReport:
    """
    Main comparison engine.

    Args:
        source1   : Parsed JSON law (from ingestion)
        extracted : Extracted TXT law (from extractor)
        law_id    : Identifier string (e.g. "law_43_1976")

    Returns:
        ComparisonReport ready for reporter.py
    """
    logger.info("=" * 50)
    logger.info("COMPARISON STARTED")
    logger.info(f"  Law ID  : {law_id}")
    logger.info(f"  JSON    : {len(source1.articles)} articles")
    logger.info(f"  TXT     : {len(extracted.articles)} articles")
    logger.info("=" * 50)

    # ── Level 1: Metadata ──────────────────────
    metadata = _compare_metadata(source1, extracted)

    # ── Build lookup index for TXT articles ────
    txt_index = build_article_index(extracted)

    json_numbers = {a.article_number for a in source1.articles}
    txt_numbers  = set(txt_index.keys())

    missing_numbers = json_numbers - txt_numbers   # in JSON, not TXT
    extra_numbers   = txt_numbers  - json_numbers  # in TXT, not JSON

    logger.info(
        f"Coverage: {len(json_numbers - missing_numbers)}/{len(json_numbers)} "
        f"articles found in TXT "
        f"({len(missing_numbers)} missing, {len(extra_numbers)} extra)"
    )

    # ── Level 2 & 3: Article comparison ────────
    article_results: list[ArticleResult] = []

    for json_article in source1.articles:
        num = json_article.article_number

        if num in missing_numbers:
            # Article exists in JSON but not in TXT
            article_results.append(ArticleResult(
                article_number   = num,
                status           = MatchStatus.MISSING,
                similarity_score = 0.0,
                json_text        = json_article.text,
                txt_text         = "",
            ))

        else:
            # Article exists in both — score it
            txt_article = txt_index[num]
            result      = _score_articles(json_article, txt_article)
            article_results.append(result)

    # ── Add extra TXT articles ─────────────────
    for num in sorted(extra_numbers, key=lambda x: int(x) if x.isdigit() else 0):
        txt_article = txt_index[num]
        article_results.append(ArticleResult(
            article_number   = num,
            status           = MatchStatus.EXTRA,
            similarity_score = 0.0,
            json_text        = "",
            txt_text         = txt_article.text,
        ))

    # ── Compute summary counts ─────────────────
    counts = {s: 0 for s in MatchStatus}
    for r in article_results:
        counts[r.status] += 1

    report = ComparisonReport(
        law_id           = law_id,
        law_name         = source1.leg_name,
        law_number       = source1.leg_number,
        year             = source1.year,
        metadata         = metadata,
        articles         = article_results,
        total_json       = len(source1.articles),
        total_txt        = len(extracted.articles),
        count_match      = counts[MatchStatus.MATCH],
        count_near_match = counts[MatchStatus.NEAR_MATCH],
        count_mismatch   = counts[MatchStatus.MISMATCH],
        count_missing    = counts[MatchStatus.MISSING],
        count_extra      = counts[MatchStatus.EXTRA],
    )

    logger.info(f"Comparison complete: {report}")
    logger.info(f"  ✅ Match      : {report.count_match}")
    logger.info(f"  ⚠️  Near match : {report.count_near_match}")
    logger.info(f"  ❌ Mismatch   : {report.count_mismatch}")
    logger.info(f"  🔍 Missing    : {report.count_missing}")
    logger.info(f"  ➕ Extra      : {report.count_extra}")
    logger.info(f"  Coverage     : {report.coverage_pct:.1f}%")
    logger.info(f"  Match rate   : {report.match_pct:.1f}%")
    logger.info(f"  Verdict      : {report.overall_verdict}")

    return report


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
        description="Comparator module — compare JSON and TXT law pair."
    )
    parser.add_argument("--json",      type=str, required=True)
    parser.add_argument("--txt",       type=str, required=True)
    parser.add_argument("--law-index", type=int, default=0)
    parser.add_argument("--sample",    type=int, default=5,
                        help="Number of sample results to display per status")
    args = parser.parse_args()

    from src.ingestion import load_pair
    from src.extractor import extract
    from pathlib import Path

    # Load
    pair = load_pair(args.json, args.txt, law_index=args.law_index)

    # Extract
    for enc in ["utf-8-sig", "utf-8", "cp1256"]:
        try:
            raw = Path(args.txt).read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue

    extracted = extract(raw)

    # Compare
    report = compare(pair.source1, extracted, pair.law_id)

    SEP = "=" * 65

    print()
    print(SEP)
    print("  COMPARISON REPORT SUMMARY")
    print(SEP)
    print(f"  Law             : {report.law_name}")
    print(f"  Law number      : {report.law_number}/{report.year}")
    print(f"  Magazine №      : JSON={report.metadata.json_magazine} "
          f"TXT={report.metadata.txt_magazine} "
          f"{'✅' if report.metadata.match else '❌'}")
    print()
    print(f"  Total JSON      : {report.total_json}")
    print(f"  Total TXT       : {report.total_txt}")
    print(f"  Coverage        : {report.coverage_pct:.1f}%")
    print(f"  Match rate      : {report.match_pct:.1f}%")
    print(f"  Verdict         : {report.overall_verdict}")
    print()
    print(f"  ✅ Match         : {report.count_match}")
    print(f"  ⚠️  Near match    : {report.count_near_match}")
    print(f"  ❌ Mismatch      : {report.count_mismatch}")
    print(f"  🔍 Missing       : {report.count_missing}")
    print(f"  ➕ Extra         : {report.count_extra}")
    print(SEP)

    # Sample results per status
    for status in MatchStatus:
        samples = [r for r in report.articles if r.status == status][:args.sample]
        if not samples:
            continue
        print(f"\n  --- Sample {status.value} articles ---")
        for r in samples:
            print(f"  Article {r.article_number:>6} | "
                  f"Score: {r.similarity_score:>6.1f}% | "
                  f"{STATUS_EMOJI[r.status]} {status.value}")
            if r.diff_hint:
                print(f"             Diff : {r.diff_hint[:100]}")

    print()
    print(SEP)