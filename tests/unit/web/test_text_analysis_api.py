"""Unit tests for the text-decision pattern-analysis endpoints.

Mirrors tests/unit/web/test_models_retrain.py for the parallel
/api/v2/extraction/* endpoints. Subprocess spawn is suppressed via the
INGEST_SPAWN_SUBPROCESS=False config flag.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = "postgresql://test"
    app.config["_db_pool"] = None
    app.config["INGEST_SPAWN_SUBPROCESS"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("src.web.routes.api_unified.get_db") as mock_get_db:
        db = MagicMock()
        # Defaults: no running analysis, no last run, no decisions.
        db.is_text_analysis_running.return_value = (False, None)
        db.get_last_text_analysis_run.return_value = None
        db.count_text_decisions_since.return_value = 0
        db.execute.return_value = None
        db.query.return_value = []
        db.insert_audit_log.return_value = None
        mock_get_db.return_value = db
        yield db


_TRIGGER = "/api/v2/extraction/analyze-text-decisions"
_STATUS_TEMPLATE = "/api/v2/extraction/analysis-runs/{run_id}/status"
_VALID_REVIEWER = {"reviewer_id": "RGM"}


class TestTriggerGuards:
    def test_missing_reviewer_id_returns_403(self, client, mock_db):
        resp = client.post(_TRIGGER, json={})
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "reviewer_name_required"
        mock_db.count_text_decisions_since.assert_not_called()

    def test_blocklisted_reviewer_returns_403(self, client, mock_db):
        resp = client.post(_TRIGGER, json={"reviewer_id": "anonymous"})
        assert resp.status_code == 403

    def test_below_threshold_returns_409(self, client, mock_db):
        mock_db.count_text_decisions_since.return_value = 10
        resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "below_threshold"
        assert body["count"] == 10
        assert body["threshold"] == 50

    def test_running_analysis_returns_409(self, client, mock_db):
        rid = str(uuid.uuid4())
        mock_db.is_text_analysis_running.return_value = (True, rid)
        # Even with above-threshold counts, concurrency wins.
        mock_db.count_text_decisions_since.return_value = 1000
        resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "analysis_already_running"
        assert body["running_run_id"] == rid
        # Concurrency gate must short-circuit before threshold work.
        mock_db.count_text_decisions_since.assert_not_called()


class TestStaleRowSweep:
    """A 'running' row older than 1 hour gets auto-flipped to 'failed' before
    the concurrency check, so a SIGKILL/OOM-leaked row does not permanently
    block future analyses. Mirrors gh-392 for the image-retrain sibling."""

    def test_sweep_runs_before_concurrency_check(self, client, mock_db):
        mock_db.count_text_decisions_since.return_value = 100
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 202
        sweep_sql = mock_db.execute.call_args_list[0].args[0]
        assert "UPDATE text_decision_analysis_runs" in sweep_sql
        assert "auto-cleanup" in sweep_sql

    def test_sweep_scoped_to_running_status_and_one_hour(self, client, mock_db):
        mock_db.count_text_decisions_since.return_value = 100
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            client.post(_TRIGGER, json=_VALID_REVIEWER)
        sweep_sql = mock_db.execute.call_args_list[0].args[0]
        assert "status = 'running'" in sweep_sql
        assert "INTERVAL '1 hour'" in sweep_sql
        assert "started_at <" in sweep_sql

    def test_sweep_runs_even_when_below_threshold(self, client, mock_db):
        mock_db.count_text_decisions_since.return_value = 10
        resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        assert resp.get_json()["error"] == "below_threshold"
        # Sweep ran exactly once before short-circuit.
        assert mock_db.execute.call_count == 1
        assert "UPDATE text_decision_analysis_runs" in mock_db.execute.call_args_list[0].args[0]


class TestTriggerSpawn:
    def test_above_threshold_inserts_row_and_returns_run_id(self, client, mock_db):
        mock_db.count_text_decisions_since.return_value = 100
        with patch("src.web.routes.api_unified.subprocess.Popen") as mock_popen:
            resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["status"] == "running"
        run_id = body["run_id"]
        uuid.UUID(run_id)  # valid uuid
        # Two execute calls: stale-row sweep + INSERT.
        assert mock_db.execute.call_count == 2
        sweep_call = mock_db.execute.call_args_list[0]
        assert "UPDATE text_decision_analysis_runs" in sweep_call.args[0]
        assert "auto-cleanup" in sweep_call.args[0]
        insert_call = mock_db.execute.call_args_list[1]
        sql, params = insert_call.args[0], insert_call.args[1]
        assert "INSERT INTO text_decision_analysis_runs" in sql
        assert params["id"] == run_id
        assert params["triggered_by"] == "RGM"
        # INGEST_SPAWN_SUBPROCESS=False short-circuits before Popen.
        mock_popen.assert_not_called()

    def test_anchor_uses_last_run_completed_at(self, client, mock_db):
        ts = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        mock_db.get_last_text_analysis_run.return_value = {
            "id": uuid.uuid4(),
            "completed_at": ts,
        }
        mock_db.count_text_decisions_since.return_value = 100
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 202
        # Threshold helper called with that anchor.
        mock_db.count_text_decisions_since.assert_called_once_with(ts)

    def test_spawn_failure_marks_row_failed(self, client, mock_db, app):
        mock_db.count_text_decisions_since.return_value = 100
        app.config["INGEST_SPAWN_SUBPROCESS"] = True
        with (
            patch("src.web.routes.api_unified.subprocess.Popen") as mock_popen,
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            mock_popen.side_effect = OSError("fork failed")
            resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"] == "subprocess_spawn_failed"
        # Three execute calls: stale-row sweep + INSERT row + UPDATE→failed.
        assert mock_db.execute.call_count == 3
        update_call = mock_db.execute.call_args_list[2]
        assert "UPDATE text_decision_analysis_runs" in update_call.args[0]
        assert "subprocess_spawn_failed" in update_call.args[0]


class TestStatusEndpoint:
    def test_unknown_run_id_returns_404(self, client, mock_db):
        run_id = str(uuid.uuid4())
        mock_db.query.return_value = []
        resp = client.get(_STATUS_TEMPLATE.format(run_id=run_id))
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "not_found"

    def test_known_run_id_returns_row(self, client, mock_db):
        run_id = uuid.uuid4()
        ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
        mock_db.query.return_value = [
            {
                "id": run_id,
                "status": "succeeded",
                "started_at": ts,
                "completed_at": ts,
                "num_decisions_analyzed": 320,
                "num_metrics_analyzed": 12,
                "triggered_by": "RGM",
                "error": None,
            }
        ]
        resp = client.get(_STATUS_TEMPLATE.format(run_id=str(run_id)))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "succeeded"
        assert body["num_decisions_analyzed"] == 320
        assert body["num_metrics_analyzed"] == 12
        assert body["completed_at"] == ts.isoformat()
        assert body["id"] == str(run_id)

    def test_non_uuid_path_returns_404(self, client, mock_db):
        resp = client.get("/api/v2/extraction/analysis-runs/not-a-uuid/status")
        assert resp.status_code == 404
        mock_db.query.assert_not_called()


class TestThresholdConfig:
    def test_env_overrides_default(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("TEXT_ANALYSIS_THRESHOLD_TOTAL", "5")
        # 7 decisions: would fail default 50, clears the override 5.
        mock_db.count_text_decisions_since.return_value = 7
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 202

    def test_invalid_env_falls_back_to_default(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("TEXT_ANALYSIS_THRESHOLD_TOTAL", "not-a-number")
        mock_db.count_text_decisions_since.return_value = 100
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            resp = client.post(_TRIGGER, json=_VALID_REVIEWER)
        assert resp.status_code == 202
