#!/usr/bin/env python3
"""
Validate all filing URLs in the database.

This script:
1. Validates URL format and structure
2. Checks CIK and accession number formatting
3. Identifies malformed URLs
4. Generates validation report
"""

import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def validate_url_format(url: str, cik: str, accession_number: str) -> dict:
    """
    Validate a single filing URL.

    Args:
        url: SEC URL to validate
        cik: CIK from database
        accession_number: Accession number from database

    Returns:
        Dict with validation results
    """
    result = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'url_type': None,
    }

    # Check URL type
    if '/cgi-bin/viewer' in url:
        result['url_type'] = 'viewer_url'
        result['valid'] = False
        result['errors'].append("Still using deprecated viewer URL format")
        return result

    elif url.endswith('/'):
        result['url_type'] = 'directory_url'

        # Validate directory URL format
        # Expected: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/
        pattern = r'https://www\.sec\.gov/Archives/edgar/data/(\d+)/(\w+)/$'
        match = re.match(pattern, url)

        if not match:
            result['valid'] = False
            result['errors'].append(f"Malformed directory URL: {url}")
            return result

        url_cik = match.group(1)
        url_accession = match.group(2)

        # Validate CIK matches
        if url_cik != cik:
            result['valid'] = False
            result['errors'].append(f"CIK mismatch: URL has {url_cik}, DB has {cik}")

        # Validate accession number (remove dashes and compare)
        accession_no_dashes = accession_number.replace('-', '')
        if url_accession != accession_no_dashes:
            result['valid'] = False
            result['errors'].append(
                f"Accession mismatch: URL has {url_accession}, expected {accession_no_dashes}"
            )

        # Validate accession number length (should be 18 chars without dashes)
        if len(accession_no_dashes) != 18:
            result['warnings'].append(
                f"Unusual accession number length: {len(accession_no_dashes)} chars"
            )

    else:
        result['url_type'] = 'direct_url'

        # Validate direct URL format
        # Expected: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{filename}.htm
        pattern = r'https://www\.sec\.gov/Archives/edgar/data/(\d+)/(\w+)/([^/]+\.(htm|html))$'
        match = re.match(pattern, url)

        if not match:
            result['valid'] = False
            result['errors'].append(f"Malformed direct URL: {url}")
            return result

        url_cik = match.group(1)
        url_accession = match.group(2)
        filename = match.group(3)

        # Validate CIK matches
        if url_cik != cik:
            result['valid'] = False
            result['errors'].append(f"CIK mismatch: URL has {url_cik}, DB has {cik}")

        # Validate accession number
        accession_no_dashes = accession_number.replace('-', '')
        if url_accession != accession_no_dashes:
            result['valid'] = False
            result['errors'].append(
                f"Accession mismatch: URL has {url_accession}, expected {accession_no_dashes}"
            )

    # Validate CIK format (should be 10 digits, zero-padded)
    if not re.match(r'^\d{10}$', cik):
        result['warnings'].append(f"CIK not 10 digits: '{cik}'")

    # Validate accession number format (should have dashes: NNNNNNNNNN-NN-NNNNNN)
    if not re.match(r'^\d{10}-\d{2}-\d{6}$', accession_number):
        result['warnings'].append(
            f"Unusual accession number format: '{accession_number}'"
        )

    return result


def main():
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)

    logger.info("=" * 80)
    logger.info("Database URL Validation")
    logger.info("=" * 80)

    # Get all filings with URLs
    query = """
        SELECT
            f.filing_id,
            f.cik,
            f.accession_number,
            f.sec_html_url,
            f.form_type,
            c.company_name
        FROM filings f
        JOIN companies c USING (company_id)
        ORDER BY f.filing_id
    """

    filings = db.query(query)

    if not filings:
        logger.warning("No filings found in database!")
        return

    logger.info(f"Validating {len(filings):,} filing URLs")
    logger.info("")

    # Validate each URL
    results = {
        'total': 0,
        'valid': 0,
        'invalid': 0,
        'by_type': {},
        'errors': [],
        'warnings': [],
    }

    for i, filing in enumerate(filings, 1):
        if i % 5000 == 0:
            logger.info(f"Progress: {i:,}/{len(filings):,} ({i/len(filings)*100:.1f}%)")

        result = validate_url_format(
            filing['sec_html_url'],
            filing['cik'],
            filing['accession_number']
        )

        results['total'] += 1

        if result['valid']:
            results['valid'] += 1
        else:
            results['invalid'] += 1
            results['errors'].append({
                'filing_id': filing['filing_id'],
                'company': filing['company_name'],
                'cik': filing['cik'],
                'accession': filing['accession_number'],
                'url': filing['sec_html_url'],
                'errors': result['errors'],
            })

        # Track warnings
        if result['warnings']:
            results['warnings'].append({
                'filing_id': filing['filing_id'],
                'company': filing['company_name'],
                'cik': filing['cik'],
                'accession': filing['accession_number'],
                'warnings': result['warnings'],
            })

        # Track URL types
        url_type = result['url_type']
        if url_type not in results['by_type']:
            results['by_type'][url_type] = 0
        results['by_type'][url_type] += 1

    # Generate summary report
    logger.info("")
    logger.info("=" * 80)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 80)

    logger.info(f"Total URLs validated: {results['total']:,}")
    logger.info(f"  Valid: {results['valid']:,} ({results['valid']/results['total']*100:.1f}%)")
    logger.info(f"  Invalid: {results['invalid']:,} ({results['invalid']/results['total']*100:.1f}%)")

    logger.info("")
    logger.info("URL Types:")
    for url_type, count in sorted(results['by_type'].items()):
        logger.info(f"  {url_type}: {count:,} ({count/results['total']*100:.1f}%)")

    # Report errors
    if results['errors']:
        logger.info("")
        logger.info(f"INVALID URLs ({len(results['errors'])} filings):")
        logger.info("-" * 80)

        # Show first 10 errors
        for error in results['errors'][:10]:
            logger.error(f"{error['company']}")
            logger.error(f"  CIK: {error['cik']}")
            logger.error(f"  Accession: {error['accession']}")
            logger.error(f"  URL: {error['url']}")
            for err_msg in error['errors']:
                logger.error(f"  - {err_msg}")
            logger.error("")

        if len(results['errors']) > 10:
            logger.error(f"... and {len(results['errors']) - 10} more invalid URLs")

    # Report warnings
    if results['warnings']:
        logger.info("")
        logger.info(f"WARNINGS ({len(results['warnings'])} filings):")
        logger.info("-" * 80)

        # Show first 5 warnings
        for warning in results['warnings'][:5]:
            logger.warning(f"{warning['company']}")
            logger.warning(f"  CIK: {warning['cik']}")
            logger.warning(f"  Accession: {warning['accession']}")
            for warn_msg in warning['warnings']:
                logger.warning(f"  - {warn_msg}")
            logger.warning("")

        if len(results['warnings']) > 5:
            logger.warning(f"... and {len(results['warnings']) - 5} more warnings")

    logger.info("=" * 80)

    if results['invalid'] > 0:
        logger.error(f"⚠️  VALIDATION FAILED - {results['invalid']:,} invalid URLs")
        sys.exit(1)
    else:
        logger.info("✓ VALIDATION PASSED - All URLs valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
