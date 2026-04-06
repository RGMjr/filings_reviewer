#!/usr/bin/env python3
"""
Convert reviewed presentation annotation CSVs into the main gold standard format.

Reads *_reviewed.csv files from data/presentation_gold_standard/, filters to
ACCEPT/EDIT rows, and writes:
  - data/gold_standard/{CompanyDir}/filing.html  (copied from local presentations cache)
  - data/gold_standard/{CompanyDir}/metadata.json
  - data/gold_standard/{CompanyDir}/extracted_values.csv
  - Appends rows to data/gold_standard/golden_set_251218.csv

Usage:
    # Convert a specific reviewed file
    python3 scripts/convert_presentation_to_gold_standard.py --reviewed CHWY_S-1_2019-06-12_reviewed.csv

    # Convert all reviewed files (skips already-converted companies)
    python3 scripts/convert_presentation_to_gold_standard.py --all

    # Dry run — print what would be added without writing anything
    python3 scripts/convert_presentation_to_gold_standard.py --reviewed CHWY_S-1_2019-06-12_reviewed.csv --dry-run
"""

import argparse
import csv
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
PRES_GS_DIR = REPO_ROOT / "data" / "presentation_gold_standard"
MAIN_GS_DIR = REPO_ROOT / "data" / "gold_standard"
GOLDEN_SET_CSV = MAIN_GS_DIR / "golden_set_251218.csv"

GOLDEN_SET_FIELDNAMES = [
    "Document URL",
    "Company",
    "Standard Metric Name",
    "New standard metric?",
    "Name in the text",
    "Raw value",
    "Scaled value",
    "Scale/unit",
    "Period",
    "Definition",
    "Quote/context",
    "segment_type",
    "is_definition_only",
    "value_context",
    "detection_difficulty",
    "period_start",
    "period_end",
    "duplicate_group",
]

EXTRACTED_VALUES_FIELDNAMES = [
    "review_status",
    "notes",
    "metric_value_id",
    "metric_id",
    "metric_name",
    "value_numeric",
    "value_text",
    "unit",
    "period_start",
    "period_end",
    "period_type",
    "source_type",
    "extraction_method",
    "section_heading",
    "source_text_preview",
]

UNIT_MAP = {
    "percent": "%",
    "currency": "$",
    "count": "count",
    "ratio": "ratio",
    "": "",
}

SOURCE_TYPE_MAP = {
    "html_table": "table",
    "text": "text",
    "image": "chart",
    "filing": "text",
    "ocr_table": "table",
    "chart": "chart",
}

CONFIDENCE_TO_DIFFICULTY = {
    "HIGH": "easy",
    "MEDIUM": "medium",
    "LOW": "hard",
}

# Fiscal year end dates for known tickers (month, day)
FISCAL_YEAR_END = {
    "CHWY": (1, 31),   # Chewy FY ends ~Jan 31
    "CART": (12, 31),
    "DDOG": (12, 31),
    "FLYW": (12, 31),
    "GTLB": (1, 31),
    "HOOD": (12, 31),
}


def parse_sec_url_local(url: str):
    """
    Parse CIK, accession number, and filename from an SEC EDGAR URL.
    Returns (cik_padded, accession_dashes, filename) or None.
    """
    pattern = r"https?://(?:www\.)?sec\.gov/Archives/edgar/data/(\d+)/(\d+)/([^/?#]+)"
    match = re.match(pattern, url, re.IGNORECASE)
    if not match:
        return None
    cik = match.group(1).zfill(10)
    raw_accession = match.group(2)
    filename = match.group(3)
    # Format accession as XXXXXXXXXX-XX-XXXXXX
    accession_dashes = f"{raw_accession[:10]}-{raw_accession[10:12]}-{raw_accession[12:]}"
    return cik, accession_dashes, filename


def normalize_company_for_path(company_name: str) -> str:
    """Match the logic in fresh_extractor._normalize_company_for_path."""
    normalized = company_name.replace(" ", "_").replace(".", "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


def parse_value_numeric(value_str: str) -> str:
    """
    Parse a value string to a numeric string.
    Handles: "7.7 million", "$1,234", "66%", "1.73", "2.1 billion"
    """
    if not value_str:
        return ""
    s = value_str.strip().lower()
    multiplier = 1.0
    if "billion" in s:
        multiplier = 1_000_000_000
        s = s.replace("billion", "")
    elif "million" in s:
        multiplier = 1_000_000
        s = s.replace("million", "")
    # Strip non-numeric except decimal point and minus
    s = re.sub(r"[,$%\s]", "", s)
    try:
        numeric = float(s) * multiplier
        # Format: no trailing zeros for large numbers, keep decimals for small
        if multiplier > 1 and numeric == int(numeric):
            return str(int(numeric))
        return str(numeric)
    except ValueError:
        return ""


def parse_period_fields(period_str: str):
    """
    Parse period string into (period_display, period_start, period_end).
    Handles:
      - "2022-01-01 to 2022-12-31"  -> ("31-Dec-22", "2022-01-01", "2022-12-31")
      - "2023-06-30"                -> ("30-Jun-23", "", "2023-06-30")
      - "other" or free text        -> ("", "", "")
    """
    if not period_str or period_str.strip().lower() in ("other", "unknown", ""):
        return "", "", ""

    # Range pattern: YYYY-MM-DD to YYYY-MM-DD
    range_match = re.match(
        r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", period_str.strip()
    )
    if range_match:
        start_str, end_str = range_match.group(1), range_match.group(2)
        try:
            end_dt = datetime.strptime(end_str, "%Y-%m-%d")
            display = end_dt.strftime("%-d-%b-%y")  # e.g. "31-Dec-22"
            return display, start_str, end_str
        except ValueError:
            return period_str, start_str, end_str

    # Single date: YYYY-MM-DD
    single_match = re.match(r"(\d{4}-\d{2}-\d{2})$", period_str.strip())
    if single_match:
        date_str = single_match.group(1)
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display = dt.strftime("%-d-%b-%y")
            return display, "", date_str
        except ValueError:
            return period_str, "", date_str

    # Unparseable — use raw text in Period, leave start/end empty
    return period_str, "", ""


def extract_filing_key(filename: str) -> str:
    """
    Extract the filing key from a reviewed CSV filename.
    E.g. "CHWY_S-1_2019-06-12_reviewed.csv" -> "CHWY_S-1_2019-06-12"
    """
    name = Path(filename).stem  # strip .csv
    if name.endswith("_reviewed"):
        return name[: -len("_reviewed")]
    if name.endswith("_preannotated"):
        return name[: -len("_preannotated")]
    return name


def extract_ticker(filing_key: str) -> str:
    """E.g. "CHWY_S-1_2019-06-12" -> "CHWY" """
    return filing_key.split("_")[0]


def load_json_index(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def get_companies_already_in_golden_set() -> set:
    """Return set of company names already in golden_set_251218.csv."""
    if not GOLDEN_SET_CSV.exists():
        return set()
    companies = set()
    with open(GOLDEN_SET_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            companies.add(row.get("Company", "").strip())
    return companies


def load_reviewed_rows(reviewed_csv: Path) -> list[dict]:
    """Load and filter rows from a reviewed CSV to only ACCEPT/EDIT, non-trap."""
    rows = []
    with open(reviewed_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            disposition = row.get("disposition", "").strip().upper()
            if disposition not in ("ACCEPT", "EDIT"):
                continue
            is_trap = row.get("is_trap", "").strip().lower()
            if is_trap in ("true", "1", "yes"):
                continue
            rows.append(row)
    return rows


def build_golden_set_row(row: dict, document_url: str) -> dict:
    """Map a reviewed CSV row to a golden_set_251218.csv row."""
    period_display, period_start, period_end = parse_period_fields(row.get("period", ""))
    source_type_raw = row.get("source_type", "").strip()
    confidence_raw = row.get("confidence", "").strip().upper()

    return {
        "Document URL": document_url,
        "Company": row.get("company", "").strip(),
        "Standard Metric Name": row.get("metric_id", "").strip(),
        "New standard metric?": "",
        "Name in the text": row.get("raw_text", "").strip(),
        "Raw value": row.get("value", "").strip(),
        "Scaled value": parse_value_numeric(row.get("value", "")),
        "Scale/unit": UNIT_MAP.get(row.get("unit", "").strip().lower(), row.get("unit", "").strip()),
        "Period": period_display,
        "Definition": "",
        "Quote/context": row.get("raw_text", "").strip(),
        "segment_type": SOURCE_TYPE_MAP.get(source_type_raw, source_type_raw),
        "is_definition_only": "",
        "value_context": "",
        "detection_difficulty": CONFIDENCE_TO_DIFFICULTY.get(confidence_raw, ""),
        "period_start": period_start,
        "period_end": period_end,
        "duplicate_group": "",
    }


def build_extracted_values_row(row: dict, idx: int) -> dict:
    """Map a reviewed CSV row to extracted_values.csv format."""
    _, period_start, period_end = parse_period_fields(row.get("period", ""))
    source_type_raw = row.get("source_type", "").strip()

    return {
        "review_status": "accepted",
        "notes": row.get("disposition_reason", "").strip(),
        "metric_value_id": str(20000 + idx),
        "metric_id": row.get("metric_id", "").strip(),
        "metric_name": row.get("metric_id", "").strip(),
        "value_numeric": parse_value_numeric(row.get("value", "")),
        "value_text": row.get("value", "").strip(),
        "unit": UNIT_MAP.get(row.get("unit", "").strip().lower(), row.get("unit", "").strip()),
        "period_start": period_start,
        "period_end": period_end,
        "period_type": "",
        "source_type": SOURCE_TYPE_MAP.get(source_type_raw, source_type_raw),
        "extraction_method": "manual",
        "section_heading": row.get("section", "").strip(),
        "source_text_preview": row.get("raw_text", "").strip(),
    }


def convert_reviewed_file(
    reviewed_csv: Path,
    url_index: dict,
    file_index: dict,
    dry_run: bool = False,
) -> int:
    """
    Convert a single reviewed CSV into gold standard format.
    Returns count of rows added.
    """
    filing_key = extract_filing_key(reviewed_csv.name)
    ticker = extract_ticker(filing_key)

    document_url = url_index.get(filing_key)
    if not document_url:
        logger.error(f"No URL found for filing key '{filing_key}' in _url_index.json — skipping")
        return 0

    local_html_rel = file_index.get(filing_key)
    if not local_html_rel:
        logger.error(f"No local HTML path for '{filing_key}' in _file_index.json — skipping")
        return 0

    local_html = REPO_ROOT / local_html_rel
    if not local_html.exists():
        logger.error(f"Local HTML file not found: {local_html} — skipping")
        return 0

    rows = load_reviewed_rows(reviewed_csv)
    if not rows:
        logger.warning(f"No ACCEPT/EDIT rows in {reviewed_csv.name} — skipping")
        return 0

    company_name = rows[0].get("company", "").strip()
    if not company_name:
        logger.error(f"No company name in {reviewed_csv.name} — skipping")
        return 0

    parsed = parse_sec_url_local(document_url)
    if not parsed:
        logger.error(f"Could not parse SEC URL: {document_url} — skipping")
        return 0

    cik, accession_dashes, _ = parsed
    company_dir_name = normalize_company_for_path(company_name)
    company_dir = MAIN_GS_DIR / company_dir_name

    fy_month, fy_day = FISCAL_YEAR_END.get(ticker, (12, 31))

    golden_set_rows = [build_golden_set_row(r, document_url) for r in rows]
    extracted_rows = [build_extracted_values_row(r, i) for i, r in enumerate(rows)]

    logger.info(
        f"{filing_key}: {len(rows)} accepted rows -> {company_dir_name}/"
        f"  (CIK={cik}, accession={accession_dashes})"
    )

    if dry_run:
        print(f"\n--- DRY RUN: {reviewed_csv.name} ---")
        print(f"  Company dir : data/gold_standard/{company_dir_name}/")
        print(f"  Filing HTML : {local_html_rel}")
        print(f"  Rows to add : {len(rows)}")
        print(f"  Document URL: {document_url}")
        print(f"  Sample row  : {golden_set_rows[0]}")
        return len(rows)

    # Create company directory
    company_dir.mkdir(parents=True, exist_ok=True)

    # Copy filing HTML
    dest_html = company_dir / "filing.html"
    shutil.copy2(local_html, dest_html)
    logger.info(f"  Copied filing HTML to {dest_html}")

    # Write metadata.json
    metadata = {
        "cik": cik,
        "accession_number": accession_dashes,
        "fiscal_year_end_month": fy_month,
        "fiscal_year_end_day": fy_day,
    }
    (company_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    logger.info("  Wrote metadata.json")

    # Write extracted_values.csv
    extracted_csv_path = company_dir / "extracted_values.csv"
    with open(extracted_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXTRACTED_VALUES_FIELDNAMES)
        writer.writeheader()
        writer.writerows(extracted_rows)
    logger.info(f"  Wrote extracted_values.csv ({len(extracted_rows)} rows)")

    # Append to golden_set_251218.csv
    append_mode = GOLDEN_SET_CSV.exists()
    with open(GOLDEN_SET_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=GOLDEN_SET_FIELDNAMES)
        if not append_mode:
            writer.writeheader()
        writer.writerows(golden_set_rows)
    logger.info(f"  Appended {len(golden_set_rows)} rows to golden_set_251218.csv")

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--reviewed",
        nargs="+",
        metavar="FILENAME",
        help="Reviewed CSV filename(s) from data/presentation_gold_standard/",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Convert all *_reviewed.csv files in data/presentation_gold_standard/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be added without writing anything",
    )
    args = parser.parse_args()

    url_index = load_json_index(PRES_GS_DIR / "_url_index.json")
    file_index = load_json_index(PRES_GS_DIR / "_file_index.json")

    if args.all:
        reviewed_files = sorted(PRES_GS_DIR.glob("*_reviewed.csv"))
    else:
        reviewed_files = [PRES_GS_DIR / name for name in args.reviewed]

    if not reviewed_files:
        logger.error("No reviewed CSV files found.")
        sys.exit(1)

    # Skip companies already in the golden set (unless dry run)
    already_present = set() if args.dry_run else get_companies_already_in_golden_set()

    total_added = 0
    for reviewed_csv in reviewed_files:
        if not reviewed_csv.exists():
            logger.error(f"File not found: {reviewed_csv}")
            continue

        # Check if company already in golden set by peeking at first data row
        with open(reviewed_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            first_row = next(reader, None)
        if first_row is None:
            logger.warning(f"Empty file: {reviewed_csv.name} — skipping")
            continue

        company_name = first_row.get("company", "").strip()
        if company_name in already_present and not args.dry_run:
            logger.info(f"Skipping {reviewed_csv.name}: '{company_name}' already in golden set")
            continue

        count = convert_reviewed_file(reviewed_csv, url_index, file_index, dry_run=args.dry_run)
        total_added += count

    print(f"\nDone. Total rows {'would be ' if args.dry_run else ''}added: {total_added}")


if __name__ == "__main__":
    main()
