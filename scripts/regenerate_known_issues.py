#!/usr/bin/env python3
"""Regenerate docs/KNOWN_ISSUES.md from docs/known-issues/ fragment files.

The rollup is a deterministic function of the fragment set + CHANGELOG.md.
Calling this twice with the same input must produce byte-identical output,
so pre-commit can safely auto-stage the regenerated file without looping.

Usage:
    python3 scripts/regenerate_known_issues.py                    # write rollup
    python3 scripts/regenerate_known_issues.py --check            # exit 1 on drift
    python3 scripts/regenerate_known_issues.py --stage            # `git add` rollup
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from validate_known_issues_fragments import (  # noqa: E402
    DEFAULT_FRAGMENTS_DIR,
    Fragment,
    load_all_fragments,
    validate_fragment,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROLLUP_PATH = REPO_ROOT / "docs" / "KNOWN_ISSUES.md"
DEFAULT_CHANGELOG_PATH = DEFAULT_FRAGMENTS_DIR / "CHANGELOG.md"

STATUS_RANK: dict[str, int] = {
    "open": 0,
    "partially-resolved": 1,
    "archived": 2,
    "resolved": 3,
}
SEVERITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2, "n/a": 3}

STATUS_LABELS: dict[str, str] = {
    "open": "Open",
    "partially-resolved": "Partially Resolved",
    "archived": "Archived",
    "resolved": "Resolved",
}

BANNER = (
    "<!-- AUTO-GENERATED — do not edit directly. "
    "Edit fragments in docs/known-issues/ and run scripts/regenerate_known_issues.py. -->\n"
)
TITLE = "# Known Issues\n"


def _fmt_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fmt_touches_cell(touches: list[str]) -> str:
    if not touches:
        return "—"
    return " ".join(f"`{t}`" for t in touches)


def _issue_label(fragment: Fragment) -> str:
    if fragment.source == "gh":
        return f"#{fragment.id} (GH)"
    return f"#{fragment.id}"


def _sort_key(fragment: Fragment) -> tuple[int, int, int]:
    status_rank = STATUS_RANK.get(fragment.status, 99)
    severity = str(fragment.frontmatter.get("severity", "n/a"))
    severity_rank = SEVERITY_RANK.get(severity, 99)
    return (status_rank, severity_rank, fragment.id)


def render_classification_table(fragments: list[Fragment]) -> str:
    """Render the Nightly Sweeper Classification table.

    Rows are sorted ascending by numeric id. Only issues with autonomy in
    {safe, review, skip} are included (not n/a).
    """
    rows = sorted(
        (f for f in fragments if f.frontmatter.get("autonomy") in {"safe", "review", "skip"}),
        key=lambda f: (f.source, f.id),
    )
    lines: list[str] = [
        "## Nightly Sweeper Classification",
        "",
        "| Issue | Autonomy | Estimated | Touches | Note |",
        "|-------|----------|-----------|---------|------|",
    ]
    for f in rows:
        touches = list(f.frontmatter.get("touches") or [])
        note = str(f.frontmatter.get("note") or "").replace("|", r"\|")
        lines.append(
            f"| {_issue_label(f)} "
            f"| {f.frontmatter['autonomy']} "
            f"| {f.frontmatter['estimated']} "
            f"| {_fmt_touches_cell(touches)} "
            f"| {note} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary(fragments: list[Fragment]) -> str:
    """Render the Summary section: status + severity counts."""
    by_status: dict[str, int] = {}
    for f in fragments:
        by_status[f.status] = by_status.get(f.status, 0) + 1

    lines: list[str] = ["## Summary", ""]
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    for status in ("open", "partially-resolved", "archived", "resolved"):
        if status in by_status:
            lines.append(f"| {STATUS_LABELS[status]} | {by_status[status]} |")
    lines.append("")
    return "\n".join(lines)


def render_issue_body(fragment: Fragment) -> str:
    """Render one issue section: heading + metadata block + body."""
    fm = fragment.frontmatter
    label = _issue_label(fragment)
    lines: list[str] = [
        f"## {label}. {fm['title']}",
        "",
        f"**Status**: {STATUS_LABELS.get(fragment.status, fragment.status)}  ",
        f"**Severity**: {fm.get('severity', 'n/a')}  ",
        f"**Discovered**: {_fmt_date(fm.get('discovered', ''))}  ",
        f"**Updated**: {_fmt_date(fm.get('updated', ''))}  ",
    ]
    pr_refs = fm.get("pr_refs") or []
    if pr_refs:
        lines.append(f"**PR refs**: {', '.join(f'#{n}' for n in pr_refs)}  ")
    gh_issue = fm.get("gh_issue")
    if gh_issue is not None:
        lines.append(f"**GH issue**: #{gh_issue}  ")
    lines.append("")
    body = fragment.body.strip("\n")
    if body:
        lines.append(body)
    return "\n".join(lines) + "\n"


def render_rollup(fragments: list[Fragment], changelog: str) -> str:
    """Produce the full rollup markdown. Byte-deterministic given inputs."""
    for f in fragments:
        errors = validate_fragment(f)
        if errors:
            raise ValueError(f"fragment {f.path} failed validation: {errors}")

    ordered = sorted(fragments, key=_sort_key)

    parts: list[str] = [BANNER, TITLE, ""]
    parts.append(render_summary(ordered))
    parts.append("")
    parts.append(render_classification_table(ordered))
    parts.append("")

    current_status: str | None = None
    for f in ordered:
        if f.status != current_status:
            current_status = f.status
            parts.append(f"## {STATUS_LABELS.get(f.status, f.status)} Issues")
            parts.append("")
        parts.append(render_issue_body(f))

    if changelog.strip():
        parts.append("")
        parts.append(changelog.strip("\n"))
        parts.append("")

    text = "\n".join(parts)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = text.rstrip("\n") + "\n"
    return text


def _git_add(path: Path) -> None:
    try:
        subprocess.run(
            ["git", "add", str(path)],
            check=True,
            cwd=REPO_ROOT,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"WARN: failed to `git add {path}`: {exc.stderr.decode(errors='replace').strip()}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        default=DEFAULT_FRAGMENTS_DIR,
        help="Directory containing fragment files (default: docs/known-issues)",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=None,
        help="CHANGELOG.md singleton path (default: <fragments-dir>/CHANGELOG.md)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_ROLLUP_PATH,
        help="Rollup output path (default: docs/KNOWN_ISSUES.md)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if the on-disk rollup would change (no write)",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help="After writing, run `git add <output>` (for pre-commit hook use)",
    )
    args = parser.parse_args(argv)

    if not args.fragments_dir.exists():
        print(f"fragments directory does not exist: {args.fragments_dir}", file=sys.stderr)
        return 1

    changelog_path = args.changelog or args.fragments_dir / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""

    try:
        fragments = load_all_fragments(args.fragments_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        rendered = render_rollup(fragments, changelog)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if not args.output.exists():
            print(f"DRIFT: {args.output} does not exist; regenerate it.", file=sys.stderr)
            return 1
        existing = args.output.read_text(encoding="utf-8")
        if existing != rendered:
            print(
                f"DRIFT: {args.output} is out of sync with fragments. "
                f"Run `python3 scripts/regenerate_known_issues.py` to update.",
                file=sys.stderr,
            )
            return 1
        print(f"{args.output} is up to date with {len(fragments)} fragment(s).")
        return 0

    args.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.output} ({len(fragments)} fragment(s))")
    if args.stage:
        _git_add(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
