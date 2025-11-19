#!/usr/bin/env python3
"""
Download SEC filing fixtures on-demand.

This script downloads SEC filings from EDGAR when needed, rather than
storing them in Git. This keeps the repository size small.

Usage:
    # Download all fixtures from manifest
    python scripts/download_fixtures.py

    # Download specific filing
    python scripts/download_fixtures.py --cik 0001234567 --accession 0001234567-20-000001

    # Download from custom manifest
    python scripts/download_fixtures.py --manifest path/to/manifest.json

    # Clean/delete all downloaded fixtures
    python scripts/download_fixtures.py --clean
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_MANIFEST = Path("data/fixtures/filings_manifest.json")
FILINGS_DIR = Path("data/filings")
USER_AGENT = "CMASB Filings Analyzer rgmarkey@gmail.com"
SEC_EDGAR_BASE = "https://www.sec.gov/Archives/edgar/data"
RATE_LIMIT_DELAY = 0.11  # SEC allows ~10 requests/second


class FixtureDownloader:
    """Download SEC filings on-demand."""

    def __init__(self, user_agent: str = USER_AGENT):
        """
        Initialize downloader.

        Args:
            user_agent: User-Agent header for SEC requests
        """
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce rate limiting for SEC requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def construct_sec_url(self, cik: str, accession_number: str) -> str:
        """
        Construct SEC EDGAR URL for a filing.

        Args:
            cik: SEC Central Index Key (with leading zeros)
            accession_number: SEC accession number (with or without dashes)

        Returns:
            URL to primary HTML document
        """
        # Remove leading zeros from CIK for URL
        cik_numeric = str(int(cik))

        # Remove dashes from accession number
        accession_clean = accession_number.replace("-", "")

        # Try common primary document patterns
        # Pattern 1: accession-index.htm
        primary_doc = f"{accession_number}-index.htm"

        url = f"{SEC_EDGAR_BASE}/{cik_numeric}/{accession_clean}/{primary_doc}"
        return url

    def download_filing(
        self,
        cik: str,
        accession_number: str,
        force: bool = False
    ) -> Optional[Path]:
        """
        Download a single filing from SEC EDGAR.

        Args:
            cik: SEC Central Index Key
            accession_number: SEC accession number
            force: If True, re-download even if file exists

        Returns:
            Path to downloaded file, or None if failed
        """
        # Create storage directory
        accession_clean = accession_number.replace("-", "")
        storage_dir = FILINGS_DIR / cik / accession_clean
        output_file = storage_dir / "primary.htm"

        # Skip if already exists
        if output_file.exists() and not force:
            logger.debug(f"Already cached: {cik}/{accession_number}")
            return output_file

        storage_dir.mkdir(parents=True, exist_ok=True)

        # Construct URL
        url = self.construct_sec_url(cik, accession_number)

        # Download with rate limiting
        try:
            self._rate_limit()
            logger.info(f"Downloading: {cik}/{accession_number}")
            logger.debug(f"  URL: {url}")

            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            # Basic validation
            if len(response.text) < 1000:
                logger.warning(f"  File seems too small ({len(response.text)} bytes), might be an error page")

            # Save to disk
            output_file.write_text(response.text, encoding="utf-8")
            logger.info(f"  ✓ Saved to {output_file}")

            return output_file

        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logger.error(f"  ✗ Not found (404): {url}")
            else:
                logger.error(f"  ✗ HTTP error {e.response.status_code}: {url}")
            return None

        except Exception as e:
            logger.error(f"  ✗ Error downloading: {e}")
            return None

    def download_from_manifest(
        self,
        manifest_path: Path = DEFAULT_MANIFEST,
        max_downloads: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Download all filings listed in manifest.

        Args:
            manifest_path: Path to manifest JSON file
            max_downloads: Maximum number of filings to download (None = all)

        Returns:
            Statistics dict with counts
        """
        if not manifest_path.exists():
            logger.error(f"Manifest not found: {manifest_path}")
            return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

        # Load manifest
        with open(manifest_path) as f:
            manifest = json.load(f)

        logger.info(f"Loading manifest: {manifest_path}")
        logger.info(f"Found {len(manifest)} filings")

        if max_downloads:
            manifest = manifest[:max_downloads]
            logger.info(f"Limiting to {max_downloads} downloads")

        # Download each filing
        stats = {
            "total": len(manifest),
            "success": 0,
            "failed": 0,
            "skipped": 0
        }

        for i, filing in enumerate(manifest, 1):
            cik = filing["cik"]
            accession = filing["accession_number"]

            logger.info(f"[{i}/{len(manifest)}] Processing {cik}/{accession}")

            # Check if already exists
            accession_clean = accession.replace("-", "")
            output_file = FILINGS_DIR / cik / accession_clean / "primary.htm"

            if output_file.exists():
                logger.info(f"  Already cached, skipping")
                stats["skipped"] += 1
                continue

            # Download
            result = self.download_filing(cik, accession)

            if result:
                stats["success"] += 1
            else:
                stats["failed"] += 1

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("Download Summary")
        logger.info("=" * 60)
        logger.info(f"Total filings:        {stats['total']}")
        logger.info(f"Successfully downloaded: {stats['success']}")
        logger.info(f"Failed:               {stats['failed']}")
        logger.info(f"Already cached:       {stats['skipped']}")
        logger.info("=" * 60)

        return stats

    def clean_fixtures(self):
        """Remove all downloaded fixtures."""
        if not FILINGS_DIR.exists():
            logger.info("No filings directory to clean")
            return

        import shutil
        shutil.rmtree(FILINGS_DIR)
        logger.info(f"✓ Removed {FILINGS_DIR}")


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Download SEC filing fixtures on-demand",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download all fixtures from manifest
  python scripts/download_fixtures.py

  # Download specific filing
  python scripts/download_fixtures.py --cik 0001234567 --accession 0001234567-20-000001

  # Download first 10 from manifest (for testing)
  python scripts/download_fixtures.py --max 10

  # Clean all downloaded fixtures
  python scripts/download_fixtures.py --clean
        """
    )

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to filings manifest JSON file"
    )

    parser.add_argument(
        "--cik",
        help="Download specific CIK (requires --accession)"
    )

    parser.add_argument(
        "--accession",
        help="Download specific accession number (requires --cik)"
    )

    parser.add_argument(
        "--max",
        type=int,
        help="Maximum number of filings to download"
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove all downloaded fixtures"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if file exists"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create downloader
    downloader = FixtureDownloader()

    # Handle clean operation
    if args.clean:
        downloader.clean_fixtures()
        return 0

    # Handle specific filing download
    if args.cik and args.accession:
        result = downloader.download_filing(args.cik, args.accession, force=args.force)
        return 0 if result else 1

    # Handle manifest download
    if args.cik or args.accession:
        parser.error("Both --cik and --accession are required for specific filing download")
        return 1

    # Download from manifest
    stats = downloader.download_from_manifest(args.manifest, max_downloads=args.max)

    # Exit code based on results
    if stats["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
