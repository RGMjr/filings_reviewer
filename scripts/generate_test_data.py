#!/usr/bin/env python3
"""
Generate synthetic test data for manual testing of the review interface.

Creates:
- Test companies
- Test filings
- Test source segments
- Test review candidates (using CandidateGenerator)

This script is for TESTING ONLY. Use generate_review_candidates.py for production data.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.review.candidate_generator import CandidateGenerator

logger = logging.getLogger(__name__)

# Sample text segments containing customer metrics
SAMPLE_SEGMENTS = [
    # Active Customers - Good example
    {
        "text": """As of December 31, 2023, we had approximately 125,000 active customers.
        We define an active customer as any customer who has made a transaction with us
        in the trailing 12-month period. Our active customer base has grown by 45%
        year-over-year, driven primarily by improvements in our go-to-market strategy.""",
        "section_name": "Business Overview",
        "segment_type": "paragraph",
    },
    # ARR - Good example
    {
        "text": """Annual Recurring Revenue (ARR) was $493 million as of December 31, 2023,
        up from $312 million in the prior year. We calculate ARR as the annualized value
        of all active subscription contracts at the end of the period, excluding one-time
        fees and professional services revenue.""",
        "section_name": "Business Metrics",
        "segment_type": "paragraph",
    },
    # NRR - Good example
    {
        "text": """Our net revenue retention rate was 118% for the year ended December 31, 2023.
        We define net revenue retention as the percentage change in revenue from our
        existing customer base, including expansion, contraction, and churn.""",
        "section_name": "Key Performance Indicators",
        "segment_type": "paragraph",
    },
    # CAC - Table format
    {
        "text": """
        | Metric | 2023 | 2022 |
        |--------|------|------|
        | Customer Acquisition Cost | $1,250 | $1,450 |
        | Average Contract Value | $15,000 | $12,000 |
        | Payback Period (months) | 10 | 14 |
        """,
        "section_name": "Operating Metrics",
        "segment_type": "table",
    },
    # Gross Margin - Good example
    {
        "text": """Our gross margin was 72% for the year ended December 31, 2023, compared to
        68% in the prior year. The improvement was primarily due to economies of scale
        in our infrastructure and improved pricing.""",
        "section_name": "Results of Operations",
        "segment_type": "paragraph",
    },
    # Churn Rate - Good example
    {
        "text": """Our monthly logo churn rate was 2.3% in 2023, down from 3.1% in 2022.
        We calculate logo churn as the number of customers who canceled their subscriptions
        divided by the total number of customers at the beginning of the period.""",
        "section_name": "Customer Metrics",
        "segment_type": "paragraph",
    },
    # LTV - Good example
    {
        "text": """We estimate our customer lifetime value at approximately $50,000 based on
        historical customer cohorts. This represents a 3:1 ratio to our customer acquisition
        cost of approximately $1,250.""",
        "section_name": "Unit Economics",
        "segment_type": "paragraph",
    },
    # False positive examples (for testing filtering)
    {
        "text": """Risk Factors: Our business is subject to numerous risks. As of December 31, 2023,
        we had 125 full-time employees. We operate in over 50 countries worldwide.
        Page 45 of this prospectus contains additional risk information.""",
        "section_name": "Risk Factors",
        "segment_type": "paragraph",
    },
    # Another false positive
    {
        "text": """See Note 15 to our consolidated financial statements for the year ended
        December 31, 2023, which begins on page F-12 of this prospectus.""",
        "section_name": "Notes",
        "segment_type": "paragraph",
    },
]

# Test companies
TEST_COMPANIES = [
    {
        "cik": "0001234567",
        "name": "CloudTech Solutions, Inc.",
        "ticker": "CLDT",
        "exchange": "NASDAQ",
        "sic_code": "7372",
        "sic_description": "Prepackaged Software",
    },
    {
        "cik": "0001234568",
        "name": "DataFlow Analytics, Inc.",
        "ticker": "DFLW",
        "exchange": "NYSE",
        "sic_code": "7373",
        "sic_description": "Computer Integrated Systems Design",
    },
    {
        "cik": "0001234569",
        "name": "NetworkHub Technologies, Inc.",
        "ticker": "NTWK",
        "exchange": "NASDAQ",
        "sic_code": "7374",
        "sic_description": "Computer Processing and Data Preparation",
    },
]


def create_test_companies(db: DatabaseAdapter) -> dict[str, int]:
    """
    Create test companies in the database.

    Returns:
        Dict mapping CIK to company_id
    """
    logger.info("Creating test companies...")
    cik_to_id = {}

    for company in TEST_COMPANIES:
        company_id = db.insert_company(
            cik=company["cik"],
            name=company["name"],
            ticker=company.get("ticker"),
            exchange=company.get("exchange"),
            sic_code=company.get("sic_code"),
            sic_description=company.get("sic_description"),
        )
        cik_to_id[company["cik"]] = company_id
        logger.info(f"  Created company: {company['name']} (CIK: {company['cik']}, ID: {company_id})")

    return cik_to_id


def create_test_filings(db: DatabaseAdapter, cik_to_id: dict[str, int]) -> list[int]:
    """
    Create test filings in the database.

    Args:
        cik_to_id: Mapping of CIK to company_id

    Returns:
        List of filing_ids
    """
    logger.info("Creating test filings...")
    filing_ids = []

    # Create 2 filings per company (6 total)
    for i, (cik, company_id) in enumerate(cik_to_id.items()):
        for filing_num in [1, 2]:
            accession = f"0001193125-23-{100000 + i * 10 + filing_num:06d}"
            filing_date = datetime(2023, 3 + i, filing_num * 15)

            filing_id = db.insert_filing(
                company_id=company_id,
                accession_number=accession,
                form_type="S-1",
                filing_date=filing_date,
                is_first_time_issuer=True,
                business_type="SaaS",
            )
            filing_ids.append(filing_id)
            logger.info(f"  Created filing: {accession} (ID: {filing_id})")

    return filing_ids


def create_test_segments(db: DatabaseAdapter, filing_ids: list[int]) -> dict[int, list[int]]:
    """
    Create test source segments for each filing.

    Args:
        filing_ids: List of filing IDs

    Returns:
        Dict mapping filing_id to list of segment_ids
    """
    logger.info("Creating test source segments...")
    filing_to_segments = {}

    for filing_id in filing_ids:
        segment_ids = []

        # Add a subset of sample segments to each filing
        # Use different segments for variety
        num_segments = min(len(SAMPLE_SEGMENTS), 5 + (filing_id % 3))
        segments_to_use = SAMPLE_SEGMENTS[:num_segments]

        for i, segment in enumerate(segments_to_use):
            segment_id = db.insert_source_segment(
                filing_id=filing_id,
                section_name=segment["section_name"],
                segment_type=segment["segment_type"],
                segment_text=segment["text"],
                char_position=i * 1000,  # Mock position
                word_count=len(segment["text"].split()),
            )
            segment_ids.append(segment_id)

        filing_to_segments[filing_id] = segment_ids
        logger.info(f"  Created {len(segment_ids)} segments for filing {filing_id}")

    return filing_to_segments


def generate_candidates(
    db: DatabaseAdapter,
    filing_ids: list[int],
    filing_to_segments: dict[int, list[int]]
) -> dict[int, int]:
    """
    Generate review candidates for each filing using CandidateGenerator.

    Args:
        db: Database adapter
        filing_ids: List of filing IDs
        filing_to_segments: Mapping of filing_id to segment_ids

    Returns:
        Dict mapping filing_id to number of candidates generated
    """
    logger.info("Generating review candidates using CandidateGenerator...")
    generator = CandidateGenerator()

    filing_to_count = {}

    for filing_id in filing_ids:
        segment_ids = filing_to_segments.get(filing_id, [])

        if not segment_ids:
            logger.warning(f"  No segments found for filing {filing_id}, skipping")
            continue

        # Get segments from database
        segments = []
        for segment_id in segment_ids:
            segment = db.get_source_segment(segment_id)
            if segment:
                segments.append(segment)

        if not segments:
            logger.warning(f"  Could not retrieve segments for filing {filing_id}, skipping")
            continue

        # Generate candidates
        try:
            candidates = generator.generate_candidates_from_segments(
                filing_id=filing_id,
                segments=segments
            )

            # Insert candidates into database
            candidate_count = 0
            for candidate in candidates:
                db.insert_review_candidate(
                    filing_id=candidate.filing_id,
                    company_id=candidate.company_id,
                    source_segment_id=candidate.source_segment_id,
                    char_position=candidate.char_position,
                    context_text=candidate.context_text,
                    raw_number_text=candidate.raw_number_text,
                    parsed_value=candidate.parsed_value,
                    parsed_unit=candidate.parsed_unit,
                    triggering_keyword=candidate.triggering_keyword,
                    keyword_distance=candidate.keyword_distance,
                    keyword_position=candidate.keyword_position,
                    suggested_metric_id=candidate.suggested_metric_id,
                    suggestion_confidence=candidate.suggestion_confidence,
                    features=candidate.features,
                )
                candidate_count += 1

            filing_to_count[filing_id] = candidate_count
            logger.info(f"  Generated {candidate_count} candidates for filing {filing_id}")

        except Exception as e:
            logger.error(f"  Error generating candidates for filing {filing_id}: {e}")
            filing_to_count[filing_id] = 0

    return filing_to_count


def main():
    """Generate test data for manual testing."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic test data for review interface testing"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="PostgreSQL connection URL (default: DATABASE_URL env var)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing review data before generating",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(level="INFO")

    # Load environment
    load_dotenv()

    # Get database URL
    import os
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set. Use --database-url or set DATABASE_URL env var")
        sys.exit(1)

    # Connect to database
    db = DatabaseAdapter(database_url)

    try:
        logger.info("=" * 60)
        logger.info("Generating Test Data for Review Interface")
        logger.info("=" * 60)

        if args.clear:
            logger.info("Clearing existing review data...")
            db.execute("DELETE FROM review_decisions")
            db.execute("DELETE FROM review_candidates")
            db.execute("DELETE FROM source_segments")
            db.execute("DELETE FROM filings")
            db.execute("DELETE FROM companies")
            logger.info("  Cleared existing data")

        # Step 1: Create companies
        cik_to_id = create_test_companies(db)

        # Step 2: Create filings
        filing_ids = create_test_filings(db, cik_to_id)

        # Step 3: Create segments
        filing_to_segments = create_test_segments(db, filing_ids)

        # Step 4: Generate candidates
        filing_to_count = generate_candidates(db, filing_ids, filing_to_segments)

        # Summary
        logger.info("=" * 60)
        logger.info("Test Data Generation Complete!")
        logger.info("=" * 60)
        logger.info(f"  Companies created: {len(cik_to_id)}")
        logger.info(f"  Filings created: {len(filing_ids)}")
        logger.info(f"  Total segments: {sum(len(segs) for segs in filing_to_segments.values())}")
        logger.info(f"  Total candidates: {sum(filing_to_count.values())}")
        logger.info("")
        logger.info("Candidate breakdown by filing:")
        for filing_id, count in filing_to_count.items():
            logger.info(f"  Filing {filing_id}: {count} candidates")
        logger.info("")
        logger.info("You can now test the review interface:")
        logger.info("  python scripts/run_dev_server.py")
        logger.info("  Open: http://127.0.0.1:5000/filings")

    except Exception as e:
        logger.error(f"Error generating test data: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
