#!/usr/bin/env python3
"""Debug script to check database connection."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter

# Get database URL
db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
print(f"Database URL: {db_url}")

# Connect
db = DatabaseAdapter(connection_string=db_url)

# Try to query filings
print("\nQuerying filings table...")
result = db.query("SELECT COUNT(*) as count FROM filings")
print(f"Total filings: {result[0]['count']}")

# Try specific filing IDs
filing_ids = [38540, 41000, 38570]
for fid in filing_ids:
    result = db.query(
        "SELECT filing_id, cik FROM filings WHERE filing_id = %(filing_id)s",
        {"filing_id": fid}
    )
    if result:
        print(f"Filing {fid}: Found (CIK: {result[0]['cik']})")
    else:
        print(f"Filing {fid}: NOT FOUND")

print("\nDone.")
