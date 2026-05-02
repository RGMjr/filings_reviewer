"""
Unit tests for the learned-triage inference helper in image_features.

Covers:
- predict_relevance returns None when the model file is absent (graceful fallback)
- predict_relevance returns a float in [0, 1] when a mocked pipeline is present
- _load_model caches results so repeated calls do not re-load from disk
- Bad pipelines surface as None rather than raising
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.shared import image_features
from src.shared.image_features import _load_model, predict_relevance


@pytest.fixture(autouse=True)
def _reset_model_cache() -> None:
    """Ensure each test starts with a clean model cache."""
    image_features._MODEL_CACHE.clear()
    yield
    image_features._MODEL_CACHE.clear()


def _sample_features() -> dict:
    """Minimal feature dict matching v2_row_to_features_input output shape."""
    return {
        "nearby_text": "Customer retention cohort",
        "relevance_score": 0.75,
        "width": 800,
        "height": 600,
        "classification": "chart",
        "filename": "chart.png",
    }


def test_predict_relevance_returns_none_when_model_absent(tmp_path: Path) -> None:
    """Graceful fallback: missing model artifact → None (caller uses heuristic)."""
    missing = tmp_path / "does_not_exist.joblib"
    assert not missing.exists()

    result = predict_relevance(_sample_features(), model_path=missing)
    assert result is None


def test_predict_relevance_returns_float_when_pipeline_loads(tmp_path: Path) -> None:
    """Happy path: mocked joblib.load returns a pipeline with predict_proba."""
    model_path = tmp_path / "relevance_model.joblib"
    model_path.write_bytes(b"sentinel")  # Content ignored; joblib.load is mocked.

    mock_pipeline = MagicMock()
    # predict_proba returns a (N, 2) array: [prob_not_relevant, prob_relevant]
    mock_pipeline.predict_proba.return_value = np.array([[0.1, 0.9]])

    with patch("joblib.load", return_value=mock_pipeline):
        result = predict_relevance(_sample_features(), model_path=model_path)

    assert result is not None
    assert 0.0 <= result <= 1.0
    assert result == pytest.approx(0.9)


def test_predict_relevance_returns_none_on_bad_pipeline(tmp_path: Path) -> None:
    """Pipeline that raises during predict_proba → None (no crash)."""
    model_path = tmp_path / "relevance_model.joblib"
    model_path.write_bytes(b"sentinel")

    mock_pipeline = MagicMock()
    mock_pipeline.predict_proba.side_effect = RuntimeError("broken pipeline")

    with patch("joblib.load", return_value=mock_pipeline):
        result = predict_relevance(_sample_features(), model_path=model_path)

    assert result is None


def test_load_model_caches_per_path(tmp_path: Path) -> None:
    """Cached loader: repeated calls for the same path hit disk exactly once."""
    model_path = tmp_path / "relevance_model.joblib"
    model_path.write_bytes(b"sentinel")

    mock_pipeline = MagicMock()

    with patch("joblib.load", return_value=mock_pipeline) as mock_load:
        first = _load_model(model_path)
        second = _load_model(model_path)
        third = _load_model(model_path)

        assert mock_load.call_count == 1
        assert first is mock_pipeline
        assert second is mock_pipeline
        assert third is mock_pipeline


def test_load_model_caches_absent_result(tmp_path: Path) -> None:
    """Absent-model sentinel is cached too — don't stat the filesystem repeatedly."""
    missing = tmp_path / "does_not_exist.joblib"
    assert not missing.exists()

    # First call caches the absent sentinel.
    assert _load_model(missing) is None
    # Second call returns None without attempting another stat/load.
    assert _load_model(missing) is None
    # Internal cache holds the sentinel, not a real pipeline.
    resolved = str(missing.resolve())
    assert resolved in image_features._MODEL_CACHE
    assert image_features._MODEL_CACHE[resolved] is image_features._MODEL_ABSENT


def test_explicit_model_path_bypasses_storage_under_r2_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for gh-391: an explicit model_path must short-circuit the R2 branch.

    Test fixtures pass a tmp joblib via model_path; if R2_BUCKET happens to be set
    in the environment (e.g. integration test contamination, accidental leak), the
    loader must still read from the explicit path, not attempt a storage lookup.
    """
    monkeypatch.setenv("R2_BUCKET", "should-not-be-touched")
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://example.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test")

    model_path = tmp_path / "relevance_model.joblib"
    model_path.write_bytes(b"sentinel")

    mock_pipeline = MagicMock()
    mock_pipeline.predict_proba.return_value = np.array([[0.2, 0.8]])

    # Patch get_model_storage so any accidental call surfaces as an explicit
    # failure — the explicit-path branch must never reach this.
    with patch("src.infra.model_storage.get_model_storage") as mock_storage_factory:
        mock_storage_factory.side_effect = AssertionError(
            "explicit model_path should bypass storage abstraction"
        )
        with patch("joblib.load", return_value=mock_pipeline):
            result = predict_relevance(_sample_features(), model_path=model_path)

    assert result == pytest.approx(0.8)
    # Cache key in the local-FS branch is the resolved string path, not "r2:<run_id>".
    assert str(model_path.resolve()) in image_features._MODEL_CACHE
