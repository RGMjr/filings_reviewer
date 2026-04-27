#!/usr/bin/env python3
"""Validate YAML frontmatter of docs/known-issues/*.md fragment files.

Each fragment is a markdown file with YAML frontmatter fenced by `---` lines.
Frontmatter carries machine-readable metadata (id, status, autonomy, touches,
etc.) that drives both the rollup regenerator and the nightly sweeper selector.

Usage:
    python3 scripts/validate_known_issues_fragments.py             # validate all
    python3 scripts/validate_known_issues_fragments.py --path FILE # validate one

Exits 0 on success, 1 if any fragment fails validation.
"""

from __future__ import annotations

import argparse
import functools
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FRAGMENTS_DIR = REPO_ROOT / "docs" / "known-issues"
LEGACY_ALLOWLIST_PATH = DEFAULT_FRAGMENTS_DIR / ".legacy-allowlist.txt"


@functools.cache
def _load_legacy_allowlist(path: Path = LEGACY_ALLOWLIST_PATH) -> frozenset[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"legacy allow-list missing at {path} — this file is checked in to "
            "enforce the gh-N namespace; if you're seeing this, restore it from git."
        )
    return frozenset(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "source",
        "slug",
        "title",
        "status",
        "severity",
        "autonomy",
        "estimated",
        "touches",
        "discovered",
        "updated",
    }
)
OPTIONAL_FIELDS: frozenset[str] = frozenset({"pr_refs", "gh_issue", "note"})
ALL_FIELDS: frozenset[str] = REQUIRED_FIELDS | OPTIONAL_FIELDS

VALID_SOURCE = frozenset({"legacy", "gh"})
VALID_STATUS = frozenset({"open", "resolved", "partially-resolved", "archived"})
VALID_SEVERITY = frozenset({"high", "medium", "low", "n/a"})
VALID_AUTONOMY = frozenset({"safe", "review", "skip", "n/a"})
VALID_ESTIMATED = frozenset({"XS", "S", "M", "L", "—"})

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FILENAME_RE = re.compile(r"^(?P<source>legacy|gh)-(?P<id>\d+)-(?P<slug>[a-z0-9][a-z0-9-]*)\.md$")

FRONTMATTER_FENCE = "---"


@dataclass
class Fragment:
    frontmatter: dict[str, Any]
    body: str
    path: Path

    @property
    def id(self) -> int:
        return int(self.frontmatter["id"])

    @property
    def status(self) -> str:
        return str(self.frontmatter["status"])

    @property
    def source(self) -> str:
        return str(self.frontmatter["source"])


def parse_fragment(path: Path) -> Fragment:
    """Read a fragment file and split frontmatter from body.

    Raises ValueError if the file is not a valid fragment (missing fences,
    invalid YAML, or frontmatter is not a mapping).
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FRONTMATTER_FENCE + "\n"):
        raise ValueError(f"{path}: missing opening frontmatter fence '---'")

    rest = text[len(FRONTMATTER_FENCE) + 1 :]
    close_idx = rest.find("\n" + FRONTMATTER_FENCE + "\n")
    if close_idx == -1:
        if rest.rstrip("\n").endswith(FRONTMATTER_FENCE):
            close_idx = rest.rfind(FRONTMATTER_FENCE) - 1
        else:
            raise ValueError(f"{path}: missing closing frontmatter fence '---'")

    fm_text = rest[:close_idx]
    body = rest[close_idx + len("\n" + FRONTMATTER_FENCE + "\n") :]

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML frontmatter: {exc}") from exc

    if not isinstance(fm, dict):
        raise ValueError(f"{path}: frontmatter must be a YAML mapping, got {type(fm).__name__}")

    return Fragment(frontmatter=fm, body=body, path=path)


def _validate_date(value: Any, field: str) -> str | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return None
    if isinstance(value, str):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return None
        except ValueError:
            return f"field '{field}' must be ISO date YYYY-MM-DD, got {value!r}"
    return f"field '{field}' must be an ISO date YYYY-MM-DD string, got {type(value).__name__}"


def validate_fragment(fragment: Fragment) -> list[str]:
    """Return a list of human-readable error strings; empty list = valid."""
    errors: list[str] = []
    fm = fragment.frontmatter
    path = fragment.path

    missing = REQUIRED_FIELDS - set(fm.keys())
    if missing:
        errors.append(f"missing required field(s): {sorted(missing)}")

    unknown = set(fm.keys()) - ALL_FIELDS
    if unknown:
        errors.append(f"unknown field(s): {sorted(unknown)}")

    if "id" in fm and not isinstance(fm["id"], int):
        errors.append(f"field 'id' must be an int, got {type(fm['id']).__name__}")
    if "source" in fm and fm["source"] not in VALID_SOURCE:
        errors.append(f"field 'source' must be one of {sorted(VALID_SOURCE)}, got {fm['source']!r}")
    if "slug" in fm:
        if not isinstance(fm["slug"], str) or not SLUG_RE.match(fm["slug"]):
            errors.append(f"field 'slug' must be kebab-case, got {fm['slug']!r}")
    if "title" in fm and not isinstance(fm["title"], str):
        errors.append(f"field 'title' must be a string, got {type(fm['title']).__name__}")
    if "status" in fm and fm["status"] not in VALID_STATUS:
        errors.append(f"field 'status' must be one of {sorted(VALID_STATUS)}, got {fm['status']!r}")
    if "severity" in fm and fm["severity"] not in VALID_SEVERITY:
        errors.append(
            f"field 'severity' must be one of {sorted(VALID_SEVERITY)}, got {fm['severity']!r}"
        )
    if "autonomy" in fm and fm["autonomy"] not in VALID_AUTONOMY:
        errors.append(
            f"field 'autonomy' must be one of {sorted(VALID_AUTONOMY)}, got {fm['autonomy']!r}"
        )
    if "estimated" in fm and fm["estimated"] not in VALID_ESTIMATED:
        errors.append(
            f"field 'estimated' must be one of {sorted(VALID_ESTIMATED)}, got {fm['estimated']!r}"
        )
    if "touches" in fm:
        if not isinstance(fm["touches"], list) or not all(
            isinstance(t, str) for t in fm["touches"]
        ):
            errors.append(f"field 'touches' must be a list of strings, got {fm['touches']!r}")
    for date_field in ("discovered", "updated"):
        if date_field in fm:
            err = _validate_date(fm[date_field], date_field)
            if err:
                errors.append(err)
    if "pr_refs" in fm:
        prs = fm["pr_refs"]
        if not isinstance(prs, list) or not all(isinstance(n, int) for n in prs):
            errors.append(f"field 'pr_refs' must be a list of ints, got {prs!r}")
    if "gh_issue" in fm and fm["gh_issue"] is not None and not isinstance(fm["gh_issue"], int):
        errors.append(
            f"field 'gh_issue' must be an int or null, got {type(fm['gh_issue']).__name__}"
        )
    if "note" in fm and not isinstance(fm["note"], str):
        errors.append(f"field 'note' must be a string, got {type(fm['note']).__name__}")

    if "source" in fm and fm["source"] == "gh" and fm.get("gh_issue") is None:
        errors.append("field 'gh_issue' must be set when source is 'gh'")

    filename_match = FILENAME_RE.match(path.name)
    if filename_match is None:
        errors.append(f"filename must match pattern (legacy|gh)-<id>-<slug>.md, got {path.name!r}")
    else:
        fname_source = filename_match.group("source")
        if fname_source == "legacy" and path.name not in _load_legacy_allowlist():
            errors.append(
                "new 'legacy-*' filenames are not allowed; use 'gh-<issue>-<slug>.md' "
                "for new fragments. See CLAUDE.md / docs/development/CONTRIBUTING.md."
            )
    if filename_match is not None and not errors:
        fname_source = filename_match.group("source")
        fname_id = int(filename_match.group("id"))
        fname_slug = filename_match.group("slug")
        if fname_source != fm.get("source"):
            errors.append(
                f"filename source {fname_source!r} does not match frontmatter source {fm.get('source')!r}"
            )
        if fname_id != fm.get("id"):
            errors.append(f"filename id {fname_id} does not match frontmatter id {fm.get('id')!r}")
        if fname_slug != fm.get("slug"):
            errors.append(
                f"filename slug {fname_slug!r} does not match frontmatter slug {fm.get('slug')!r}"
            )

    return errors


def load_all_fragments(fragments_dir: Path) -> list[Fragment]:
    """Load every *.md file under fragments_dir except CHANGELOG.md; raise on parse errors.

    Returned list is sorted by (source, id) for determinism. Duplicate
    (source, id) pairs raise ValueError — a single issue must have exactly one
    fragment.
    """
    if not fragments_dir.exists():
        raise FileNotFoundError(f"fragments directory does not exist: {fragments_dir}")
    fragments: list[Fragment] = []
    for path in sorted(fragments_dir.glob("*.md")):
        if path.name == "CHANGELOG.md":
            continue
        fragments.append(parse_fragment(path))
    seen: dict[tuple[str, int], Path] = {}
    for f in fragments:
        key = (f.source, f.id)
        if key in seen:
            raise ValueError(f"duplicate fragment for {f.source}#{f.id}: {seen[key]} and {f.path}")
        seen[key] = f.path
    fragments.sort(key=lambda f: (f.source, f.id))
    return fragments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        default=DEFAULT_FRAGMENTS_DIR,
        help="Directory containing fragment files (default: docs/known-issues)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Validate a single fragment file instead of the whole directory",
    )
    args = parser.parse_args(argv)

    paths: list[Path]
    if args.path is not None:
        paths = [args.path]
    else:
        if not args.fragments_dir.exists():
            print(f"fragments directory does not exist: {args.fragments_dir}", file=sys.stderr)
            return 1
        paths = sorted(p for p in args.fragments_dir.glob("*.md") if p.name != "CHANGELOG.md")

    if not paths:
        print(f"no fragment files found in {args.fragments_dir}")
        return 0

    exit_code = 0
    for path in paths:
        try:
            fragment = parse_fragment(path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        errors = validate_fragment(fragment)
        for err in errors:
            print(f"ERROR: {path}: {err}", file=sys.stderr)
        if errors:
            exit_code = 1

    if exit_code == 0:
        print(f"validated {len(paths)} fragment(s): OK")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
