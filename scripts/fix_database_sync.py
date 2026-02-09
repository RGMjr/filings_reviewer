#!/usr/bin/env python3
"""
Fix Database/File Sync Issues

This script identifies and fixes discrepancies between database records
and actual files on disk:

1. Finds filings marked as "fetched" in database
2. Checks if HTML files actually exist
3. Updates database for missing files (clears fetch status, allows re-download)
4. Provides detailed statistics

Usage:
    # Dry run (no changes)
    python scripts/fix_database_sync.py --dry-run

    # Actually fix the database
    python scripts/fix_database_sync.py

    # Check specific CIK
    python scripts/fix_database_sync.py --cik 0001234567
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

load_dotenv()


def get_all_fetched_filings(db: DatabaseAdapter, cik: str = None) -> list[dict]:
    """Get all filings marked as fetched in database."""
    query = """
        SELECT
            f.filing_id,
            f.cik,
            f.accession_number,
            c.company_name,
            f.form_type,
            f.filing_date,
            f.html_storage_path,
            f.txt_storage_path,
            f.html_fetched_at,
            f.processing_status
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE
            f.html_fetched_at IS NOT NULL
    """

    params = {}

    if cik:
        query += " AND f.cik = %(cik)s"
        params['cik'] = cik

    query += " ORDER BY f.filing_date DESC"

    return db.query(query, params)


def check_file_exists(file_path: str) -> bool:
    """Check if file exists on disk."""
    if not file_path:
        return False
    return Path(file_path).exists()


def clear_fetch_status(db: DatabaseAdapter, filing_id: int, dry_run: bool = False) -> bool:
    """Clear fetch status for a filing to allow re-download."""
    if dry_run:
        return True

    try:
        query = """
            UPDATE filings
            SET
                html_storage_path = NULL,
                txt_storage_path = NULL,
                html_fetched_at = NULL,
                html_fetch_error = 'File missing - marked for re-download',
                processing_status = 'pending',
                updated_at = now()
            WHERE filing_id = %(filing_id)s
        """
        db.execute(query, {"filing_id": filing_id})
        return True
    except Exception as e:
        print(f"  ❌ Error updating filing {filing_id}: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fix database/file sync issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--cik",
        help="Only check filings for specific CIK",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )

    args = parser.parse_args()

    print("\n" + "="*100)
    print("Database/File Sync Repair Tool")
    print("="*100)

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made\n")
    else:
        print("\n🔧 LIVE MODE - Database will be updated\n")

    # Connect to database
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )
    db = DatabaseAdapter(db_url)

    print(f"Connected to database: {db_url}")

    # Get all fetched filings
    print("\nQuerying database for fetched filings...")
    if args.cik:
        print(f"  Filtering by CIK: {args.cik}")

    filings = get_all_fetched_filings(db, args.cik)
    print(f"✅ Found {len(filings)} filings marked as fetched\n")

    # Check each filing
    print("="*100)
    print("Checking file existence...")
    print("="*100)

    missing_html = []
    missing_txt = []
    valid_filings = []

    for i, filing in enumerate(filings, 1):
        if i <= 10 or i % 50 == 0:
            print(f"Progress: {i}/{len(filings)} ({i/len(filings)*100:.1f}%)")

        html_exists = check_file_exists(filing['html_storage_path'])
        txt_exists = check_file_exists(filing['txt_storage_path'])

        if not html_exists:
            missing_html.append(filing)
        elif not txt_exists and filing['txt_storage_path']:
            # TXT is optional, just track it
            missing_txt.append(filing)
        else:
            valid_filings.append(filing)

    print(f"\nCompleted checking {len(filings)} filings")

    # Print statistics
    print("\n" + "="*100)
    print("RESULTS")
    print("="*100)

    print(f"\n✅ Valid filings (HTML exists):      {len(valid_filings):>5} ({len(valid_filings)/len(filings)*100:>5.1f}%)")
    print(f"❌ Missing HTML files:               {len(missing_html):>5} ({len(missing_html)/len(filings)*100:>5.1f}%)")
    print(f"⚠️  Missing TXT (HTML exists):       {len(missing_txt):>5} ({len(missing_txt)/len(filings)*100:>5.1f}%)")

    # Show sample of missing files
    if missing_html:
        print("\n" + "="*100)
        print("MISSING HTML FILES (Sample)")
        print("="*100)
        print(f"\n{'Company':<40} {'CIK':<12} {'Form':<8} {'Filing Date':<12} {'Path'}")
        print("-"*100)

        for filing in missing_html[:20]:
            company = filing['company_name'][:38] if filing['company_name'] else 'N/A'
            print(f"{company:<40} {filing['cik']:<12} {filing['form_type']:<8} "
                  f"{str(filing['filing_date']):<12} {filing['html_storage_path']}")

        if len(missing_html) > 20:
            print(f"\n... and {len(missing_html) - 20} more")

    # Fix missing files
    if missing_html:
        print("\n" + "="*100)
        if args.dry_run:
            print("WOULD FIX MISSING FILES (Dry Run)")
        else:
            print("FIXING MISSING FILES")
        print("="*100)

        if not args.dry_run:
            response = input(f"\n⚠️  About to clear fetch status for {len(missing_html)} filings. Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("\nAborted by user")
                sys.exit(0)

        print(f"\nClearing fetch status for {len(missing_html)} filings...")

        fixed_count = 0
        failed_count = 0

        for i, filing in enumerate(missing_html, 1):
            if i % 50 == 0:
                print(f"  Progress: {i}/{len(missing_html)} ({i/len(missing_html)*100:.1f}%)")

            success = clear_fetch_status(db, filing['filing_id'], args.dry_run)
            if success:
                fixed_count += 1
            else:
                failed_count += 1

        print(f"\n✅ Successfully cleared: {fixed_count}")
        if failed_count > 0:
            print(f"❌ Failed to clear:     {failed_count}")

    # Final summary
    print("\n" + "="*100)
    print("SUMMARY")
    print("="*100)

    print(f"\nTotal filings checked:           {len(filings)}")
    print(f"  ✅ Valid (ready for extraction): {len(valid_filings)}")
    print(f"  ❌ Missing HTML (fixed):         {len(missing_html)}")
    print(f"  ⚠️  Missing TXT only:            {len(missing_txt)}")

    if not args.dry_run and missing_html:
        print("\n✅ Database updated successfully")
        print(f"   {len(missing_html)} filings marked for re-download")
        print("   Run batch_download_filings.py to fetch missing files")

    if args.dry_run and missing_html:
        print("\n💡 To fix these issues, run:")
        print("   python3 scripts/fix_database_sync.py")

    print("\n" + "="*100)


if __name__ == "__main__":
    main()
