"""Unit tests for scripts/known_issues_selector.py.

Uses importlib.util.spec_from_file_location so that scripts/__init__.py is not required.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "known_issues_selector.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("known_issues_selector", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["known_issues_selector"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
parse_classification_table = _mod.parse_classification_table
touches_collide = _mod.touches_collide
select_picks = _mod.select_picks
IssueRecord = _mod.IssueRecord


TABLE_SNIPPET = """\
# Known Issues

## Nightly Sweeper Classification

Preamble text.

| Issue | Autonomy | Estimated | Touches                                              | Note                                |
|-------|----------|-----------|------------------------------------------------------|-------------------------------------|
| #1    | safe     | XS        | `src/a/mod_a.py`                                     | Alpha                               |
| #2    | safe     | S         | `tests/integration/web/test_foo.py`                  | Bravo                               |
| #3    | review   | M         | `src/b/mod_b.py tests/unit/b/*`                      | Charlie                             |
| #4    | skip     | L         | —                                                    | Delta                               |
| #5    | safe     | XS        | `src/a/mod_a.py`                                     | Echo — collides with #1             |

## Next Section

Unrelated content.
"""


class TestParseClassificationTable:
    def test_parses_all_non_skip_and_skip_rows(self) -> None:
        records = parse_classification_table(TABLE_SNIPPET)
        issues = sorted(r.issue for r in records)
        assert issues == [1, 2, 3, 4, 5]

    def test_parses_autonomy_values(self) -> None:
        records = {r.issue: r for r in parse_classification_table(TABLE_SNIPPET)}
        assert records[1].autonomy == "safe"
        assert records[3].autonomy == "review"
        assert records[4].autonomy == "skip"

    def test_parses_touches_globs(self) -> None:
        records = {r.issue: r for r in parse_classification_table(TABLE_SNIPPET)}
        assert records[3].touches == ("src/b/mod_b.py", "tests/unit/b/*")
        assert records[4].touches == ()  # em-dash → empty

    def test_raises_on_missing_heading(self) -> None:
        with pytest.raises(ValueError, match="Missing"):
            parse_classification_table("# Just a document\n\nNo table here.")

    def test_raises_on_bad_autonomy_value(self) -> None:
        bad = TABLE_SNIPPET.replace("| safe     | XS", "| maybe    | XS", 1)
        with pytest.raises(ValueError, match="unknown Autonomy"):
            parse_classification_table(bad)

    def test_stops_at_next_heading(self) -> None:
        records = parse_classification_table(TABLE_SNIPPET)
        assert all(r.issue <= 5 for r in records)


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


class TestSelectPicks:
    def _records(self) -> list:
        return parse_classification_table(TABLE_SNIPPET)

    def test_safe_only_by_default(self) -> None:
        picks = select_picks(self._records(), max_n=5, include_review=False, open_pr_refs=set())
        assert [p.issue for p in picks] == [1, 2]  # #5 collides with #1

    def test_include_review_adds_review_picks(self) -> None:
        picks = select_picks(self._records(), max_n=5, include_review=True, open_pr_refs=set())
        assert [p.issue for p in picks] == [1, 2, 3]

    def test_max_caps_results(self) -> None:
        picks = select_picks(self._records(), max_n=1, include_review=False, open_pr_refs=set())
        assert [p.issue for p in picks] == [1]

    def test_open_pr_refs_exclude_issue(self) -> None:
        picks = select_picks(self._records(), max_n=5, include_review=False, open_pr_refs={1})
        # #1 excluded → #5 no longer collides → #5 takes its slot
        assert [p.issue for p in picks] == [2, 5]

    def test_skip_never_picked(self) -> None:
        picks = select_picks(self._records(), max_n=10, include_review=True, open_pr_refs=set())
        assert 4 not in {p.issue for p in picks}

    def test_collision_drops_second_pick(self) -> None:
        picks = select_picks(self._records(), max_n=10, include_review=False, open_pr_refs=set())
        issues = {p.issue for p in picks}
        # #1 and #5 both touch src/a/mod_a.py — only one should be in picks
        assert not ({1, 5}.issubset(issues))

    def test_safe_comes_before_review(self) -> None:
        picks = select_picks(self._records(), max_n=10, include_review=True, open_pr_refs=set())
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
