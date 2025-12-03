"""
Pytest configuration and fixtures for integration tests.

Provides database setup/teardown and fixture loading utilities.
"""

import json
import os
from pathlib import Path
from typing import Dict

import pytest
from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata, MockSECClient

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
            cur.execute("TRUNCATE TABLE filings CASCADE")
            cur.execute("TRUNCATE TABLE companies CASCADE")
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


def load_fixture_metadata(fixture_name: str) -> Dict:
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


def metadata_to_filing_metadata(metadata: Dict) -> FilingMetadata:
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
