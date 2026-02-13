#!/usr/bin/env python3
"""
Collect sample earnings call transcripts from HuggingFace dataset.

Downloads transcripts for target companies and saves them as text files
in data/spike_samples/transcripts/.

Also creates inventory.csv tracking all collected samples.
"""

import csv
import json
import re
from pathlib import Path

from datasets import load_dataset

# Project root
ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES_DIR = ROOT / "data" / "spike_samples"
TRANSCRIPTS_DIR = SAMPLES_DIR / "transcripts"
PRESENTATIONS_DIR = SAMPLES_DIR / "presentations"

# Target companies selected for customer metric density in earnings calls
# (symbol -> display name, sector)
TARGET_COMPANIES = {
    "CRM": ("Salesforce", "SaaS"),
    "ADBE": ("Adobe", "SaaS"),
    "ADSK": ("Autodesk", "SaaS"),
    "INTU": ("Intuit", "SaaS"),
    "MSFT": ("Microsoft", "SaaS"),
    "PYPL": ("PayPal", "Fintech"),
    "META": ("Meta Platforms", "Consumer Tech"),
    "GDDY": ("GoDaddy", "SaaS"),
    "TMUS": ("T-Mobile", "Telecom"),
    "EA": ("Electronic Arts", "Gaming"),
}

# How many transcripts per company (most recent)
MAX_PER_COMPANY = 2


def collect_transcripts():
    """Download transcripts from HuggingFace and save locally."""
    print("Loading kurry/sp500_earnings_transcripts dataset...")
    ds = load_dataset("kurry/sp500_earnings_transcripts", split="train")
    print(f"  Total transcripts in dataset: {len(ds)}")
    print(f"  Columns: {ds.column_names}")

    # Group by symbol, keeping most recent first
    by_symbol = {}
    for row in ds:
        sym = row["symbol"]
        if sym in TARGET_COMPANIES:
            if sym not in by_symbol:
                by_symbol[sym] = []
            by_symbol[sym].append(row)

    # Sort each company's transcripts by date (most recent first)
    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda r: r.get("date", ""), reverse=True)

    inventory = []

    for sym, rows in sorted(by_symbol.items()):
        company_name, sector = TARGET_COMPANIES[sym]
        print(f"\n  {company_name} ({sym}): {len(rows)} transcripts available")

        for i, row in enumerate(rows[:MAX_PER_COMPANY]):
            date_val = row.get("date", "unknown")
            quarter = row.get("quarter", "")
            year = row.get("year", "")

            # Build transcript text from structured content
            content = None
            structured = row.get("structured_content", None)
            if structured and isinstance(structured, list):
                parts = []
                for item in structured:
                    if isinstance(item, dict):
                        speaker = item.get("speaker", "Unknown")
                        text = item.get("text", "")
                        parts.append(f"{speaker}: {text}")
                    elif isinstance(item, str):
                        parts.append(item)
                content = "\n\n".join(parts)

            if not content:
                content = row.get("content", "")

            if not content or len(content) < 100:
                print(f"    Skipping {date_val} (content too short)")
                continue

            # Save to file
            safe_date = re.sub(r'[^\w\-]', '_', str(date_val)[:10])
            filename = f"{sym}_{safe_date}.txt"
            filepath = TRANSCRIPTS_DIR / filename
            filepath.write_text(content, encoding="utf-8")

            inventory.append({
                "company": company_name,
                "ticker": sym,
                "date": str(date_val)[:10],
                "quarter": f"Q{quarter} {year}" if quarter and year else "",
                "source": "kurry/sp500_earnings_transcripts",
                "format": "text",
                "doc_type": "transcript",
                "filename": filename,
                "size_chars": len(content),
                "sector": sector,
            })

            print(f"    Saved: {filename} ({len(content):,} chars) - Q{quarter} {year}")

    return inventory


def write_inventory(inventory):
    """Write inventory.csv with all collected samples."""
    inventory_path = SAMPLES_DIR / "inventory.csv"

    fieldnames = [
        "company", "ticker", "date", "quarter", "source", "format",
        "doc_type", "filename", "size_chars", "sector",
    ]

    with open(inventory_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(inventory)

    print(f"\nInventory written: {inventory_path} ({len(inventory)} entries)")


def main():
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("SAMPLE COLLECTION FOR BEYOND-SEC RESEARCH SPIKE")
    print("=" * 60)

    transcript_inventory = collect_transcripts()
    write_inventory(transcript_inventory)

    print(f"\nTotal samples collected: {len(transcript_inventory)}")
    print("\nNote: Investor presentations need manual collection from")
    print("SEC EDGAR 8-K exhibits. See docs/spike/data_source_evaluation.md")


if __name__ == "__main__":
    main()
