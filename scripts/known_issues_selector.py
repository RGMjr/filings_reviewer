#!/usr/bin/env python3
"""Known issues selector for the nightly autonomous sweeper.

Parses the "Nightly Sweeper Classification" table in docs/KNOWN_ISSUES.md,
filters for safe/review items, dedupes against open PRs (via `gh`), picks
a non-colliding batch of up to N issues, and emits the picks as JSON.

Usage:
    python3 scripts/known_issues_selector.py [--max N] [--include-review]
                                             [--known-issues PATH]
                                             [--dry-run]
                                             [--no-pr-dedupe]

Exit codes:
    0 — picks emitted (possibly empty array if nothing to do)
    1 — parse error (malformed classification table)
    2 — `gh` call failed and --no-pr-dedupe was not set

The orchestrator (scripts/run_nightly_sweep.sh) consumes the JSON output.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KNOWN_ISSUES = REPO_ROOT / "docs" / "KNOWN_ISSUES.md"
TABLE_HEADING = "## Nightly Sweeper Classification"


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


def parse_classification_table(md_content: str) -> list[IssueRecord]:
    """Extract the Nightly Sweeper Classification table rows as IssueRecords.

    Raises ValueError if the table heading is missing or no rows are parsed.
    """
    heading_idx = md_content.find(TABLE_HEADING)
    if heading_idx == -1:
        raise ValueError(
            f"Missing {TABLE_HEADING!r} heading in KNOWN_ISSUES.md — "
            "sweeper cannot determine which issues to work."
        )
    # The table ends at the next top-level "## " heading after the heading.
    tail = md_content[heading_idx + len(TABLE_HEADING) :]
    next_heading = re.search(r"\n## ", tail)
    table_block = tail[: next_heading.start()] if next_heading else tail

    records: list[IssueRecord] = []
    for line in table_block.splitlines():
        stripped = line.strip()
        # Table rows look like "| #60 | safe | XS | glob glob | note |"
        if not stripped.startswith("| #"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        issue_cell, autonomy, estimated, touches_cell, note = cells[:5]
        m = re.match(r"#(\d+)", issue_cell)
        if not m:
            continue
        issue_num = int(m.group(1))
        if autonomy not in {"safe", "review", "skip"}:
            raise ValueError(
                f"Issue #{issue_num}: unknown Autonomy value {autonomy!r}. "
                "Must be safe|review|skip."
            )
        touches_tuple: tuple[str, ...] = ()
        if touches_cell and touches_cell not in {"—", "-"}:
            # Strip backticks the table uses for inline code.
            cleaned = touches_cell.replace("`", "")
            touches_tuple = tuple(g for g in cleaned.split() if g)
        records.append(
            IssueRecord(
                issue=issue_num,
                autonomy=autonomy,
                estimated=estimated,
                touches=touches_tuple,
                note=note,
            )
        )
    if not records:
        raise ValueError(
            "Nightly Sweeper Classification table parsed zero rows — "
            "check the table format in docs/KNOWN_ISSUES.md."
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
        "--known-issues",
        type=Path,
        default=DEFAULT_KNOWN_ISSUES,
        help="Path to KNOWN_ISSUES.md (default: docs/KNOWN_ISSUES.md).",
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
        md = args.known_issues.read_text()
    except FileNotFoundError:
        print(f"error: {args.known_issues} not found", file=sys.stderr)
        return 1
    try:
        records = parse_classification_table(md)
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
