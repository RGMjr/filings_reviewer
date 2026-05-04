"""Unit tests for the sklearn version guard in scripts/retrain_image_triage.py."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "retrain_image_triage.py"


def _load_module() -> Any:
    root = str(_SCRIPT_PATH.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("retrain_image_triage", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["retrain_image_triage"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def script():
    return _load_module()


def test_read_pinned_sklearn_version_returns_semver(script: Any) -> None:
    version = script._read_pinned_sklearn_version()
    parts = version.split(".")
    assert len(parts) >= 2, f"Expected semver, got: {version!r}"
    assert all(p.isdigit() for p in parts), f"Non-numeric version parts in: {version!r}"


def test_check_sklearn_version_passes_on_match(
    script: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = script._read_pinned_sklearn_version()
    monkeypatch.setattr("sklearn.__version__", pinned)
    script.check_sklearn_version()  # must not raise or exit


def test_check_sklearn_version_exits_on_mismatch(
    script: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sklearn.__version__", "0.0.0-mock")
    with pytest.raises(SystemExit) as exc_info:
        script.check_sklearn_version()
    assert exc_info.value.code == 1


def test_check_sklearn_version_allow_mismatch_warns_not_exits(
    script: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("sklearn.__version__", "0.0.0-mock")

    with caplog.at_level(logging.WARNING, logger="retrain_image_triage"):
        script.check_sklearn_version(allow_mismatch=True)

    assert any("--allow-version-mismatch" in record.message for record in caplog.records), (
        "Expected warning mentioning --allow-version-mismatch"
    )


def test_read_pinned_sklearn_version_returns_none_when_lock_file_missing(
    script: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    # Point the script's __file__ into a tmp dir that has no requirements.lock.
    monkeypatch.setattr(script, "__file__", str(tmp_path / "scripts" / "retrain_image_triage.py"))

    with caplog.at_level(logging.WARNING, logger="retrain_image_triage"):
        result = script._read_pinned_sklearn_version()

    assert result is None
    assert any("requirements.lock" in r.message for r in caplog.records), (
        "Expected warning mentioning requirements.lock"
    )


def test_check_sklearn_version_noop_when_pin_unknown(
    script: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(script, "_read_pinned_sklearn_version", lambda: None)
    # Must not raise or call sys.exit when pinned version is unknown.
    script.check_sklearn_version()


def test_check_sklearn_version_in_run_id_branch_writes_failed_on_mismatch(
    script: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When check_sklearn_version raises inside the run-id try/except, _update_run_status
    is called with status='failed' and a non-empty error string (gh-437)."""
    monkeypatch.setattr(script, "_read_pinned_sklearn_version", lambda: "99.99.99")
    monkeypatch.setattr("sklearn.__version__", "0.0.0-mock")
    monkeypatch.setattr(script, "configure_logging", lambda **_kw: None)

    captured: list[dict] = []

    def fake_update(
        database_url: str, run_id: str, *, status: str, error: str | None = None, **_kw: object
    ) -> None:
        captured.append({"status": status, "error": error})

    monkeypatch.setattr(script, "_update_run_status", fake_update)
    monkeypatch.setattr(script, "_orchestrate", lambda _args: None)  # should not be reached

    test_argv = [
        "retrain_image_triage.py",
        "--run-id",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "--database-url",
        "postgresql://test",
        "--source",
        "all",
    ]
    with patch("sys.argv", test_argv):
        with pytest.raises(SystemExit):
            script.main()

    assert captured, "Expected _update_run_status to be called on version-check failure"
    assert captured[0]["status"] == "failed"
    assert captured[0]["error"], "Expected non-empty error string in failed row"
