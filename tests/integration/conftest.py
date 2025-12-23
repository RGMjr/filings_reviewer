"""
Pytest configuration and fixtures for integration tests.

Provides database setup/teardown and fixture loading utilities.
"""

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata, MockSECClient

# =============================================================================
# Test Data Helper Functions
# =============================================================================
# These helpers create test data with sensible defaults while allowing
# customization. They are designed to be composable - each higher-level
# helper can create its dependencies automatically if not provided.


def create_test_company(
    db: DatabaseAdapter,
    cik: str = "0001234567",
    company_name: str = "Test Corp",
    ticker: str | None = None,
    industry_code: str | None = None,
) -> int:
    """
    Create a test company and return company_id.

    Args:
        db: Database adapter instance
        cik: Company CIK (default: "0001234567")
        company_name: Company name (default: "Test Corp")
        ticker: Optional ticker symbol
        industry_code: Optional SIC industry code (e.g., "7372")

    Returns:
        company_id of the created company
    """
    return db.upsert_company(
        cik=cik, company_name=company_name, ticker=ticker, industry_code=industry_code
    )


def create_test_company_and_filing(
    db: DatabaseAdapter,
    company_id: int | None = None,
    cik: str = "0001234567",
    accession_number: str = "0001234567-24-000001",
    form_type: str = "S-1",
    filing_date: str = "2024-01-15",
    company_name: str = "Test Corp",
    industry_code: str | None = None,
) -> tuple[int, int]:
    """
    Create a test company and filing.

    Args:
        db: Database adapter instance
        company_id: Optional existing company_id (creates company if None)
        cik: Company CIK (default: "0001234567")
        accession_number: Filing accession number
        form_type: SEC form type (default: "S-1")
        filing_date: Filing date (default: "2024-01-15")
        company_name: Company name if creating new company
        industry_code: Optional SIC industry code (e.g., "7372")

    Returns:
        Tuple of (company_id, filing_id)
    """
    if company_id is None:
        company_id = create_test_company(
            db, cik=cik, company_name=company_name, industry_code=industry_code
        )

    filing_id = db.upsert_filing(
        company_id=company_id,
        cik=cik,
        accession_number=accession_number,
        form_type=form_type,
        filing_date=filing_date,
        sec_html_url=f"https://www.sec.gov/test/{accession_number}",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )
    return company_id, filing_id


def create_test_candidate(
    db: DatabaseAdapter,
    filing_id: int | None = None,
    company_id: int | None = None,
    char_position: int = 100,
    context_text: str = "We have 10,000 customers.",
    raw_number_text: str = "10,000",
    triggering_keyword: str = "customers",
    keyword_distance: int = 15,
    keyword_position: str = "after",
    suggested_metric_id: str | None = None,
) -> tuple[int, int, int]:
    """
    Create a test candidate (with company and filing if needed).

    Args:
        db: Database adapter instance
        filing_id: Optional existing filing_id (creates filing if None)
        company_id: Optional existing company_id (required if filing_id provided)
        char_position: Character position in segment (default: 100)
        context_text: Context text around the number
        raw_number_text: The raw number string found
        triggering_keyword: Keyword that triggered this candidate
        keyword_distance: Distance from number to keyword
        keyword_position: Position of keyword relative to number
        suggested_metric_id: Optional suggested metric classification

    Returns:
        Tuple of (company_id, filing_id, candidate_id)
    """
    if filing_id is None:
        company_id, filing_id = create_test_company_and_filing(db)

    candidate_id = db.insert_review_candidate(
        filing_id=filing_id,
        company_id=company_id,
        char_position=char_position,
        context_text=context_text,
        raw_number_text=raw_number_text,
        triggering_keyword=triggering_keyword,
        keyword_distance=keyword_distance,
        keyword_position=keyword_position,
        suggested_metric_id=suggested_metric_id,
    )
    return company_id, filing_id, candidate_id


def create_test_decision(
    db: DatabaseAdapter,
    candidate_id: int | None = None,
    decision: str = "accept",
    assigned_metric_id: str | None = "test_metric",
    rejection_reason: str | None = None,
    rejection_category: str | None = None,
    reviewer_id: str | None = None,
    review_time_seconds: int | None = None,
) -> tuple[int, int, int, int]:
    """
    Create a test review decision (with candidate, filing, company if needed).

    Args:
        db: Database adapter instance
        candidate_id: Optional existing candidate_id (creates candidate if None)
        decision: Decision type: 'accept', 'reject', or 'reclassify'
        assigned_metric_id: Metric ID for accept/reclassify decisions
        rejection_reason: Free-text rejection reason
        rejection_category: Category for rejection (e.g., 'wrong_metric', 'not_a_metric')
        reviewer_id: Identifier for the reviewer
        review_time_seconds: Time spent on decision

    Returns:
        Tuple of (company_id, filing_id, candidate_id, decision_id)
    """
    if candidate_id is None:
        company_id, filing_id, candidate_id = create_test_candidate(db)
    else:
        # Get company_id and filing_id from the candidate
        candidate = db.get_review_candidate(candidate_id)
        company_id = candidate["company_id"]
        filing_id = candidate["filing_id"]

    # For reject decisions, don't pass assigned_metric_id
    metric_id = None if decision == "reject" else assigned_metric_id

    decision_id = db.insert_review_decision(
        candidate_id=candidate_id,
        decision=decision,
        assigned_metric_id=metric_id,
        rejection_reason=rejection_reason,
        rejection_category=rejection_category,
        reviewer_id=reviewer_id,
        review_time_seconds=review_time_seconds,
    )
    return company_id, filing_id, candidate_id, decision_id


# Load environment
load_dotenv()

# Paths
FIXTURES_DIR = Path(__file__).parent.parent.parent / "data" / "fixtures"


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
def clean_db(test_db_adapter):
    """
    Provide a clean database for each test.

    This fixture:
    1. Truncates all tables before the test
    2. Yields the database adapter
    3. Truncates again after the test (cleanup)

    Usage:
        def test_something(clean_db):
            # clean_db is a DatabaseAdapter with empty tables
            clean_db.upsert_company(...)
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


def load_fixture_metadata(fixture_name: str) -> dict:
    """
    Load fixture metadata from JSON file.

    Args:
        fixture_name: Name of fixture (without .json extension)

    Returns:
        Dictionary with fixture metadata

    Raises:
        FileNotFoundError: If fixture doesn't exist
    """
    json_path = FIXTURES_DIR / f"{fixture_name}.json"

    if not json_path.exists():
        raise FileNotFoundError(f"Fixture not found: {json_path}")

    with open(json_path, "r") as f:
        return json.load(f)


def metadata_to_filing_metadata(metadata: dict) -> FilingMetadata:
    """
    Convert fixture metadata to FilingMetadata object.

    Args:
        metadata: Dictionary from load_fixture_metadata

    Returns:
        FilingMetadata object for use with MockSECClient
    """
    return FilingMetadata(
        cik=metadata["cik"],
        company_name=metadata["company_name"],
        form_type=metadata["form_type"],
        filing_date=metadata["filing_date"],
        accession_number=metadata["accession_number"],
        primary_doc_url=metadata["primary_doc_url"],
        ticker=metadata.get("ticker"),
    )


@pytest.fixture
def fixture_shopify():
    """Load Shopify S-1 fixture metadata."""
    return load_fixture_metadata("shopify_s1_2015")


@pytest.fixture
def fixture_datadog():
    """Load Datadog F-1 fixture metadata."""
    return load_fixture_metadata("datadog_f1_2019")


@pytest.fixture
def fixture_spac():
    """Load dMY SPAC fixture metadata."""
    return load_fixture_metadata("dmy_spac_2020")


@pytest.fixture
def all_fixtures():
    """
    Load all fixture metadata.

    Returns:
        List of fixture metadata dictionaries
    """
    return [
        load_fixture_metadata("shopify_s1_2015"),
        load_fixture_metadata("datadog_f1_2019"),
        load_fixture_metadata("dmy_spac_2020"),
    ]


@pytest.fixture
def mock_sec_client_with_fixtures(all_fixtures):
    """
    Create MockSECClient with all test fixtures loaded.

    Returns:
        MockSECClient configured with test fixtures
    """
    filing_metadata_list = [
        metadata_to_filing_metadata(fixture) for fixture in all_fixtures
    ]

    return MockSECClient(mock_filings=filing_metadata_list)


