#!/usr/bin/env python3
"""Debug table extraction - simplified version"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from src.infra.db import DatabaseAdapter

load_dotenv()

def main():
    db_url = os.getenv("DATABASE_URL")
    db = DatabaseAdapter(db_url)

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Find Slack filing
        cursor.execute("""
            SELECT COUNT(*)
            FROM companies
            WHERE company_name ILIKE '%slack%'
        """)
        count = cursor.fetchone()[0]
        print(f"Companies with 'slack' in name: {count}")

        if count == 0:
            print("No Slack company found in database!")
            print("Listing all companies:")
            cursor.execute("SELECT company_id, cik, company_name FROM companies LIMIT 10")
            for row in cursor.fetchall():
                print(f"  {row}")
            return 1

        # Get company info
        cursor.execute("""
            SELECT company_id, cik, company_name
            FROM companies
            WHERE company_name ILIKE '%slack%'
        """)
        company = cursor.fetchone()
        print(f"\nCompany: {company}")

        # Get filing
        cursor.execute("""
            SELECT filing_id, form_type, filing_date
            FROM filings
            WHERE company_id = %s
            LIMIT 1
        """, (company[0],))
        filing = cursor.fetchone()

        if not filing:
            print("No filings found!")
            return 1

        print(f"Filing: {filing}")
        filing_id = filing[0]

        # Get segments
        cursor.execute("""
            SELECT segment_id, segment_type, LENGTH(raw_text)
            FROM source_segments
            WHERE filing_id = %s
            AND raw_text ILIKE '%Paid Customers >%100,000%'
        """, (filing_id,))

        segments = cursor.fetchall()
        print(f"\nFound {len(segments)} segments with 'Paid Customers >$100,000'")

        for seg_id, seg_type, text_len in segments:
            print(f"\nSegment {seg_id} (type={seg_type}, length={text_len}):")

            # Get the actual text
            cursor.execute("""
                SELECT raw_text
                FROM source_segments
                WHERE segment_id = %s
            """, (seg_id,))

            raw_text = cursor.fetchone()[0]

            # Show first 500 chars
            print("Text preview:")
            print(raw_text[:500])
            print()

            # Check for markers
            print(f"Has [ROW] markers: {'[ROW]' in raw_text}")
            print(f"Has [CELL] markers: {'[CELL]' in raw_text}")

            # Find target values
            targets = ['135', '298', '351', '575', '645']
            print(f"\nLooking for values: {targets}")
            for val in targets:
                if val in raw_text:
                    idx = raw_text.find(val)
                    start = max(0, idx - 50)
                    end = min(len(raw_text), idx + 50)
                    print(f"  '{val}' found at pos {idx}: ...{raw_text[start:end]}...")
                else:
                    print(f"  '{val}' NOT FOUND")

    return 0

if __name__ == "__main__":
    sys.exit(main())
