"""Unit tests for scripts/validate_known_issues_fragments.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
_SCRIPT_PATH = _SCRIPTS_DIR / "validate_known_issues_fragments.py"


def _load_module() -> Any:
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("validate_known_issues_fragments", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_known_issues_fragments"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _load_module()
parse_fragment = _mod.parse_fragment
validate_fragment = _mod.validate_fragment
load_all_fragments = _mod.load_all_fragments
Fragment = _mod.Fragment
# Captured before any monkeypatching can happen, so the missing-allow-list test
# can call the real loader (bypassing both lru_cache and the autouse fixture).
_REAL_LOAD_ALLOWLIST = _mod._load_legacy_allowlist.__wrapped__


class _AlwaysContains:
    def __contains__(self, item: object) -> bool:
        return True


@pytest.fixture(autouse=True)
def _permissive_legacy_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to permissive allow-list so existing tests using synthesized
    legacy- filenames don't trip the new namespace-freeze check. Tests that
    exercise the allow-list explicitly override this by patching again."""
    monkeypatch.setattr(_mod, "_load_legacy_allowlist", lambda *a, **kw: _AlwaysContains())


VALID_FRAGMENT = """\
---
id: 68
source: legacy
slug: nightly-sweeper-macos-timeout
title: Nightly Sweeper Orchestrator Uses GNU timeout
status: resolved
severity: medium
autonomy: safe
estimated: XS
touches:
  - scripts/run_nightly_sweep.sh
discovered: 2026-04-19
updated: 2026-04-22
pr_refs: [107]
note: Detect timeout vs gtimeout; fallback path for macOS
---

## Problem

Body text here.
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestParseFragment:
    def test_parses_valid_fragment(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "legacy-068-nightly-sweeper-macos-timeout.md", VALID_FRAGMENT)
        f = parse_fragment(p)
        assert f.id == 68
        assert f.source == "legacy"
        assert f.frontmatter["autonomy"] == "safe"
        assert "## Problem" in f.body

    def test_missing_opening_fence_raises(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "legacy-001-foo.md", "no fence\n## Body\n")
        with pytest.raises(ValueError, match="missing opening frontmatter fence"):
            parse_fragment(p)

    def test_missing_closing_fence_raises(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "legacy-001-foo.md", "---\nid: 1\n\nno closing fence\n")
        with pytest.raises(ValueError, match="missing closing frontmatter fence"):
            parse_fragment(p)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "legacy-001-foo.md", "---\nid: [unbalanced\n---\nbody\n")
        with pytest.raises(ValueError, match="invalid YAML"):
            parse_fragment(p)

    def test_non_mapping_frontmatter_raises(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "legacy-001-foo.md", "---\n- just a list\n---\nbody\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            parse_fragment(p)


class TestValidateFragment:
    def _base_frontmatter(self) -> dict:
        return {
            "id": 68,
            "source": "legacy",
            "slug": "nightly-sweeper-macos-timeout",
            "title": "T",
            "status": "resolved",
            "severity": "medium",
            "autonomy": "safe",
            "estimated": "XS",
            "touches": ["scripts/run_nightly_sweep.sh"],
            "discovered": "2026-04-19",
            "updated": "2026-04-22",
        }

    def _make(self, frontmatter: dict, path: Path) -> Any:
        return Fragment(frontmatter=frontmatter, body="b", path=path)

    def test_valid_fragment_passes(self, tmp_path: Path) -> None:
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        f = self._make(self._base_frontmatter(), p)
        assert validate_fragment(f) == []

    def test_missing_required_field(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        del fm["touches"]
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("missing required field" in e and "'touches'" in e for e in errors)

    def test_invalid_status(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["status"] = "in-progress"
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("'status'" in e for e in errors)

    def test_invalid_autonomy(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["autonomy"] = "yolo"
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("'autonomy'" in e for e in errors)

    def test_invalid_estimated(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["estimated"] = "XL"
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("'estimated'" in e for e in errors)

    def test_touches_not_list(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["touches"] = "scripts/foo.sh"
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("'touches'" in e for e in errors)

    def test_filename_id_must_match_frontmatter(self, tmp_path: Path) -> None:
        p = tmp_path / "legacy-999-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(self._base_frontmatter(), p))
        assert any("filename id 999 does not match" in e for e in errors)

    def test_filename_source_must_match(self, tmp_path: Path) -> None:
        p = tmp_path / "gh-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(self._base_frontmatter(), p))
        assert any("filename source 'gh' does not match" in e for e in errors)

    def test_filename_slug_must_match(self, tmp_path: Path) -> None:
        p = tmp_path / "legacy-068-other-slug.md"
        errors = validate_fragment(self._make(self._base_frontmatter(), p))
        assert any("filename slug" in e for e in errors)

    def test_bad_filename_format(self, tmp_path: Path) -> None:
        p = tmp_path / "68-no-prefix.md"
        errors = validate_fragment(self._make(self._base_frontmatter(), p))
        assert any("filename must match pattern" in e for e in errors)

    def test_gh_source_requires_gh_issue(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["source"] = "gh"
        fm["id"] = 123
        fm["slug"] = "my-gh-issue"
        p = tmp_path / "gh-123-my-gh-issue.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("'gh_issue' must be set when source is 'gh'" in e for e in errors)

    def test_invalid_date_string(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["discovered"] = "April 19 2026"
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("'discovered'" in e for e in errors)

    def test_accepts_yaml_date_objects(self, tmp_path: Path) -> None:
        from datetime import date as _date

        fm = self._base_frontmatter()
        fm["discovered"] = _date(2026, 4, 19)
        fm["updated"] = _date(2026, 4, 22)
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        assert validate_fragment(self._make(fm, p)) == []

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        fm = self._base_frontmatter()
        fm["rogue"] = "value"
        p = tmp_path / "legacy-068-nightly-sweeper-macos-timeout.md"
        errors = validate_fragment(self._make(fm, p))
        assert any("unknown field" in e for e in errors)


class TestLoadAllFragments:
    def test_loads_sorted_and_skips_changelog(self, tmp_path: Path) -> None:
        (tmp_path / "CHANGELOG.md").write_text("# CL\n", encoding="utf-8")
        names = [
            ("legacy-002-alpha.md", 2),
            ("legacy-010-beta.md", 10),
            ("legacy-005-gamma.md", 5),
        ]
        for name, issue_id in names:
            slug = name.split("-", 2)[2].removesuffix(".md")
            content = (
                VALID_FRAGMENT.replace("id: 68", f"id: {issue_id}")
                .replace("slug: nightly-sweeper-macos-timeout", f"slug: {slug}")
                .replace("status: resolved", "status: open")
            )
            (tmp_path / name).write_text(content, encoding="utf-8")

        frags = load_all_fragments(tmp_path)
        assert [f.id for f in frags] == [2, 5, 10]

    def test_duplicate_id_raises(self, tmp_path: Path) -> None:
        for name, slug in [
            ("legacy-073-first.md", "first"),
            ("legacy-073-second.md", "second"),
        ]:
            content = (
                VALID_FRAGMENT.replace("id: 68", "id: 73")
                .replace("slug: nightly-sweeper-macos-timeout", f"slug: {slug}")
                .replace("status: resolved", "status: open")
            )
            (tmp_path / name).write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate fragment for legacy#73"):
            load_all_fragments(tmp_path)


class TestLegacyAllowlist:
    """Enforce that new `legacy-*` filenames are rejected; only frozen names pass."""

    def _base_fm(self, *, source: str = "legacy", issue_id: int = 68, slug: str = "frozen-fragment") -> dict:
        fm = {
            "id": issue_id,
            "source": source,
            "slug": slug,
            "title": "T",
            "status": "open",
            "severity": "medium",
            "autonomy": "skip",
            "estimated": "XS",
            "touches": ["x"],
            "discovered": "2026-04-19",
            "updated": "2026-04-22",
        }
        if source == "gh":
            fm["gh_issue"] = issue_id
        return fm

    def test_listed_legacy_filename_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _mod, "_load_legacy_allowlist",
            lambda *a, **kw: frozenset({"legacy-068-frozen-fragment.md"}),
        )
        p = tmp_path / "legacy-068-frozen-fragment.md"
        f = Fragment(frontmatter=self._base_fm(), body="b", path=p)
        assert validate_fragment(f) == []

    def test_unlisted_legacy_filename_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _mod, "_load_legacy_allowlist",
            lambda *a, **kw: frozenset({"legacy-068-frozen-fragment.md"}),
        )
        p = tmp_path / "legacy-999-not-in-list.md"
        fm = self._base_fm(issue_id=999, slug="not-in-list")
        errors = validate_fragment(Fragment(frontmatter=fm, body="b", path=p))
        assert any("new 'legacy-*' filenames are not allowed" in e for e in errors)

    def test_gh_filename_passes_regardless_of_allowlist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _mod, "_load_legacy_allowlist", lambda *a, **kw: frozenset(),
        )
        fm = self._base_fm(source="gh", issue_id=300, slug="my-issue")
        p = tmp_path / "gh-300-my-issue.md"
        assert validate_fragment(Fragment(frontmatter=fm, body="b", path=p)) == []

    def test_missing_allowlist_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="legacy allow-list missing"):
            _REAL_LOAD_ALLOWLIST(tmp_path / "does-not-exist.txt")
