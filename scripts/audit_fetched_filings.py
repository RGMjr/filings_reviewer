#!/usr/bin/env python3
"""
Audit all fetched filings to validate data quality.

This script:
1. Validates all fetched filing content
2. Checks file sizes and metadata
3. Detects error pages or corrupted downloads
4. Generates quality assurance report
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.filing_fetcher.filing_fetcher import FilingFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def validate_filing_file(file_path: str, cik: str, accession_number: str, fetcher: FilingFetcher) -> dict:
    """
    Validate a single filing file.

    Args:
        file_path: Path to filing HTML file
        cik: Expected CIK
        accession_number: Expected accession number
        fetcher: FilingFetcher instance for validation

    Returns:
        Dict with validation results
    """
    result = {
        'path': file_path,
        'cik': cik,
        'accession': accession_number,
        'exists': False,
        'size': 0,
        'valid': False,
        'error': None,
    }

    path = Path(file_path)

    # Check if file exists
    if not path.exists():
        result['error'] = "File not found on disk"
        return result

    result['exists'] = True
    result['size'] = path.stat().st_size

    # Check minimum size
    if result['size'] < 20_000:
        result['error'] = f"File too small ({result['size']:,} bytes)"
        return result

    # Read and validate content
    try:
        content = path.read_text(encoding='utf-8')

        # Use FilingFetcher's validation method
        is_valid, error_msg = fetcher._validate_filing_content(content, cik, accession_number)

        result['valid'] = is_valid
        if not is_valid:
            result['error'] = error_msg

    except Exception as e:
        result['error'] = f"Error reading file: {e}"

    return result


def main():
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)
    fetcher = FilingFetcher(storage_root="data/filings")

    logger.info("=" * 80)
    logger.info("Filing Quality Audit")
    logger.info("=" * 80)

    # Get all fetched filings from database
    query = """
        SELECT
            f.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            f.html_storage_path,
            f.html_fetched_at,
            f.html_fetch_error,
            c.company_name
        FROM filings f
        JOIN companies c USING (company_id)
        WHERE f.html_fetched_at IS NOT NULL
        ORDER BY c.company_name, f.filing_date
    """

    filings = db.query(query)

    if not filings:
        logger.warning("No fetched filings found in database!")
        return

    logger.info(f"Found {len(filings)} fetched filings to audit")
    logger.info("")

    # Validate each filing
    results = []
    file_sizes = []

    for i, filing in enumerate(filings, 1):
        cik = filing['cik']
        accession = filing['accession_number']
        company = filing['company_name']

        logger.info(f"[{i}/{len(filings)}] Validating {company} ({accession[:10]}...)")

        result = validate_filing_file(
            filing['html_storage_path'],
            cik,
            accession,
            fetcher
        )

        result['company_name'] = company
        result['form_type'] = filing['form_type']
        result['filing_date'] = filing['filing_date']
        result['db_error'] = filing['html_fetch_error']

        results.append(result)

        if result['exists']:
            file_sizes.append(result['size'])

        # Report on this filing
        if result['valid']:
            logger.info(f"  ✓ Valid ({result['size']:,} bytes)")
        else:
            logger.error(f"  ✗ INVALID: {result['error']}")

    # Generate summary report
    logger.info("")
    logger.info("=" * 80)
    logger.info("AUDIT SUMMARY")
    logger.info("=" * 80)

    total = len(results)
    exists = sum(1 for r in results if r['exists'])
    valid = sum(1 for r in results if r['valid'])
    invalid = sum(1 for r in results if r['exists'] and not r['valid'])
    missing = total - exists

    logger.info(f"Total filings audited: {total}")
    logger.info(f"  Files exist: {exists} ({exists/total*100:.1f}%)")
    logger.info(f"  Files missing: {missing} ({missing/total*100:.1f}%)" if missing > 0 else "  Files missing: 0")
    logger.info(f"  Valid filings: {valid} ({valid/total*100:.1f}%)")
    logger.info(f"  Invalid filings: {invalid} ({invalid/total*100:.1f}%)" if invalid > 0 else "  Invalid filings: 0")

    if file_sizes:
        logger.info("")
        logger.info("File Size Statistics:")
        logger.info(f"  Minimum: {min(file_sizes):,} bytes")
        logger.info(f"  Maximum: {max(file_sizes):,} bytes")
        logger.info(f"  Average: {sum(file_sizes)//len(file_sizes):,} bytes")
        logger.info(f"  Median: {sorted(file_sizes)[len(file_sizes)//2]:,} bytes")

    # Report invalid filings
    if invalid > 0:
        logger.info("")
        logger.info("INVALID FILINGS:")
        logger.info("-" * 80)
        for r in results:
            if r['exists'] and not r['valid']:
                logger.error(f"{r['company_name']}")
                logger.error(f"  Accession: {r['accession']}")
                logger.error(f"  Path: {r['path']}")
                logger.error(f"  Size: {r['size']:,} bytes")
                logger.error(f"  Error: {r['error']}")
                logger.error("")

    # Report missing filings
    if missing > 0:
        logger.info("")
        logger.info("MISSING FILES:")
        logger.info("-" * 80)
        for r in results:
            if not r['exists']:
                logger.error(f"{r['company_name']}")
                logger.error(f"  Accession: {r['accession']}")
                logger.error(f"  Expected path: {r['path']}")
                logger.error(f"  DB error: {r['db_error']}")
                logger.error("")

    logger.info("=" * 80)

    if invalid > 0 or missing > 0:
        logger.error("⚠️  AUDIT FAILED - Issues detected")
        sys.exit(1)
    else:
        logger.info("✓ AUDIT PASSED - All filings valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
