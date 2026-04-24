"""
Pytest configuration and fixtures for integration tests.

Provides database setup/teardown and fixture loading utilities.
"""

import json
import json as _json
import logging
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata, MockSECClient

# Make scripts/ importable for migration runner
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)

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


def create_test_v2_document(
    db: DatabaseAdapter,
    filing_id: int,
    **overrides,
) -> str:
    """
    Create a V2 document record and return doc_id (UUID string).

    The v2_documents table tracks filing-level processing metadata.
    """
    params: dict = {
        "filing_id": filing_id,
        "parse_version": "2.0.0",
        "status": "complete",
        "segment_count": 10,
        "table_count": 2,
        "image_count": 0,
        "fact_count": 1,
    }
    params.update(overrides)

    rows = db.query(
        """
        INSERT INTO v2_documents (filing_id, parse_version, status, segment_count, table_count, image_count, fact_count)
        VALUES (%(filing_id)s, %(parse_version)s, %(status)s, %(segment_count)s, %(table_count)s, %(image_count)s, %(fact_count)s)
        ON CONFLICT (filing_id) DO UPDATE SET status = EXCLUDED.status, updated_at = NOW()
        RETURNING doc_id::text
        """,
        params,
    )
    return rows[0]["doc_id"]


def create_test_v2_fact(
    db: DatabaseAdapter,
    filing_id: int,
    **overrides,
) -> str:
    """
    Create a V2 metric fact and return fact_id (UUID string).

    Note: doc_id in v2_metric_facts is a BIGINT FK to filings.filing_id.
    Uses cm_customers_period_end as default metric (seeded by 04_seed_metrics_taxonomy.sql).
    """
    params: dict = {
        "doc_id": filing_id,
        "canonical_metric_id": "cm_customers_period_end",
        "value": 10000,
        "value_raw": "10,000",
        "unit": "count",
        "currency": None,
        "period_type": "point_in_time",
        "period_start": "2023-01-01",
        "period_end": "2023-12-31",
        "source_type": "html_table",
        "source_locator": _json.dumps({"dom_locator": "/html/body/table[1]"}),
        "evidence_pack": _json.dumps(
            {"snippet_html": "<td>10,000</td>", "context_before": "We had"}
        ),
        "confidence": 0.85,
        "extraction_method": "exact_match",
        "requires_review": True,
        "review_status": "pending_review",
    }
    params.update(overrides)

    # Ensure JSONB fields are serialized if caller passed dicts
    if isinstance(params.get("source_locator"), dict):
        params["source_locator"] = _json.dumps(params["source_locator"])
    if isinstance(params.get("evidence_pack"), dict):
        params["evidence_pack"] = _json.dumps(params["evidence_pack"])

    rows = db.query(
        """
        INSERT INTO v2_metric_facts (
            doc_id, canonical_metric_id, value, value_raw, unit, currency,
            period_type, period_start, period_end, source_type, source_locator,
            evidence_pack, confidence, extraction_method, requires_review, review_status
        ) VALUES (
            %(doc_id)s, %(canonical_metric_id)s, %(value)s, %(value_raw)s, %(unit)s, %(currency)s,
            %(period_type)s, %(period_start)s, %(period_end)s, %(source_type)s, %(source_locator)s,
            %(evidence_pack)s, %(confidence)s, %(extraction_method)s, %(requires_review)s, %(review_status)s
        )
        RETURNING fact_id::text
        """,
        params,
    )
    return rows[0]["fact_id"]


def create_test_v2_decision(
    db: DatabaseAdapter,
    fact_id: str,
    decision: str = "accept",
    **overrides,
) -> str:
    """
    Create a V2 review decision and return decision_id (UUID string).

    The v2_review_decision_updates_fact trigger will update v2_metric_facts.review_status.
    """
    params: dict = {
        "fact_id": fact_id,
        "decision": decision,
        "assigned_metric_id": None,
        "corrected_value": None,
        "rejection_reason": None,
        "rejection_category": None,
        "reviewer_id": "test_reviewer",
        "reviewer_notes": None,
        "review_time_seconds": None,
    }
    params.update(overrides)

    rows = db.query(
        """
        INSERT INTO v2_review_decisions (
            fact_id, decision, assigned_metric_id, corrected_value,
            rejection_reason, rejection_category, reviewer_id, reviewer_notes, review_time_seconds
        ) VALUES (
            %(fact_id)s, %(decision)s, %(assigned_metric_id)s, %(corrected_value)s,
            %(rejection_reason)s, %(rejection_category)s, %(reviewer_id)s, %(reviewer_notes)s, %(review_time_seconds)s
        )
        RETURNING decision_id::text
        """,
        params,
    )
    return rows[0]["decision_id"]


# Load environment
load_dotenv()

# Paths
FIXTURES_DIR = Path(__file__).parent.parent.parent / "data" / "fixtures"


@pytest.fixture(scope="session")
def test_db_url(_isolate_xdist_worker_database):
    """
    Get test database URL from environment.

    Set TEST_DATABASE_URL environment variable to a test database.
    Default: postgresql://localhost/filings_analysis_test

    Depends on ``_isolate_xdist_worker_database`` so the per-worker URL
    rewrite is guaranteed to have happened before this fixture captures it.
    """
    return os.getenv("TEST_DATABASE_URL", "postgresql://localhost/filings_analysis_test")


@pytest.fixture(scope="session")
def test_db_adapter(test_db_url, _terminate_stale_connections):
    """
    Create a database adapter for the test database.

    This is session-scoped, so one adapter is shared across all tests.
    Uses a connection pool to avoid creating new TCP connections per operation.
    Depends on _terminate_stale_connections to ensure zombie connections are
    cleared before the pool is created (prevents deadlocks from stale locks).
    """
    from src.infra.pool import create_pool

    pool = create_pool(test_db_url, min_size=1, max_size=5)
    adapter = DatabaseAdapter(test_db_url, pool=pool)
    yield adapter
    adapter.close()


@pytest.fixture(scope="session", autouse=True)
def _isolate_xdist_worker_database():
    """Give each pytest-xdist worker its own Postgres DB so parallel test
    runs don't share state (TRUNCATEs, FK cascades, fixture seed rows).

    Rewrites ``os.environ["TEST_DATABASE_URL"]`` at session start so the
    fixture chain and the ~13 call-sites that read the env var directly
    both pick up the worker-specific URL. No-op in sequential mode
    (``PYTEST_XDIST_WORKER`` unset). DBs are left on disk between runs so
    the session migration apply stays cheap on repeat invocations.
    """
    base_url = os.getenv("TEST_DATABASE_URL")
    if not base_url:
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return

    from urllib.parse import urlparse, urlunparse

    import psycopg

    parsed = urlparse(base_url)
    base_db = parsed.path.lstrip("/")
    worker_db = f"{base_db}_{worker}"
    admin_url = urlunparse(parsed._replace(path="/postgres"))

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (worker_db,))
            if not cur.fetchone():
                try:
                    cur.execute(f'CREATE DATABASE "{worker_db}"')
                except psycopg.errors.DuplicateDatabase:
                    pass  # racing worker won the create — benign

    os.environ["TEST_DATABASE_URL"] = urlunparse(parsed._replace(path=f"/{worker_db}"))


@pytest.fixture(scope="session", autouse=True)
def _terminate_stale_connections(_isolate_xdist_worker_database):
    """Kill zombie connections from previous test runs to prevent deadlocks.

    Terminates connections that have been idle (or idle-in-transaction) for
    >5 seconds. The 'idle in transaction' state holds row-level locks that
    survive session boundaries and cause deadlocks in subsequent runs.
    The 5-second guard avoids killing connections from a concurrent pytest
    session that is actively mid-transaction (which would cause AdminShutdown
    errors in that session).
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return
    import psycopg

    try:
        conn = psycopg.connect(url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid != pg_backend_pid()
                  AND state IN ('idle', 'idle in transaction', 'idle in transaction (aborted)')
                  AND state_change < now() - interval '5 seconds'
            """)
        conn.close()
    except Exception:
        pass  # Best-effort; DB-unreachable tests will skip downstream


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations_to_test_db(_isolate_xdist_worker_database, _terminate_stale_connections):
    """Apply all migrations to test DB at session start (idempotent).

    Under pytest-xdist, multiple workers call this concurrently against
    their own per-worker DBs. Most migrations only touch per-DB catalogs
    and are safe to apply in parallel, but migration 37 creates/alters the
    cluster-level ``metabase_ro`` role and hits ``pg_authid`` — which races
    across workers as ``tuple concurrently updated``. Serialize apply with
    a cluster-wide advisory lock held on the ``postgres`` admin DB.
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return  # Skip if no test DB configured

    from urllib.parse import urlparse, urlunparse

    import psycopg

    from scripts.apply_migrations import MIGRATIONS, apply_migration, bootstrap_ledger

    # Lock key is arbitrary but must be stable across workers.
    MIGRATION_LOCK_KEY = 0x4949_7878_7800_0078  # "II xx ..." — Issue 78

    admin_url = urlunparse(urlparse(url)._replace(path="/postgres"))
    lock_conn = psycopg.connect(admin_url, autocommit=True)
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))

        import hashlib

        db = DatabaseAdapter(url)
        sql_dir = Path(__file__).parent.parent.parent / "sql"

        bootstrap_ledger(db)

        # Migrations intentionally edited after being applied to the test DB
        # (comment additions, hook-guard annotations — no schema-semantic change).
        # Drop stale ledger rows so the normal loop re-applies the current file.
        # All other checksum mismatches still raise as before.
        _CHECKSUM_REFRESH_ALLOWLIST = {"37_create_analytics_role.sql"}
        for _name in _CHECKSUM_REFRESH_ALLOWLIST:
            _sql_file = sql_dir / _name
            if not _sql_file.exists():
                continue
            _current_chk = hashlib.sha256(_sql_file.read_text().encode()).hexdigest()
            _rows = db.query(
                "SELECT checksum FROM schema_migrations WHERE id = %(id)s",
                {"id": _name},
            )
            if _rows and _rows[0]["checksum"] != _current_chk:
                with db.get_connection() as _conn:
                    with _conn.cursor() as _cur:
                        _cur.execute(
                            "DELETE FROM schema_migrations WHERE id = %(id)s",
                            {"id": _name},
                        )

        for migration_name in MIGRATIONS:
            sql_file = sql_dir / migration_name
            if sql_file.exists():
                try:
                    apply_migration(db, sql_dir, migration_name)
                except RuntimeError as exc:
                    test_url = os.getenv("TEST_DATABASE_URL", "")
                    if "Checksum mismatch" in str(exc) and url == test_url and test_url:
                        # Test DB only: drop stale ledger row and re-apply
                        # (test_url exact-match prevents accidental trigger on prod URLs)
                        with db.get_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "DELETE FROM schema_migrations WHERE id = %s",
                                    [migration_name],
                                )
                        logger.warning(
                            "Auto-recovered checksum drift for %s on test DB", migration_name
                        )
                        apply_migration(db, sql_dir, migration_name)
                    else:
                        raise
    finally:
        lock_conn.close()  # closing the session releases the advisory lock


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
                    TRUNCATE TABLE suppressed_candidates CASCADE;
                    TRUNCATE TABLE learned_patterns CASCADE;
                    TRUNCATE TABLE review_decisions CASCADE;
                    TRUNCATE TABLE review_candidates CASCADE;
                EXCEPTION WHEN undefined_table THEN
                    -- Tables don't exist yet, ignore
                    NULL;
                END $$;
                """
            )
            # V2 tables (if they exist)
            cur.execute(
                """
                DO $$
                BEGIN
                    TRUNCATE TABLE v2_review_decisions CASCADE;
                    TRUNCATE TABLE v2_metric_facts CASCADE;
                    TRUNCATE TABLE v2_metric_definitions CASCADE;
                    TRUNCATE TABLE v2_image_review_decisions CASCADE;
                    TRUNCATE TABLE v2_image_assets CASCADE;
                    TRUNCATE TABLE v2_table_cells CASCADE;
                    TRUNCATE TABLE v2_tables CASCADE;
                    TRUNCATE TABLE v2_segments CASCADE;
                    TRUNCATE TABLE v2_documents CASCADE;
                EXCEPTION WHEN undefined_table THEN
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
                    TRUNCATE TABLE suppressed_candidates CASCADE;
                    TRUNCATE TABLE learned_patterns CASCADE;
                    TRUNCATE TABLE review_decisions CASCADE;
                    TRUNCATE TABLE review_candidates CASCADE;
                EXCEPTION WHEN undefined_table THEN
                    -- Tables don't exist yet, ignore
                    NULL;
                END $$;
                """
            )
            # V2 tables (if they exist)
            cur.execute(
                """
                DO $$
                BEGIN
                    TRUNCATE TABLE v2_review_decisions CASCADE;
                    TRUNCATE TABLE v2_metric_facts CASCADE;
                    TRUNCATE TABLE v2_metric_definitions CASCADE;
                    TRUNCATE TABLE v2_image_review_decisions CASCADE;
                    TRUNCATE TABLE v2_image_assets CASCADE;
                    TRUNCATE TABLE v2_table_cells CASCADE;
                    TRUNCATE TABLE v2_tables CASCADE;
                    TRUNCATE TABLE v2_segments CASCADE;
                    TRUNCATE TABLE v2_documents CASCADE;
                EXCEPTION WHEN undefined_table THEN
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

    with open(json_path) as f:
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
    filing_metadata_list = [metadata_to_filing_metadata(fixture) for fixture in all_fixtures]

    return MockSECClient(mock_filings=filing_metadata_list)


# =============================================================================
# V2 Gold Standard Regression Test Fixtures
# =============================================================================

V2_BASELINE_PATH = (
    Path(__file__).parent.parent.parent / "data" / "gold_standard" / "v2_baseline.json"
)


@pytest.fixture(scope="module")
def v2_baseline_path():
    """Return the path to the V2 baseline metrics file."""
    return V2_BASELINE_PATH


@pytest.fixture(scope="module")
def v2_baseline_metrics(v2_baseline_path):
    """
    Load V2 baseline metrics from file.

    Returns None if baseline file doesn't exist (allows tests to skip gracefully).
    """
    from src.gold_standard.baseline import load_baseline

    if not v2_baseline_path.exists():
        return None

    return load_baseline(v2_baseline_path)


# =============================================================================
# Transcript Gold Standard Fixtures
# =============================================================================

_TRANSCRIPT_GS_DIR = Path(__file__).parent.parent.parent / "data" / "transcript_gold_standard"
_TRANSCRIPT_RESULTS_DIR = Path(__file__).parent.parent.parent / "data" / "spike_results"


@pytest.fixture(scope="session")
def transcript_split(request):
    """Return the transcript split selected via --transcript-split (default: tuning)."""
    return request.config.getoption("--transcript-split")


@pytest.fixture(scope="session")
def transcript_update_baseline(request):
    """Return True if --transcript-update-baseline flag was set."""
    return request.config.getoption("--transcript-update-baseline")


@pytest.fixture(scope="session")
def transcript_baseline_path(transcript_split):
    """Return the baseline JSON path for the selected split."""
    if transcript_split == "tuning":
        return _TRANSCRIPT_RESULTS_DIR / "transcript_baseline_tuning.json"
    if transcript_split == "test":
        return _TRANSCRIPT_RESULTS_DIR / "transcript_baseline_test.json"
    return _TRANSCRIPT_RESULTS_DIR / "transcript_baseline.json"


@pytest.fixture(scope="session")
def transcript_baseline(transcript_baseline_path):
    """
    Load the transcript extraction baseline JSON.

    Returns None if no baseline exists (first run before --transcript-update-baseline).
    """
    if not transcript_baseline_path.exists():
        return None
    try:
        return json.loads(transcript_baseline_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# =============================================================================
# V2 Parity Test Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def unified_report():
    """Run unified comparison across all gold standard companies."""
    from src.gold_standard.unified_comparison import UnifiedComparisonRunner

    runner = UnifiedComparisonRunner(skip_image_comparison=True)
    return runner.run()
