"""R2-backed model load path for src.shared.image_features._load_model (gh-391).

Covers the post-gh-391 cold-start fetch flow: pointer file → run-id → joblib
materialized to a local cache → joblib.load. Also exercises the failure-mode
branches that must return None so extraction falls back to the heuristic.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.shared import image_features
from src.shared.image_features import predict_relevance


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Reset module + factory caches; redirect model_cache_dir into tmp_path.

    Teardown of monkeypatch undoes the patch and clears caches so the next
    test starts clean — no manual cache_clear needed in the post-yield path.
    """
    from src.infra import model_storage, paths

    image_features._MODEL_CACHE.clear()
    image_features._reset_active_run_id_cache()
    model_storage.get_model_storage.cache_clear()
    paths.model_cache_dir.cache_clear()

    # The materialization scratch must land inside tmp_path so each test starts
    # clean. model_cache_dir() is path-fixed (no env override by design); patch
    # the function on its source module — _materialize_from_storage does a local
    # `from src.infra.paths import model_cache_dir` per call, which re-resolves
    # the attribute and picks up this override.
    monkeypatch.setattr(paths, "model_cache_dir", lambda: tmp_path)

    yield

    image_features._MODEL_CACHE.clear()
    image_features._reset_active_run_id_cache()
    model_storage.get_model_storage.cache_clear()


@pytest.fixture
def _moto_bucket(monkeypatch: pytest.MonkeyPatch):
    """Boot moto S3 + create the R2 bucket. Wires the four R2_* env vars."""
    moto = pytest.importorskip("moto")
    import boto3

    original_client = boto3.client

    def patched_client(service, **kwargs):
        kwargs.pop("endpoint_url", None)
        kwargs["region_name"] = "us-east-1"
        return original_client(service, **kwargs)

    monkeypatch.setattr(boto3, "client", patched_client)
    monkeypatch.setenv("R2_BUCKET", "model-r2-load-bucket")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("FILINGS_REVIEWER_ALLOW_PROD_WRITES", "1")

    with moto.mock_aws():
        original_client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        ).create_bucket(Bucket="model-r2-load-bucket")
        yield


def _sample_features() -> dict:
    return {
        "nearby_text": "Customer retention cohort",
        "relevance_score": 0.75,
        "width": 800,
        "height": 600,
        "classification": "chart",
        "filename": "chart.png",
    }


def _seed_storage(run_id: str, model_bytes: bytes = b"sentinel-joblib") -> None:
    """Upload latest_run_id.txt + per-run joblib via the storage factory."""
    from src.infra.model_storage import get_model_storage

    storage = get_model_storage()
    storage.put_bytes(
        f"models/image_relevance/{run_id}/relevance_model.joblib",
        model_bytes,
        content_type="application/octet-stream",
    )
    storage.put_bytes(
        "models/image_relevance/latest_run_id.txt",
        run_id.encode("utf-8"),
        content_type="text/plain",
    )


class TestR2LoadCold:
    def test_predict_relevance_fetches_from_r2_on_cold_start(
        self, _moto_bucket, tmp_path: Path
    ) -> None:
        """Pointer → run-id → fetch joblib → joblib.load → predict_proba."""
        run_id = "run-aaaa-1111"
        _seed_storage(run_id)

        mock_pipeline = MagicMock()
        mock_pipeline.predict_proba.return_value = np.array([[0.3, 0.7]])

        with patch("joblib.load", return_value=mock_pipeline):
            result = predict_relevance(_sample_features())

        assert result == pytest.approx(0.7)
        # Materialized to <model_cache_dir>/_cache/<run_id>/relevance_model.joblib.
        assert (tmp_path / "_cache" / run_id / "relevance_model.joblib").exists()
        # In-memory cache key is "r2:<run_id>".
        assert f"r2:{run_id}" in image_features._MODEL_CACHE

    def test_warm_cache_does_not_redownload(self, _moto_bucket, tmp_path: Path) -> None:
        """Second predict call hits _MODEL_CACHE — no extra storage GETs.

        Both the pointer resolution (_resolve_active_run_id) AND the loaded
        pipeline (_MODEL_CACHE) are cached for the worker's lifetime — at the
        cost of stale-window-bounded-by-worker-rotation, we save ~1 GET per
        image at extraction scale.
        """
        run_id = "run-bbbb-2222"
        _seed_storage(run_id)

        mock_pipeline = MagicMock()
        mock_pipeline.predict_proba.return_value = np.array([[0.5, 0.5]])

        from src.infra.model_storage import get_model_storage

        storage = get_model_storage()
        with (
            patch.object(storage, "get_bytes", wraps=storage.get_bytes) as wrapped_get,
            patch("joblib.load", return_value=mock_pipeline),
        ):
            predict_relevance(_sample_features())  # cold
            cold_calls = wrapped_get.call_count
            predict_relevance(_sample_features())  # warm
            warm_calls = wrapped_get.call_count

        # Cold: 1 pointer GET + 1 joblib GET = 2. Warm: 0 additional.
        assert cold_calls == 2, f"expected 2 cold GETs (pointer + model), got {cold_calls}"
        assert warm_calls == cold_calls, "warm call must not re-fetch from storage"

    def test_pointer_change_triggers_redownload_after_worker_restart(
        self, _moto_bucket, tmp_path: Path
    ) -> None:
        """A new run_id materializes only after the active-run-id cache resets.

        The cache reset models a worker process restart (Render deploy or cron
        run). Within a single worker, _resolve_active_run_id is sticky — see
        the docstring on _resolve_active_run_id for the why.
        """
        first = "run-cccc-3333"
        second = "run-dddd-4444"

        _seed_storage(first, model_bytes=b"first-joblib")

        mock_pipeline = MagicMock()
        mock_pipeline.predict_proba.return_value = np.array([[0.4, 0.6]])

        with patch("joblib.load", return_value=mock_pipeline):
            predict_relevance(_sample_features())

        assert (tmp_path / "_cache" / first / "relevance_model.joblib").exists()

        # Second retrain replaces the pointer + uploads a new per-run joblib.
        _seed_storage(second, model_bytes=b"second-joblib")
        # Without a worker restart, the cached run_id stays as `first` — the
        # second retrain is invisible to this process.
        with patch("joblib.load", return_value=mock_pipeline):
            predict_relevance(_sample_features())
        assert not (tmp_path / "_cache" / second / "relevance_model.joblib").exists()

        # Simulate worker restart: clear the run_id cache + the model cache.
        image_features._reset_active_run_id_cache()
        image_features._MODEL_CACHE.clear()

        with patch("joblib.load", return_value=mock_pipeline):
            predict_relevance(_sample_features())

        assert (tmp_path / "_cache" / second / "relevance_model.joblib").exists()
        assert f"r2:{second}" in image_features._MODEL_CACHE


class TestR2LoadFailureModes:
    def test_missing_pointer_falls_back_to_none(self, _moto_bucket) -> None:
        """No latest_run_id.txt in storage → None (heuristic fallback)."""
        # Bucket exists but is empty.
        result = predict_relevance(_sample_features())
        assert result is None

    def test_pointer_references_missing_joblib_falls_back(self, _moto_bucket) -> None:
        """Pointer present, but the per-run joblib is missing → None."""
        from src.infra.model_storage import get_model_storage

        storage = get_model_storage()
        storage.put_bytes(
            "models/image_relevance/latest_run_id.txt",
            b"orphan-run-id",
            content_type="text/plain",
        )
        # No per-run joblib upload.

        result = predict_relevance(_sample_features())
        assert result is None
        # Sentinel cached so a second call doesn't re-attempt the fetch.
        assert image_features._MODEL_CACHE["r2:orphan-run-id"] is image_features._MODEL_ABSENT

    def test_endpoint_connection_error_falls_back(
        self, _moto_bucket, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Network outage on pointer GET → None (no crash)."""
        from botocore.exceptions import EndpointConnectionError

        from src.infra.model_storage import get_model_storage

        storage = get_model_storage()

        def boom(*_args, **_kwargs):
            raise EndpointConnectionError(endpoint_url="https://example.com")

        monkeypatch.setattr(storage, "get_bytes", boom)

        result = predict_relevance(_sample_features())
        assert result is None
