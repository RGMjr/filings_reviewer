"""
Pytest fixtures for extraction pipeline integration tests.

Provides sample HTML fixtures, database setup, and pipeline configuration.
"""

import os

import pytest
from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

# Load environment
load_dotenv()


@pytest.fixture(scope="session")
def test_db_url():
    """Get test database URL from environment."""
    return os.getenv(
        "TEST_DATABASE_URL", "postgresql://dev:dev@localhost:5433/filings_analysis_test"
    )


@pytest.fixture(scope="session")
def test_db_adapter(test_db_url):
    """Create a database adapter for the test database."""
    return DatabaseAdapter(test_db_url)


@pytest.fixture(scope="function")
def clean_extraction_db(test_db_adapter):
    """
    Provide a clean database with extraction tables for each test.

    Truncates extraction-related tables and provides a company/filing for testing.
    """
    # Setup: truncate extraction tables
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")

            # Truncate extraction tables (in FK order)
            cur.execute("TRUNCATE TABLE filing_metric_incidence CASCADE")
            cur.execute("TRUNCATE TABLE metric_definitions CASCADE")
            cur.execute("TRUNCATE TABLE metric_values CASCADE")
            cur.execute("TRUNCATE TABLE source_segments CASCADE")
            cur.execute("TRUNCATE TABLE filings CASCADE")
            cur.execute("TRUNCATE TABLE companies CASCADE")

            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    yield test_db_adapter

    # Teardown
    with test_db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
            cur.execute("TRUNCATE TABLE filing_metric_incidence CASCADE")
            cur.execute("TRUNCATE TABLE metric_definitions CASCADE")
            cur.execute("TRUNCATE TABLE metric_values CASCADE")
            cur.execute("TRUNCATE TABLE source_segments CASCADE")
            cur.execute("TRUNCATE TABLE filings CASCADE")
            cur.execute("TRUNCATE TABLE companies CASCADE")
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.fixture
def sample_filing_html():
    """
    Sample S-1 filing HTML with customer metrics.

    Contains:
    - Monthly active users disclosure
    - Customer count with definition
    - Revenue by cohort table
    """
    return """
<!DOCTYPE html>
<html>
<head><title>FORM S-1 Registration Statement</title></head>
<body>
<div>
<h1>PROSPECTUS SUMMARY</h1>
<p>This summary highlights information contained elsewhere in this prospectus.</p>

<h2>Our Business</h2>
<p>We are a leading technology platform. As of December 31, 2023, we had
approximately 10.5 million monthly active users, representing a 25% increase
from the prior year. We acquired 500,000 new customers during fiscal year 2023.</p>

<h2>Key Business Metrics</h2>
<p>We define Monthly Active Users, or MAUs, as the number of unique users who
logged into our platform at least once in a given calendar month. We believe
MAUs is an important indicator of our user engagement and the overall health
of our business.</p>

<p>Our customer retention rate was 92% for the year ended December 31, 2023,
compared to 88% for the prior year. Net revenue retention was 115%.</p>

<h2>Revenue by Cohort</h2>
<table border="1">
<tr>
<th>Cohort</th>
<th>Year 1</th>
<th>Year 2</th>
<th>Year 3</th>
</tr>
<tr>
<td>2021 Cohort</td>
<td>$5.2M</td>
<td>$6.8M</td>
<td>$8.1M</td>
</tr>
<tr>
<td>2022 Cohort</td>
<td>$7.1M</td>
<td>$9.2M</td>
<td>-</td>
</tr>
<tr>
<td>2023 Cohort</td>
<td>$12.5M</td>
<td>-</td>
<td>-</td>
</tr>
</table>

<h2>Risk Factors</h2>
<p>Investing in our common stock involves a high degree of risk.</p>
</div>
</body>
</html>
"""


@pytest.fixture
def empty_filing_html():
    """Minimal HTML with no customer metrics."""
    return """
<!DOCTYPE html>
<html>
<head><title>FORM S-1</title></head>
<body>
<div>
<h1>LEGAL DISCLOSURES</h1>
<p>This is a legal notice with no customer metrics.</p>
</div>
</body>
</html>
"""


@pytest.fixture
def setup_test_filing(clean_extraction_db, sample_filing_html, tmp_path):
    """
    Set up a test company and filing with HTML file.

    Returns:
        dict with company_id, filing_id, and html_path
    """
    db = clean_extraction_db

    # Create test company
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, industry_code)
                VALUES ('0001234567', 'Test Corp', '7372')
                RETURNING company_id
                """
            )
            company_id = cur.fetchone()["company_id"]

    # Create HTML file
    html_path = tmp_path / "test_filing.htm"
    html_path.write_text(sample_filing_html)

    # Create test filing
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type,
                    filing_date, sec_html_url, html_storage_path
                )
                VALUES (
                    %(company_id)s, '0001234567', '0001234567-24-000001', 'S-1',
                    '2024-01-15', 'https://www.sec.gov/test/filing.htm', %(html_path)s
                )
                RETURNING filing_id
                """,
                {"company_id": company_id, "html_path": str(html_path)},
            )
            filing_id = cur.fetchone()["filing_id"]

    return {
        "company_id": company_id,
        "filing_id": filing_id,
        "html_path": str(html_path),
    }


@pytest.fixture
def setup_empty_filing(clean_extraction_db, empty_filing_html, tmp_path):
    """Set up a test filing with empty/minimal HTML."""
    db = clean_extraction_db

    # Create test company
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (cik, company_name, industry_code)
                VALUES ('0007654321', 'Empty Corp', '7372')
                RETURNING company_id
                """
            )
            company_id = cur.fetchone()["company_id"]

    # Create HTML file
    html_path = tmp_path / "empty_filing.htm"
    html_path.write_text(empty_filing_html)

    # Create test filing
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filings (
                    company_id, cik, accession_number, form_type,
                    filing_date, sec_html_url, html_storage_path
                )
                VALUES (
                    %(company_id)s, '0007654321', '0007654321-24-000001', 'S-1',
                    '2024-01-15', 'https://www.sec.gov/test/empty.htm', %(html_path)s
                )
                RETURNING filing_id
                """,
                {"company_id": company_id, "html_path": str(html_path)},
            )
            filing_id = cur.fetchone()["filing_id"]

    return {
        "company_id": company_id,
        "filing_id": filing_id,
        "html_path": str(html_path),
    }
