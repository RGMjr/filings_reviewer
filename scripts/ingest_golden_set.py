#!/usr/bin/env python3
"""
Ingest user provided golden set CSV into the data/gold_standard directory structure.

Usage:
    python3 scripts/ingest_golden_set.py
"""

import csv
import json
import logging
import shutil
import ssl
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Mapping from Company Name in CSV to Directory Name
COMPANY_MAP = {
    "Samsara": "Samsara_Inc_",
    "Samsara Inc.": "Samsara_Inc_",
    "SAMSARA VISION INC.": "Samsara_Vision_Inc_",
    "Farfetch": "Farfetch_Limited",
    "Farfetch Limited": "Farfetch_Limited",
    "Slack": "Slack_Technologies",
    "Slack Technologies": "Slack_Technologies",
}

# Target columns for extracted_values.csv
TARGET_FIELDNAMES = [
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
    "source_text_preview"
]

def clean_money(val_str):
    """Clean string to be numeric if possible"""
    if not val_str:
        return ""
    clean = val_str.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return str(float(clean))
    except ValueError:
        return clean

def parse_period(period_str):
    """Attempt to parse period string to standardized date format"""
    if not period_str:
        return "", "", ""

    # Try common formats
    formats = ["%d-%b-%y", "%Y-%m-%d", "%m/%d/%Y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(period_str, fmt)
            return "", dt.strftime("%Y-%m-%d"), "" # Start, End, Type
        except ValueError:
            continue

    # If explicit range or other text, just return as is?
    # For now assume mostly end dates in the input
    return "", period_str, ""

def main():
    base_dir = Path(__file__).parent.parent
    gold_dir = base_dir / "data" / "gold_standard"
    input_csv = gold_dir / "golden_set_251218.csv"

    if not input_csv.exists():
        logger.error(f"Input file not found: {input_csv}")
        return

    logger.info(f"Reading from {input_csv}")

    # Group rows by company
    company_data = defaultdict(list)
    company_urls = {}

    with open(input_csv, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            company_name = row.get("Company", "").strip()
            # Handle variations or lookups
            # Try exact match first, then partial
            mapped_name = None
            if company_name in COMPANY_MAP:
                mapped_name = COMPANY_MAP[company_name]
            else:
                 # fuzzy match attempt
                for k, v in COMPANY_MAP.items():
                    if k in company_name or company_name in k:
                        mapped_name = v
                        break

            if not mapped_name:
                logger.warning(f"Could not map company '{company_name}', skipping row.")
                continue

            company_data[mapped_name].append(row)
            if row.get("Document URL"):
                company_urls[mapped_name] = row["Document URL"]

    # Process each company
    for dir_name, rows in company_data.items():
        target_dir = gold_dir / dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        # Ensure metadata.json exists and has local_path
        metadata_path = target_dir / "metadata.json"
        meta = {}
        if metadata_path.exists():
            with open(metadata_path) as f:
                meta = json.load(f)

        # If new or needs update
        needs_save = False
        if not meta:
            clean_name = dir_name.replace("_", " ")
            meta = {
                "company_name": clean_name,
                "cik": "0000000000", # Placeholder
                "accession_number": "0000000000-00-000000", # Placeholder
                "filing_date": "2020-01-01", # Placeholder
                "report_period": "2019-12-31", # Placeholder
                "form_type": "S-1", # Likely S-1 for these IPO companies
                "source_url": company_urls.get(dir_name, "")
            }
            needs_save = True

        # Check/Download HTML
        local_path = meta.get("local_path")
        full_local_path = base_dir / local_path if local_path else None

        if not local_path or not full_local_path.exists():
            source_url = meta.get("source_url") or company_urls.get(dir_name)
            if source_url:
                logger.info(f"Downloading filing for {dir_name} from {source_url}...")
                try:
                    # Save to target_dir/filing.html
                    filename = "filing.html"
                    save_path = target_dir / filename

                    # Add User-Agent to avoid 403 from SEC
                    req = urllib.request.Request(
                        source_url,
                        headers={'User-Agent': 'FilingsReviewer/1.0 (antigravity_agent@google.com)'}
                    )

                    # Bypass SSL verification
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    with urllib.request.urlopen(req, context=ctx) as response, open(save_path, 'wb') as out_file:
                        shutil.copyfileobj(response, out_file)

                    # Update metadata with relative path from base_dir
                    rel_path = save_path.relative_to(base_dir)
                    meta["local_path"] = str(rel_path)
                    if "source_url" not in meta:
                        meta["source_url"] = source_url
                    needs_save = True
                    logger.info(f"Downloaded to {save_path}")
                except Exception as e:
                    logger.error(f"Failed to download {source_url}: {e}")
            else:
                logger.warning(f"No local_path and no source_url for {dir_name}")

        if needs_save:
            with open(metadata_path, 'w') as f:
                json.dump(meta, f, indent=2)
            logger.info(f"Updated metadata.json for {dir_name}")

        # Create/Overwrite extracted_values.csv
        output_csv = target_dir / "extracted_values.csv"

        extracted_rows = []
        for i, row in enumerate(rows):
            # Map columns
            period_start, period_end, _ = parse_period(row.get("Period"))

            # Logic to determine actual metric name to use
            metric_id = row.get("Standard Metric Name") or row.get("New standard metric?")
            # Basic cleaning of metric_id to be snake_case if it isn't
            if metric_id:
                metric_id = metric_id.lower().replace(" ", "_")

            new_row = {
                "review_status": "accepted", # Treat golden set as accepted
                "notes": row.get("Definition", ""),
                "metric_value_id": f"{10000 + i}", # Generate dummy ID
                "metric_id": metric_id,
                "metric_name": row.get("Standard Metric Name"),
                "value_numeric": clean_money(row.get("Scaled value") or row.get("Raw value")),
                "value_text": row.get("Raw value"),
                "unit": row.get("Scale/unit"),
                "period_start": period_start,
                "period_end": period_end,
                "period_type": "", # derived?
                "source_type": "text",
                "extraction_method": "manual",
                "section_heading": "",
                "source_text_preview": row.get("Quote/context", "")
            }
            extracted_rows.append(new_row)

        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=TARGET_FIELDNAMES)
            writer.writeheader()
            writer.writerows(extracted_rows)

        logger.info(f"Wrote {len(extracted_rows)} rows to {output_csv}")

if __name__ == "__main__":
    main()
