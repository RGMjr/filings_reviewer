"""Unit tests for scripts/regenerate_known_issues.py.

Byte-determinism of the rollup is the critical invariant — without it, the
pre-commit hook would auto-stage a different file on every run and loop.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def _load_module(name: str) -> Any:
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_validator = _load_module("validate_known_issues_fragments")
_regen = _load_module("regenerate_known_issues")

Fragment = _validator.Fragment
render_rollup = _regen.render_rollup
render_classification_table = _regen.render_classification_table
render_issue_body = _regen.render_issue_body
main = _regen.main


def _fragment(
    tmp_path: Path,
    *,
    id: int,
    title: str = "T",
    status: str = "open",
    severity: str = "medium",
    autonomy: str = "safe",
    estimated: str = "XS",
    touches: list[str] | None = None,
    note: str = "",
    source: str = "legacy",
    slug: str = "slug",
    body: str = "## Problem\n\nBody text.\n",
) -> Any:
    fm = {
        "id": id,
        "source": source,
        "slug": slug,
        "title": title,
        "status": status,
        "severity": severity,
        "autonomy": autonomy,
        "estimated": estimated,
        "touches": touches or [],
        "discovered": "2026-04-19",
        "updated": "2026-04-22",
    }
    if note:
        fm["note"] = note
    filename = f"{source}-{id:03d}-{slug}.md"
    return Fragment(frontmatter=fm, body=body, path=tmp_path / filename)


class TestRenderClassificationTable:
    def test_rows_sorted_by_id(self, tmp_path: Path) -> None:
        frags = [
            _fragment(tmp_path, id=74, slug="a", note="n74"),
            _fragment(tmp_path, id=68, slug="b", note="n68"),
            _fragment(tmp_path, id=71, slug="c", note="n71"),
        ]
        table = render_classification_table(frags)
        # Find the issue number rows
        lines = [ln for ln in table.splitlines() if ln.startswith("| #")]
        ids = [int(ln.split()[1].lstrip("#")) for ln in lines]
        assert ids == [68, 71, 74]

    def test_excludes_na_autonomy(self, tmp_path: Path) -> None:
        frags = [
            _fragment(tmp_path, id=1, slug="a", autonomy="safe", note="in"),
            _fragment(tmp_path, id=2, slug="b", autonomy="n/a", note="out"),
        ]
        table = render_classification_table(frags)
        assert "| #1 |" in table.replace("  ", " ")
        assert "| #2 |" not in table.replace("  ", " ")

    def test_touches_rendered_as_backticked_globs(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=5, slug="x", touches=["src/foo.py", "tests/bar/*"], note="n")
        table = render_classification_table([frag])
        assert "`src/foo.py` `tests/bar/*`" in table

    def test_empty_touches_renders_dash(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=5, slug="x", touches=[], note="n", autonomy="skip")
        table = render_classification_table([frag])
        assert "| — |" in table

    def test_gh_source_gets_gh_suffix(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=123, slug="x", source="gh", note="n")
        frag.frontmatter["gh_issue"] = 123
        table = render_classification_table([frag])
        assert "| #123 (GH) |" in table


class TestRenderRollup:
    def test_byte_deterministic(self, tmp_path: Path) -> None:
        frags = [
            _fragment(
                tmp_path, id=68, slug="nightly", note="n68", status="resolved", severity="medium"
            ),
            _fragment(tmp_path, id=74, slug="lock", note="n74", status="open", severity="low"),
        ]
        a = render_rollup(frags, "## Change Log\n\n- entry 1\n")
        b = render_rollup(frags, "## Change Log\n\n- entry 1\n")
        assert a == b

    def test_order_is_open_before_resolved(self, tmp_path: Path) -> None:
        frags = [
            _fragment(tmp_path, id=68, slug="a", status="resolved", severity="medium"),
            _fragment(tmp_path, id=74, slug="b", status="open", severity="medium"),
        ]
        out = render_rollup(frags, "")
        open_idx = out.index("## #74. T")
        resolved_idx = out.index("## #68. T")
        assert open_idx < resolved_idx

    def test_partially_resolved_between_open_and_archived(self, tmp_path: Path) -> None:
        frags = [
            _fragment(tmp_path, id=1, slug="a", status="open"),
            _fragment(tmp_path, id=2, slug="b", status="partially-resolved"),
            _fragment(tmp_path, id=3, slug="c", status="archived"),
            _fragment(tmp_path, id=4, slug="d", status="resolved"),
        ]
        out = render_rollup(frags, "")
        idxs = [out.index(f"## #{n}. T") for n in (1, 2, 3, 4)]
        assert idxs == sorted(idxs)

    def test_higher_severity_first_within_status(self, tmp_path: Path) -> None:
        frags = [
            _fragment(tmp_path, id=1, slug="a", status="open", severity="low"),
            _fragment(tmp_path, id=2, slug="b", status="open", severity="high"),
            _fragment(tmp_path, id=3, slug="c", status="open", severity="medium"),
        ]
        out = render_rollup(frags, "")
        idxs = [out.index(f"## #{n}. T") for n in (2, 3, 1)]
        assert idxs == sorted(idxs)

    def test_no_trailing_whitespace(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=1, slug="a", body="## X\n\ncontent\n")
        out = render_rollup([frag], "")
        for line in out.splitlines():
            assert line == line.rstrip(), f"trailing whitespace in: {line!r}"

    def test_single_trailing_newline(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=1, slug="a")
        out = render_rollup([frag], "")
        assert out.endswith("\n")
        assert not out.endswith("\n\n")

    def test_banner_present(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=1, slug="a")
        out = render_rollup([frag], "")
        assert out.startswith("<!-- AUTO-GENERATED")

    def test_fragment_validation_failures_raise(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=1, slug="a")
        frag.frontmatter["status"] = "bogus"
        with pytest.raises(ValueError, match="failed validation"):
            render_rollup([frag], "")

    def test_changelog_appended_when_nonempty(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=1, slug="a")
        out = render_rollup([frag], "## Change Log\n\n- 2026-04-22: something\n")
        assert "## Change Log" in out
        assert "2026-04-22: something" in out

    def test_empty_changelog_omitted(self, tmp_path: Path) -> None:
        frag = _fragment(tmp_path, id=1, slug="a")
        out = render_rollup([frag], "")
        assert "## Change Log" not in out


class TestMainCheckMode:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path]:
        fragments_dir = tmp_path / "frags"
        fragments_dir.mkdir()
        (fragments_dir / "legacy-001-a.md").write_text(
            textwrap.dedent(
                """\
                ---
                id: 1
                source: legacy
                slug: a
                title: Alpha
                status: open
                severity: medium
                autonomy: safe
                estimated: XS
                touches:
                  - src/a.py
                discovered: 2026-04-19
                updated: 2026-04-22
                note: Alpha note
                ---

                ## Problem

                Alpha body.
                """
            ),
            encoding="utf-8",
        )
        output = tmp_path / "rollup.md"
        return fragments_dir, output

    def test_check_exits_0_when_fresh(self, tmp_path: Path) -> None:
        fragments_dir, output = self._setup(tmp_path)
        # First write
        rc = main(["--fragments-dir", str(fragments_dir), "--output", str(output)])
        assert rc == 0
        # Then check
        rc = main(["--fragments-dir", str(fragments_dir), "--output", str(output), "--check"])
        assert rc == 0

    def test_check_exits_1_when_stale(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        fragments_dir, output = self._setup(tmp_path)
        output.write_text("stale content\n", encoding="utf-8")
        rc = main(["--fragments-dir", str(fragments_dir), "--output", str(output), "--check"])
        assert rc == 1
        assert "DRIFT" in capsys.readouterr().err

    def test_check_exits_1_when_missing(self, tmp_path: Path) -> None:
        fragments_dir, output = self._setup(tmp_path)
        # output does not exist
        rc = main(["--fragments-dir", str(fragments_dir), "--output", str(output), "--check"])
        assert rc == 1

    def test_write_twice_is_idempotent(self, tmp_path: Path) -> None:
        fragments_dir, output = self._setup(tmp_path)
        main(["--fragments-dir", str(fragments_dir), "--output", str(output)])
        first = output.read_bytes()
        main(["--fragments-dir", str(fragments_dir), "--output", str(output)])
        second = output.read_bytes()
        assert first == second


class TestMainValidateMode:
    def _write_valid_fragment(self, fragments_dir: Path) -> None:
        (fragments_dir / "legacy-001-a.md").write_text(
            textwrap.dedent(
                """\
                ---
                id: 1
                source: legacy
                slug: a
                title: Alpha
                status: open
                severity: medium
                autonomy: safe
                estimated: XS
                touches:
                  - src/a.py
                discovered: 2026-04-19
                updated: 2026-04-22
                note: Alpha note
                ---

                ## Problem

                Alpha body.
                """
            ),
            encoding="utf-8",
        )

    def test_validate_exits_0_on_clean_fragments(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fragments_dir = tmp_path / "frags"
        fragments_dir.mkdir()
        self._write_valid_fragment(fragments_dir)
        rc = main(["--fragments-dir", str(fragments_dir), "--validate"])
        assert rc == 0
        assert "OK: 1 fragment(s) validated" in capsys.readouterr().out

    def test_validate_exits_1_on_invalid_frontmatter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fragments_dir = tmp_path / "frags"
        fragments_dir.mkdir()
        (fragments_dir / "legacy-001-a.md").write_text(
            textwrap.dedent(
                """\
                ---
                id: 1
                source: legacy
                slug: a
                title: Alpha
                status: bogus-status
                severity: medium
                autonomy: safe
                estimated: XS
                touches: []
                discovered: 2026-04-19
                updated: 2026-04-22
                ---

                Body.
                """
            ),
            encoding="utf-8",
        )
        rc = main(["--fragments-dir", str(fragments_dir), "--validate"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "failed validation" in err

    def test_validate_does_not_write_rollup(self, tmp_path: Path) -> None:
        fragments_dir = tmp_path / "frags"
        fragments_dir.mkdir()
        self._write_valid_fragment(fragments_dir)
        output = tmp_path / "rollup.md"
        rc = main(["--fragments-dir", str(fragments_dir), "--output", str(output), "--validate"])
        assert rc == 0
        assert not output.exists(), "--validate must not write the rollup"
