#!/usr/bin/env python3
"""
Fix all filing URLs in the database by converting viewer URLs to directory URLs.

This updates all filings to use the new directory URL format that will be
resolved to actual document URLs at fetch time.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.infra.db import DatabaseAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")

    logger.info("=" * 80)
    logger.info("Fixing All Filing URLs in Database")
    logger.info("=" * 80)

    db = DatabaseAdapter(db_url)

    # Get count of filings with viewer URLs
    count_query = """
        SELECT COUNT(*) as count
        FROM filings
        WHERE sec_html_url LIKE '%%/cgi-bin/viewer%%'
    """

    result = db.query(count_query)
    viewer_url_count = result[0]['count'] if result else 0

    logger.info(f"Found {viewer_url_count:,} filings with viewer URLs to fix")

    if viewer_url_count == 0:
        logger.info("All URLs already in correct format!")
        return

    # Update all filings to use directory URL format
    # The directory URL format: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/
    # This will be resolved to the actual document URL at fetch time
    update_query = """
        UPDATE filings
        SET
            sec_html_url = 'https://www.sec.gov/Archives/edgar/data/' ||
                          cik || '/' ||
                          REPLACE(accession_number, '-', '') || '/',
            updated_at = now()
        WHERE sec_html_url LIKE '%%/cgi-bin/viewer%%'
    """

    logger.info("Updating URLs to directory format...")
    logger.info("  Pattern: https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/")

    try:
        db.execute(update_query)

        # Verify update
        verify_query = """
            SELECT COUNT(*) as count
            FROM filings
            WHERE sec_html_url LIKE '%%/Archives/edgar/data/%%/'
        """

        result = db.query(verify_query)
        updated_count = result[0]['count'] if result else 0

        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ URL Fix Complete!")
        logger.info("=" * 80)
        logger.info(f"  Updated: {viewer_url_count:,} filings")
        logger.info(f"  Verified: {updated_count:,} filings with directory URLs")
        logger.info("=" * 80)
        logger.info("")
        logger.info("All filing URLs now use directory format.")
        logger.info("The FilingFetcher will automatically resolve these to actual")
        logger.info("document URLs when fetching filings.")

    except Exception as e:
        logger.error(f"Error updating URLs: {e}")
        raise


if __name__ == "__main__":
    main()
