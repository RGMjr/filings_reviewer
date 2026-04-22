"""Unit tests for scripts/known_issues_selector.py.

Uses importlib.util.spec_from_file_location so that scripts/__init__.py is not required.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "known_issues_selector.py"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRAGMENTS_DIR = _REPO_ROOT / "docs" / "known-issues"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("known_issues_selector", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["known_issues_selector"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
parse_classification_from_fragments = _mod.parse_classification_from_fragments
touches_collide = _mod.touches_collide
select_picks = _mod.select_picks
IssueRecord = _mod.IssueRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_fragment(tmp_path: Path, filename: str, frontmatter: dict[str, Any]) -> Path:
    """Write a minimal valid fragment file to tmp_path."""
    import yaml

    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n\nBody text.\n"
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


def _base_fm(
    id: int,
    slug: str,
    autonomy: str = "safe",
    status: str = "open",
    estimated: str = "XS",
    touches: list[str] | None = None,
    note: str = "",
    source: str = "legacy",
) -> dict[str, Any]:
    return {
        "id": id,
        "source": source,
        "slug": slug,
        "title": f"Issue {id}",
        "status": status,
        "severity": "low",
        "autonomy": autonomy,
        "estimated": estimated,
        "touches": touches if touches is not None else [f"src/mod_{id}.py"],
        "discovered": "2026-01-01",
        "updated": "2026-01-01",
        "note": note,
    }


# ---------------------------------------------------------------------------
# TestTouchesCollide — unchanged function; keep tests
# ---------------------------------------------------------------------------


class TestTouchesCollide:
    def test_same_file_collides(self) -> None:
        assert touches_collide(("src/a.py",), ("src/a.py",))

    def test_disjoint_dirs_do_not_collide(self) -> None:
        assert not touches_collide(("src/a/*",), ("src/b/*",))

    def test_prefix_overlap_collides(self) -> None:
        assert touches_collide(("src/a/foo.py",), ("src/a/*",))

    def test_empty_touches_does_not_collide(self) -> None:
        assert not touches_collide((), ("src/a.py",))
        assert not touches_collide(("src/a.py",), ())


# ---------------------------------------------------------------------------
# TestSelectPicks — unchanged function; keep tests (uses inline IssueRecords)
# ---------------------------------------------------------------------------


def _make_records() -> list:
    """Build a synthetic record list matching the original TABLE_SNIPPET shape."""
    return [
        IssueRecord(
            issue=1, autonomy="safe", estimated="XS", touches=("src/a/mod_a.py",), note="Alpha"
        ),
        IssueRecord(
            issue=2,
            autonomy="safe",
            estimated="S",
            touches=("tests/integration/web/test_foo.py",),
            note="Bravo",
        ),
        IssueRecord(
            issue=3,
            autonomy="review",
            estimated="M",
            touches=("src/b/mod_b.py", "tests/unit/b/*"),
            note="Charlie",
        ),
        IssueRecord(issue=4, autonomy="skip", estimated="L", touches=(), note="Delta"),
        IssueRecord(
            issue=5,
            autonomy="safe",
            estimated="XS",
            touches=("src/a/mod_a.py",),
            note="Echo — collides with #1",
        ),
    ]


class TestSelectPicks:
    def test_safe_only_by_default(self) -> None:
        picks = select_picks(_make_records(), max_n=5, include_review=False, open_pr_refs=set())
        assert [p.issue for p in picks] == [1, 2]  # #5 collides with #1

    def test_include_review_adds_review_picks(self) -> None:
        picks = select_picks(_make_records(), max_n=5, include_review=True, open_pr_refs=set())
        assert [p.issue for p in picks] == [1, 2, 3]

    def test_max_caps_results(self) -> None:
        picks = select_picks(_make_records(), max_n=1, include_review=False, open_pr_refs=set())
        assert [p.issue for p in picks] == [1]

    def test_open_pr_refs_exclude_issue(self) -> None:
        picks = select_picks(_make_records(), max_n=5, include_review=False, open_pr_refs={1})
        # #1 excluded → #5 no longer collides → #5 takes its slot
        assert [p.issue for p in picks] == [2, 5]

    def test_skip_never_picked(self) -> None:
        picks = select_picks(_make_records(), max_n=10, include_review=True, open_pr_refs=set())
        assert 4 not in {p.issue for p in picks}

    def test_collision_drops_second_pick(self) -> None:
        picks = select_picks(_make_records(), max_n=10, include_review=False, open_pr_refs=set())
        issues = {p.issue for p in picks}
        # #1 and #5 both touch src/a/mod_a.py — only one should be in picks
        assert not ({1, 5}.issubset(issues))

    def test_safe_comes_before_review(self) -> None:
        picks = select_picks(_make_records(), max_n=10, include_review=True, open_pr_refs=set())
        autonomies = [p.autonomy for p in picks]
        # safe entries must all appear before review entries
        last_safe = max((i for i, a in enumerate(autonomies) if a == "safe"), default=-1)
        first_review = min(
            (i for i, a in enumerate(autonomies) if a == "review"), default=len(autonomies)
        )
        assert last_safe < first_review

    def test_records_without_touches_are_excluded(self) -> None:
        # A safe record with no Touches cannot be scoped by the sweeper → skip.
        record = IssueRecord(issue=99, autonomy="safe", estimated="XS", touches=(), note="no globs")
        picks = select_picks([record], max_n=1, include_review=False, open_pr_refs=set())
        assert picks == []


# ---------------------------------------------------------------------------
# TestParseClassificationFromFragments
# ---------------------------------------------------------------------------


class TestParseClassificationFromFragments:
    def test_skips_na_autonomy(self, tmp_path: Path) -> None:
        _write_fragment(
            tmp_path, "legacy-10-some-issue.md", _base_fm(10, "some-issue", autonomy="n/a")
        )
        records = parse_classification_from_fragments(tmp_path)
        assert records == []

    def test_skips_resolved(self, tmp_path: Path) -> None:
        """Regression test for issue #79: resolved fragments must not be picked."""
        _write_fragment(
            tmp_path,
            "legacy-20-resolved-issue.md",
            _base_fm(20, "resolved-issue", autonomy="safe", status="resolved"),
        )
        records = parse_classification_from_fragments(tmp_path)
        assert records == []

    def test_skips_archived(self, tmp_path: Path) -> None:
        _write_fragment(
            tmp_path,
            "legacy-21-archived-issue.md",
            _base_fm(21, "archived-issue", autonomy="safe", status="archived"),
        )
        records = parse_classification_from_fragments(tmp_path)
        assert records == []

    def test_emits_open_and_partially_resolved(self, tmp_path: Path) -> None:
        _write_fragment(
            tmp_path, "legacy-30-open-issue.md", _base_fm(30, "open-issue", status="open")
        )
        _write_fragment(
            tmp_path,
            "legacy-31-partial-issue.md",
            _base_fm(31, "partial-issue", status="partially-resolved"),
        )
        records = parse_classification_from_fragments(tmp_path)
        ids = {r.issue for r in records}
        assert 30 in ids
        assert 31 in ids

    def test_preserves_issue_record_shape(self, tmp_path: Path) -> None:
        _write_fragment(
            tmp_path,
            "legacy-40-shaped-issue.md",
            _base_fm(
                40,
                "shaped-issue",
                autonomy="review",
                estimated="M",
                touches=["src/foo.py"],
                note="my note",
            ),
        )
        records = parse_classification_from_fragments(tmp_path)
        assert len(records) == 1
        r = records[0]
        assert r.issue == 40
        assert r.autonomy == "review"
        assert r.estimated == "M"
        assert r.note == "my note"
        assert isinstance(r.issue, int)
        assert isinstance(r.autonomy, str)
        assert isinstance(r.estimated, str)
        assert isinstance(r.note, str)

    def test_touches_tuple_not_list(self, tmp_path: Path) -> None:
        """IssueRecord.touches must be a tuple (hashable, required for collision check)."""
        _write_fragment(
            tmp_path,
            "legacy-50-tuple-issue.md",
            _base_fm(50, "tuple-issue", touches=["src/a.py", "src/b.py"]),
        )
        records = parse_classification_from_fragments(tmp_path)
        assert len(records) == 1
        assert isinstance(records[0].touches, tuple)

    def test_missing_fragments_dir_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "no-such-dir"
        with pytest.raises(FileNotFoundError):
            parse_classification_from_fragments(missing)


# ---------------------------------------------------------------------------
# TestFragmentParityWithMainBaseline
# ---------------------------------------------------------------------------


class TestFragmentParityWithMainBaseline:
    """Real-repo structural parity test: run the selector against the live fragments
    and verify the output has correct shape and no resolved/archived issues."""

    def test_dry_run_produces_valid_output(self) -> None:
        """Selector should run without errors against the real fragment directory."""
        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--dry-run",
                "--no-pr-dedupe",
                "--fragments-dir",
                str(_FRAGMENTS_DIR),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"selector failed:\n{result.stderr}"
        assert "Classification totals:" in result.stdout
        assert "Picks" in result.stdout

    def test_json_output_is_valid_and_nonempty(self) -> None:
        """JSON output must be parseable and contain at least one pick."""
        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--no-pr-dedupe",
                "--fragments-dir",
                str(_FRAGMENTS_DIR),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"selector failed:\n{result.stderr}"
        picks = json.loads(result.stdout)
        assert isinstance(picks, list)
        assert len(picks) > 0, "Expected at least one pick from the real fragment directory"

    def test_json_output_schema_matches_contract(self) -> None:
        """Each pick must have the fields run_nightly_sweep.sh expects."""
        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--no-pr-dedupe",
                "--fragments-dir",
                str(_FRAGMENTS_DIR),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        picks = json.loads(result.stdout)
        for pick in picks:
            assert "issue" in pick and isinstance(pick["issue"], int)
            assert "autonomy" in pick and isinstance(pick["autonomy"], str)
            assert "estimated" in pick and isinstance(pick["estimated"], str)
            assert "touches" in pick and isinstance(pick["touches"], list)
            assert "note" in pick and isinstance(pick["note"], str)

    def test_no_resolved_or_archived_in_picks(self) -> None:
        """Core regression for #79: resolved/archived fragments must never appear in picks."""
        import yaml

        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--no-pr-dedupe",
                "--max",
                "10",
                "--include-review",
                "--fragments-dir",
                str(_FRAGMENTS_DIR),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        picks = json.loads(result.stdout)
        picked_ids = {p["issue"] for p in picks}

        # Build a map from id → status from fragment files.
        id_to_status: dict[int, str] = {}
        for frag_path in _FRAGMENTS_DIR.glob("*.md"):
            if frag_path.name == "CHANGELOG.md":
                continue
            text = frag_path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue
            fm_text = text[4 : text.find("\n---\n", 4)]
            fm = yaml.safe_load(fm_text) or {}
            if isinstance(fm, dict) and "id" in fm:
                id_to_status[int(fm["id"])] = str(fm.get("status") or "")

        for issue_id in picked_ids:
            status = id_to_status.get(issue_id, "unknown")
            assert status not in {"resolved", "archived"}, (
                f"Issue #{issue_id} has status={status!r} but appeared in picks — "
                "selector should filter out resolved/archived fragments (issue #79)"
            )
