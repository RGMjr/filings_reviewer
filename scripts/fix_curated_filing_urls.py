#!/usr/bin/env python3
"""
Fix filing URLs for curated companies by fetching correct Archives URLs.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.infra.db import DatabaseAdapter
from src.infra.sec_client import SECClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Known good companies
CURATED_COMPANIES = [
    'SHOPIFY INC.',
    'Square, Inc.',
    'DROPBOX, INC.',
    'Zoom Video Communications, Inc.',
    'Slack Technologies, Inc.',
    'Datadog, Inc.',
]

def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")

    logger.info("=" * 80)
    logger.info("Fixing Filing URLs for Curated Companies")
    logger.info("=" * 80)

    db = DatabaseAdapter(db_url)
    client = SECClient(user_agent="CMASB Filings Analyzer rgmarkey@gmail.com")

    # Query for these specific companies
    query = """
        SELECT
            c.company_name,
            f.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            f.sec_html_url as current_url
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE c.company_name = ANY(%(companies)s)
          AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
        ORDER BY f.filing_date
    """

    results = db.query(query, {"companies": CURATED_COMPANIES})

    if not results:
        logger.warning("No curated filings found!")
        return

    logger.info(f"Found {len(results)} curated company filings to fix")

    updated = 0
    failed = 0

    for i, r in enumerate(results, 1):
        company = r['company_name']
        cik = r['cik']
        accession = r['accession_number']

        logger.info(f"Processing {i}/{len(results)}: {company} - {accession}")

        try:
            # Get correct filing metadata from SEC
            filing_meta = client.get_filing_by_accession(cik, accession)

            if not filing_meta:
                logger.warning(f"  Could not retrieve filing metadata from SEC")
                failed += 1
                continue

            # Update database with correct URL
            update_query = """
                UPDATE filings
                SET
                    sec_html_url = %(url)s,
                    updated_at = now()
                WHERE accession_number = %(accession)s
            """

            db.execute(update_query, {
                "url": filing_meta.primary_doc_url,
                "accession": accession
            })

            logger.info(f"  ✓ Updated URL: {filing_meta.primary_doc_url}")
            updated += 1

        except Exception as e:
            logger.error(f"  ✗ Error: {e}")
            failed += 1
            continue

    logger.info("")
    logger.info("=" * 80)
    logger.info("✓ URL Fix Complete!")
    logger.info("=" * 80)
    logger.info(f"  Updated: {updated}")
    logger.info(f"  Failed: {failed}")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()
