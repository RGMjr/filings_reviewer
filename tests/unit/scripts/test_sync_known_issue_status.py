"""Unit tests for scripts/sync_known_issue_status.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "sync_known_issue_status.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("sync_known_issue_status", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_known_issue_status"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_fragment(tmp_path: Path, filename: str, frontmatter: dict[str, Any]) -> Path:
    """Write a minimal valid fragment file to tmp_path."""
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=True)
    content = f"---\n{fm_str}---\n\nBody text here.\n"
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


def _base_fm(
    id: int,
    slug: str,
    status: str = "open",
    autonomy: str = "safe",
    pr_refs: list[int] | None = None,
) -> dict[str, Any]:
    fm: dict[str, Any] = {
        "id": id,
        "source": "legacy",
        "slug": slug,
        "title": f"Issue {id}",
        "status": status,
        "severity": "low",
        "autonomy": autonomy,
        "estimated": "XS",
        "touches": ["src/foo.py"],
        "discovered": "2026-01-01",
        "updated": "2026-01-01",
        "note": f"test issue {id}",
    }
    if pr_refs is not None:
        fm["pr_refs"] = pr_refs
    return fm


def _make_gh_mock(state_by_ref: dict[int, str]) -> Any:
    """Return a mock for subprocess.run that simulates gh pr view responses."""

    def _fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        result = MagicMock()
        # cmd looks like: ['gh', 'pr', 'view', '<ref>', '--json', 'state', '-q', '.state']
        ref_idx = cmd.index("view") + 1 if "view" in cmd else None
        if ref_idx is not None:
            ref = int(cmd[ref_idx])
            if ref in state_by_ref:
                result.returncode = 0
                result.stdout = state_by_ref[ref] + "\n"
                result.stderr = ""
            else:
                result.returncode = 1
                result.stdout = ""
                result.stderr = "could not find PR"
        else:
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
        return result

    return _fake_run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNormalizeRef:
    def test_int(self) -> None:
        assert _mod._normalize_ref(107) == 107

    def test_string_with_hash(self) -> None:
        assert _mod._normalize_ref("#107") == 107

    def test_string_bare(self) -> None:
        assert _mod._normalize_ref("107") == 107

    def test_malformed_string(self) -> None:
        assert _mod._normalize_ref("abc") is None

    def test_none(self) -> None:
        assert _mod._normalize_ref(None) is None


class TestMainAllMerged:
    """Fragment (a): all pr_refs MERGED — should be updated."""

    def test_updates_fragment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_fragment(
            tmp_path,
            "legacy-001-all-merged.md",
            _base_fm(1, "all-merged", pr_refs=[101, 102]),
        )

        monkeypatch.setattr(
            "subprocess.run",
            _make_gh_mock({101: "MERGED", 102: "MERGED"}),
        )
        # no-op the regenerator subprocess call
        _regen_calls: list[list[str]] = []

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            if "regenerate_known_issues" in " ".join(str(c) for c in cmd):
                _regen_calls.append(cmd)
                result = MagicMock()
                result.returncode = 0
                return result
            return _make_gh_mock({101: "MERGED", 102: "MERGED"})(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", _patched_run)

        exit_code = _mod.main(["--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        text = (tmp_path / "legacy-001-all-merged.md").read_text()
        fm_block = text.split("---")[1]
        fm = yaml.safe_load(fm_block)
        assert fm["status"] == "resolved"
        assert fm["autonomy"] == "n/a"
        # updated should be today's ISO date
        import datetime

        assert fm["updated"] == datetime.date.today().isoformat()
        # Body preserved
        assert "Body text here." in text


class TestMainMixedState:
    """Fragment (b): one PR not MERGED — should NOT be updated."""

    def test_does_not_update(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_fragment(
            tmp_path,
            "legacy-002-mixed.md",
            _base_fm(2, "mixed", pr_refs=[201, 202]),
        )

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            if "regenerate_known_issues" in " ".join(str(c) for c in cmd):
                r = MagicMock()
                r.returncode = 0
                return r
            return _make_gh_mock({201: "MERGED", 202: "OPEN"})(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", _patched_run)

        exit_code = _mod.main(["--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        text = (tmp_path / "legacy-002-mixed.md").read_text()
        fm = yaml.safe_load(text.split("---")[1])
        assert fm["status"] == "open"  # unchanged


class TestMainNoPrRefs:
    """Fragment (c): no pr_refs — should be ignored."""

    def test_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_fragment(
            tmp_path,
            "legacy-003-no-refs.md",
            _base_fm(3, "no-refs"),  # no pr_refs key
        )

        gh_called = []

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            gh_called.append(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        monkeypatch.setattr("subprocess.run", _patched_run)

        exit_code = _mod.main(["--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        # gh should not be called at all for fragments without pr_refs
        gh_cmds = [c for c in gh_called if "gh" in " ".join(str(x) for x in c)]
        assert len(gh_cmds) == 0


class TestDryRun:
    """--dry-run must not mutate files."""

    def test_no_write_on_dry_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_fragment(
            tmp_path,
            "legacy-001-all-merged.md",
            _base_fm(1, "all-merged", pr_refs=[101]),
        )
        original_text = (tmp_path / "legacy-001-all-merged.md").read_text()

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            return _make_gh_mock({101: "MERGED"})(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", _patched_run)

        exit_code = _mod.main(["--dry-run", "--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        assert (tmp_path / "legacy-001-all-merged.md").read_text() == original_text


class TestMalformedPrRefs:
    """Malformed pr_refs entries are skipped with a warning, not a crash."""

    def test_skips_with_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # pr_refs with a bad entry — write raw YAML manually
        content = "---\nautonomy: safe\ndiscovered: '2026-01-01'\nestimated: XS\nid: 1\nnote: test\npr_refs:\n- not-a-number\nseverity: low\nslug: malformed\nsource: legacy\nstatus: open\ntitle: Issue 1\ntouches:\n- src/foo.py\nupdated: '2026-01-01'\n---\n\nBody.\n"
        (tmp_path / "legacy-001-malformed.md").write_text(content)

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            return r

        monkeypatch.setattr("subprocess.run", _patched_run)

        # Should not raise
        exit_code = _mod.main(["--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "malformed" in captured.err.lower() or "malformed" in captured.out.lower()
        # File should be unchanged
        assert "status: open" in (tmp_path / "legacy-001-malformed.md").read_text()


class TestAlreadyResolved:
    """Already-resolved fragments are skipped."""

    def test_skips_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_fragment(
            tmp_path,
            "legacy-001-already.md",
            _base_fm(1, "already", status="resolved", pr_refs=[101]),
        )

        gh_called = []

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            gh_called.append(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = "MERGED\n"
            r.stderr = ""
            return r

        monkeypatch.setattr("subprocess.run", _patched_run)

        exit_code = _mod.main(["--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        # gh should not be called for already-resolved fragments
        assert len(gh_called) == 0


class TestThreeFragmentsCombined:
    """Combined scenario: (a) all-merged, (b) mixed, (c) no pr_refs."""

    def test_only_a_is_updated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_fragment(
            tmp_path,
            "legacy-001-all-merged.md",
            _base_fm(1, "all-merged", pr_refs=[101]),
        )
        _write_fragment(
            tmp_path,
            "legacy-002-mixed.md",
            _base_fm(2, "mixed", pr_refs=[201, 202]),
        )
        _write_fragment(
            tmp_path,
            "legacy-003-no-refs.md",
            _base_fm(3, "no-refs"),
        )

        def _patched_run(cmd: list[str], **kwargs: Any) -> Any:
            if "regenerate_known_issues" in " ".join(str(c) for c in cmd):
                r = MagicMock()
                r.returncode = 0
                return r
            return _make_gh_mock({101: "MERGED", 201: "MERGED", 202: "OPEN"})(cmd, **kwargs)

        monkeypatch.setattr("subprocess.run", _patched_run)

        exit_code = _mod.main(["--fragments-dir", str(tmp_path)])
        assert exit_code == 0

        fm_a = yaml.safe_load((tmp_path / "legacy-001-all-merged.md").read_text().split("---")[1])
        fm_b = yaml.safe_load((tmp_path / "legacy-002-mixed.md").read_text().split("---")[1])
        fm_c = yaml.safe_load((tmp_path / "legacy-003-no-refs.md").read_text().split("---")[1])

        assert fm_a["status"] == "resolved"
        assert fm_b["status"] == "open"
        assert fm_c["status"] == "open"
