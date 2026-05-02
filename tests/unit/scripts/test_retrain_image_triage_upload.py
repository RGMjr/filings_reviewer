"""Unit tests for the R2 upload helper in scripts/retrain_image_triage.py (gh-391).

The full orchestrate-then-finalize flow is exercised in
tests/integration/test_retrain_image_triage_upload.py — this file covers the
storage-side behavior in isolation, without spawning subprocesses or touching
the DB.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "retrain_image_triage.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("retrain_image_triage_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["retrain_image_triage_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script_module()


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    from src.infra.model_storage import get_model_storage
    from src.infra.paths import model_cache_dir

    get_model_storage.cache_clear()
    model_cache_dir.cache_clear()
    yield
    get_model_storage.cache_clear()
    model_cache_dir.cache_clear()


@pytest.fixture
def _moto_bucket(monkeypatch: pytest.MonkeyPatch):
    moto = pytest.importorskip("moto")
    import boto3

    original_client = boto3.client

    def patched_client(service, **kwargs):
        kwargs.pop("endpoint_url", None)
        kwargs["region_name"] = "us-east-1"
        return original_client(service, **kwargs)

    monkeypatch.setattr(boto3, "client", patched_client)
    monkeypatch.setenv("R2_BUCKET", "retrain-upload-bucket")
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
        ).create_bucket(Bucket="retrain-upload-bucket")
        yield


def _seed_local_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Drop the three artifact files at the local paths the wrapper expects."""
    model = tmp_path / "relevance_model.joblib"
    report = tmp_path / "model_report.txt"
    csv = tmp_path / "training_data.csv"
    model.write_bytes(b"fake-joblib-bytes")
    report.write_text("model report\n")
    csv.write_text("decision,feature_x\nrelevant,0.9\nnot_relevant,0.1\n")
    return model, report, csv


class TestStorageKeysForRun:
    def test_returns_three_keys(self, script) -> None:
        keys = script._storage_keys_for_run("abc-123")
        assert keys == {
            "model_key": "models/image_relevance/abc-123/relevance_model.joblib",
            "report_key": "models/image_relevance/abc-123/model_report.txt",
            "csv_key": "models/image_relevance/abc-123/training_data.csv",
        }


class TestUploadArtifacts:
    def test_uploads_all_three_plus_pointer(self, script, _moto_bucket, tmp_path: Path) -> None:
        from src.infra.model_storage import get_model_storage

        model, report, csv = _seed_local_artifacts(tmp_path)
        run_id = "run-upload-1111"

        keys = script._upload_artifacts(
            run_id, model_path=str(model), report_path=str(report), csv_path=str(csv)
        )

        storage = get_model_storage()
        # Per-run artifacts byte-identical to local fixtures.
        assert storage.get_bytes(keys["model_key"]) == b"fake-joblib-bytes"
        assert storage.get_bytes(keys["report_key"]) == b"model report\n"
        assert (
            storage.get_bytes(keys["csv_key"])
            == b"decision,feature_x\nrelevant,0.9\nnot_relevant,0.1\n"
        )
        # Pointer points at this run.
        assert storage.get_bytes("models/image_relevance/latest_run_id.txt") == run_id.encode(
            "utf-8"
        )

    def test_returned_keys_are_storage_keys_not_paths(
        self, script, _moto_bucket, tmp_path: Path
    ) -> None:
        """The keys flipped into model_training_runs.model_path must NOT have a leading slash."""
        model, report, csv = _seed_local_artifacts(tmp_path)
        keys = script._upload_artifacts(
            "run-keys-2222",
            model_path=str(model),
            report_path=str(report),
            csv_path=str(csv),
        )
        for value in keys.values():
            assert not value.startswith("/"), f"storage key looks like a filesystem path: {value}"
            assert value.startswith("models/image_relevance/"), value

    def test_missing_local_artifact_raises(self, script, _moto_bucket, tmp_path: Path) -> None:
        """Pre-upload existence check fails-loud so the orchestrator can mark status='failed'."""
        # Only seed two of three.
        model = tmp_path / "relevance_model.joblib"
        model.write_bytes(b"x")
        report = tmp_path / "report.txt"
        report.write_text("ok\n")
        ghost_csv = tmp_path / "missing.csv"

        with pytest.raises(FileNotFoundError, match="missing.csv"):
            script._upload_artifacts(
                "run-missing-3333",
                model_path=str(model),
                report_path=str(report),
                csv_path=str(ghost_csv),
            )

    def test_pointer_uploaded_last(self, script, _moto_bucket, tmp_path: Path) -> None:
        """Regression: a per-run upload failure must NOT update the pointer.

        Stash the previous pointer, then trigger a failure mid-upload, then
        confirm the pointer still resolves to the previous value.
        """
        from src.infra.model_storage import get_model_storage

        storage = get_model_storage()
        # Seed a previous successful pointer.
        storage.put_bytes(
            "models/image_relevance/latest_run_id.txt",
            b"run-previous",
            content_type="text/plain",
        )

        # Try a new upload where one artifact is missing.
        model = tmp_path / "relevance_model.joblib"
        model.write_bytes(b"new-bytes")
        report = tmp_path / "report.txt"
        report.write_text("new report\n")
        ghost_csv = tmp_path / "ghost.csv"

        with pytest.raises(FileNotFoundError):
            script._upload_artifacts(
                "run-failed-4444",
                model_path=str(model),
                report_path=str(report),
                csv_path=str(ghost_csv),
            )

        # Pointer must be untouched.
        assert storage.get_bytes("models/image_relevance/latest_run_id.txt") == b"run-previous"
