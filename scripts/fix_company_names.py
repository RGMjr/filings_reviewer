#!/usr/bin/env python3
"""
One-time fix script to correct misnamed company records in the database.

This script fixes a data integrity issue where company records were created
with incorrect names due to hardcoded CIK-to-name mappings in setup_manual_test.py.

Affected records:
- CIK 0001828365: Was labeled "Snowflake", actually "RLX Technology Inc"
- CIK 0001620053: Was labeled "DocuSign", actually "Vodka Brands Corp"

Usage:
    python scripts/fix_company_names.py           # Dry run (show changes)
    python scripts/fix_company_names.py --apply   # Apply changes

See: docs/worker-prompts/archive/WORKER_PROMPT_TASK_GR-16.md for investigation details.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Corrections to apply: CIK -> correct company name
COMPANY_NAME_CORRECTIONS = {
    "0001828365": "RLX Technology Inc",      # Was incorrectly "Snowflake"
    "0001620053": "Vodka Brands Corp",       # Was incorrectly "DocuSign"
}


def show_current_state(db: DatabaseAdapter) -> None:
    """Display current company records that need fixing."""
    logger.info("\n=== Current State ===")

    ciks = list(COMPANY_NAME_CORRECTIONS.keys())
    result = db.query("""
        SELECT c.company_id, c.cik, c.company_name,
               (SELECT COUNT(*) FROM filings f WHERE f.company_id = c.company_id) as filing_count,
               (SELECT COUNT(*) FROM source_segments ss
                JOIN filings f ON ss.filing_id = f.filing_id
                WHERE f.company_id = c.company_id) as segment_count
        FROM companies c
        WHERE c.cik = ANY(%(ciks)s)
        ORDER BY c.company_id;
    """, {"ciks": ciks})

    if not result:
        logger.info("No matching company records found.")
        return

    for row in result:
        correct_name = COMPANY_NAME_CORRECTIONS.get(row["cik"], "Unknown")
        needs_fix = row["company_name"] != correct_name

        status = "❌ NEEDS FIX" if needs_fix else "✓ OK"
        logger.info(f"""
  Company ID: {row['company_id']}
  CIK: {row['cik']}
  Current Name: {row['company_name']}
  Correct Name: {correct_name}
  Status: {status}
  Filings: {row['filing_count']} | Segments: {row['segment_count']}
""")


def apply_fixes(db: DatabaseAdapter) -> int:
    """Apply company name corrections. Returns count of records updated."""
    updated = 0

    for cik, correct_name in COMPANY_NAME_CORRECTIONS.items():
        # Check current state
        result = db.query(
            "SELECT company_id, company_name FROM companies WHERE cik = %(cik)s;",
            {"cik": cik}
        )

        if not result:
            logger.warning(f"No company found with CIK {cik}")
            continue

        current_name = result[0]["company_name"]
        company_id = result[0]["company_id"]

        if current_name == correct_name:
            logger.info(f"✓ CIK {cik} already has correct name: {correct_name}")
            continue

        # Apply fix (use execute for UPDATE, not query)
        db.execute(
            "UPDATE companies SET company_name = %(name)s WHERE cik = %(cik)s;",
            {"cik": cik, "name": correct_name},
            fetch=False
        )

        logger.info(f"✓ Updated CIK {cik}: '{current_name}' → '{correct_name}' (company_id: {company_id})")
        updated += 1

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix misnamed company records")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the fixes (default: dry run only)"
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", "postgresql://dev:dev@localhost:5433/filings_analysis")
    db = DatabaseAdapter(db_url)

    logger.info("=== Company Name Fix Script ===")
    logger.info(f"Database: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    # Show current state
    show_current_state(db)

    if args.apply:
        logger.info("\n=== Applying Fixes ===")
        updated = apply_fixes(db)
        logger.info(f"\n=== Complete: {updated} record(s) updated ===")

        # Show final state
        logger.info("\n=== Final State ===")
        show_current_state(db)
    else:
        logger.info("\n=== DRY RUN ===")
        logger.info("No changes made. Run with --apply to apply fixes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
