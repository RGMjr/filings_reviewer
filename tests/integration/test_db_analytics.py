"""Integration tests for Phase-2 analytics helpers in DatabaseAdapter.

Covers:
- get_last_training_run
- get_recent_text_corrections
- get_recent_text_additions
- get_recent_image_additions
- get_recent_image_corrections

These helpers have unit tests (mocked db.query) but no integration tests
against a real Postgres instance. This file exercises the actual SQL to catch
JOIN issues, ORDER BY correctness, LIMIT enforcement, and NULL handling that
mocks miss.

Requires TEST_DATABASE_URL. Tests skip gracefully when it is not set
(the session-scoped fixtures resolve to no-ops and downstream tests do not
get a DatabaseAdapter).
"""

from __future__ import annotations

from src.infra.db import DatabaseAdapter
from tests.integration.conftest import (
    create_test_company_and_filing,
    create_test_v2_decision,
    create_test_v2_fact,
)

# ---------------------------------------------------------------------------
# Local seed helpers
# ---------------------------------------------------------------------------


def _insert_image_asset(
    db: DatabaseAdapter,
    filing_id: int,
    filename: str,
    *,
    classification: str = "chart",
    relevance_score: float = 0.8,
) -> str:
    """Insert a v2_image_assets row; return img_id as string."""
    rows = db.query(
        """
        INSERT INTO v2_image_assets
            (filing_id, filename, dom_locator, width, height,
             classification, relevance_score, review_status)
        VALUES
            (%(filing_id)s, %(filename)s, %(dom_locator)s, 600, 400,
             %(classification)s, %(relevance_score)s, 'pending')
        RETURNING img_id
        """,
        {
            "filing_id": filing_id,
            "filename": filename,
            "dom_locator": f"body > img[src='{filename}']",
            "classification": classification,
            "relevance_score": relevance_score,
        },
    )
    return str(rows[0]["img_id"])


def _insert_image_confirmation(
    db: DatabaseAdapter,
    img_id: str,
    *,
    decision: str,
    detected_metric_id: str | None = None,
    confirmed_metric_id: str | None = None,
    rejection_reason: str | None = None,
    reviewer_id: str = "test_reviewer",
) -> str:
    """Insert a v2_image_metric_confirmations row; return id as string."""
    rows = db.query(
        """
        INSERT INTO v2_image_metric_confirmations
            (img_id, detected_metric_id, confirmed_metric_id,
             decision, rejection_reason, reviewer_id)
        VALUES
            (%(img_id)s, %(detected_metric_id)s, %(confirmed_metric_id)s,
             %(decision)s, %(rejection_reason)s, %(reviewer_id)s)
        RETURNING id
        """,
        {
            "img_id": img_id,
            "detected_metric_id": detected_metric_id,
            "confirmed_metric_id": confirmed_metric_id,
            "decision": decision,
            "rejection_reason": rejection_reason,
            "reviewer_id": reviewer_id,
        },
    )
    return str(rows[0]["id"])


def _insert_training_run(
    db: DatabaseAdapter,
    *,
    model_type: str = "image_relevance",
    status: str = "succeeded",
    num_training_rows: int | None = 100,
    num_positive_rows: int | None = 40,
    model_path: str | None = "models/image_relevance/test-run/relevance_model.joblib",
    report_path: str | None = None,
    triggered_by: str | None = "test",
) -> str:
    """Insert a model_training_runs row; return id as string."""
    rows = db.query(
        """
        INSERT INTO model_training_runs
            (model_type, status, started_at, completed_at,
             num_training_rows, num_positive_rows,
             model_path, report_path, triggered_by)
        VALUES
            (%(model_type)s, %(status)s,
             NOW() - INTERVAL '10 minutes', NOW(),
             %(num_training_rows)s, %(num_positive_rows)s,
             %(model_path)s, %(report_path)s, %(triggered_by)s)
        RETURNING id
        """,
        {
            "model_type": model_type,
            "status": status,
            "num_training_rows": num_training_rows,
            "num_positive_rows": num_positive_rows,
            "model_path": model_path,
            "report_path": report_path,
            "triggered_by": triggered_by,
        },
    )
    return str(rows[0]["id"])


# ---------------------------------------------------------------------------
# Tests: get_last_training_run
# ---------------------------------------------------------------------------


class TestGetLastTrainingRun:
    """Tests for get_last_training_run.

    model_training_runs is not included in the clean_db truncate set, so each
    test truncates the table explicitly at setup to prevent cross-test bleed.
    """

    def _reset(self, db: DatabaseAdapter) -> None:
        """Truncate model_training_runs before the assertions in each test."""
        db.execute("TRUNCATE TABLE model_training_runs")

    def test_empty_db_returns_none(self, clean_db: DatabaseAdapter) -> None:
        """No training runs → None."""
        self._reset(clean_db)
        result = clean_db.get_last_training_run("image_relevance")
        assert result is None

    def test_unknown_model_type_returns_none(self, clean_db: DatabaseAdapter) -> None:
        """Runs for a different model_type are not returned."""
        self._reset(clean_db)
        _insert_training_run(clean_db, model_type="image_relevance")
        result = clean_db.get_last_training_run("text_relevance")
        assert result is None

    def test_failed_run_not_returned(self, clean_db: DatabaseAdapter) -> None:
        """Only 'succeeded' rows are returned; failed/running are excluded."""
        self._reset(clean_db)
        _insert_training_run(clean_db, status="failed")
        _insert_training_run(clean_db, status="running")
        result = clean_db.get_last_training_run("image_relevance")
        assert result is None

    def test_happy_path_returns_latest(self, clean_db: DatabaseAdapter) -> None:
        """Returns the most-recent succeeded run with all expected keys."""
        self._reset(clean_db)
        run_id = _insert_training_run(
            clean_db,
            model_type="image_relevance",
            num_training_rows=200,
            num_positive_rows=80,
            triggered_by="ci",
        )
        result = clean_db.get_last_training_run("image_relevance")
        assert result is not None
        assert str(result["id"]) == run_id
        assert result["model_type"] == "image_relevance"
        assert result["status"] == "succeeded"
        assert result["num_training_rows"] == 200
        assert result["num_positive_rows"] == 80
        assert result["triggered_by"] == "ci"
        # All expected keys present
        for key in (
            "id",
            "model_type",
            "started_at",
            "completed_at",
            "status",
            "num_training_rows",
            "num_positive_rows",
            "model_path",
            "report_path",
            "triggered_by",
        ):
            assert key in result

    def test_returns_most_recent_when_multiple_runs(self, clean_db: DatabaseAdapter) -> None:
        """When multiple succeeded runs exist, the latest completed_at wins."""
        self._reset(clean_db)
        _insert_training_run(clean_db, triggered_by="first")
        latest_id = _insert_training_run(clean_db, triggered_by="second")
        result = clean_db.get_last_training_run("image_relevance")
        assert result is not None
        assert str(result["id"]) == latest_id
        assert result["triggered_by"] == "second"

    def test_nullable_columns_allowed(self, clean_db: DatabaseAdapter) -> None:
        """model_path and report_path may be NULL; helper must not crash."""
        self._reset(clean_db)
        _insert_training_run(clean_db, model_path=None, report_path=None, num_training_rows=None)
        result = clean_db.get_last_training_run("image_relevance")
        assert result is not None
        assert result["model_path"] is None
        assert result["report_path"] is None
        assert result["num_training_rows"] is None


# ---------------------------------------------------------------------------
# Tests: get_recent_text_corrections
# ---------------------------------------------------------------------------


class TestGetRecentTextCorrections:
    def test_empty_db_returns_empty_list(self, clean_db: DatabaseAdapter) -> None:
        assert clean_db.get_recent_text_corrections() == []

    def test_accept_decision_not_returned(self, clean_db: DatabaseAdapter) -> None:
        """Only 'correct' decisions are returned; accepts are excluded."""
        _, filing_id = create_test_company_and_filing(clean_db)
        fact_id = create_test_v2_fact(clean_db, filing_id)
        create_test_v2_decision(clean_db, fact_id, decision="accept")
        assert clean_db.get_recent_text_corrections() == []

    def test_happy_path_returns_correction(self, clean_db: DatabaseAdapter) -> None:
        """A 'correct' decision is returned with joined filing/company context."""
        _, filing_id = create_test_company_and_filing(
            clean_db, cik="0001111111", company_name="Corrections Corp"
        )
        fact_id = create_test_v2_fact(clean_db, filing_id)
        create_test_v2_decision(
            clean_db,
            fact_id,
            decision="correct",
            assigned_metric_id="cm_net_revenue_retention",
            corrected_value=95.5,
            reviewer_id="reviewer_a",
        )

        rows = clean_db.get_recent_text_corrections()
        assert len(rows) == 1
        row = rows[0]
        assert row["corrected_metric_id"] == "cm_net_revenue_retention"
        assert row["original_metric_id"] == "cm_customers_period_end"
        assert row["company_name"] == "Corrections Corp"
        assert row["cik"] == "0001111111"
        assert row["filing_id"] == filing_id
        # Nullable fields should be present in dict
        assert "reviewer_notes" in row
        assert "original_value_raw" in row

    def test_limit_honored(self, clean_db: DatabaseAdapter) -> None:
        """LIMIT parameter is respected."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0001222222")
        for i in range(5):
            fact_id = create_test_v2_fact(
                clean_db,
                filing_id,
                period_start=f"2023-0{i + 1}-01",
                period_end=f"2023-0{i + 1}-28",
            )
            create_test_v2_decision(clean_db, fact_id, decision="correct")

        rows = clean_db.get_recent_text_corrections(limit=3)
        assert len(rows) == 3

    def test_order_by_desc(self, clean_db: DatabaseAdapter) -> None:
        """Results are ordered most-recent first (created_at DESC)."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0001333333")
        ids = []
        for i in range(3):
            fact_id = create_test_v2_fact(
                clean_db,
                filing_id,
                period_start=f"2023-0{i + 1}-01",
                period_end=f"2023-0{i + 1}-28",
            )
            dec_id = create_test_v2_decision(clean_db, fact_id, decision="correct")
            ids.append(dec_id)

        rows = clean_db.get_recent_text_corrections(limit=10)
        assert len(rows) == 3
        # Most recent decision was inserted last — its created_at is largest
        returned_ts = [row["created_at"] for row in rows]
        assert returned_ts == sorted(returned_ts, reverse=True)


# ---------------------------------------------------------------------------
# Tests: get_recent_text_additions
# ---------------------------------------------------------------------------


class TestGetRecentTextAdditions:
    def test_empty_db_returns_empty_list(self, clean_db: DatabaseAdapter) -> None:
        assert clean_db.get_recent_text_additions() == []

    def test_non_manual_fact_not_returned(self, clean_db: DatabaseAdapter) -> None:
        """Facts extracted via 'exact_match' (not 'manual') are excluded."""
        _, filing_id = create_test_company_and_filing(clean_db)
        create_test_v2_fact(clean_db, filing_id, extraction_method="exact_match")
        assert clean_db.get_recent_text_additions() == []

    def test_happy_path_returns_manual_fact(self, clean_db: DatabaseAdapter) -> None:
        """A manually-added fact is returned with joined filing/company context."""
        _, filing_id = create_test_company_and_filing(
            clean_db, cik="0002111111", company_name="Manual Entry Co"
        )
        create_test_v2_fact(
            clean_db,
            filing_id,
            extraction_method="manual",
            canonical_metric_id="cm_net_revenue_retention",
            value_raw="120%",
        )

        rows = clean_db.get_recent_text_additions()
        assert len(rows) == 1
        row = rows[0]
        assert row["canonical_metric_id"] == "cm_net_revenue_retention"
        assert row["value_raw"] == "120%"
        assert row["company_name"] == "Manual Entry Co"
        assert row["cik"] == "0002111111"
        assert row["filing_id"] == filing_id
        assert "unit" in row
        assert "review_reason" in row

    def test_limit_honored(self, clean_db: DatabaseAdapter) -> None:
        """LIMIT parameter is respected."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0002222222")
        for i in range(5):
            create_test_v2_fact(
                clean_db,
                filing_id,
                extraction_method="manual",
                period_start=f"2023-0{i + 1}-01",
                period_end=f"2023-0{i + 1}-28",
            )

        rows = clean_db.get_recent_text_additions(limit=2)
        assert len(rows) == 2

    def test_order_by_desc(self, clean_db: DatabaseAdapter) -> None:
        """Results are ordered most-recent first (created_at DESC)."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0002333333")
        for i in range(3):
            create_test_v2_fact(
                clean_db,
                filing_id,
                extraction_method="manual",
                period_start=f"2023-0{i + 1}-01",
                period_end=f"2023-0{i + 1}-28",
            )

        rows = clean_db.get_recent_text_additions(limit=10)
        assert len(rows) == 3
        returned_ts = [row["created_at"] for row in rows]
        assert returned_ts == sorted(returned_ts, reverse=True)


# ---------------------------------------------------------------------------
# Tests: get_recent_image_additions
# ---------------------------------------------------------------------------


class TestGetRecentImageAdditions:
    def test_empty_db_returns_empty_list(self, clean_db: DatabaseAdapter) -> None:
        assert clean_db.get_recent_image_additions() == []

    def test_non_add_decision_not_returned(self, clean_db: DatabaseAdapter) -> None:
        """Only 'add' decisions are returned; accept/correct/reject excluded."""
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image_asset(clean_db, filing_id, "img_a.jpg")
        _insert_image_confirmation(
            clean_db,
            img_id,
            decision="accept",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_customers_period_end",
        )
        assert clean_db.get_recent_image_additions() == []

    def test_happy_path_returns_add_decision(self, clean_db: DatabaseAdapter) -> None:
        """An 'add' confirmation returns with joined filing/company context."""
        _, filing_id = create_test_company_and_filing(
            clean_db, cik="0003111111", company_name="Image Additions Inc"
        )
        img_id = _insert_image_asset(clean_db, filing_id, "chart_add.png")
        conf_id = _insert_image_confirmation(
            clean_db,
            img_id,
            decision="add",
            confirmed_metric_id="cm_net_revenue_retention",
            reviewer_id="rev_x",
        )

        rows = clean_db.get_recent_image_additions()
        assert len(rows) == 1
        row = rows[0]
        assert str(row["confirmation_id"]) == conf_id
        assert str(row["img_id"]) == img_id
        assert row["confirmed_metric_id"] == "cm_net_revenue_retention"
        assert row["reviewer_id"] == "rev_x"
        assert row["filing_id"] == filing_id
        assert row["company_name"] == "Image Additions Inc"
        assert row["cik"] == "0003111111"

    def test_limit_honored(self, clean_db: DatabaseAdapter) -> None:
        """LIMIT parameter is respected."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0003222222")
        for i in range(5):
            img_id = _insert_image_asset(clean_db, filing_id, f"add_{i}.png")
            _insert_image_confirmation(
                clean_db,
                img_id,
                decision="add",
                confirmed_metric_id="cm_customers_period_end",
                reviewer_id=f"rev_{i}",
            )

        rows = clean_db.get_recent_image_additions(limit=3)
        assert len(rows) == 3

    def test_order_by_desc(self, clean_db: DatabaseAdapter) -> None:
        """Results are ordered most-recent first (created_at DESC)."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0003333333")
        for i in range(3):
            img_id = _insert_image_asset(clean_db, filing_id, f"add_order_{i}.png")
            _insert_image_confirmation(
                clean_db,
                img_id,
                decision="add",
                confirmed_metric_id="cm_customers_period_end",
                reviewer_id=f"rev_{i}",
            )

        rows = clean_db.get_recent_image_additions(limit=10)
        assert len(rows) == 3
        returned_ts = [row["created_at"] for row in rows]
        assert returned_ts == sorted(returned_ts, reverse=True)


# ---------------------------------------------------------------------------
# Tests: get_recent_image_corrections
# ---------------------------------------------------------------------------


class TestGetRecentImageCorrections:
    def test_empty_db_returns_empty_list(self, clean_db: DatabaseAdapter) -> None:
        assert clean_db.get_recent_image_corrections() == []

    def test_accept_decision_not_returned(self, clean_db: DatabaseAdapter) -> None:
        """Only 'correct' decisions are returned; accept/add/reject excluded."""
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_image_asset(clean_db, filing_id, "img_b.jpg")
        _insert_image_confirmation(
            clean_db,
            img_id,
            decision="accept",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_customers_period_end",
        )
        assert clean_db.get_recent_image_corrections() == []

    def test_happy_path_returns_correction(self, clean_db: DatabaseAdapter) -> None:
        """A 'correct' confirmation returns both detected and confirmed metric ids."""
        _, filing_id = create_test_company_and_filing(
            clean_db, cik="0004111111", company_name="Image Corrections LLC"
        )
        img_id = _insert_image_asset(clean_db, filing_id, "chart_correct.png")
        conf_id = _insert_image_confirmation(
            clean_db,
            img_id,
            decision="correct",
            detected_metric_id="cm_customers_period_end",
            confirmed_metric_id="cm_net_revenue_retention",
            reviewer_id="rev_y",
        )

        rows = clean_db.get_recent_image_corrections()
        assert len(rows) == 1
        row = rows[0]
        assert str(row["confirmation_id"]) == conf_id
        assert str(row["img_id"]) == img_id
        assert row["detected_metric_id"] == "cm_customers_period_end"
        assert row["confirmed_metric_id"] == "cm_net_revenue_retention"
        assert row["reviewer_id"] == "rev_y"
        assert row["filing_id"] == filing_id
        assert row["company_name"] == "Image Corrections LLC"
        assert row["cik"] == "0004111111"

    def test_null_detected_metric_allowed(self, clean_db: DatabaseAdapter) -> None:
        """detected_metric_id may be NULL on a 'correct' row; helper must not crash."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0004222222")
        img_id = _insert_image_asset(clean_db, filing_id, "chart_null_detected.png")
        # The unique index allows this because COALESCE falls back to confirmed_metric_id
        _insert_image_confirmation(
            clean_db,
            img_id,
            decision="correct",
            detected_metric_id=None,
            confirmed_metric_id="cm_net_revenue_retention",
            reviewer_id="rev_null",
        )

        rows = clean_db.get_recent_image_corrections()
        assert len(rows) == 1
        assert rows[0]["detected_metric_id"] is None
        assert rows[0]["confirmed_metric_id"] == "cm_net_revenue_retention"

    def test_limit_honored(self, clean_db: DatabaseAdapter) -> None:
        """LIMIT parameter is respected."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0004333333")
        for i in range(5):
            img_id = _insert_image_asset(clean_db, filing_id, f"correct_{i}.png")
            _insert_image_confirmation(
                clean_db,
                img_id,
                decision="correct",
                detected_metric_id=f"cm_metric_{i}",
                confirmed_metric_id="cm_net_revenue_retention",
                reviewer_id=f"rev_{i}",
            )

        rows = clean_db.get_recent_image_corrections(limit=2)
        assert len(rows) == 2

    def test_order_by_desc(self, clean_db: DatabaseAdapter) -> None:
        """Results are ordered most-recent first (created_at DESC)."""
        _, filing_id = create_test_company_and_filing(clean_db, cik="0004444444")
        for i in range(3):
            img_id = _insert_image_asset(clean_db, filing_id, f"correct_order_{i}.png")
            _insert_image_confirmation(
                clean_db,
                img_id,
                decision="correct",
                detected_metric_id=f"cm_metric_order_{i}",
                confirmed_metric_id="cm_net_revenue_retention",
                reviewer_id=f"rev_{i}",
            )

        rows = clean_db.get_recent_image_corrections(limit=10)
        assert len(rows) == 3
        returned_ts = [row["created_at"] for row in rows]
        assert returned_ts == sorted(returned_ts, reverse=True)
