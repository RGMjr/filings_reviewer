"""
Example script demonstrating how to use UniverseBuilder.

This script shows how to:
1. Set up database connection
2. Initialize SEC client
3. Build the universe of filings
4. Get coverage statistics
"""

import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import SECClient, MockSECClient, FilingMetadata
from src.universe.universe_builder import UniverseBuilder

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def example_with_mock_data():
    """
    Example using mock SEC client with sample data.

    This is useful for testing without hitting the real SEC API.
    """
    logger.info("=== Example: Building universe with mock data ===")

    # 1. Set up database connection
    load_dotenv()
    db_connection_string = os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info(f"Connecting to database...")
    db = DatabaseAdapter(db_connection_string)

    # 2. Create sample filing data
    sample_filings = [
        FilingMetadata(
            cik="0001419612",
            company_name="Shopify Inc.",
            form_type="S-1",
            filing_date="2015-04-14",
            accession_number="0001193125-15-140667",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1419612/000119312515140667/d893971ds1.htm",
            ticker="SHOP",
        ),
        FilingMetadata(
            cik="0001561550",
            company_name="Datadog, Inc.",
            form_type="F-1",
            filing_date="2019-08-19",
            accession_number="0001193125-19-222862",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1561550/000119312519222862/d735281df1.htm",
            ticker="DDOG",
        ),
        FilingMetadata(
            cik="9999999",
            company_name="Example Acquisition Corp.",
            form_type="S-1",
            filing_date="2020-06-15",
            accession_number="0001234567-20-000001",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/9999999/000123456720000001/example-s1.htm",
            ticker="EXMPU",
        ),
    ]

    # 3. Initialize mock SEC client
    sec_client = MockSECClient(mock_filings=sample_filings)

    # 4. Initialize UniverseBuilder
    builder = UniverseBuilder(sec_client=sec_client, db=db)

    # 5. Build universe
    logger.info("Building universe...")
    in_scope_count = builder.build_universe(
        start_date="2015-01-01", end_date="2025-12-31"
    )

    logger.info(f"Universe build complete: {in_scope_count} in-scope filings")

    # 6. Get coverage stats
    logger.info("Getting coverage statistics...")
    stats = builder.get_coverage_stats()

    logger.info("Coverage Statistics:")
    logger.info(f"  Total companies: {stats['total_companies']}")
    logger.info(f"  Total filings: {stats['total_filings']}")
    logger.info(f"  In-scope filings: {stats['in_scope_filings']}")
    logger.info(f"  SPACs: {stats['spac_count']}")
    logger.info(f"  First-time issuers: {stats['first_time_issuer_count']}")
    logger.info(f"  By year: {stats['by_year']}")


def example_with_real_sec_api():
    """
    Example using real SEC API.

    Note: This requires a valid user agent and respects SEC rate limits.
    For production use, consider implementing more robust SEC querying
    using RSS feeds or bulk downloads.
    """
    logger.info("=== Example: Building universe with real SEC API ===")

    # 1. Set up database connection
    load_dotenv()
    db_connection_string = os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info(f"Connecting to database...")
    db = DatabaseAdapter(db_connection_string)

    # 2. Initialize SEC client with proper user agent
    # IMPORTANT: Replace with your company name and contact email
    user_agent = "CMASB Filings Analyzer contact@example.com"
    sec_client = SECClient(user_agent=user_agent)

    # 3. Initialize UniverseBuilder
    builder = UniverseBuilder(sec_client=sec_client, db=db)

    # 4. Build universe for a small date range
    # Note: The current SEC client implementation is simplified for v0.1
    # For production, implement using RSS feeds or bulk data
    logger.warning(
        "Current SEC client implementation is simplified. "
        "For production, use RSS feeds or bulk downloads."
    )

    logger.info("Building universe...")
    in_scope_count = builder.build_universe(
        start_date="2024-01-01", end_date="2024-01-31"
    )

    logger.info(f"Universe build complete: {in_scope_count} in-scope filings")

    # 5. Get coverage stats
    stats = builder.get_coverage_stats()
    logger.info("Coverage Statistics:")
    logger.info(f"  Total companies: {stats['total_companies']}")
    logger.info(f"  Total filings: {stats['total_filings']}")
    logger.info(f"  In-scope filings: {stats['in_scope_filings']}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Example script for UniverseBuilder"
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "real"],
        default="mock",
        help="Use mock data or real SEC API (default: mock)",
    )

    args = parser.parse_args()

    if args.mode == "mock":
        example_with_mock_data()
    else:
        example_with_real_sec_api()


if __name__ == "__main__":
    main()
