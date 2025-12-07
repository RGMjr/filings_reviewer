#!/usr/bin/env python3
"""
Test fetch on a diverse sample of filings for quality assurance.

This script:
1. Selects a diverse sample of filings (different years, companies, form types)
2. Fetches them using FilingFetcher with validation
3. Monitors success rate and errors
4. Generates quality report
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata, SECClient
from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def main():
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)
    sec_client = SECClient(user_agent="CMASB Filings Analyzer rgmarkey@gmail.com")
    fetcher = FilingFetcher(
        storage_root="data/filings",
        db=db,
        sec_client=sec_client
    )

    logger.info("=" * 80)
    logger.info("Diverse Filing Fetch Test")
    logger.info("=" * 80)

    # Select diverse sample of filings
    # Strategy: Get filings from different years, companies, and form types
    query = """
        WITH diverse_sample AS (
            SELECT
                f.cik,
                f.accession_number,
                f.form_type,
                f.filing_date,
                f.sec_html_url as primary_doc_url,
                f.sec_txt_url as txt_url,
                c.company_name,
                EXTRACT(YEAR FROM f.filing_date) as filing_year,
                ROW_NUMBER() OVER (
                    PARTITION BY EXTRACT(YEAR FROM f.filing_date), f.form_type
                    ORDER BY RANDOM()
                ) as rn
            FROM filings f
            JOIN companies c USING (company_id)
            WHERE
                f.is_in_scope_phase1 = true
                AND f.html_fetched_at IS NULL
                AND (f.html_fetch_error IS NULL OR f.html_fetch_error = '')
                AND f.filing_date >= '2015-01-01'
        )
        SELECT
            cik,
            accession_number,
            form_type,
            filing_date,
            primary_doc_url,
            txt_url,
            company_name,
            filing_year
        FROM diverse_sample
        WHERE rn <= 2  -- 2 filings per year-formtype combination
        ORDER BY filing_year, form_type, RANDOM()
        LIMIT 100
    """

    results = db.query(query)

    if not results:
        logger.warning("No unfetched filings found!")
        return

    logger.info(f"Selected {len(results)} diverse filings to test:")
    logger.info("")

    # Show distribution
    by_year = {}
    by_form = {}
    for r in results:
        year = r['filing_year']
        form = r['form_type']

        by_year[year] = by_year.get(year, 0) + 1
        by_form[form] = by_form.get(form, 0) + 1

    logger.info("Distribution by Year:")
    for year in sorted(by_year.keys()):
        logger.info(f"  {year}: {by_year[year]} filings")

    logger.info("")
    logger.info("Distribution by Form Type:")
    for form in sorted(by_form.keys()):
        logger.info(f"  {form}: {by_form[form]} filings")

    logger.info("")
    logger.info("-" * 80)
    logger.info("Starting fetch test...")
    logger.info("-" * 80)
    logger.info("")

    # Convert to FilingMetadata objects
    filings = [
        FilingMetadata(
            cik=r["cik"],
            company_name=r["company_name"],
            form_type=r["form_type"],
            filing_date=str(r["filing_date"]),
            accession_number=r["accession_number"],
            primary_doc_url=r["primary_doc_url"],
            txt_url=r.get("txt_url"),
        )
        for r in results
    ]

    # Fetch filings
    stats = fetcher.fetch_batch(filings, fetch_txt=False)

    # Generate detailed report
    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST RESULTS")
    logger.info("=" * 80)

    total = stats['total']
    fetched = stats['fetched']
    failed = stats['failed']
    skipped = stats['skipped']

    logger.info(f"Total filings: {total}")
    logger.info(f"  Successfully fetched: {fetched} ({fetched/total*100:.1f}%)")
    logger.info(f"  Failed: {failed} ({failed/total*100:.1f}%)")
    logger.info(f"  Skipped (cached): {skipped} ({skipped/total*100:.1f}%)")

    # Check for errors in database
    error_query = """
        SELECT
            f.cik,
            f.accession_number,
            f.html_fetch_error,
            c.company_name
        FROM filings f
        JOIN companies c USING (company_id)
        WHERE f.accession_number = ANY(%(accessions)s)
          AND f.html_fetch_error IS NOT NULL
    """

    accessions = [r['accession_number'] for r in results]
    errors = db.query(error_query, {"accessions": accessions})

    if errors:
        logger.info("")
        logger.info(f"ERRORS ({len(errors)} filings):")
        logger.info("-" * 80)
        for err in errors:
            logger.error(f"{err['company_name']}")
            logger.error(f"  Accession: {err['accession_number']}")
            logger.error(f"  Error: {err['html_fetch_error']}")
            logger.error("")

    # Run audit on newly fetched filings
    if fetched > 0:
        logger.info("")
        logger.info("Running validation audit on fetched filings...")
        logger.info("-" * 80)

        audit_query = """
            SELECT
                f.cik,
                f.accession_number,
                f.html_storage_path,
                c.company_name
            FROM filings f
            JOIN companies c USING (company_id)
            WHERE f.accession_number = ANY(%(accessions)s)
              AND f.html_fetched_at IS NOT NULL
        """

        fetched_filings = db.query(audit_query, {"accessions": accessions})

        validation_failures = 0
        for filing in fetched_filings:
            path = Path(filing['html_storage_path'])
            if not path.exists():
                logger.error(f"Missing file: {filing['company_name']} - {path}")
                validation_failures += 1
                continue

            content = path.read_text(encoding='utf-8')
            is_valid, error_msg = fetcher._validate_filing_content(
                content,
                filing['cik'],
                filing['accession_number']
            )

            if not is_valid:
                logger.error(f"Invalid content: {filing['company_name']}")
                logger.error(f"  Error: {error_msg}")
                validation_failures += 1

        if validation_failures == 0:
            logger.info(f"✓ All {len(fetched_filings)} fetched filings passed validation")
        else:
            logger.error(f"✗ {validation_failures} validation failures")

    logger.info("")
    logger.info("=" * 80)

    # Determine pass/fail
    success_rate = (fetched / total * 100) if total > 0 else 0

    if failed == 0 and success_rate >= 95:
        logger.info("✓ TEST PASSED")
        logger.info(f"  Success rate: {success_rate:.1f}%")
        logger.info(f"  All critical checks passed")
        sys.exit(0)
    elif failed > 0 and success_rate >= 80:
        logger.warning("⚠️  TEST PASSED WITH WARNINGS")
        logger.warning(f"  Success rate: {success_rate:.1f}%")
        logger.warning(f"  Some failures detected - review errors above")
        sys.exit(0)
    else:
        logger.error("✗ TEST FAILED")
        logger.error(f"  Success rate: {success_rate:.1f}%")
        logger.error(f"  Too many failures - investigate before scaling")
        sys.exit(1)


if __name__ == "__main__":
    main()
