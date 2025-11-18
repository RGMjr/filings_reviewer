"""
Download real SEC filings to use as test fixtures.

This script downloads specific S-1/F-1 filings from EDGAR and saves them locally
along with metadata for integration testing.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import requests

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# SEC requires User-Agent with company name and contact
USER_AGENT = "CMASB Filings Analyzer research@cmasb.org"

# Fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "data" / "fixtures"


# Define fixtures to download
FIXTURES = [
    {
        "name": "shopify_s1_2015",
        "cik": "0001419612",
        "company_name": "Shopify Inc.",
        "form_type": "S-1",
        "filing_date": "2015-04-14",
        "accession_number": "0001193125-15-140667",
        "ticker": "SHOP",
        "primary_doc": "d893971ds1.htm",
        "expected_classification": {
            "is_spac": False,
            "is_first_time_issuer": True,
            "offering_type": "primary",  # Will be uncertain without full text analysis
            "is_in_scope_phase1": True,
            "classification_method": "heuristic",
        },
        "notes": "Canonical example of tech SaaS IPO with excellent customer metrics disclosure",
    },
    {
        "name": "datadog_f1_2019",
        "cik": "0001561550",
        "company_name": "Datadog, Inc.",
        "form_type": "F-1",
        "filing_date": "2019-08-19",
        "accession_number": "0001193125-19-222862",
        "ticker": "DDOG",
        "primary_doc": "d735281df1.htm",
        "expected_classification": {
            "is_spac": False,
            "is_first_time_issuer": True,
            "offering_type": "primary",
            "is_in_scope_phase1": True,
            "classification_method": "heuristic",
        },
        "notes": "Foreign private issuer (F-1) with strong customer cohort disclosures",
    },
    {
        "name": "draft_kings_spac_2020",
        "cik": "0001772757",
        "company_name": "dMY Technology Group, Inc.",
        "form_type": "S-1",
        "filing_date": "2020-06-16",
        "accession_number": "0001193125-20-170226",
        "ticker": "DMYT",
        "primary_doc": "d917755ds1.htm",
        "expected_classification": {
            "is_spac": True,
            "is_first_time_issuer": True,
            "offering_type": None,  # SPACs excluded before offering type matters
            "is_in_scope_phase1": False,  # Excluded due to SPAC
            "classification_method": "heuristic",
        },
        "notes": "SPAC example - should be excluded from Phase 1 scope",
    },
]


def construct_edgar_url(cik: str, accession_number: str, primary_doc: str) -> str:
    """
    Construct the EDGAR URL for a filing.

    Args:
        cik: SEC Central Index Key (with leading zeros)
        accession_number: SEC accession number (format: 0000000000-00-000000)
        primary_doc: Primary document filename

    Returns:
        Full EDGAR URL
    """
    # Remove dashes from accession number for URL path
    accession_no_dashes = accession_number.replace("-", "")

    # Remove leading zeros from CIK for URL
    cik_no_zeros = str(int(cik))

    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/"
        f"{accession_no_dashes}/{primary_doc}"
    )

    return url


def download_filing(
    url: str, output_path: Path, rate_limit_delay: float = 0.11
) -> bool:
    """
    Download a filing from EDGAR.

    Args:
        url: URL to download
        output_path: Where to save the file
        rate_limit_delay: Delay between requests (SEC limit: 10/sec)

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Downloading: {url}")

    try:
        time.sleep(rate_limit_delay)  # Rate limiting

        response = requests.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()

        # Save to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        logger.info(f"Saved to: {output_path}")
        return True

    except requests.HTTPError as e:
        logger.error(f"HTTP error downloading {url}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        return False


def save_metadata(fixture: Dict, output_path: Path) -> None:
    """
    Save fixture metadata as JSON.

    Args:
        fixture: Fixture definition dict
        output_path: Where to save the metadata JSON
    """
    # Build metadata
    metadata = {
        "cik": fixture["cik"],
        "company_name": fixture["company_name"],
        "form_type": fixture["form_type"],
        "filing_date": fixture["filing_date"],
        "accession_number": fixture["accession_number"],
        "ticker": fixture["ticker"],
        "primary_doc_url": construct_edgar_url(
            fixture["cik"], fixture["accession_number"], fixture["primary_doc"]
        ),
        "expected_classification": fixture["expected_classification"],
        "notes": fixture["notes"],
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Saved metadata to: {output_path}")


def download_all_fixtures(force: bool = False) -> None:
    """
    Download all defined fixtures.

    Args:
        force: If True, re-download even if files exist
    """
    logger.info(f"Downloading {len(FIXTURES)} fixtures to {FIXTURES_DIR}")

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    success_count = 0
    skip_count = 0

    for fixture in FIXTURES:
        name = fixture["name"]
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {name}")
        logger.info(f"{'='*60}")

        # Output paths
        html_path = FIXTURES_DIR / f"{name}.html"
        json_path = FIXTURES_DIR / f"{name}.json"

        # Check if already exists
        if html_path.exists() and not force:
            logger.info(f"Fixture already exists: {html_path}")
            logger.info("Use --force to re-download")
            skip_count += 1

            # Still update metadata in case expected classifications changed
            save_metadata(fixture, json_path)
            continue

        # Construct URL
        url = construct_edgar_url(
            fixture["cik"], fixture["accession_number"], fixture["primary_doc"]
        )

        # Download
        success = download_filing(url, html_path)

        if success:
            # Save metadata
            save_metadata(fixture, json_path)
            success_count += 1
        else:
            logger.error(f"Failed to download: {name}")

    logger.info(f"\n{'='*60}")
    logger.info("Download Summary")
    logger.info(f"{'='*60}")
    logger.info(f"Successfully downloaded: {success_count}")
    logger.info(f"Skipped (already exist): {skip_count}")
    logger.info(f"Failed: {len(FIXTURES) - success_count - skip_count}")
    logger.info(f"Total fixtures: {len(FIXTURES)}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Download real SEC filings as test fixtures"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files already exist",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List fixtures without downloading",
    )

    args = parser.parse_args()

    if args.list:
        logger.info("Defined fixtures:")
        for fixture in FIXTURES:
            logger.info(f"\n{fixture['name']}:")
            logger.info(f"  Company: {fixture['company_name']}")
            logger.info(f"  Form: {fixture['form_type']}")
            logger.info(f"  Date: {fixture['filing_date']}")
            logger.info(f"  CIK: {fixture['cik']}")
            logger.info(
                f"  In scope: {fixture['expected_classification']['is_in_scope_phase1']}"
            )
        return

    download_all_fixtures(force=args.force)


if __name__ == "__main__":
    main()
