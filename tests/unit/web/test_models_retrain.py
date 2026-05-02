"""Unit tests for the Phase-3 image-classifier retrain endpoints.

Covers:
  - POST /api/v2/models/image-classifier/retrain — threshold gate, concurrency
    gate (queued + running), reviewer-id gate, subprocess spawn, queued-mode
    behaviour, model-type validation.
  - GET  /api/v2/models/training/<uuid>/status — 404 path, 200 path.

The default `app` fixture sets RETRAIN_SPAWN_SUBPROCESS=True so the dev/test
"spawn locally" path is exercised; tests that need to verify queued-mode
behaviour (gh-400 worker pattern) flip the flag to False.
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
    # Default: dev/test spawn-locally path. Tests patch subprocess.Popen so
    # nothing actually runs. Tests that exercise prod queued-mode flip this
    # to False explicitly.
    app.config["RETRAIN_SPAWN_SUBPROCESS"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with patch("src.web.routes.api_unified.get_db") as mock_get_db:
        db = MagicMock()
        # Defaults: no running retrain, no last run (so since_ts = None).
        db.query.return_value = []
        db.execute.return_value = None
        db.count_image_decisions_since.return_value = {
            "total": 0,
            "positive": 0,
            "negative": 0,
        }
        # insert_audit_log must not raise (after_request hooks may call it).
        db.insert_audit_log.return_value = None
        mock_get_db.return_value = db
        yield db


_RETRAIN = "/api/v2/models/image-classifier/retrain"
_STATUS_TEMPLATE = "/api/v2/models/training/{run_id}/status"
_VALID_REVIEWER = {"reviewer_id": "RGM"}


def _at_threshold():
    """Counts that meet the default thresholds (100 total, 10 positive)."""
    return {"total": 150, "positive": 25, "negative": 125}


# ---------------------------------------------------------------------------
# POST /api/v2/models/image-classifier/retrain
# ---------------------------------------------------------------------------


class TestRetrainGuards:
    def test_missing_reviewer_id_returns_403(self, client, mock_db):
        resp = client.post(_RETRAIN, json={})
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["error"] == "reviewer_name_required"
        # Should never reach the threshold check.
        mock_db.count_image_decisions_since.assert_not_called()

    def test_blocklisted_reviewer_returns_403(self, client, mock_db):
        resp = client.post(_RETRAIN, json={"reviewer_id": "anonymous"})
        assert resp.status_code == 403

    def test_invalid_model_type_returns_400(self, client, mock_db):
        resp = client.post(_RETRAIN, json={**_VALID_REVIEWER, "model_type": "transformer"})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_model_type"

    def test_below_threshold_returns_409(self, client, mock_db):
        mock_db.count_image_decisions_since.return_value = {
            "total": 50,
            "positive": 5,
            "negative": 45,
        }
        resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "below_threshold"
        assert body["counts"]["total"] == 50
        assert body["thresholds"]["total"] == 100

    def test_below_positive_threshold_returns_409(self, client, mock_db):
        # Total clears, positive doesn't — minority class is the binding gate.
        mock_db.count_image_decisions_since.return_value = {
            "total": 200,
            "positive": 5,
            "negative": 195,
        }
        resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 409

    def test_running_retrain_returns_409(self, client, mock_db):
        mock_db.query.return_value = [{"id": uuid.uuid4(), "status": "running"}]
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "retrain_already_running"
        assert "running_run_id" in body
        # Concurrency gate must short-circuit before threshold work.
        mock_db.count_image_decisions_since.assert_not_called()

    def test_queued_retrain_returns_409(self, client, mock_db):
        """gh-400: a 'queued' row (worker hasn't picked it up yet) must also
        block a new POST so two clicks don't pile up parallel retrains."""
        mock_db.query.return_value = [{"id": uuid.uuid4(), "status": "queued"}]
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "retrain_already_running"
        assert "running_run_id" in body

    def test_concurrency_gate_sql_includes_queued(self, client, mock_db):
        """The SQL filter must cover both 'queued' and 'running' (gh-400)."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            client.post(_RETRAIN, json=_VALID_REVIEWER)
        # First db.query call is the concurrency gate.
        gate_sql = mock_db.query.call_args_list[0].args[0]
        assert "status IN ('queued', 'running')" in gate_sql


class TestStaleRowSweep:
    """gh-392: a 'running' row older than 1 hour gets auto-flipped to 'failed'
    before the concurrency check, so a SIGKILL/OOM-leaked row does not
    permanently block future retrains via the concurrency gate."""

    def test_sweep_runs_before_concurrency_check(self, client, mock_db):
        """Cleanup UPDATE must fire on every retrain attempt — not gated on
        whether anything is currently 'running'. This is what unblocks a
        previously-stuck row."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with (
            patch("src.web.routes.api_unified.subprocess.Popen"),
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 202
        # First execute is the sweep.
        sweep_call = mock_db.execute.call_args_list[0]
        sql = sweep_call.args[0]
        assert "UPDATE model_training_runs" in sql
        assert "auto-cleanup" in sql

    def test_sweep_scoped_to_image_relevance_only(self, client, mock_db):
        """Other model_type values (future ML models) must not be touched."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with (
            patch("src.web.routes.api_unified.subprocess.Popen"),
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            client.post(_RETRAIN, json=_VALID_REVIEWER)
        sweep_sql = mock_db.execute.call_args_list[0].args[0]
        assert "model_type = 'image_relevance'" in sweep_sql

    def test_sweep_scoped_to_running_status_and_one_hour(self, client, mock_db):
        """Sweep must only touch rows with status='running' AND old enough.
        Prevents accidentally clobbering a freshly-spawned retrain that
        happens to overlap with a button-click."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with (
            patch("src.web.routes.api_unified.subprocess.Popen"),
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            client.post(_RETRAIN, json=_VALID_REVIEWER)
        sweep_sql = mock_db.execute.call_args_list[0].args[0]
        assert "status = 'running'" in sweep_sql
        assert "INTERVAL '1 hour'" in sweep_sql
        assert "started_at <" in sweep_sql

    def test_sweep_runs_even_when_below_threshold(self, client, mock_db):
        """Idempotency: cleanup runs first, even if the threshold gate
        rejects this attempt. Means the next *valid* attempt sees a clean
        slate (no leaked row from a prior failed attempt). The behaviour
        also degrades safely — a stale row is cleared regardless of why
        the operator clicked."""
        # Below-threshold counts → 409, but the sweep should still have run.
        mock_db.count_image_decisions_since.return_value = {
            "total": 50,
            "positive": 5,
            "negative": 45,
        }
        resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        # Sweep ran exactly once before short-circuit.
        assert mock_db.execute.call_count == 1
        assert "UPDATE model_training_runs" in mock_db.execute.call_args_list[0].args[0]


class TestRetrainSpawn:
    def test_above_threshold_inserts_row_and_returns_run_id(self, client, mock_db):
        """Default fixture has RETRAIN_SPAWN_SUBPROCESS=True (dev/test spawn-locally)."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with (
            patch("src.web.routes.api_unified.subprocess.Popen") as mock_popen,
            # `open(log_path, "ab")` is real on disk — make it a no-op.
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        # 202 Accepted — kicked off, not yet complete.
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["status"] == "running"
        run_id = body["run_id"]
        uuid.UUID(run_id)
        # Two execute calls: stale-row sweep (gh-392) + INSERT.
        assert mock_db.execute.call_count == 2
        sweep_call = mock_db.execute.call_args_list[0]
        assert "UPDATE model_training_runs" in sweep_call.args[0]
        assert "auto-cleanup" in sweep_call.args[0]
        insert_call = mock_db.execute.call_args_list[1]
        sql, params = insert_call.args[0], insert_call.args[1]
        assert "INSERT INTO model_training_runs" in sql
        assert params["id"] == run_id
        assert params["status"] == "running"
        assert params["triggered_by"] == "RGM"
        # Spawn path is exercised.
        mock_popen.assert_called_once()

    def test_spawn_failure_marks_row_failed(self, client, mock_db):
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with (
            patch("src.web.routes.api_unified.subprocess.Popen") as mock_popen,
            # `open(log_path, "ab")` is real on disk — make it a no-op.
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            mock_popen.side_effect = OSError("fork failed")
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"] == "subprocess_spawn_failed"
        # Three execute calls: stale-row sweep + INSERT row + UPDATE→failed.
        assert mock_db.execute.call_count == 3
        update_call = mock_db.execute.call_args_list[2]
        assert "UPDATE model_training_runs" in update_call.args[0]
        assert "subprocess_spawn_failed" in update_call.args[0]


class TestRetrainQueuedMode:
    """gh-400: when RETRAIN_SPAWN_SUBPROCESS=false (prod), the endpoint
    enqueues a status='queued' row and returns immediately. The
    filings-onboarding-runner worker drains the queue."""

    def test_queued_mode_inserts_queued_row_and_skips_spawn(self, client, mock_db, app):
        app.config["RETRAIN_SPAWN_SUBPROCESS"] = False
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with patch("src.web.routes.api_unified.subprocess.Popen") as mock_popen:
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["status"] == "queued"
        run_id = body["run_id"]
        uuid.UUID(run_id)
        # Two execute calls: stale-row sweep + INSERT (no UPDATE on spawn-failure path).
        assert mock_db.execute.call_count == 2
        insert_call = mock_db.execute.call_args_list[1]
        sql, params = insert_call.args[0], insert_call.args[1]
        assert "INSERT INTO model_training_runs" in sql
        assert params["id"] == run_id
        assert params["status"] == "queued"
        assert params["triggered_by"] == "RGM"
        # Critical: subprocess MUST NOT spawn in queued mode.
        mock_popen.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/v2/models/training/<uuid:run_id>/status
# ---------------------------------------------------------------------------


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
                "model_type": "image_relevance",
                "status": "succeeded",
                "started_at": ts,
                "completed_at": ts,
                "num_training_rows": 500,
                "num_positive_rows": 25,
                "model_path": "data/image_model/relevance_model.joblib",
                "report_path": "data/image_model/model_report.txt",
                "triggered_by": "RGM",
                "error": None,
            }
        ]
        resp = client.get(_STATUS_TEMPLATE.format(run_id=str(run_id)))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "succeeded"
        assert body["num_training_rows"] == 500
        assert body["completed_at"] == ts.isoformat()
        assert body["id"] == str(run_id)

    def test_non_uuid_path_returns_404(self, client, mock_db):
        # Flask's <uuid:> converter rejects non-UUID strings before handler.
        resp = client.get("/api/v2/models/training/not-a-uuid/status")
        assert resp.status_code == 404
        # Handler never ran → DB never queried.
        mock_db.query.assert_not_called()


# ---------------------------------------------------------------------------
# Threshold env-var override
# ---------------------------------------------------------------------------


class TestThresholdConfig:
    def test_env_overrides_defaults(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("MODEL_UPDATE_THRESHOLD_TOTAL", "10")
        monkeypatch.setenv("MODEL_UPDATE_THRESHOLD_POSITIVE", "1")
        # Counts that would fail default (100/10) but clear the override (10/1).
        mock_db.count_image_decisions_since.return_value = {
            "total": 15,
            "positive": 2,
            "negative": 13,
        }
        with (
            patch("src.web.routes.api_unified.subprocess.Popen"),
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 202

    def test_invalid_env_falls_back_to_default(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("MODEL_UPDATE_THRESHOLD_TOTAL", "not-a-number")
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with (
            patch("src.web.routes.api_unified.subprocess.Popen"),
            patch("src.web.routes.api_unified.open", create=True) as mock_open,
        ):
            mock_open.return_value = MagicMock()
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        # Falls back to default 100; counts (150, 25) clear it → 202.
        assert resp.status_code == 202
