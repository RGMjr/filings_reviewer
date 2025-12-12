"""
Pytest configuration and fixtures for performance tests.

Provides benchmark database setup and realistic test data for performance testing.
"""

import os
from typing import Dict, List

import pytest
from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

# Load environment
load_dotenv()


@pytest.fixture(scope="session")
def test_db_url():
    """
    Get test database URL from environment.

    Set TEST_DATABASE_URL environment variable to a test database.
    Default: postgresql://localhost/filings_analysis_test
    """
    return os.getenv(
        "TEST_DATABASE_URL", "postgresql://localhost/filings_analysis_test"
    )


@pytest.fixture(scope="session")
def test_db_adapter(test_db_url):
    """
    Create a database adapter for the test database.

    This is session-scoped, so one adapter is shared across all tests.
    """
    return DatabaseAdapter(test_db_url)


@pytest.fixture(scope="function")
def benchmark_db(test_db_adapter):
    """
    Provide a clean database for each benchmark test.

    This fixture:
    1. Truncates all tables before the test
    2. Yields the database adapter
    3. Truncates again after the test (cleanup)

    Usage:
        def test_benchmark(benchmark_db):
            # benchmark_db is a DatabaseAdapter with empty tables
            benchmark_db.upsert_company(...)
    """
    # Setup: truncate tables before test
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            # Disable foreign key checks temporarily
            cur.execute("SET CONSTRAINTS ALL DEFERRED")

            # Truncate in correct order (respecting foreign keys)
            # Review tables (if they exist)
            cur.execute(
                """
                DO $$
                BEGIN
                    TRUNCATE TABLE learned_patterns CASCADE;
                    TRUNCATE TABLE review_decisions CASCADE;
                    TRUNCATE TABLE review_candidates CASCADE;
                EXCEPTION WHEN undefined_table THEN
                    -- Tables don't exist yet, ignore
                    NULL;
                END $$;
                """
            )
            cur.execute("TRUNCATE TABLE filings CASCADE")
            cur.execute("TRUNCATE TABLE companies CASCADE")

            # Re-enable constraints
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    # Provide the adapter
    yield test_db_adapter

    # Teardown: truncate tables after test
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
            # Review tables (if they exist)
            cur.execute(
                """
                DO $$
                BEGIN
                    TRUNCATE TABLE learned_patterns CASCADE;
                    TRUNCATE TABLE review_decisions CASCADE;
                    TRUNCATE TABLE review_candidates CASCADE;
                EXCEPTION WHEN undefined_table THEN
                    -- Tables don't exist yet, ignore
                    NULL;
                END $$;
                """
            )
            cur.execute("TRUNCATE TABLE filings CASCADE")
            cur.execute("TRUNCATE TABLE companies CASCADE")
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


def _generate_realistic_segments(count: int, filing_id: int) -> List[Dict]:
    """
    Generate realistic segment data for performance testing.

    Args:
        count: Number of segments to generate
        filing_id: Filing ID to associate with segments

    Returns:
        List of segment dictionaries with realistic text containing
        numbers, metric keywords, and contextual information
    """
    # Template texts with various metric patterns
    templates = [
        "Our annual recurring revenue (ARR) was ${value} million for the year ended December 31, 2022.",
        "We had {value} active customers as of December 31, 2022, representing a {pct}% increase from the prior year.",
        "Total contract value (TCV) reached ${value} million in fiscal year 2022.",
        "Our net revenue retention rate was {pct}% for the year ended December 31, 2022.",
        "The Company serves {value} enterprise customers globally as of December 31, 2022.",
        "Dollar-based net retention was {pct}% for the twelve months ended December 31, 2022.",
        "We generated ${value} million in subscription revenue for the year.",
        "Our monthly active users (MAU) reached {value} million at year end.",
        "Average revenue per user (ARPU) was ${value} per month in 2022.",
        "Customer lifetime value (LTV) was estimated at ${value} thousand.",
        "The customer acquisition cost (CAC) was ${value} in fiscal 2022.",
        "Our gross retention rate was {pct}% for the year ended December 31, 2022.",
        "We had {value} paying customers using our premium tier.",
        "Total addressable market (TAM) is estimated at ${value} billion.",
        "Our serviceable addressable market (SAM) is approximately ${value} billion.",
        "We achieved a net promoter score (NPS) of {value} in our latest survey.",
        "Average contract value (ACV) was ${value} thousand in 2022.",
        "Our churn rate was {pct}% for the fiscal year.",
        "We had {value} daily active users (DAU) on average.",
        "Revenue from existing customers grew {pct}% year-over-year.",
    ]

    sections = [
        "Business Overview",
        "Our Customers",
        "Revenue Model",
        "Key Metrics",
        "Results of Operations",
        "Management Discussion and Analysis",
        "Financial Highlights",
        "Operating Metrics",
    ]

    segments = []
    for i in range(count):
        template = templates[i % len(templates)]
        section = sections[i % len(sections)]

        # Generate realistic values
        value = 10 + (i * 7) % 1000  # Values between 10-1000
        pct = 50 + (i * 3) % 50  # Percentages between 50-100

        text = template.format(value=value, pct=pct)

        segments.append(
            {
                "source_segment_id": i + 1,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": text,
                "section_heading": section,
                "section_path": f"/{section}",
            }
        )

    return segments


@pytest.fixture
def realistic_segments_100(benchmark_db):
    """
    Create realistic filing with 100 segments for performance testing.

    Returns:
        Dict with filing_id, company_id, and list of 100 realistic segments
    """
    # Create company
    company_id = benchmark_db.upsert_company(
        cik="0001111111",
        company_name="Benchmark Company 100",
    )

    # Create filing
    filing_id = benchmark_db.upsert_filing(
        company_id=company_id,
        cik="0001111111",
        accession_number="0001111111-23-000001",
        filing_date="2023-06-15",
        form_type="S-1",
        sec_html_url="https://benchmark.example.com/100",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )

    # Generate 100 realistic segments
    segments = _generate_realistic_segments(100, filing_id)

    return {
        "filing_id": filing_id,
        "company_id": company_id,
        "segments": segments,
    }


@pytest.fixture
def realistic_segments_500(benchmark_db):
    """
    Create realistic filing with 500 segments for performance testing.

    Returns:
        Dict with filing_id, company_id, and list of 500 realistic segments
    """
    # Create company
    company_id = benchmark_db.upsert_company(
        cik="0002222222",
        company_name="Benchmark Company 500",
    )

    # Create filing
    filing_id = benchmark_db.upsert_filing(
        company_id=company_id,
        cik="0002222222",
        accession_number="0002222222-23-000001",
        filing_date="2023-06-15",
        form_type="S-1",
        sec_html_url="https://benchmark.example.com/500",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )

    # Generate 500 realistic segments
    segments = _generate_realistic_segments(500, filing_id)

    return {
        "filing_id": filing_id,
        "company_id": company_id,
        "segments": segments,
    }
