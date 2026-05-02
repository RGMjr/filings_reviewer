"""Integration test for scripts/retrain_image_triage.py R2 upload flow (gh-391).

Exercises the wrapper end-to-end with a seeded model_training_runs row,
mocked export+train subprocesses, and a moto-backed R2 bucket. Verifies that
on success the per-run keys land in storage, the pointer is updated, and the
DB row's model_path/report_path columns hold opaque storage keys (not
filesystem paths).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.infra.db import DatabaseAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set",
    ),
]

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "retrain_image_triage.py"


def _load_script_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("retrain_image_triage_integration", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["retrain_image_triage_integration"] = module
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
    monkeypatch.setenv("R2_BUCKET", "retrain-integration-bucket")
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
        ).create_bucket(Bucket="retrain-integration-bucket")
        yield


def _seed_running_row(db: DatabaseAdapter, run_id: str) -> None:
    """Insert a 'running' row that the wrapper will UPDATE to 'succeeded'."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_training_runs (id, model_type, status, triggered_by)
                VALUES (%(id)s, 'image_relevance', 'running', 'pytest')
                """,
                {"id": run_id},
            )
            conn.commit()


def _read_row(db: DatabaseAdapter, run_id: str) -> dict:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM model_training_runs WHERE id = %(id)s", {"id": run_id})
            return dict(cur.fetchone())


def _delete_row(db: DatabaseAdapter, run_id: str) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_training_runs WHERE id = %(id)s", {"id": run_id})
            conn.commit()


def _make_subprocess_stub(model_path: Path, report_path: Path, csv_path: Path):
    """Return a subprocess.run drop-in that creates the expected artifact files.

    The wrapper invokes export_image_training_data.py (writes csv_path) then
    train_image_relevance_model.py (writes model_path + report_path). We
    distinguish by inspecting the script name in the cmd list.
    """

    def stub_run(cmd, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd)
        if "export_image_training_data.py" in cmd_str:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text("decision,relevance_score\nrelevant,0.9\nnot_relevant,0.1\n")
        elif "train_image_relevance_model.py" in cmd_str:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(b"fake-trained-joblib-bytes")
            report_path.write_text("Image Relevance Model Report\n")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    return stub_run


def test_main_uploads_artifacts_and_writes_storage_keys(
    script,
    clean_db: DatabaseAdapter,
    _moto_bucket,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: main() with --run-id uploads to R2 and writes keys to the DB row."""
    run_id = str(uuid.uuid4())
    _seed_running_row(clean_db, run_id)

    csv_path = tmp_path / "training_data.csv"
    model_path = tmp_path / "relevance_model.joblib"
    report_path = tmp_path / "model_report.txt"

    stub = _make_subprocess_stub(model_path, report_path, csv_path)
    db_url = os.environ["TEST_DATABASE_URL"]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--database-url",
            db_url,
            "--run-id",
            run_id,
            "--output-csv",
            str(csv_path),
            "--output-model",
            str(model_path),
            "--output-report",
            str(report_path),
        ],
    )

    try:
        with patch.object(subprocess, "run", side_effect=stub):
            script.main()

        # ---- Storage assertions ----
        from src.infra.model_storage import get_model_storage

        storage = get_model_storage()
        prefix = f"models/image_relevance/{run_id}"
        assert storage.exists(f"{prefix}/relevance_model.joblib")
        assert storage.exists(f"{prefix}/model_report.txt")
        assert storage.exists(f"{prefix}/training_data.csv")
        assert storage.get_bytes(f"{prefix}/relevance_model.joblib") == b"fake-trained-joblib-bytes"
        # Pointer resolves to this run.
        assert storage.get_bytes("models/image_relevance/latest_run_id.txt") == run_id.encode(
            "utf-8"
        )

        # ---- DB assertions ----
        row = _read_row(clean_db, run_id)
        assert row["status"] == "succeeded"
        # model_path / report_path are storage keys, NOT filesystem paths.
        assert row["model_path"] == f"{prefix}/relevance_model.joblib"
        assert row["report_path"] == f"{prefix}/model_report.txt"
        assert not row["model_path"].startswith("/")
        # Counts populated from the CSV stub (1 relevant, 1 not_relevant).
        assert row["num_training_rows"] == 2
        assert row["num_positive_rows"] == 1
        assert row["completed_at"] is not None
    finally:
        _delete_row(clean_db, run_id)
