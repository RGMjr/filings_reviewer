#!/usr/bin/env python3
"""
Validate that fetched filings in database have corresponding files on disk.
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter


def main():
    db = DatabaseAdapter(os.environ['DATABASE_URL'])

    # Get all fetched filings
    fetched_filings = db.query("""
        SELECT cik, accession_number, html_fetched_at
        FROM filings
        WHERE processing_status = 'fetched'
        ORDER BY html_fetched_at DESC
    """)

    print(f"\n{'='*80}")
    print(f"VALIDATION REPORT: Fetched Filings vs Files on Disk")
    print(f"{'='*80}\n")

    with_files = 0
    without_files = 0
    missing_examples = []

    for filing in fetched_filings:
        cik = filing['cik']
        acc = filing['accession_number']
        acc_clean = acc.replace("-", "")

        file_path = Path(f"data/filings/{cik}/{acc_clean}/primary.htm")

        if file_path.exists():
            with_files += 1
        else:
            without_files += 1
            if len(missing_examples) < 10:
                missing_examples.append({
                    'cik': cik,
                    'accession': acc,
                    'fetched_at': filing['html_fetched_at'],
                    'expected_path': str(file_path)
                })

    # Print summary
    print(f"Total fetched records in database: {len(fetched_filings)}")
    print(f"  ✓ With files on disk: {with_files} ({with_files/len(fetched_filings)*100:.1f}%)")
    print(f"  ✗ Without files: {without_files} ({without_files/len(fetched_filings)*100:.1f}%)")

    if missing_examples:
        print(f"\n{'='*80}")
        print(f"Examples of records marked 'fetched' but missing files:")
        print(f"{'='*80}\n")
        for ex in missing_examples:
            print(f"CIK: {ex['cik']}")
            print(f"  Accession: {ex['accession']}")
            print(f"  Fetched at: {ex['fetched_at']}")
            print(f"  Expected: {ex['expected_path']}")
            print()

    # Check for orphaned directories (directories without files)
    filings_root = Path("data/filings")
    orphaned_dirs = []

    for cik_dir in filings_root.glob("*"):
        if not cik_dir.is_dir():
            continue
        for acc_dir in cik_dir.glob("*"):
            if not acc_dir.is_dir():
                continue
            htm_file = acc_dir / "primary.htm"
            if not htm_file.exists():
                orphaned_dirs.append(str(acc_dir))

    print(f"\n{'='*80}")
    print(f"Orphaned Directories (no primary.htm file)")
    print(f"{'='*80}\n")
    print(f"Total orphaned directories: {len(orphaned_dirs)}")

    if orphaned_dirs:
        print(f"\nFirst 10 examples:")
        for dir_path in orphaned_dirs[:10]:
            print(f"  - {dir_path}")


if __name__ == "__main__":
    main()
