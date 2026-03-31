"""
Integration tests for V2 quality scoring: V2QualityScorer.score_filing()
and V2PersistenceAdapter.persist_quality_scores().

These tests require a running PostgreSQL database.
Set TEST_DATABASE_URL environment variable to run.

Example:
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \
        pytest tests/integration/extraction_v2/test_quality_scoring_integration.py -v
"""

from __future__ import annotations

import os
import uuid

import pytest

from src.extraction_v2.models import (
    ExtractionMethod,
    MetricDefinition,
    MetricFact,
    PeriodType,
    ReviewStatus,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.persistence import V2PersistenceAdapter
from src.extraction_v2.quality_scoring import V2QualityScorer
from src.infra.db import DatabaseAdapter

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------


def get_test_db_url() -> str | None:
    """Get test database URL from environment."""
    return os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def db_adapter() -> DatabaseAdapter:
    """Create database adapter for tests."""
    url = get_test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)


@pytest.fixture(scope="module")
def persistence_adapter(db_adapter: DatabaseAdapter) -> V2PersistenceAdapter:
    """Create persistence adapter for tests."""
    return V2PersistenceAdapter(db_adapter)


@pytest.fixture
def test_ids(db_adapter: DatabaseAdapter) -> dict[str, int]:
    """Create test company and filing, return dict with company_id and filing_id."""
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO companies (cik, company_name, ticker)
                VALUES ('8888888882', 'QS Test Company', 'QSTC')
                ON CONFLICT (cik) DO UPDATE SET company_name = EXCLUDED.company_name
                RETURNING company_id
            """)
            company_id = cur.fetchone()["company_id"]
            cur.execute(
                """INSERT INTO filings (company_id, cik, accession_number, form_type, filing_date, sec_html_url)
                VALUES (%(company_id)s, '8888888882', '8888888882-88-888882', 'S-1', '2026-01-01', 'https://www.sec.gov/test/filing2.htm')
                ON CONFLICT (company_id, accession_number) DO UPDATE SET form_type = EXCLUDED.form_type
                RETURNING filing_id""",
                {"company_id": company_id},
            )
            filing_id = cur.fetchone()["filing_id"]
    return {"company_id": company_id, "filing_id": filing_id}


# ---------------------------------------------------------------------------
# Function-scoped cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_quality_tables(db_adapter: DatabaseAdapter, test_ids: dict[str, int]) -> None:
    """Clean up filing_metric_incidence and v2_metric_definitions before and after each test."""
    filing_id = test_ids["filing_id"]

    def _cleanup() -> None:
        with db_adapter.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM filing_metric_incidence WHERE filing_id = %s",
                    (filing_id,),
                )
                cur.execute(
                    "DELETE FROM v2_metric_definitions WHERE doc_id = %s",
                    (filing_id,),
                )

    _cleanup()
    yield
    _cleanup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fact(
    metric_id: str = "cm_new_customers_acquired",
    value: float = 1000.0,
    **overrides: object,
) -> MetricFact:
    """Create a MetricFact with minimal required fields."""
    defaults: dict[str, object] = {
        "fact_id": str(uuid.uuid4()),
        "doc_id": "",
        "canonical_metric_id": metric_id,
        "value": value,
        "value_raw": str(value),
        "unit": Unit.COUNT,
        "period_type": PeriodType.ANNUAL,
        "source_type": SourceType.TEXT,
        "source_locator": SourceLocator(),
        "confidence": 0.8,
        "extraction_method": ExtractionMethod.EXACT_MATCH,
        "requires_review": False,
        "review_status": ReviewStatus.AUTO_ACCEPTED,
    }
    defaults.update(overrides)
    return MetricFact(**defaults)  # type: ignore[arg-type]


def make_definition(
    metric_id: str,
    alignment: str = "aligned",
    with_methodology: bool = False,
) -> MetricDefinition:
    """Create a MetricDefinition with standard test fields."""
    methodology = "Calculated as orders / active users." if with_methodology else ""
    return MetricDefinition(
        definition_id=str(uuid.uuid4()),
        canonical_metric_id=metric_id,
        definition_text="Customers who ordered during the period.",
        definition_text_normalized="Customers who ordered during the period.",
        methodology_text=methodology,
        methodology_text_normalized=methodology,
        alignment_flag=alignment,
    )


# ---------------------------------------------------------------------------
# TestQualityScoringPersistence
# ---------------------------------------------------------------------------


class TestQualityScoringPersistence:
    """Tests that call persist_quality_scores() directly."""

    def test_persist_basic_scores(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """Persist scores for a single fact and confirm a row is written."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        scorer = V2QualityScorer()
        fact = make_fact("cm_new_customers_acquired")
        scores = scorer.score_filing(filing_id, company_id, [fact], [], [])

        result = persistence_adapter.persist_quality_scores(scores, filing_id)
        assert result > 0

        with persistence_adapter._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM filing_metric_incidence WHERE filing_id = %s",
                    (filing_id,),
                )
                row = cur.fetchone()
        assert row["cnt"] > 0

    def test_persist_idempotent(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """Persisting the same scores twice yields the same row count (DELETE + INSERT)."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        scorer = V2QualityScorer()
        fact = make_fact("cm_new_customers_acquired")
        scores = scorer.score_filing(filing_id, company_id, [fact], [], [])

        persistence_adapter.persist_quality_scores(scores, filing_id)
        persistence_adapter.persist_quality_scores(scores, filing_id)

        with persistence_adapter._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM filing_metric_incidence WHERE filing_id = %s",
                    (filing_id,),
                )
                row = cur.fetchone()

        unique_metrics = len({s.metric_id for s in scores})
        assert row["cnt"] == unique_metrics

    def test_persist_empty_scores(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """Persisting an empty list returns 0 and writes no rows."""
        filing_id = test_ids["filing_id"]

        result = persistence_adapter.persist_quality_scores([], filing_id)
        assert result == 0

        with persistence_adapter._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM filing_metric_incidence WHERE filing_id = %s",
                    (filing_id,),
                )
                row = cur.fetchone()
        assert row["cnt"] == 0

    def test_persist_multiple_metrics(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """Persisting facts for 3 different metrics writes 3 rows."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        scorer = V2QualityScorer()
        facts = [
            make_fact("cm_new_customers_acquired", 500.0),
            make_fact("cm_customers_period_end", 2000.0),
            make_fact("cm_net_revenue_retention", 110.0),
        ]
        scores = scorer.score_filing(filing_id, company_id, facts, [], [])
        persistence_adapter.persist_quality_scores(scores, filing_id)

        with persistence_adapter._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM filing_metric_incidence WHERE filing_id = %s",
                    (filing_id,),
                )
                row = cur.fetchone()
        assert row["cnt"] == 3


# ---------------------------------------------------------------------------
# TestQualityScoringEndToEnd
# ---------------------------------------------------------------------------


class TestQualityScoringEndToEnd:
    """Tests that exercise scoring logic and optional persistence roundtrip."""

    def test_score_with_definitions(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """A fact + aligned definition with methodology yields high quality scores."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        fact = make_fact("cm_new_customers_acquired")
        defn = make_definition(
            "cm_new_customers_acquired", alignment="aligned", with_methodology=True
        )

        scorer = V2QualityScorer()
        scores = scorer.score_filing(filing_id, company_id, [fact], [defn], [])

        assert len(scores) == 1
        score = scores[0]
        assert score.quality_overall_score >= 2
        assert score.quality_definition_score >= 2
        assert score.quality_comparability_score == 3
        assert score.metric_disclosed_flag is True

    def test_score_without_definitions(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """A fact with no definition yields zero definition score and low overall."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        fact = make_fact("cm_new_customers_acquired")

        scorer = V2QualityScorer()
        scores = scorer.score_filing(filing_id, company_id, [fact], [], [])

        assert len(scores) == 1
        score = scores[0]
        assert score.quality_definition_score == 0
        assert score.quality_overall_score in (1, 2)

    def test_score_not_aligned_definition(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """A not_aligned definition yields comparability score of 1."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        fact = make_fact("cm_new_customers_acquired")
        defn = make_definition("cm_new_customers_acquired", alignment="not_aligned")

        scorer = V2QualityScorer()
        scores = scorer.score_filing(filing_id, company_id, [fact], [defn], [])

        assert len(scores) == 1
        assert scores[0].quality_comparability_score == 1

    def test_score_persist_roundtrip(
        self,
        persistence_adapter: V2PersistenceAdapter,
        test_ids: dict[str, int],
    ) -> None:
        """Score a filing, persist, then query DB to confirm all 5 score columns are non-null."""
        filing_id = test_ids["filing_id"]
        company_id = test_ids["company_id"]

        fact = make_fact("cm_new_customers_acquired")
        defn = make_definition(
            "cm_new_customers_acquired", alignment="aligned", with_methodology=True
        )

        scorer = V2QualityScorer()
        scores = scorer.score_filing(filing_id, company_id, [fact], [defn], [])
        persistence_adapter.persist_quality_scores(scores, filing_id)

        with persistence_adapter._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        quality_overall_score,
                        quality_definition_score,
                        quality_methodology_score,
                        quality_completeness_score,
                        quality_comparability_score
                    FROM filing_metric_incidence
                    WHERE filing_id = %s
                    """,
                    (filing_id,),
                )
                row = cur.fetchone()

        assert row is not None
        assert row["quality_overall_score"] is not None
        assert row["quality_definition_score"] is not None
        assert row["quality_methodology_score"] is not None
        assert row["quality_completeness_score"] is not None
        assert row["quality_comparability_score"] is not None
