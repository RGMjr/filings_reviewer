#!/usr/bin/env python3
"""
Add specific fintech, healthcare, and e-commerce filings to the database.

For GR-17 task: Add gold standard labels for fintech, healthcare, and e-commerce filings.
"""

import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.universe.universe_builder import UniverseBuilder

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    """Add target companies to the database."""
    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://dev:dev@localhost:5433/filings_analysis")

    logger.info("=" * 80)
    logger.info("Adding Industry Filings for GR-17")
    logger.info("=" * 80)

    # Target companies for each industry
    targets = [
        # Fintech (priority: Stripe > Coinbase > Square)
        {"cik": "1512673", "name": "Square, Inc.", "industry": "fintech"},  # Already in curated list
        {"cik": "1679788", "name": "Coinbase Global, Inc.", "industry": "fintech"},

        # Healthcare tech (priority: Teladoc > Hims)
        {"cik": "1477449", "name": "Teladoc Health, Inc.", "industry": "healthcare"},
        {"cik": "1783398", "name": "Hims & Hers Health, Inc.", "industry": "healthcare"},

        # E-commerce (priority: Shopify > Etsy > DoorDash)
        {"cik": "1419612", "name": "Shopify Inc.", "industry": "ecommerce"},  # Already in curated list
        {"cik": "1370637", "name": "Etsy, Inc.", "industry": "ecommerce"},
        {"cik": "1792789", "name": "DoorDash, Inc.", "industry": "ecommerce"},
    ]

    db = DatabaseAdapter(db_url)

    # Check which companies are already in the database
    for target in targets:
        cik_padded = target["cik"].zfill(10)
        query = """
            SELECT c.company_id, c.company_name, c.cik
            FROM companies c
            WHERE c.cik = %(cik)s
        """
        results = db.query(query, {"cik": cik_padded})

        if results:
            logger.info(f"✓ {target['name']} ({target['industry']}) already in database")

            # Check for S-1/F-1 filings
            query = """
                SELECT f.filing_id, f.form_type, f.accession_number, f.filing_date
                FROM filings f
                WHERE f.cik = %(cik)s
                  AND f.form_type IN ('S-1', 'F-1')
                ORDER BY f.filing_date
                LIMIT 1
            """
            filings = db.query(query, {"cik": cik_padded})

            if filings:
                logger.info(f"  ✓ Has S-1/F-1: {filings[0]['form_type']} ({filings[0]['filing_date']})")
            else:
                logger.info(f"  ✗ No S-1/F-1 filings found")
        else:
            logger.info(f"✗ {target['name']} ({target['industry']}) NOT in database")

    logger.info("=" * 80)
    logger.info("To add missing companies:")
    logger.info("1. Add CIKs to UniverseBuilder's target list")
    logger.info("2. Run universe builder to fetch their filings")
    logger.info("3. Run fetch_curated_sample.py to download HTML")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
