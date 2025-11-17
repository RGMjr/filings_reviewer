#!/usr/bin/env python3
"""
Fix remaining filing URLs by parsing the filing directory index.
"""

import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from dotenv import load_dotenv
from src.infra.db import DatabaseAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

CURATED_COMPANIES = [
    'Square, Inc.',
    'Zoom Video Communications, Inc.',
    'Datadog, Inc.',
]

def get_primary_document_from_index(cik: str, accession_number: str, user_agent: str) -> str:
    """
    Parse the filing's index page to find the primary document filename.

    Args:
        cik: SEC Central Index Key
        accession_number: SEC accession number with dashes
        user_agent: User agent for SEC requests

    Returns:
        Primary document filename (e.g., 'd123456ds1.htm')
    """
    # Remove dashes from accession number for directory path
    accession_no_dashes = accession_number.replace('-', '')

    # Construct URL to filing directory index
    index_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcount&CIK={cik}&type=&dateb=&owner=exclude&count=100&accession={accession_number}"

    # Alternative: use the direct index.htm or index.json
    dir_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/index.json"

    try:
        session = requests.Session()
        session.headers.update({"User-Agent": user_agent})

        response = session.get(dir_url, timeout=10)
        response.raise_for_status()

        data = response.json()
        directory = data.get('directory', {})
        items = directory.get('item', [])

        # Look for the primary document (usually largest .htm file or named pattern)
        htm_files = [
            item for item in items
            if item['name'].endswith(('.htm', '.html'))
            and not item['name'].startswith('R')  # Exclude XBRL files starting with R
        ]

        if not htm_files:
            raise ValueError("No HTML files found in filing directory")

        # Find primary doc (usually matches form type in filename, like 's-1.htm' or 'd123456ds1.htm')
        for item in htm_files:
            name = item['name'].lower()
            # Common patterns: s-1.htm, slacks-1.htm, d123456ds1.htm, etc.
            if 's-1' in name or 'f-1' in name or 'ds1' in name:
                return item['name']

        # If no pattern match, return the first (and usually only) .htm file
        return htm_files[0]['name']

    except Exception as e:
        logger.error(f"Error fetching index: {e}")
        raise

def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    user_agent = "CMASB Filings Analyzer rgmarkey@gmail.com"

    logger.info("=" * 80)
    logger.info("Fixing Remaining Filing URLs (Square, Zoom, Datadog)")
    logger.info("=" * 80)

    db = DatabaseAdapter(db_url)

    # Query for remaining filings
    query = """
        SELECT
            c.company_name,
            f.cik,
            f.accession_number,
            f.form_type,
            f.sec_html_url as current_url
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE c.company_name = ANY(%(companies)s)
          AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
          AND f.sec_html_url LIKE '%%/cgi-bin/viewer%%'
        ORDER BY c.company_name, f.filing_date
    """

    results = db.query(query, {"companies": CURATED_COMPANIES})

    if not results:
        logger.info("No filings to fix - all URLs already updated!")
        return

    logger.info(f"Found {len(results)} filings to fix")

    updated = 0
    failed = 0

    for i, r in enumerate(results, 1):
        company = r['company_name']
        cik = r['cik']
        accession = r['accession_number']

        logger.info(f"Processing {i}/{len(results)}: {company} - {accession}")

        try:
            # Get primary document filename from index
            primary_doc = get_primary_document_from_index(cik, accession, user_agent)

            # Construct Archives URL
            accession_no_dashes = accession.replace('-', '')
            archives_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"

            # Update database
            update_query = """
                UPDATE filings
                SET
                    sec_html_url = %(url)s,
                    updated_at = now()
                WHERE accession_number = %(accession)s
            """

            db.execute(update_query, {
                "url": archives_url,
                "accession": accession
            })

            logger.info(f"  ✓ Updated URL: {archives_url}")
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
