#!/usr/bin/env python3
"""
Merge Transcript Annotations and Create Train/Test Split.

Combines all reviewed annotation CSVs from data/transcript_gold_standard/
into a single canonical gold standard file, then assigns companies to
tuning (60%) or test (40%) splits.

Split design:
  - Company-level splits (NOT individual transcripts) to prevent data leakage
  - Tuning set (~60%): 6 companies — used for pipeline development
  - Test set (~40%): 4 companies — NEVER used for tuning; only for reporting
  - Test set must include sector diversity: ≥1 SaaS, ≥1 Consumer Tech, ≥1 non-SaaS

The split assignment is deterministic (same output every run) once companies
are assigned. The split.json file is the source of truth.

Output:
  data/transcript_gold_standard/transcript_gold_standard.csv  — full merged set
  data/transcript_gold_standard/split.json                    — tuning/test assignment

Usage:
    # Merge all reviewed files (auto-detect from data/transcript_gold_standard/)
    python3 scripts/merge_transcript_annotations.py

    # Specify reviewed files explicitly
    python3 scripts/merge_transcript_annotations.py \\
        data/transcript_gold_standard/CRM_2025-02-26_reviewed.csv \\
        data/transcript_gold_standard/META_2025-04-30_reviewed.csv

    # Force re-split (overwrites existing split.json)
    python3 scripts/merge_transcript_annotations.py --re-split

    # Preview split without writing
    python3 scripts/merge_transcript_annotations.py --dry-run
"""

import argparse
import csv
import json
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLD_STANDARD_DIR = ROOT / "data" / "transcript_gold_standard"
OUTPUT_CSV = GOLD_STANDARD_DIR / "transcript_gold_standard.csv"
SPLIT_JSON = GOLD_STANDARD_DIR / "split.json"

# Sector metadata for the 10 sampled companies
COMPANY_SECTORS: dict[str, str] = {
    "ADBE": "SaaS",
    "ADSK": "SaaS",
    "CRM": "SaaS",
    "EA": "Gaming",
    "GDDY": "SaaS",
    "INTU": "SaaS",
    "META": "Consumer Tech",
    "MSFT": "SaaS",
    "PYPL": "Fintech",
    "TMUS": "Telecom",
}

# Desired test set: 4 companies with sector diversity.
# Test set must include: ≥1 SaaS, ≥1 Consumer Tech, ≥1 non-SaaS.
# This assignment is fixed to ensure reproducibility.
# Chosen: META (Consumer Tech), TMUS (Telecom), PYPL (Fintech), GDDY (SaaS)
DEFAULT_TEST_COMPANIES = {"META", "TMUS", "PYPL", "GDDY"}

OUTPUT_FIELDNAMES = [
    "company",
    "ticker",
    "date",
    "metric_id",
    "value",
    "unit",
    "period",
    "source_type",
    "raw_text",
    "confidence",
    "section",
    "is_trap",
    "disposition",
    "disposition_reason",
]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_reviewed_files(paths: list[Path]) -> list[dict]:
    """Load all reviewed annotation rows, filtering to accepted/edited non-trap rows."""
    all_rows = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                all_rows.append(row)
    return all_rows


def filter_valid_annotations(rows: list[dict]) -> list[dict]:
    """
    Keep only annotations that should be in the gold standard:
      - disposition is ACCEPT or EDIT
      - is_trap is false
    """
    return [
        r
        for r in rows
        if r.get("disposition", "").upper() in ("ACCEPT", "EDIT")
        and r.get("is_trap", "false").lower() != "true"
    ]


# ---------------------------------------------------------------------------
# Split logic
# ---------------------------------------------------------------------------


def load_existing_split() -> dict | None:
    """Load split.json if it exists."""
    if not SPLIT_JSON.exists():
        return None
    try:
        return json.loads(SPLIT_JSON.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def assign_split(
    tickers: set[str],
    existing_split: dict | None,
    test_companies: set[str],
    force_resplit: bool,
) -> dict:
    """
    Assign each ticker to 'tuning' or 'test'.

    If an existing split exists and force_resplit is False, preserve it and
    only assign new companies to tuning.
    """
    if existing_split and not force_resplit:
        split = dict(existing_split.get("assignments", {}))
        # Add any new companies to tuning by default
        for ticker in sorted(tickers):
            if ticker not in split:
                split[ticker] = "test" if ticker in test_companies else "tuning"
        return split

    # Fresh assignment
    split = {}
    for ticker in sorted(tickers):
        split[ticker] = "test" if ticker in test_companies else "tuning"

    return split


def validate_split(split: dict, rows: list[dict]) -> list[str]:
    """Validate the split assignment meets diversity requirements."""
    warnings = []

    test_tickers = {t for t, s in split.items() if s == "test"}

    # Check sector diversity in test set
    saas_in_test = any(COMPANY_SECTORS.get(t, "") == "SaaS" for t in test_tickers)
    consumer_in_test = any(COMPANY_SECTORS.get(t, "") == "Consumer Tech" for t in test_tickers)
    non_saas_in_test = any(COMPANY_SECTORS.get(t, "") not in ("SaaS", "") for t in test_tickers)

    if not saas_in_test:
        warnings.append("Test set has no SaaS companies — sector diversity requirement not met")
    if not consumer_in_test:
        warnings.append("Test set has no Consumer Tech companies")
    if not non_saas_in_test:
        warnings.append("Test set has no non-SaaS companies")

    # Count annotations per split
    test_ann = sum(1 for r in rows if split.get(r.get("ticker", "")) == "test")
    tuning_ann = sum(1 for r in rows if split.get(r.get("ticker", "")) == "tuning")
    total = max(test_ann + tuning_ann, 1)

    test_pct = test_ann / total
    if test_pct < 0.25 or test_pct > 0.55:
        warnings.append(
            f"Test split is {test_pct:.0%} of annotations "
            f"(target: ~40%). Consider adjusting test_companies."
        )

    return warnings


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_gold_standard(rows: list[dict], split: dict, dry_run: bool) -> None:
    """Write merged gold standard CSV with split column added."""
    enriched = []
    for row in rows:
        r = dict(row)
        r["split"] = split.get(r.get("ticker", ""), "tuning")
        enriched.append(r)

    fieldnames = OUTPUT_FIELDNAMES + ["split"]

    if dry_run:
        print(f"\n  [DRY RUN] Would write {len(enriched)} rows to {OUTPUT_CSV}")
        return

    GOLD_STANDARD_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(enriched)

    print(f"  Wrote: {OUTPUT_CSV} ({len(enriched)} annotations)")


def write_split_json(
    split: dict,
    rows: list[dict],
    source_files: list[str],
    dry_run: bool,
) -> None:
    """Write split.json with company assignments and statistics."""
    # Compute per-ticker stats
    by_ticker: dict[str, dict] = defaultdict(lambda: {"transcripts": set(), "annotations": 0})
    for row in rows:
        ticker = row.get("ticker", "")
        date = row.get("date", "")
        by_ticker[ticker]["transcripts"].add(date)
        by_ticker[ticker]["annotations"] += 1

    companies = {}
    for ticker, assignment in sorted(split.items()):
        ticker_data = by_ticker.get(ticker, {})
        transcripts = sorted(ticker_data.get("transcripts", set()))
        companies[ticker] = {
            "split": assignment,
            "sector": COMPANY_SECTORS.get(ticker, "Unknown"),
            "transcripts": transcripts,
            "annotation_count": ticker_data.get("annotations", 0),
        }

    test_tickers = sorted(t for t, s in split.items() if s == "test")
    tuning_tickers = sorted(t for t, s in split.items() if s == "tuning")

    test_ann = sum(c["annotation_count"] for t, c in companies.items() if c["split"] == "test")
    tuning_ann = sum(c["annotation_count"] for t, c in companies.items() if c["split"] == "tuning")

    split_doc = {
        "version": "1.0",
        "description": (
            "Company-level train/test split for transcript gold standard. "
            "Test companies are held out entirely — never used for tuning. "
            "Only tuning companies are used during pipeline development."
        ),
        "tuning_companies": tuning_tickers,
        "test_companies": test_tickers,
        "companies": companies,
        "statistics": {
            "total_annotations": test_ann + tuning_ann,
            "tuning_annotations": tuning_ann,
            "test_annotations": test_ann,
            "test_pct": round(test_ann / max(test_ann + tuning_ann, 1), 3),
        },
        "source_files": source_files,
    }

    if dry_run:
        print("\n  [DRY RUN] Would write split.json:")
        print(f"    Tuning: {tuning_tickers}")
        print(f"    Test:   {test_tickers}")
        return

    GOLD_STANDARD_DIR.mkdir(parents=True, exist_ok=True)
    SPLIT_JSON.write_text(json.dumps(split_doc, indent=2))
    print(f"  Wrote: {SPLIT_JSON}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_summary(rows: list[dict], split: dict) -> None:
    """Print a human-readable summary of the merged gold standard."""
    by_ticker: dict[str, list] = defaultdict(list)
    for row in rows:
        by_ticker[row.get("ticker", "UNKNOWN")].append(row)

    print(f"\n{'='*65}")
    print("  MERGED GOLD STANDARD SUMMARY")
    print(f"{'='*65}")
    print(f"  Total annotations: {len(rows)}")
    print(f"  Companies: {len(by_ticker)}")
    print()
    print(f"  {'Ticker':<8} {'Split':<10} {'Sector':<16} {'Ann':>4} {'Trans':>6}")
    print(f"  {'─'*50}")

    for ticker in sorted(by_ticker.keys()):
        ticker_rows = by_ticker[ticker]
        transcripts = {r.get("date", "") for r in ticker_rows}
        assignment = split.get(ticker, "tuning")
        sector = COMPANY_SECTORS.get(ticker, "?")
        print(
            f"  {ticker:<8} {assignment:<10} {sector:<16} {len(ticker_rows):>4} {len(transcripts):>6}"
        )

    # Totals by split
    test_tickers = {t for t, s in split.items() if s == "test"}
    tuning_tickers = {t for t, s in split.items() if s == "tuning"}
    test_ann = sum(len(v) for t, v in by_ticker.items() if t in test_tickers)
    tuning_ann = sum(len(v) for t, v in by_ticker.items() if t in tuning_tickers)

    print(f"\n  {'─'*50}")
    print(f"  {'TUNING':<8} {len(tuning_tickers)} companies, {tuning_ann} annotations")
    print(f"  {'TEST':<8} {len(test_tickers)} companies, {test_ann} annotations")

    # Metric distribution
    metric_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        metric_counts[row.get("metric_id", "")] += 1

    print("\n  Top 10 metrics by frequency:")
    for metric, count in sorted(metric_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {metric:<40} {count:>4}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Merge reviewed annotation CSVs into the transcript gold standard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              %(prog)s
              %(prog)s data/transcript_gold_standard/CRM_2025-02-26_reviewed.csv
              %(prog)s --re-split --dry-run
        """
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Reviewed CSV files to merge (default: all *_reviewed.csv in gold standard dir)",
    )
    parser.add_argument(
        "--re-split",
        action="store_true",
        help="Recompute the train/test split (overwrites split.json)",
    )
    parser.add_argument(
        "--test-companies",
        nargs="+",
        default=None,
        metavar="TICKER",
        help="Override test company set (default: META TMUS PYPL GDDY)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing files",
    )
    args = parser.parse_args()

    # Find input files
    if args.inputs:
        input_files = [Path(p) for p in args.inputs]
    else:
        input_files = sorted(GOLD_STANDARD_DIR.glob("*_reviewed.csv"))

    if not input_files:
        print(f"No reviewed CSV files found in {GOLD_STANDARD_DIR}", file=sys.stderr)
        print("Run review_transcript_annotations.py first.", file=sys.stderr)
        sys.exit(1)

    missing = [str(f) for f in input_files if not f.exists()]
    if missing:
        print(f"ERROR: Files not found: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {len(input_files)} reviewed files...")
    all_rows = load_reviewed_files(input_files)
    valid_rows = filter_valid_annotations(all_rows)

    print(f"  Total rows: {len(all_rows)}")
    print(f"  Valid (ACCEPT/EDIT, non-trap): {len(valid_rows)}")
    print(f"  Filtered out: {len(all_rows) - len(valid_rows)}")

    if not valid_rows:
        print("ERROR: No valid annotations found.", file=sys.stderr)
        sys.exit(1)

    # Determine split
    test_companies = (
        set(t.upper() for t in args.test_companies)
        if args.test_companies
        else DEFAULT_TEST_COMPANIES
    )
    tickers = {r.get("ticker", "") for r in valid_rows if r.get("ticker", "")}
    existing_split = load_existing_split()

    if existing_split and not args.re_split:
        print(f"  Using existing split from {SPLIT_JSON}")
    else:
        print(f"  Computing {'new' if args.re_split else 'initial'} split...")

    split = assign_split(tickers, existing_split, test_companies, force_resplit=args.re_split)

    # Validate split
    warnings = validate_split(split, valid_rows)
    if warnings:
        print("\n  Split warnings:")
        for w in warnings:
            print(f"    WARNING: {w}")

    # Print summary
    print_summary(valid_rows, split)

    # Write outputs
    print()
    source_files = [f.name for f in input_files]
    write_gold_standard(valid_rows, split, dry_run=args.dry_run)
    write_split_json(split, valid_rows, source_files, dry_run=args.dry_run)

    print(f"\n  Done. Gold standard ready at: {GOLD_STANDARD_DIR}")


if __name__ == "__main__":
    main()
