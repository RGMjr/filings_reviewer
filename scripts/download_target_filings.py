#!/usr/bin/env python3
"""
Download and process specific target company filings.

This script downloads the latest S-1/A registration statements for
target companies (Snowflake, DocuSign) and processes them through
the extraction pipeline.

Usage:
    python scripts/download_target_filings.py           # Dry run
    python scripts/download_target_filings.py --apply   # Download and process
    python scripts/download_target_filings.py --cik 0001640147  # Specific company

See: docs/GOLDMINE_REMEDIATION_PLAN.md for GR-16 context.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.extraction_pipeline import ExtractionPipeline
from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.sec_client import SECClient

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Target companies for GR-16
TARGET_COMPANIES = {
    "0001640147": "Snowflake Inc",      # Cloud data platform - IPO Sept 2020
    "0001261333": "DocuSign, Inc.",     # E-signature - IPO April 2018
}


def show_available_filings(sec_client: SECClient, cik: str) -> None:
    """Display available registration filings for a company."""
    logger.info(f"\n=== Checking filings for CIK {cik} ===")

    filing = sec_client.get_latest_registration_filing(cik)
    if filing:
        logger.info(f"""
  Company: {filing.company_name}
  CIK: {filing.cik}
  Form Type: {filing.form_type}
  Filing Date: {filing.filing_date}
  Accession: {filing.accession_number}
  Primary Doc URL: {filing.primary_doc_url}
""")
    else:
        logger.warning(f"No S-1/S-1/A filings found for CIK {cik}")


def download_and_process_filing(
    sec_client: SECClient,
    db: DatabaseAdapter,
    cik: str,
    dry_run: bool = True
) -> bool:
    """Download and process the latest registration filing for a company.

    Returns True if successful, False otherwise.
    """
    logger.info(f"\n=== Processing CIK {cik} ===")

    # Get latest S-1/A filing
    filing_metadata = sec_client.get_latest_registration_filing(cik)
    if not filing_metadata:
        logger.error(f"No registration filing found for CIK {cik}")
        return False

    logger.info(f"Found: {filing_metadata.company_name} - {filing_metadata.form_type}")
    logger.info(f"Filing date: {filing_metadata.filing_date}")
    logger.info(f"Accession: {filing_metadata.accession_number}")

    if dry_run:
        logger.info("[DRY RUN] Would download and process this filing")
        return True

    # Check if company already exists
    result = db.query(
        "SELECT company_id FROM companies WHERE cik = %(cik)s;",
        {"cik": filing_metadata.cik}
    )

    if result:
        company_id = result[0]["company_id"]
        logger.info(f"Company already exists (ID: {company_id})")
    else:
        # Create company record
        result = db.query("""
            INSERT INTO companies (cik, company_name, ticker)
            VALUES (%(cik)s, %(name)s, %(ticker)s)
            RETURNING company_id;
        """, {
            "cik": filing_metadata.cik,
            "name": filing_metadata.company_name,
            "ticker": filing_metadata.ticker
        })
        company_id = result[0]["company_id"]
        logger.info(f"Created company (ID: {company_id})")

    # Check if filing already exists
    result = db.query(
        "SELECT filing_id FROM filings WHERE accession_number = %(acc)s;",
        {"acc": filing_metadata.accession_number}
    )

    if result:
        filing_id = result[0]["filing_id"]
        logger.info(f"Filing already exists (ID: {filing_id})")

        # Check if it has segments
        seg_result = db.query(
            "SELECT COUNT(*) as cnt FROM source_segments WHERE filing_id = %(id)s;",
            {"id": filing_id}
        )
        if seg_result and seg_result[0]["cnt"] > 0:
            logger.info(f"Filing already has {seg_result[0]['cnt']} segments, skipping")
            return True
    else:
        # Create filing record
        result = db.query("""
            INSERT INTO filings (
                company_id, cik, form_type, filing_date,
                accession_number, sec_html_url, processing_status
            )
            VALUES (
                %(company_id)s, %(cik)s, %(form_type)s, %(filing_date)s,
                %(accession)s, %(url)s, 'pending'
            )
            RETURNING filing_id;
        """, {
            "company_id": company_id,
            "cik": filing_metadata.cik,
            "form_type": filing_metadata.form_type,
            "filing_date": filing_metadata.filing_date,
            "accession": filing_metadata.accession_number,
            "url": filing_metadata.primary_doc_url
        })
        filing_id = result[0]["filing_id"]
        logger.info(f"Created filing (ID: {filing_id})")

    # Download the filing HTML
    logger.info("Downloading filing HTML...")
    fetcher = FilingFetcher(sec_client=sec_client, db=db)
    success = fetcher.fetch_filing(filing_metadata)

    if not success:
        logger.error("Failed to download filing HTML")
        return False

    logger.info("Filing downloaded successfully")

    # Process through extraction pipeline
    logger.info("Processing through extraction pipeline...")
    pipeline = ExtractionPipeline(db=db)
    result = pipeline.process_filing(filing_id)

    if result:
        # ExtractionResult is a dataclass, access attributes directly
        segments = getattr(result, 'segments_created', 0) or getattr(result, 'total_segments', 0)
        logger.info(f"Extraction complete: {segments} segments created")
        return True
    else:
        logger.error("Extraction pipeline failed")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Download target company filings")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually download and process (default: dry run)"
    )
    parser.add_argument(
        "--cik",
        type=str,
        help="Process specific CIK only"
    )
    args = parser.parse_args()

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://dev:dev@localhost:5433/filings_analysis"
    )
    db = DatabaseAdapter(db_url)

    # SEC client requires user agent
    user_agent = os.environ.get(
        "SEC_USER_AGENT",
        "CMASB-Analytics research@example.com"
    )
    sec_client = SECClient(user_agent=user_agent)

    logger.info("=== Target Filing Downloader ===")
    logger.info(f"Database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    logger.info(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")

    # Determine which CIKs to process
    if args.cik:
        ciks_to_process = [args.cik.zfill(10)]
    else:
        ciks_to_process = list(TARGET_COMPANIES.keys())

    # Process each target
    success_count = 0
    for cik in ciks_to_process:
        expected_name = TARGET_COMPANIES.get(cik, "Unknown")
        logger.info(f"\n{'='*60}")
        logger.info(f"Target: {expected_name} (CIK: {cik})")
        logger.info(f"{'='*60}")

        if not args.apply:
            show_available_filings(sec_client, cik)
            success_count += 1
        else:
            if download_and_process_filing(sec_client, db, cik, dry_run=False):
                success_count += 1

    logger.info(f"\n=== Complete: {success_count}/{len(ciks_to_process)} successful ===")

    if not args.apply:
        logger.info("\nThis was a DRY RUN. Run with --apply to download and process.")

    return 0 if success_count == len(ciks_to_process) else 1


if __name__ == "__main__":
    sys.exit(main())
