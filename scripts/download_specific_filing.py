#!/usr/bin/env python3
"""
Download a specific filing by CIK and accession number for GR-17.

Usage:
    python3 scripts/download_specific_filing.py <CIK> <accession_number>
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.db import DatabaseAdapter
from src.infra.sec_client import SECEdgarClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Download specific SEC filing")
    parser.add_argument("cik", help="Company CIK (e.g., 1512673 for Square)")
    parser.add_argument(
        "--accession",
        help="Specific accession number (optional, will fetch first S-1/F-1 if not provided)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string",
    )

    args = parser.parse_args()

    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://dev:dev@localhost:5433/filings_analysis"
    )
    user_agent = os.getenv("SEC_USER_AGENT", "FilingsReviewer/1.0 (contact@example.com)")

    logger.info("=" * 80)
    logger.info(f"Fetching filing for CIK: {args.cik}")
    logger.info("=" * 80)

    # Initialize clients
    db = DatabaseAdapter(db_url)
    sec_client = SECEdgarClient(user_agent=user_agent)

    # Fetch company submissions
    cik_padded = args.cik.zfill(10)
    logger.info(f"Fetching submissions for CIK {cik_padded}...")

    try:
        submissions = sec_client.get_company_submissions(cik_padded)
        company_name = submissions.get("name", "Unknown")
        logger.info(f"Company: {company_name}")

        # Get filings
        recent_filings = submissions.get("filings", {}).get("recent", {})
        form_types = recent_filings.get("form", [])
        accession_numbers = recent_filings.get("accessionNumber", [])
        filing_dates = recent_filings.get("filingDate", [])
        primary_docs = recent_filings.get("primaryDocument", [])

        # Find S-1 or F-1
        s1_filings = []
        for i, form in enumerate(form_types):
            if form in ["S-1", "F-1"]:
                s1_filings.append(
                    {
                        "form_type": form,
                        "accession_number": accession_numbers[i],
                        "filing_date": filing_dates[i],
                        "primary_document": primary_docs[i] if i < len(primary_docs) else "",
                    }
                )

        if not s1_filings:
            logger.error(f"No S-1 or F-1 filings found for CIK {cik_padded}")
            return

        # Use first S-1/F-1 or specified accession
        target_filing = s1_filings[0]
        if args.accession:
            for filing in s1_filings:
                if args.accession in filing["accession_number"]:
                    target_filing = filing
                    break

        logger.info(f"Selected filing: {target_filing['form_type']} ({target_filing['filing_date']})")
        logger.info(f"Accession: {target_filing['accession_number']}")

        # Insert/update company
        logger.info("Adding company to database...")
        db.execute(
            """
            INSERT INTO companies (cik, company_name, created_at, updated_at)
            VALUES (%(cik)s, %(name)s, NOW(), NOW())
            ON CONFLICT (cik) DO UPDATE
            SET company_name = EXCLUDED.company_name,
                updated_at = NOW()
            """,
            {"cik": cik_padded, "name": company_name},
        )

        # Get company_id
        result = db.query("SELECT company_id FROM companies WHERE cik = %(cik)s", {"cik": cik_padded})
        company_id = result[0]["company_id"]

        # Build filing URL
        accession_no_dashes = target_filing["accession_number"].replace("-", "")
        base_url = f"https://www.sec.gov/Archives/edgar/data/{args.cik}/{accession_no_dashes}"

        primary_doc = target_filing.get("primary_document", "")
        if primary_doc:
            html_url = f"{base_url}/{primary_doc}"
        else:
            # Try common patterns
            html_url = f"{base_url}/{target_filing['accession_number']}.htm"

        logger.info(f"Filing URL: {html_url}")

        # Insert filing
        logger.info("Adding filing to database...")
        db.execute(
            """
            INSERT INTO filings (
                company_id, cik, accession_number, form_type, filing_date,
                sec_html_url, is_in_scope_phase1, processing_status
            )
            VALUES (
                %(company_id)s, %(cik)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
                %(html_url)s, true, 'pending'
            )
            ON CONFLICT (company_id, accession_number) DO NOTHING
            """,
            {
                "company_id": company_id,
                "cik": cik_padded,
                "accession_number": target_filing["accession_number"],
                "form_type": target_filing["form_type"],
                "filing_date": target_filing["filing_date"],
                "html_url": html_url,
            },
        )

        logger.info("✓ Filing added to database")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Run fetch_curated_sample.py to download HTML")
        logger.info("2. Run extraction pipeline to get segments and richness scores")
        logger.info("3. Query segments for labeling")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
