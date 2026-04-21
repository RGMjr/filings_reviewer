"""Unit tests for scripts/write_sweep_digest.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "write_sweep_digest.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("write_sweep_digest", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["write_sweep_digest"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
render_digest = _mod.render_digest
validate_outcome = _mod.validate_outcome


class TestRenderDigest:
    def test_empty_outcomes_produces_all_none_sections(self) -> None:
        out = render_digest([], "2026-04-22")
        assert "## Auto-merged (0)" in out
        assert "## Awaiting your approval (0)" in out
        assert "## Abandoned (0)" in out
        assert "_(none)_" in out

    def test_merged_outcome_renders_pr_link(self) -> None:
        out = render_digest(
            [
                {
                    "issue": 60,
                    "autonomy": "safe",
                    "outcome": "merged",
                    "pr_number": 78,
                    "pr_url": "https://gh.example/78",
                    "finished_at": "02:17",
                }
            ],
            "2026-04-22",
        )
        assert "#60" in out
        assert "[#78](https://gh.example/78)" in out
        assert "merged at 02:17" in out

    def test_awaiting_review_renders_approve_command(self) -> None:
        out = render_digest(
            [
                {
                    "issue": 38,
                    "autonomy": "review",
                    "outcome": "awaiting_review",
                    "pr_number": 80,
                    "pr_url": "https://gh.example/80",
                    "branch": "claude/sweep/issue-38",
                }
            ],
            "2026-04-22",
        )
        assert "gh pr review --approve 80" in out
        assert "gh pr merge --auto --squash 80" in out
        assert "gh pr close 80" in out
        assert "git push origin --delete claude/sweep/issue-38" in out

    def test_abandoned_requires_reason(self) -> None:
        out = render_digest(
            [
                {
                    "issue": 66,
                    "autonomy": "safe",
                    "outcome": "abandoned",
                    "reason": "gh pr create rate limit",
                }
            ],
            "2026-04-22",
        )
        assert "abandoned: gh pr create rate limit" in out

    def test_header_includes_run_start_and_duration(self) -> None:
        out = render_digest([], "2026-04-22", run_start="02:03", run_duration="14m")
        assert out.splitlines()[0] == "# Nightly sweep — 2026-04-22 (ran 02:03, took 14m)"


class TestValidateOutcome:
    def test_accepts_valid_merged(self) -> None:
        validate_outcome(
            {
                "issue": 60,
                "autonomy": "safe",
                "outcome": "merged",
                "pr_number": 78,
            }
        )

    def test_rejects_missing_required_field(self) -> None:
        with pytest.raises(ValueError, match="missing required fields"):
            validate_outcome({"issue": 60, "autonomy": "safe"})

    def test_rejects_unknown_outcome(self) -> None:
        with pytest.raises(ValueError, match="not in"):
            validate_outcome({"issue": 60, "autonomy": "safe", "outcome": "skipped"})

    def test_merged_without_pr_number_rejected(self) -> None:
        with pytest.raises(ValueError, match="merged outcome missing pr_number"):
            validate_outcome({"issue": 60, "autonomy": "safe", "outcome": "merged"})

    def test_awaiting_review_without_pr_number_rejected(self) -> None:
        with pytest.raises(ValueError, match="awaiting_review outcome missing pr_number"):
            validate_outcome({"issue": 60, "autonomy": "review", "outcome": "awaiting_review"})

    def test_abandoned_without_reason_rejected(self) -> None:
        with pytest.raises(ValueError, match="abandoned outcome missing reason"):
            validate_outcome({"issue": 60, "autonomy": "safe", "outcome": "abandoned"})
