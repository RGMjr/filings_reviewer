#!/usr/bin/env python3
"""
Debug script for FIX-4: Investigate table parsing issue.

This script examines why only rightmost 2 columns are being extracted
from multi-period tables in the Slack Technologies filing.
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from src.infra.db import DatabaseAdapter

load_dotenv()

def main():
    """Debug table extraction for Slack Technologies filing."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set in environment")
        return 1

    db = DatabaseAdapter(db_url)

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Get the Slack filing
        # First check what companies we have
        cursor.execute("SELECT cik, company_name FROM companies WHERE company_name ILIKE '%slack%'")
        companies = cursor.fetchall()
        print(f"Found {len(companies)} companies matching 'slack':")
        for cik, name in companies:
            print(f"  CIK: {cik}, Name: {name}")
        print()

        # Try to get any filing for slack
        cursor.execute("""
            SELECT f.filing_id, c.company_name, f.form_type, f.filing_date, f.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE c.company_name ILIKE '%slack%'
            ORDER BY f.filing_date DESC
            LIMIT 5
        """)
        filings = cursor.fetchall()

        if not filings:
            print("ERROR: No Slack Technologies filings found")
            return 1

        print(f"Found {len(filings)} filings for Slack:")
        for f_id, name, form_type, f_date, cik in filings:
            print(f"  Filing {f_id}: {name} {form_type} on {f_date} (CIK: {cik})")
        print()

        filing_id, company_name, form_type, filing_date, cik = filings[0]
        print(f"Using filing: {company_name} {form_type} on {filing_date} (ID: {filing_id})")

        filing_id, company_name, form_type, filing_date = filing_row
        print(f"Found filing: {company_name} {form_type} on {filing_date}")
        print(f"Filing ID: {filing_id}")
        print()

        # Get segments containing "Paid Customers >$100,000"
        cursor.execute("""
            SELECT segment_id, segment_type, sequence_index,
                   LENGTH(raw_text) as text_len,
                   raw_text
            FROM source_segments
            WHERE filing_id = %s
            AND raw_text ILIKE '%Paid Customers >%100,000%'
            ORDER BY sequence_index
        """, (filing_id,))

        segments = cursor.fetchall()
        print(f"Found {len(segments)} segments with 'Paid Customers >$100,000'")
        print()

        for seg_id, seg_type, seq_idx, text_len, raw_text in segments:
            print(f"Segment {seg_id} (type={seg_type}, seq={seq_idx}, len={text_len}):")
            print("-" * 80)

            # Show the raw text
            print("Raw text:")
            print(raw_text[:1000])  # First 1000 chars
            print()

            # Check for [ROW] and [CELL] markers
            has_row_markers = "[ROW]" in raw_text
            has_cell_markers = "[CELL]" in raw_text
            print(f"Has [ROW] markers: {has_row_markers}")
            print(f"Has [CELL] markers: {has_cell_markers}")

            # Count numbers in the text
            import re
            numbers = re.findall(r'\b\d+\b', raw_text)
            print(f"Numbers found: {numbers[:20]}")  # First 20 numbers
            print()

            # Check if specific values are present
            target_values = ['135', '298', '351', '412', '491', '575', '645']
            for val in target_values:
                if val in raw_text:
                    # Find context around this value
                    idx = raw_text.find(val)
                    start = max(0, idx - 100)
                    end = min(len(raw_text), idx + 100)
                    context = raw_text[start:end]
                    print(f"Value '{val}' found at position {idx}:")
                    print(f"  Context: ...{context}...")

            print()
            print("=" * 80)
            print()

    return 0

if __name__ == "__main__":
    sys.exit(main())
