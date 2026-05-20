"""Unit tests for scripts/write_sweep_digest.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
_promote_opened_outcomes = _mod._promote_opened_outcomes


class TestRenderDigest:
    def test_empty_outcomes_produces_all_none_sections(self) -> None:
        out = render_digest([], "2026-04-22")
        assert "## Auto-merged (0)" in out
        assert "## Awaiting your approval (0)" in out
        assert "## Abandoned (0)" in out
        assert "_(none)_" in out

    def test_render_digest_does_not_end_with_trailing_blank_line(self) -> None:
        # The caller writes ``digest + "\n"`` to disk, so render_digest must not
        # itself end with a newline — otherwise the file ends ``...\n\n`` and
        # end-of-file-fixer (pre-commit) loops on every push.
        out = render_digest([], "2026-04-22")
        assert not out.endswith("\n"), "render_digest must not append trailing newline"

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

    def test_accepts_valid_opened(self) -> None:
        validate_outcome(
            {
                "issue": 60,
                "autonomy": "safe",
                "outcome": "opened",
                "pr_number": 78,
            }
        )

    def test_opened_without_pr_number_rejected(self) -> None:
        with pytest.raises(ValueError, match="opened outcome missing pr_number"):
            validate_outcome({"issue": 60, "autonomy": "safe", "outcome": "opened"})

    def test_all_four_outcomes_validate_cleanly(self) -> None:
        payloads = [
            {"issue": 1, "autonomy": "safe", "outcome": "merged", "pr_number": 10},
            {"issue": 2, "autonomy": "safe", "outcome": "opened", "pr_number": 11},
            {"issue": 3, "autonomy": "review", "outcome": "awaiting_review", "pr_number": 12},
            {"issue": 4, "autonomy": "safe", "outcome": "abandoned", "reason": "timeout"},
        ]
        for p in payloads:
            validate_outcome(p)  # must not raise


class TestRenderDigestOpenedSection:
    def test_opened_outcome_renders_ci_pending_section(self) -> None:
        out = render_digest(
            [
                {
                    "issue": 99,
                    "autonomy": "safe",
                    "outcome": "opened",
                    "pr_number": 200,
                    "pr_url": "https://gh.example/200",
                }
            ],
            "2026-04-27",
        )
        assert "## Opened — awaiting CI (1)" in out
        assert "#99" in out
        assert "[#200](https://gh.example/200)" in out
        assert "open, CI pending" in out
        assert "gh pr checks 200" in out

    def test_empty_opened_section_shows_none(self) -> None:
        out = render_digest([], "2026-04-27")
        assert "## Opened — awaiting CI (0)" in out
        assert "_(none)_" in out

    def test_mixed_all_four_outcomes_sections_present(self) -> None:
        outcomes = [
            {
                "issue": 1,
                "autonomy": "safe",
                "outcome": "merged",
                "pr_number": 10,
                "pr_url": "https://gh.example/10",
            },
            {
                "issue": 2,
                "autonomy": "safe",
                "outcome": "opened",
                "pr_number": 11,
                "pr_url": "https://gh.example/11",
            },
            {
                "issue": 3,
                "autonomy": "review",
                "outcome": "awaiting_review",
                "pr_number": 12,
                "pr_url": "https://gh.example/12",
                "branch": "claude/sweep/issue-3",
            },
            {
                "issue": 4,
                "autonomy": "safe",
                "outcome": "abandoned",
                "reason": "timeout",
            },
        ]
        out = render_digest(outcomes, "2026-04-27")
        assert "## Auto-merged (1)" in out
        assert "## Opened — awaiting CI (1)" in out
        assert "## Awaiting your approval (1)" in out
        assert "## Abandoned (1)" in out


class TestPromoteOpenedOutcomes:
    """Tests for _promote_opened_outcomes; mocks subprocess.run."""

    def _make_opened(self, issue: int = 99, pr_number: int = 200) -> dict:
        return {
            "issue": issue,
            "autonomy": "safe",
            "outcome": "opened",
            "pr_number": pr_number,
            "pr_url": f"https://gh.example/{pr_number}",
        }

    def test_merged_at_non_null_promotes_to_merged(self) -> None:
        import subprocess

        gh_response = '{"state": "MERGED", "mergedAt": "2026-04-27T03:00:00Z"}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=gh_response, stderr=""
            )
            result = _promote_opened_outcomes([self._make_opened()])
        assert result[0]["outcome"] == "merged"

    def test_closed_without_merge_promotes_to_abandoned(self) -> None:
        import subprocess

        gh_response = '{"state": "CLOSED", "mergedAt": null}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=gh_response, stderr=""
            )
            result = _promote_opened_outcomes([self._make_opened()])
        assert result[0]["outcome"] == "abandoned"
        assert result[0]["reason"] == "closed without merge"

    def test_still_open_ci_pending_stays_opened(self) -> None:
        import subprocess

        gh_response = '{"state": "OPEN", "mergedAt": null}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=gh_response, stderr=""
            )
            result = _promote_opened_outcomes([self._make_opened()])
        assert result[0]["outcome"] == "opened"

    def test_gh_failure_keeps_opened(self) -> None:
        import subprocess

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not found"
            )
            result = _promote_opened_outcomes([self._make_opened()])
        assert result[0]["outcome"] == "opened"

    def test_gh_exception_keeps_opened(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("gh not found")):
            result = _promote_opened_outcomes([self._make_opened()])
        assert result[0]["outcome"] == "opened"

    def test_non_opened_outcomes_pass_through_unchanged(self) -> None:
        outcomes: list[dict] = [
            {"issue": 1, "autonomy": "safe", "outcome": "merged", "pr_number": 10},
            {"issue": 2, "autonomy": "safe", "outcome": "abandoned", "reason": "timeout"},
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = None  # should never be called
            result = _promote_opened_outcomes(outcomes)
        mock_run.assert_not_called()
        assert result[0]["outcome"] == "merged"
        assert result[1]["outcome"] == "abandoned"
