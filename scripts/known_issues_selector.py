#!/usr/bin/env python3
"""Known issues selector for the nightly autonomous sweeper.

Reads YAML frontmatter from docs/known-issues/ fragment files, filters for
safe/review items with open/partially-resolved status, dedupes against open
PRs (via `gh`), picks a non-colliding batch of up to N issues, and emits the
picks as JSON.

Usage:
    python3 scripts/known_issues_selector.py [--max N] [--include-review]
                                             [--fragments-dir PATH]
                                             [--dry-run]
                                             [--no-pr-dedupe]

Exit codes:
    0 — picks emitted (possibly empty array if nothing to do)
    1 — fragment parse error or fragments directory not found
    2 — `gh` call failed and --no-pr-dedupe was not set

The orchestrator (scripts/run_nightly_sweep.sh) consumes the JSON output.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FRAGMENTS_DIR = REPO_ROOT / "docs" / "known-issues"

# Statuses that indicate a fragment is no longer actionable.
_INACTIVE_STATUSES = frozenset({"resolved", "archived"})


def _load_fragments_module():  # type: ignore[return]
    """Load validate_known_issues_fragments as a module without requiring __init__.py."""
    script_dir = Path(__file__).resolve().parent
    module_path = script_dir / "validate_known_issues_fragments.py"
    spec = importlib.util.spec_from_file_location("validate_known_issues_fragments", module_path)
    assert spec is not None and spec.loader is not None, f"Could not load {module_path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_known_issues_fragments"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@dataclass(frozen=True)
class IssueRecord:
    issue: int
    autonomy: str  # "safe" | "review" | "skip"
    estimated: str  # "XS" | "S" | "M" | "L" | "—"
    touches: tuple[str, ...]  # file globs; empty tuple for skip rows
    note: str

    def asdict(self) -> dict:
        d = asdict(self)
        d["touches"] = list(self.touches)
        return d


def parse_classification_from_fragments(fragments_dir: Path) -> list[IssueRecord]:
    """Load IssueRecords from YAML frontmatter in docs/known-issues/ fragments.

    Skips fragments where:
    - autonomy is 'n/a' (not eligible for sweep)
    - status is 'resolved' or 'archived' (no longer actionable — fixes issue #79)

    Raises FileNotFoundError if fragments_dir does not exist.
    Raises ValueError on parse errors.
    """
    _frags = _load_fragments_module()
    fragments = _frags.load_all_fragments(fragments_dir)

    records: list[IssueRecord] = []
    for fragment in fragments:
        fm = fragment.frontmatter
        autonomy = str(fm.get("autonomy") or "")
        status = str(fm.get("status") or "")

        # Skip n/a autonomy (not eligible for sweep).
        if autonomy == "n/a":
            continue

        # Skip resolved/archived issues — they are no longer actionable.
        if status in _INACTIVE_STATUSES:
            if autonomy != "n/a":
                issue_id = fm.get("id", "?")
                print(
                    f"warning: issue #{issue_id} has status={status!r} but autonomy={autonomy!r}; "
                    "consider setting autonomy: n/a on resolved/archived entries.",
                    file=sys.stderr,
                )
            continue

        touches_raw = fm.get("touches") or []
        touches: tuple[str, ...] = tuple(touches_raw) if isinstance(touches_raw, list) else ()

        records.append(
            IssueRecord(
                issue=int(fm["id"]),
                autonomy=autonomy,
                estimated=str(fm.get("estimated") or "—"),
                touches=touches,
                note=str(fm.get("note") or ""),
            )
        )

    return records


def fetch_open_pr_issue_refs() -> set[int]:
    """Return the set of issue numbers referenced by any open PR title or body.

    Uses `gh pr list --state open --json title,body`. Raises CalledProcessError
    if `gh` is unavailable or unauthenticated.
    """
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", "title,body"],
        check=True,
        capture_output=True,
        text=True,
    )
    prs = json.loads(result.stdout)
    refs: set[int] = set()
    pattern = re.compile(r"#(\d+)")
    for pr in prs:
        for field in ("title", "body"):
            text = pr.get(field) or ""
            for m in pattern.finditer(text):
                refs.add(int(m.group(1)))
    return refs


def _glob_matches_any(g: str, others: list[str]) -> bool:
    # Treat each glob as a pattern; we call two globs "colliding" if either
    # matches a concrete path the other could also match. Without a file list,
    # approximate by: if either pattern matches against the other pattern
    # literally or their directory prefixes overlap.
    for o in others:
        if fnmatch.fnmatch(o, g) or fnmatch.fnmatch(g, o):
            return True
        # Prefix overlap: directory before first glob char.
        g_prefix = re.split(r"[*?\[]", g, maxsplit=1)[0]
        o_prefix = re.split(r"[*?\[]", o, maxsplit=1)[0]
        if (
            g_prefix
            and o_prefix
            and (g_prefix.startswith(o_prefix) or o_prefix.startswith(g_prefix))
        ):
            return True
    return False


def touches_collide(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Heuristic: two issues collide if any pair of globs overlap by prefix or fnmatch."""
    if not a or not b:
        return False
    for g in a:
        if _glob_matches_any(g, list(b)):
            return True
    return False


def select_picks(
    records: list[IssueRecord],
    max_n: int,
    include_review: bool,
    open_pr_refs: set[int],
) -> list[IssueRecord]:
    """Greedy selection: safe-first, then review (if allowed), lowest-issue-first,
    skipping any record that collides with already-picked records or appears in
    an open PR."""
    autonomy_rank = {"safe": 0, "review": 1}
    candidates = [
        r
        for r in records
        if r.autonomy in autonomy_rank
        and (include_review or r.autonomy == "safe")
        and r.issue not in open_pr_refs
        and r.touches  # skip records without Touches globs; sweeper can't scope them
    ]
    candidates.sort(key=lambda r: (autonomy_rank[r.autonomy], r.issue))
    picks: list[IssueRecord] = []
    for r in candidates:
        if any(touches_collide(r.touches, p.touches) for p in picks):
            continue
        picks.append(r)
        if len(picks) >= max_n:
            break
    return picks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max", type=int, default=3, help="Maximum number of picks to return (default: 3)."
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="Include Autonomy=review issues in selection (default: safe-only).",
    )
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        default=DEFAULT_FRAGMENTS_DIR,
        help="Path to the known-issues fragment directory (default: docs/known-issues/).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print a human-readable summary instead of JSON."
    )
    parser.add_argument(
        "--no-pr-dedupe",
        action="store_true",
        help="Skip the `gh pr list` dedupe step (for offline runs and tests).",
    )
    args = parser.parse_args()

    try:
        records = parse_classification_from_fragments(args.fragments_dir)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    open_pr_refs: set[int] = set()
    if not args.no_pr_dedupe:
        try:
            open_pr_refs = fetch_open_pr_issue_refs()
        except subprocess.CalledProcessError as e:
            print(
                f"error: `gh pr list` failed ({e.returncode}). Use --no-pr-dedupe to skip.",
                file=sys.stderr,
            )
            return 2
        except FileNotFoundError:
            print("error: `gh` CLI not found. Install or use --no-pr-dedupe.", file=sys.stderr)
            return 2

    picks = select_picks(records, args.max, args.include_review, open_pr_refs)

    if args.dry_run:
        total_safe = sum(1 for r in records if r.autonomy == "safe")
        total_review = sum(1 for r in records if r.autonomy == "review")
        total_skip = sum(1 for r in records if r.autonomy == "skip")
        print(
            f"Classification totals: {total_safe} safe, {total_review} review, {total_skip} skip."
        )
        print(f"Open-PR refs excluded: {sorted(open_pr_refs)}")
        print(f"Picks ({len(picks)}/{args.max} requested; include_review={args.include_review}):")
        for p in picks:
            print(
                f"  #{p.issue} [{p.autonomy}/{p.estimated}] touches={list(p.touches)}  — {p.note}"
            )
        return 0

    print(json.dumps([p.asdict() for p in picks], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
