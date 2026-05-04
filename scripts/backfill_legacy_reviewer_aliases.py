"""Backfill user_id on historical review/ingest rows using legacy alias mappings.

Resolves the ``reviewer_id`` text column on three tables to a ``user_id`` UUID
FK via the ``auth_legacy_aliases`` table. Only rows where ``user_id IS NULL``
and the ``reviewer_id`` matches an active alias are updated — rows already
linked or rows with unmapped ``reviewer_id`` values are untouched.

IMPORTANT — irreversibility:
    This script makes no attempt to track which rows it changed. There is no
    built-in undo. To revert a backfill run the operator would have to manually
    NULL out ``user_id`` on affected rows. For Stage C this is acceptable; the
    backfill is data correction, not a behaviour change.

Usage:
    # Dry run (default): show counts of rows that WOULD be updated.
    python3 scripts/backfill_legacy_reviewer_aliases.py --preview

    # Actually apply:
    python3 scripts/backfill_legacy_reviewer_aliases.py --apply --confirm

Environment:
    DATABASE_URL  PostgreSQL connection string (required).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Make project root importable when run directly.
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.infra.db import DatabaseAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Target tables and their reviewer-id columns (all share the same shape).
# ---------------------------------------------------------------------------

_TABLES: list[str] = [
    "v2_review_decisions",
    "v2_image_metric_confirmations",
    "v2_ingest_batches",
]

# SQL template (formatted with the table name at call time).
_PREVIEW_SQL = """
SELECT COUNT(*) AS n
FROM {table} t
JOIN auth_legacy_aliases la
    ON la.legacy_reviewer_string = t.reviewer_id
   AND la.active = TRUE
JOIN auth_users au
    ON au.normalized_email = la.target_email
WHERE t.user_id IS NULL
"""

_APPLY_SQL = """
UPDATE {table} t
SET user_id = au.id
FROM auth_legacy_aliases la
JOIN auth_users au
    ON au.normalized_email = la.target_email
WHERE t.reviewer_id = la.legacy_reviewer_string
  AND la.active = TRUE
  AND t.user_id IS NULL
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def preview(db: DatabaseAdapter) -> dict[str, int]:
    """Return per-table counts of rows that WOULD be updated by --apply."""
    counts: dict[str, int] = {}
    for table in _TABLES:
        rows = db.query(_PREVIEW_SQL.format(table=table))
        counts[table] = int(rows[0]["n"])
    return counts


def apply(db: DatabaseAdapter) -> dict[str, int]:
    """Run the three UPDATEs inside one transaction.

    Returns per-table counts of rows actually updated.
    """
    counts: dict[str, int] = {}
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            for table in _TABLES:
                cur.execute(_APPLY_SQL.format(table=table))
                counts[table] = cur.rowcount
    return counts


def _write_audit_log(
    db: DatabaseAdapter,
    before_counts: dict[str, int],
    after_counts: dict[str, int] | None,
    *,
    dry_run: bool,
) -> None:
    """Write one admin_audit_log row for this invocation."""

    def _counts_to_json(counts: dict[str, int] | None) -> Any:
        if counts is None:
            return None
        return json.dumps({"dry_run": dry_run, "counts": counts})

    db.execute(
        """
        INSERT INTO admin_audit_log
            (actor_user_id, actor_email, action_type, target_entity,
             before_state, after_state)
        VALUES
            (NULL, NULL,
             'auth.backfill_legacy_aliases',
             'v2_review_decisions,v2_image_metric_confirmations,v2_ingest_batches',
             %(before)s::jsonb,
             %(after)s::jsonb)
        """,
        {
            "before": _counts_to_json(before_counts),
            "after": _counts_to_json(after_counts),
        },
    )


def _print_counts(counts: dict[str, int], label: str) -> None:
    total = sum(counts.values())
    print(f"\n{label}")
    print("-" * 50)
    for table, n in counts.items():
        print(f"  {table:<45} {n:>6}")
    print(f"  {'TOTAL':<45} {total:>6}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill user_id on v2_review_decisions, v2_image_metric_confirmations, "
            "and v2_ingest_batches using auth_legacy_aliases. "
            "Default (no flags): same as --preview."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preview",
        action="store_true",
        default=False,
        help="Show row counts that WOULD be updated. No writes. (default behaviour)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually apply the UPDATEs. Requires --confirm.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Required with --apply to prevent accidental writes.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Default to --preview if neither flag is given.
    if not args.apply and not args.preview:
        args.preview = True

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set.", file=sys.stderr)
        return 1

    db = DatabaseAdapter(db_url)

    # --preview -----------------------------------------------------------
    if args.preview:
        counts = preview(db)
        _print_counts(counts, "Preview — rows that WOULD be updated:")
        total = sum(counts.values())
        if total == 0:
            print("\nNothing to backfill. (All eligible rows already have user_id set.)")
        else:
            print(
                f"\nRun with --apply --confirm to apply {total} update(s).\n"
                "WARNING: Apply is not reversible without manual intervention."
            )
        # Write audit log for the preview observation (dry_run=True).
        _write_audit_log(db, counts, None, dry_run=True)
        return 0

    # --apply -------------------------------------------------------------
    if args.apply:
        if not args.confirm:
            print(
                "ERROR: --apply requires --confirm. "
                "Run with --preview first to inspect row counts.",
                file=sys.stderr,
            )
            return 1

        before = preview(db)
        _print_counts(before, "Rows to update (before apply):")

        after = apply(db)
        _print_counts(after, "Rows updated (after apply):")

        # Audit log (dry_run=False, before=preview counts, after=apply counts).
        _write_audit_log(db, before, after, dry_run=False)

        total = sum(after.values())
        print(f"\nApply complete. {total} row(s) updated. Audit log written.")

        # Verify by re-running preview (should be 0 for all tables).
        remaining = preview(db)
        remaining_total = sum(remaining.values())
        if remaining_total > 0:
            print(
                f"\nWARNING: {remaining_total} row(s) still have user_id=NULL after apply. "
                "This may indicate reviewer_id values with no active alias mapping.",
                file=sys.stderr,
            )
        return 0

    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
