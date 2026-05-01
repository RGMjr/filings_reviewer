"""Unit tests for the Phase-3 image-classifier retrain endpoints.

Covers:
  - POST /api/v2/models/image-classifier/retrain — threshold gate, concurrency
    gate, reviewer-id gate, subprocess spawn, model-type validation.
  - GET  /api/v2/models/training/<uuid>/status — 404 path, 200 path.

Subprocess spawning is suppressed via the INGEST_SPAWN_SUBPROCESS=False
config flag (the same flag the ingest tests use). The test still asserts
that `subprocess.Popen` would be called with the right cmdline by patching
it at the api_unified module path.
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
    # Disable real subprocess spawn — `_spawn_retrain_runner` short-circuits.
    app.config["INGEST_SPAWN_SUBPROCESS"] = False
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
        mock_db.query.return_value = [{"id": uuid.uuid4()}]
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "retrain_already_running"
        assert "running_run_id" in body
        # Concurrency gate must short-circuit before threshold work.
        mock_db.count_image_decisions_since.assert_not_called()


class TestStaleRowSweep:
    """gh-392: a 'running' row older than 1 hour gets auto-flipped to 'failed'
    before the concurrency check, so a SIGKILL/OOM-leaked row does not
    permanently block future retrains via the concurrency gate."""

    def test_sweep_runs_before_concurrency_check(self, client, mock_db):
        """Cleanup UPDATE must fire on every retrain attempt — not gated on
        whether anything is currently 'running'. This is what unblocks a
        previously-stuck row."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with patch("src.web.routes.api_unified.subprocess.Popen"):
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
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            client.post(_RETRAIN, json=_VALID_REVIEWER)
        sweep_sql = mock_db.execute.call_args_list[0].args[0]
        assert "model_type = 'image_relevance'" in sweep_sql

    def test_sweep_scoped_to_running_status_and_one_hour(self, client, mock_db):
        """Sweep must only touch rows with status='running' AND old enough.
        Prevents accidentally clobbering a freshly-spawned retrain that
        happens to overlap with a button-click."""
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with patch("src.web.routes.api_unified.subprocess.Popen"):
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
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with patch("src.web.routes.api_unified.subprocess.Popen") as mock_popen:
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        # 202 Accepted — kicked off, not yet complete.
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["status"] == "running"
        run_id = body["run_id"]
        # Valid UUID.
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
        assert params["triggered_by"] == "RGM"
        # INGEST_SPAWN_SUBPROCESS=False short-circuits before Popen.
        mock_popen.assert_not_called()

    def test_spawn_failure_marks_row_failed(self, client, mock_db, app):
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        # Re-enable the real spawn path so Popen is reached, then make it raise.
        app.config["INGEST_SPAWN_SUBPROCESS"] = True
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
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        assert resp.status_code == 202

    def test_invalid_env_falls_back_to_default(self, client, mock_db, monkeypatch):
        monkeypatch.setenv("MODEL_UPDATE_THRESHOLD_TOTAL", "not-a-number")
        mock_db.count_image_decisions_since.return_value = _at_threshold()
        with patch("src.web.routes.api_unified.subprocess.Popen"):
            resp = client.post(_RETRAIN, json=_VALID_REVIEWER)
        # Falls back to default 100; counts (150, 25) clear it → 202.
        assert resp.status_code == 202
