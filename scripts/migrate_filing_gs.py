#!/usr/bin/env python3
"""
Phase 1 data migration: split presentation_gold_standard/ index files into
presentation-only (8-K) and filing-only (S-1/F-1/10-K) variants.

Companion CSV/JSON files were already moved via `git mv` before this script runs.
This script only handles the shared index files:
  - _file_index.json
  - _url_index.json
  - _image_decisions.json
  - presentation_gold_standard.csv
  - split.json

Usage:
    python3 scripts/migrate_filing_gs.py --dry-run   # inspect without writing
    python3 scripts/migrate_filing_gs.py             # apply changes
"""

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PRES_DIR = REPO_ROOT / "data" / "presentation_gold_standard"
FILING_DIR = REPO_ROOT / "data" / "filing_gold_standard"

# The 18 non-8-K keys being migrated to filing_gold_standard
NON_8K_KEYS: set[str] = {
    "ABNB_S-1_2020-12-07",
    "BRZE_S-1_2021-11-08",
    "CART_S-1_2023-09-15",
    "CHWY_S-1_2019-06-12",
    "CURV_S-1_2021-06-30",
    "DASH_S-1_2020-12-07",
    "DDOG_S-1_2019-09-17",
    "DUOL_S-1_2021-07-26",
    "FLYW_10-K_2026-02-24",
    "GTLB_S-1_2021-10-12",
    "HOOD_S-1_2021-10-08",
    "IOT_S-1_2021-12-06",
    "KC_F-1_2020-09-23",
    "NETS_F-1_2017-03-21",
    "SI_S-1_2018-11-07",
    "SI_S-1_2025-07-25",
    "SNOW_S-1_2020-09-14",
    "TENB_S-1_2018-07-24",
}

# Regex pattern for non-8-K keys: TICKER_FORM_DATE
NON_8K_PATTERN = re.compile(
    r"^[A-Z]+_(S-1|F-1|10-K|10-K/A|10-Q)_\d{4}-\d{2}-\d{2}$"
)

# Build (ticker, date) set from the 18 migration keys for CSV row classification.
# HOOD's date in split.json and CSV is '10/8/21' (not ISO format), so we need
# to match by ticker key derivation from the file index key.
NON_8K_TICKER_DATES: set[tuple[str, str]] = set()
for _key in NON_8K_KEYS:
    _parts = _key.split("_")
    _ticker = _parts[0]
    _date = _parts[-1]  # last part is always the ISO date
    NON_8K_TICKER_DATES.add((_ticker, _date))

# Map ticker -> set of ISO dates for non-8K entries, for matching
# against potentially non-ISO dates in the CSV (e.g. HOOD's '10/8/21')
NON_8K_TICKER_ISO_DATES: dict[str, set[str]] = {}
for _ticker, _date in NON_8K_TICKER_DATES:
    NON_8K_TICKER_ISO_DATES.setdefault(_ticker, set()).add(_date)


def normalize_date(date_str: str) -> str:
    """Normalize various date formats to ISO YYYY-MM-DD if possible."""
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    # M/D/YY format (e.g. 10/8/21)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2})$", date_str)
    if m:
        month, day, year = m.groups()
        full_year = f"20{year}" if int(year) < 50 else f"19{year}"
        return f"{full_year}-{int(month):02d}-{int(day):02d}"
    # M/D/YYYY format
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", date_str)
    if m:
        month, day, year = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return date_str  # return as-is if unrecognized


def is_non_8k_csv_row(row: dict[str, str]) -> bool:
    """Return True if this CSV row belongs in the filing (non-8K) directory."""
    ticker = row["ticker"]
    raw_date = row["date"]
    iso_date = normalize_date(raw_date)
    if ticker not in NON_8K_TICKER_ISO_DATES:
        return False
    return iso_date in NON_8K_TICKER_ISO_DATES[ticker]


def count_accepted_rows(reviewed_csv_path: Path) -> int:
    """Count ACCEPT or EDIT rows in a reviewed CSV."""
    if not reviewed_csv_path.exists():
        return 0
    count = 0
    with open(reviewed_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("disposition", "").upper() in ("ACCEPT", "EDIT"):
                count += 1
    return count


def split_file_index(
    original: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Split _file_index.json into (presentation, filing) dicts."""
    pres: dict[str, str] = {}
    filing: dict[str, str] = {}
    for key, val in original.items():
        if key in NON_8K_KEYS:
            filing[key] = val
        else:
            pres[key] = val
    return pres, filing


def split_url_index(
    original: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Split _url_index.json into (presentation, filing) dicts."""
    pres: dict[str, str] = {}
    filing: dict[str, str] = {}
    for key, val in original.items():
        if key in NON_8K_KEYS:
            filing[key] = val
        else:
            pres[key] = val
    return pres, filing


def split_image_decisions(
    original: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split _image_decisions.json into (presentation, filing) dicts."""
    pres: dict[str, Any] = {}
    filing: dict[str, Any] = {}
    for compound_key, val in original.items():
        filing_key = compound_key.split(":")[0]
        if filing_key in NON_8K_KEYS:
            filing[compound_key] = val
        else:
            pres[compound_key] = val
    return pres, filing


def split_csv(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split CSV rows into (presentation, filing) lists."""
    pres: list[dict[str, str]] = []
    filing: list[dict[str, str]] = []
    for row in rows:
        if is_non_8k_csv_row(row):
            filing.append(row)
        else:
            pres.append(row)
    return pres, filing


def classify_source_file(filename: str) -> bool:
    """Return True if this _reviewed.csv filename belongs in the filing (non-8K) dir."""
    # filename format: KEY_reviewed.csv where KEY is the filing key
    # Strip the _reviewed.csv suffix to get the key
    if not filename.endswith("_reviewed.csv"):
        return False
    key = filename[: -len("_reviewed.csv")]
    return key in NON_8K_KEYS


def build_split_json(
    original: dict[str, Any],
    target_dir: Path,
    include_non_8k: bool,
) -> dict[str, Any]:
    """
    Build a split.json for either the presentation or filing directory.

    include_non_8k=True  → filing split.json (only non-8K presentations)
    include_non_8k=False → presentation split.json (only 8-K presentations)
    """
    companies_out: dict[str, Any] = {}

    for ticker, info in original["companies"].items():
        pres_dates: list[str] = info["presentations"]

        # Classify each date as 8-K or non-8-K
        matching_dates: list[str] = []
        for raw_date in pres_dates:
            iso_date = normalize_date(raw_date)
            is_non_8k = (ticker, iso_date) in NON_8K_TICKER_DATES
            if include_non_8k and is_non_8k:
                matching_dates.append(raw_date)
            elif not include_non_8k and not is_non_8k:
                matching_dates.append(raw_date)

        if not matching_dates:
            continue

        # Recompute annotation count from _reviewed.csv files in target dir
        annotation_count = 0
        for raw_date in matching_dates:
            iso_date = normalize_date(raw_date)
            # Reconstruct filing key from ticker and date
            # We need to find which key matches this ticker+date
            matching_key: str | None = None
            if include_non_8k:
                for k in NON_8K_KEYS:
                    k_parts = k.split("_")
                    k_ticker = k_parts[0]
                    k_date = k_parts[-1]
                    if k_ticker == ticker and k_date == iso_date:
                        matching_key = k
                        break
                if matching_key:
                    reviewed_path = target_dir / f"{matching_key}_reviewed.csv"
                    annotation_count += count_accepted_rows(reviewed_path)
            else:
                # 8-K keys have format TICKER_DATE (no form type)
                # The reviewed CSV name is TICKER_DATE_reviewed.csv
                # where DATE is the raw date (may not be ISO)
                # Try both formats
                for date_fmt in [raw_date, iso_date]:
                    candidate = target_dir / f"{ticker}_{date_fmt}_reviewed.csv"
                    if candidate.exists():
                        annotation_count += count_accepted_rows(candidate)
                        break

        companies_out[ticker] = {
            "split": info["split"],
            "sector": info.get("sector", ""),
            "presentations": matching_dates,
            "annotation_count": annotation_count,
        }

    # Build tuning/test lists (only companies present in this output)
    tuning_companies = [
        t for t in original["tuning_companies"] if t in companies_out
    ]
    test_companies = [
        t for t in original["test_companies"] if t in companies_out
    ]

    # Build source_files list by classifying original source_files directly.
    # This preserves entries for companies with 0 annotations (e.g. ADBE, CRM)
    # that appear in source_files but not in the companies dict.
    orig_source_files: list[str] = original.get("source_files", [])
    source_files: list[str] = [
        f for f in orig_source_files
        if classify_source_file(f) == include_non_8k
    ]
    # source_files already ordered as in original; sort for determinism
    source_files.sort()

    # Recompute statistics
    total_annotations = sum(
        info["annotation_count"] for info in companies_out.values()
    )
    tuning_annotations = sum(
        info["annotation_count"]
        for t, info in companies_out.items()
        if t in tuning_companies
    )
    test_annotations = sum(
        info["annotation_count"]
        for t, info in companies_out.items()
        if t in test_companies
    )
    test_pct = (
        round(test_annotations / total_annotations, 3)
        if total_annotations > 0
        else 0.0
    )

    result: dict[str, Any] = {
        "version": original.get("version", "1.0"),
        "description": original.get("description", ""),
        "tuning_companies": tuning_companies,
        "test_companies": test_companies,
        "companies": companies_out,
        "statistics": {
            "total_annotations": total_annotations,
            "tuning_annotations": tuning_annotations,
            "test_annotations": test_annotations,
            "test_pct": test_pct,
        },
        "source_files": source_files,
    }
    return result


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(dry_run: bool) -> None:
    print(f"{'[DRY RUN] ' if dry_run else ''}Starting migration...\n")

    # --- Load originals ---
    with open(PRES_DIR / "_file_index.json") as f:
        orig_file_index: dict[str, str] = json.load(f)
    with open(PRES_DIR / "_url_index.json") as f:
        orig_url_index: dict[str, str] = json.load(f)
    with open(PRES_DIR / "_image_decisions.json") as f:
        orig_img_decisions: dict[str, Any] = json.load(f)
    with open(PRES_DIR / "presentation_gold_standard.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        orig_csv_rows: list[dict[str, str]] = list(reader)
    with open(PRES_DIR / "split.json") as f:
        orig_split: dict[str, Any] = json.load(f)

    orig_source_files = orig_split.get("source_files", [])

    print(f"Original file_index: {len(orig_file_index)} keys")
    print(f"Original url_index: {len(orig_url_index)} keys")
    print(f"Original image_decisions: {len(orig_img_decisions)} entries")
    print(f"Original CSV rows: {len(orig_csv_rows)}")
    print(f"Original source_files: {len(orig_source_files)}")
    print()

    # --- Split indexes ---
    pres_file_index, filing_file_index = split_file_index(orig_file_index)
    pres_url_index, filing_url_index = split_url_index(orig_url_index)
    pres_img_decisions, filing_img_decisions = split_image_decisions(orig_img_decisions)
    pres_csv_rows, filing_csv_rows = split_csv(orig_csv_rows)

    # --- Build split.json for each dir ---
    # For filing: target_dir is FILING_DIR (files were already moved there)
    filing_split = build_split_json(orig_split, FILING_DIR, include_non_8k=True)
    # For pres: target_dir is PRES_DIR
    pres_split = build_split_json(orig_split, PRES_DIR, include_non_8k=False)

    filing_source_files = filing_split["source_files"]
    pres_source_files = pres_split["source_files"]

    # --- Validate ---
    print("Running validation assertions...")

    # file_index: 35 original (SI_S-1_2025-07-25 absent from file index)
    assert len(pres_file_index) + len(filing_file_index) == len(orig_file_index), (
        f"file_index split mismatch: {len(pres_file_index)} + {len(filing_file_index)} "
        f"!= {len(orig_file_index)}"
    )
    print(f"  file_index: {len(pres_file_index)} pres + {len(filing_file_index)} filing = {len(orig_file_index)} OK")

    assert len(pres_url_index) + len(filing_url_index) == len(orig_url_index), (
        f"url_index split mismatch: {len(pres_url_index)} + {len(filing_url_index)} "
        f"!= {len(orig_url_index)}"
    )
    print(f"  url_index: {len(pres_url_index)} pres + {len(filing_url_index)} filing = {len(orig_url_index)} OK")

    assert len(pres_img_decisions) + len(filing_img_decisions) == len(orig_img_decisions), (
        f"image_decisions split mismatch: {len(pres_img_decisions)} + {len(filing_img_decisions)} "
        f"!= {len(orig_img_decisions)}"
    )
    print(f"  image_decisions: {len(pres_img_decisions)} pres + {len(filing_img_decisions)} filing = {len(orig_img_decisions)} OK")

    assert len(pres_csv_rows) + len(filing_csv_rows) == len(orig_csv_rows), (
        f"CSV rows split mismatch: {len(pres_csv_rows)} + {len(filing_csv_rows)} "
        f"!= {len(orig_csv_rows)}"
    )
    print(f"  CSV rows: {len(pres_csv_rows)} pres + {len(filing_csv_rows)} filing = {len(orig_csv_rows)} OK")

    assert len(pres_source_files) + len(filing_source_files) == len(orig_source_files), (
        f"source_files split mismatch: {len(pres_source_files)} + {len(filing_source_files)} "
        f"!= {len(orig_source_files)}\n"
        f"  pres: {sorted(pres_source_files)}\n"
        f"  filing: {sorted(filing_source_files)}\n"
        f"  orig: {sorted(orig_source_files)}"
    )
    print(f"  source_files: {len(pres_source_files)} pres + {len(filing_source_files)} filing = {len(orig_source_files)} OK")

    print("\nAll assertions passed.\n")

    # --- Summary ---
    print(f"Presentation _file_index.json: {len(pres_file_index)} keys")
    print(f"Filing _file_index.json: {len(filing_file_index)} keys")
    print()
    print(f"Presentation split.json companies: {sorted(pres_split['companies'].keys())}")
    print(f"Filing split.json companies: {sorted(filing_split['companies'].keys())}")
    print()
    print(f"Presentation CSV rows: {len(pres_csv_rows)}")
    print(f"Filing CSV rows: {len(filing_csv_rows)}")
    print()
    print(f"Presentation source_files: {sorted(pres_source_files)}")
    print(f"Filing source_files: {sorted(filing_source_files)}")
    print()

    if dry_run:
        print("[DRY RUN] No files written. Rerun without --dry-run to apply.")
        return

    # --- Write outputs ---
    # Filing directory
    with open(FILING_DIR / "_file_index.json", "w") as f:
        json.dump(filing_file_index, f, indent=2)
    print(f"Wrote {FILING_DIR / '_file_index.json'}")

    with open(FILING_DIR / "_url_index.json", "w") as f:
        json.dump(filing_url_index, f, indent=2)
    print(f"Wrote {FILING_DIR / '_url_index.json'}")

    with open(FILING_DIR / "_image_decisions.json", "w") as f:
        json.dump(filing_img_decisions, f, indent=2)
    print(f"Wrote {FILING_DIR / '_image_decisions.json'}")

    write_csv(FILING_DIR / "filing_gold_standard.csv", filing_csv_rows, fieldnames)
    print(f"Wrote {FILING_DIR / 'filing_gold_standard.csv'} ({len(filing_csv_rows)} rows)")

    with open(FILING_DIR / "split.json", "w") as f:
        json.dump(filing_split, f, indent=2)
    print(f"Wrote {FILING_DIR / 'split.json'}")

    print()

    # Presentation directory (overwrite originals)
    with open(PRES_DIR / "_file_index.json", "w") as f:
        json.dump(pres_file_index, f, indent=2)
    print(f"Wrote {PRES_DIR / '_file_index.json'}")

    with open(PRES_DIR / "_url_index.json", "w") as f:
        json.dump(pres_url_index, f, indent=2)
    print(f"Wrote {PRES_DIR / '_url_index.json'}")

    with open(PRES_DIR / "_image_decisions.json", "w") as f:
        json.dump(pres_img_decisions, f, indent=2)
    print(f"Wrote {PRES_DIR / '_image_decisions.json'}")

    write_csv(PRES_DIR / "presentation_gold_standard.csv", pres_csv_rows, fieldnames)
    print(f"Wrote {PRES_DIR / 'presentation_gold_standard.csv'} ({len(pres_csv_rows)} rows)")

    with open(PRES_DIR / "split.json", "w") as f:
        json.dump(pres_split, f, indent=2)
    print(f"Wrote {PRES_DIR / 'split.json'}")

    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Split presentation GS index files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
