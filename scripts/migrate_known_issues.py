#!/usr/bin/env python3
"""One-shot migration of docs/KNOWN_ISSUES.md into docs/known-issues/ fragments.

Walks the monolithic file, extracts per-issue bodies and the Nightly Sweeper
Classification table, and emits one fragment file per issue with YAML
frontmatter. Safe to run multiple times: existing fragments are skipped unless
--overwrite is passed.

Deleted in Phase 4 once Phase 1b migration has landed.

Usage:
    python3 scripts/migrate_known_issues.py --dry-run
    python3 scripts/migrate_known_issues.py
    python3 scripts/migrate_known_issues.py --overwrite
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROLLUP_PATH = REPO_ROOT / "docs" / "KNOWN_ISSUES.md"
DEFAULT_FRAGMENTS_DIR = REPO_ROOT / "docs" / "known-issues"
DEFAULT_CHANGELOG_OUT = DEFAULT_FRAGMENTS_DIR / "CHANGELOG.md"

CLASSIFICATION_HEADING = "## Nightly Sweeper Classification"
ARCHIVE_HEADING = "## Archive (Resolved Issues)"
CHANGELOG_HEADING = "## Change Log"

ISSUE_HEADING_RE = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
ARCHIVE_HEADING_RE = re.compile(r"^### Issue #(\d+):\s*(.+)$", re.MULTILINE)
TABLE_ROW_RE = re.compile(
    r"^\| #(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$"
)

STATUS_RE = re.compile(r"^\*\*Status\*\*:\s*(.+?)\s*$", re.MULTILINE)
SEVERITY_RE = re.compile(r"^\*\*Severity\*\*:\s*(.+?)\s*$", re.MULTILINE)
DISCOVERED_RE = re.compile(r"^\*\*Discovered\*\*:\s*(.+?)\s*$", re.MULTILINE)
UPDATED_RE = re.compile(r"^\*\*Updated\*\*:\s*(.+?)\s*$", re.MULTILINE)

DATE_FALLBACK = "2026-04-22"


@dataclass
class ClassificationRow:
    issue: int
    autonomy: str
    estimated: str
    touches: list[str]
    note: str


@dataclass
class IssueBlock:
    issue: int
    title: str
    body: str
    in_archive: bool


def extract_classification_rows(md: str) -> dict[int, ClassificationRow]:
    start = md.find(CLASSIFICATION_HEADING)
    if start == -1:
        return {}
    tail = md[start:]
    next_heading = re.search(r"\n## [^\n]", tail[len(CLASSIFICATION_HEADING) :])
    if next_heading:
        tail = tail[: len(CLASSIFICATION_HEADING) + next_heading.start()]
    rows: dict[int, ClassificationRow] = {}
    for line in tail.splitlines():
        m = TABLE_ROW_RE.match(line)
        if not m:
            continue
        issue = int(m.group(1))
        autonomy = m.group(2).strip()
        estimated = m.group(3).strip()
        touches_cell = m.group(4).strip()
        note = m.group(5).strip()
        touches: list[str]
        if touches_cell in {"—", "-", ""}:
            touches = []
        else:
            touches = [t.strip("`").strip() for t in touches_cell.split() if t.strip("`").strip()]
        rows[issue] = ClassificationRow(
            issue=issue,
            autonomy=autonomy,
            estimated=estimated,
            touches=touches,
            note=note,
        )
    return rows


def extract_issue_blocks(md: str) -> list[IssueBlock]:
    archive_idx = md.find(ARCHIVE_HEADING)
    changelog_idx = md.find(CHANGELOG_HEADING)
    end_idx = changelog_idx if changelog_idx != -1 else len(md)
    pre_archive = md[:archive_idx] if archive_idx != -1 else md[:end_idx]
    archive_section = md[archive_idx:end_idx] if archive_idx != -1 else ""

    blocks: list[IssueBlock] = []

    def _walk(text: str, in_archive: bool) -> None:
        heading_re = ARCHIVE_HEADING_RE if in_archive else ISSUE_HEADING_RE
        matches = list(heading_re.finditer(text))
        for i, m in enumerate(matches):
            issue = int(m.group(1))
            title = m.group(2).strip()
            body_start = m.end()
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[body_start:body_end]
            body = re.sub(r"\n\s*---\s*\n?\s*$", "\n", body)
            body = body.strip("\n")
            blocks.append(IssueBlock(issue=issue, title=title, body=body, in_archive=in_archive))

    _walk(pre_archive, in_archive=False)
    _walk(archive_section, in_archive=True)
    return blocks


def _parse_status(raw: str, in_archive: bool) -> str:
    """Map a Status line to one of: open | resolved | partially-resolved | archived."""
    s = raw.lower()
    if "partial" in s:
        return "partially-resolved"
    if "resolv" in s or "fixed" in s:
        return "resolved" if not in_archive else "archived"
    if in_archive:
        return "archived"
    return "open"


def _parse_severity(raw: str) -> str:
    """Map a Severity line to one of: high | medium | low | n/a."""
    s = raw.lower()
    if "high" in s or "critical" in s:
        return "high"
    if "medium" in s:
        return "medium"
    if "low" in s:
        return "low"
    return "n/a"


def _parse_date(raw: str) -> str:
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw)
    return m.group(1) if m else DATE_FALLBACK


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"`([^`]+)`", r"\1", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = "untitled"
    slug = slug[:60].rstrip("-")
    return slug


def build_fragment_frontmatter(
    block: IssueBlock,
    row: ClassificationRow | None,
) -> dict:
    status_m = STATUS_RE.search(block.body)
    severity_m = SEVERITY_RE.search(block.body)
    discovered_m = DISCOVERED_RE.search(block.body)
    updated_m = UPDATED_RE.search(block.body)

    status = _parse_status(status_m.group(1) if status_m else "", block.in_archive)
    severity = _parse_severity(severity_m.group(1) if severity_m else "")
    discovered = _parse_date(discovered_m.group(1) if discovered_m else "")
    updated = _parse_date(updated_m.group(1) if updated_m else discovered)

    autonomy = row.autonomy if row else "n/a"
    estimated = row.estimated if row else "—"
    touches = row.touches if row else []
    note = row.note if row else ""

    slug = _slugify(block.title)
    fm: dict = {
        "id": block.issue,
        "source": "legacy",
        "slug": slug,
        "title": block.title,
        "status": status,
        "severity": severity,
        "autonomy": autonomy,
        "estimated": estimated,
        "touches": touches,
        "discovered": discovered,
        "updated": updated,
    }
    if note:
        fm["note"] = note
    return fm


def strip_inline_metadata(body: str) -> str:
    """Remove the **Status/Severity/Discovered/Updated** lines; they move to frontmatter."""
    lines = body.splitlines()
    kept: list[str] = []
    for line in lines:
        if (
            STATUS_RE.match(line)
            or SEVERITY_RE.match(line)
            or DISCOVERED_RE.match(line)
            or UPDATED_RE.match(line)
        ):
            continue
        kept.append(line)
    text = "\n".join(kept)
    text = re.sub(r"^\n+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + "\n"


def render_fragment(frontmatter: dict, body: str) -> str:
    fm_yaml = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=True,
        allow_unicode=True,
    )
    return f"---\n{fm_yaml}---\n\n{body}"


def extract_changelog(md: str) -> str:
    idx = md.find(CHANGELOG_HEADING)
    if idx == -1:
        return ""
    return md[idx:].rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rollup",
        type=Path,
        default=DEFAULT_ROLLUP_PATH,
        help="Path to the monolithic KNOWN_ISSUES.md",
    )
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        default=DEFAULT_FRAGMENTS_DIR,
        help="Output directory for fragment files",
    )
    parser.add_argument(
        "--changelog-out",
        type=Path,
        default=None,
        help="Output path for the extracted CHANGELOG singleton",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be written, don't touch disk"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing fragment files"
    )
    args = parser.parse_args(argv)

    if not args.rollup.exists():
        print(f"ERROR: rollup not found: {args.rollup}", file=sys.stderr)
        return 1

    md = args.rollup.read_text(encoding="utf-8")
    rows = extract_classification_rows(md)
    blocks = extract_issue_blocks(md)

    if not blocks:
        print(f"ERROR: no `## N. Title` issue headings found in {args.rollup}", file=sys.stderr)
        return 1

    fragments_dir = args.fragments_dir
    changelog_out = args.changelog_out or fragments_dir / "CHANGELOG.md"

    if not args.dry_run:
        fragments_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    for block in blocks:
        row = rows.get(block.issue)
        fm = build_fragment_frontmatter(block, row)
        body = strip_inline_metadata(block.body)
        filename = f"legacy-{block.issue:03d}-{fm['slug']}.md"
        path = fragments_dir / filename

        if path.exists() and not args.overwrite:
            skipped += 1
            continue

        rendered = render_fragment(fm, body)
        if args.dry_run:
            print(f"WOULD WRITE: {path} ({len(rendered)} bytes)")
            written += 1
        else:
            path.write_text(rendered, encoding="utf-8")
            written += 1

    changelog = extract_changelog(md)
    if changelog:
        if args.dry_run:
            print(f"WOULD WRITE: {changelog_out} ({len(changelog)} bytes)")
        else:
            changelog_out.parent.mkdir(parents=True, exist_ok=True)
            if not changelog_out.exists() or args.overwrite:
                changelog_out.write_text(changelog, encoding="utf-8")

    print(f"migration: wrote {written} fragment(s), skipped {skipped} existing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
