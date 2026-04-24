#!/usr/bin/env python3
"""Sync known-issue fragment status from GitHub PR state.

For each fragment whose pr_refs are all MERGED, rewrites the frontmatter
in-place: status -> resolved, autonomy -> n/a, updated -> today.

Usage:
    python3 scripts/sync_known_issue_status.py [--dry-run] [--fragments-dir PATH] [--verbose]

Exit codes:
    0 — success (including 0 updates)
    1 — catastrophic failure (fragments dir not found, gh not installed)
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FRAGMENTS_DIR = REPO_ROOT / "docs" / "known-issues"


def _load_validate_module() -> Any:
    """Load validate_known_issues_fragments without requiring __init__.py."""
    script_dir = Path(__file__).resolve().parent
    module_path = script_dir / "validate_known_issues_fragments.py"
    spec = importlib.util.spec_from_file_location("validate_known_issues_fragments", module_path)
    assert spec is not None and spec.loader is not None, f"Could not load {module_path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_known_issues_fragments"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _normalize_ref(raw: Any) -> int | None:
    """Return a PR number int from int, '#N', or 'N' string. None on malformed."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.lstrip("#").strip()
        if s.isdigit():
            return int(s)
    return None


def _gh_pr_state(ref: int, cache: dict[int, str | None], verbose: bool) -> str | None:
    """Return 'MERGED', 'OPEN', 'CLOSED', etc., or None on failure. Caches results."""
    if ref in cache:
        return cache[ref]
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(ref), "--json", "state", "-q", ".state"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            if verbose:
                print(
                    f"  [warn] gh pr view {ref} failed (exit {result.returncode}): "
                    f"{result.stderr.strip()}",
                    file=sys.stderr,
                )
            cache[ref] = None
            return None
        state = result.stdout.strip()
        if verbose:
            print(f"  [gh]   PR #{ref} -> {state}")
        cache[ref] = state
        return state
    except FileNotFoundError:
        print("FATAL: 'gh' is not installed or not on PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"  [warn] gh pr view {ref} timed out", file=sys.stderr)
        cache[ref] = None
        return None


def _rewrite_frontmatter(path: Path, today: str, verbose: bool) -> None:
    """Rewrite status, autonomy, and updated in the fragment's YAML frontmatter."""
    text = path.read_text(encoding="utf-8")

    # Split into frontmatter + rest.
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: no opening frontmatter fence")
    rest = text[4:]
    close_idx = rest.find("\n---\n")
    if close_idx == -1:
        raise ValueError(f"{path}: no closing frontmatter fence")

    fm_text = rest[:close_idx]
    body_part = rest[close_idx:]  # includes "\n---\n..."

    def _set_field(block: str, key: str, value: str) -> tuple[str, bool]:
        """Replace an existing `key: <anything>` line; return (new_block, replaced)."""
        pattern = re.compile(r"^" + re.escape(key) + r":.*$", re.MULTILINE)
        new_block, count = pattern.subn(f"{key}: {value}", block)
        return new_block, count > 0

    fm_text, replaced_status = _set_field(fm_text, "status", "resolved")
    if not replaced_status:
        # Insert after first line
        lines = fm_text.splitlines()
        lines.insert(1, "status: resolved")
        fm_text = "\n".join(lines)

    fm_text, replaced_autonomy = _set_field(fm_text, "autonomy", "n/a")
    if not replaced_autonomy:
        lines = fm_text.splitlines()
        lines.insert(1, "autonomy: n/a")
        fm_text = "\n".join(lines)

    fm_text, replaced_updated = _set_field(fm_text, "updated", f"'{today}'")
    if not replaced_updated:
        lines = fm_text.splitlines()
        lines.insert(1, f"updated: '{today}'")
        fm_text = "\n".join(lines)

    new_text = "---\n" + fm_text + body_part
    path.write_text(new_text, encoding="utf-8")

    if verbose:
        print(f"  [write] {path.name}: status=resolved, autonomy=n/a, updated={today}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Log changes but do not write")
    parser.add_argument(
        "--fragments-dir",
        type=Path,
        default=DEFAULT_FRAGMENTS_DIR,
        help="Directory containing fragment files (default: docs/known-issues/)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args(argv)

    if not args.fragments_dir.exists():
        print(f"FATAL: fragments directory not found: {args.fragments_dir}", file=sys.stderr)
        return 1

    validate_mod = _load_validate_module()
    try:
        fragments = validate_mod.load_all_fragments(args.fragments_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    today = datetime.date.today().isoformat()
    pr_state_cache: dict[int, str | None] = {}
    inactive_statuses = frozenset({"resolved", "archived"})

    n_scanned = 0
    n_updates = 0
    n_skipped_pending = 0
    n_failures = 0

    for fragment in fragments:
        n_scanned += 1
        fm = fragment.frontmatter
        current_status = str(fm.get("status", ""))
        if current_status in inactive_statuses:
            if args.verbose:
                print(f"[skip]   {fragment.path.name}: already {current_status}")
            continue

        raw_refs = fm.get("pr_refs")
        if not raw_refs or not isinstance(raw_refs, list) or len(raw_refs) == 0:
            if args.verbose:
                print(f"[skip]   {fragment.path.name}: no pr_refs")
            continue

        # Normalize refs
        refs: list[int] = []
        malformed = False
        for raw in raw_refs:
            ref = _normalize_ref(raw)
            if ref is None:
                print(
                    f"[warn]   {fragment.path.name}: malformed pr_ref {raw!r} — skipping fragment",
                    file=sys.stderr,
                )
                malformed = True
                break
            refs.append(ref)
        if malformed:
            n_failures += 1
            continue

        # Query GitHub for each ref
        all_merged = True
        gh_failed = False
        for ref in refs:
            state = _gh_pr_state(ref, pr_state_cache, args.verbose)
            if state is None:
                if args.verbose:
                    print(
                        f"[skip]   {fragment.path.name}: gh lookup failed for PR #{ref}",
                        file=sys.stderr,
                    )
                gh_failed = True
                break
            if state != "MERGED":
                all_merged = False
                if args.verbose:
                    print(f"[pending] {fragment.path.name}: PR #{ref} is {state} (not MERGED)")
                break

        if gh_failed:
            n_failures += 1
            continue

        if not all_merged:
            n_skipped_pending += 1
            continue

        # All refs are MERGED — update the fragment
        if args.dry_run:
            print(
                f"[dry-run] {fragment.path.name}: would set status=resolved, "
                f"autonomy=n/a, updated={today}"
            )
            n_updates += 1
        else:
            try:
                _rewrite_frontmatter(fragment.path, today, args.verbose)
                print(f"[updated] {fragment.path.name}: status=resolved")
                n_updates += 1
            except (ValueError, OSError) as exc:
                print(f"[error]   {fragment.path.name}: rewrite failed: {exc}", file=sys.stderr)
                n_failures += 1

    print(
        f"Scanned {n_scanned} fragments, {n_updates} updates "
        f"(dry_run={args.dry_run}), {n_skipped_pending} skipped (pending PRs), "
        f"{n_failures} failures."
    )

    # Regenerate rollup if any updates happened and not dry-run
    if n_updates > 0 and not args.dry_run:
        regen_script = Path(__file__).resolve().parent / "regenerate_known_issues.py"
        result = subprocess.run(
            ["python3", str(regen_script)],
            capture_output=False,
        )
        if result.returncode != 0:
            print(
                f"[error] regenerate_known_issues.py exited {result.returncode}",
                file=sys.stderr,
            )
            return result.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
