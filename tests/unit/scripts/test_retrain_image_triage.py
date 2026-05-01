"""Unit tests for the sklearn version guard in scripts/retrain_image_triage.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

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
    import logging

    with caplog.at_level(logging.WARNING, logger="retrain_image_triage"):
        script.check_sklearn_version(allow_mismatch=True)

    assert any("--allow-version-mismatch" in record.message for record in caplog.records), (
        "Expected warning mentioning --allow-version-mismatch"
    )
