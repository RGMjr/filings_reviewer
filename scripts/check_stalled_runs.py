#!/usr/bin/env python3
"""Proactive stall alert for stranded job rows in the nightly sweep digest.

Queries three tables for rows stuck at status='running' longer than the configured
thresholds and prints a Markdown section for inclusion in the sweep digest.

Usage (called by run_nightly_sweep.sh):
    python3 scripts/check_stalled_runs.py [--database-url URL] [--text-stall-mins N] [--lock-stall-mins N]

Exit 0 always — a DB connection failure produces a warning and empty output so the
sweep orchestrator is never aborted by this check.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

_TEXT_ANALYSIS_SQL = """\
SELECT id::text, started_at, triggered_by
FROM text_decision_analysis_runs
WHERE status = 'running'
  AND started_at < NOW() - (%(threshold)s || ' minutes')::interval
ORDER BY started_at
"""

_MODEL_TRAINING_SQL = """\
SELECT id::text, started_at, run_lock_until, model_type
FROM model_training_runs
WHERE status = 'running'
  AND run_lock_until IS NOT NULL
  AND run_lock_until < NOW() - (%(threshold)s || ' minutes')::interval
ORDER BY run_lock_until
"""

_INGEST_BATCHES_SQL = """\
SELECT batch_id::text, started_at, run_lock_until
FROM v2_ingest_batches
WHERE status = 'running'
  AND run_lock_until IS NOT NULL
  AND run_lock_until < NOW() - (%(threshold)s || ' minutes')::interval
ORDER BY run_lock_until
"""


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def format_stall_section(
    text_rows: list[dict],
    model_rows: list[dict],
    batch_rows: list[dict],
) -> str:
    """Format a Markdown section for stale rows.  Returns empty string when all clear."""
    total = len(text_rows) + len(model_rows) + len(batch_rows)
    if total == 0:
        return ""

    lines: list[str] = [f"## Stalled runs ({total} detected)", ""]

    if text_rows:
        lines.append(f"### text_decision_analysis_runs ({len(text_rows)})")
        for row in text_rows:
            by = row.get("triggered_by") or "unknown"
            lines.append(
                f"- `{row['id']}` — started {_fmt_ts(row.get('started_at'))}, triggered by {by}"
            )
            lines.append(
                "  - Manual fix: `UPDATE text_decision_analysis_runs SET status='failed', error='manual cleanup', completed_at=NOW() WHERE id = '<id>';`"
            )
        lines.append("")

    if model_rows:
        lines.append(f"### model_training_runs ({len(model_rows)})")
        for row in model_rows:
            mtype = row.get("model_type") or "unknown"
            lock_ts = _fmt_ts(row.get("run_lock_until"))
            lines.append(f"- `{row['id']}` — type={mtype}, lock expired {lock_ts}")
            lines.append(
                "  - Manual fix: `UPDATE model_training_runs SET status='failed', error='manual cleanup', completed_at=NOW() WHERE id = '<id>';`"
            )
        lines.append("")

    if batch_rows:
        lines.append(f"### v2_ingest_batches ({len(batch_rows)})")
        for row in batch_rows:
            lock_ts = _fmt_ts(row.get("run_lock_until"))
            lines.append(
                f"- `{row['batch_id']}` — started {_fmt_ts(row.get('started_at'))}, lock expired {lock_ts}"
            )
            lines.append(
                "  - Manual fix: Use `POST /ingest/batch/<id>/resume` to re-queue, or update status directly in DB."
            )
        lines.append("")

    lines.append(
        "_Rows that persist across multiple nights indicate a permanently stuck worker. Check Render service logs._"
    )
    lines.append("")

    return "\n".join(lines)


def _query_stalled(
    database_url: str, text_stall_mins: int, lock_stall_mins: int
) -> tuple[list[dict], list[dict], list[dict]]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(_TEXT_ANALYSIS_SQL, {"threshold": str(text_stall_mins)})
            text_rows = cur.fetchall()

            cur.execute(_MODEL_TRAINING_SQL, {"threshold": str(lock_stall_mins)})
            model_rows = cur.fetchall()

            cur.execute(_INGEST_BATCHES_SQL, {"threshold": str(lock_stall_mins)})
            batch_rows = cur.fetchall()

    return list(text_rows), list(model_rows), list(batch_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL"),
        help="Database connection string. Defaults to $DATABASE_URL then $TEST_DATABASE_URL.",
    )
    parser.add_argument(
        "--text-stall-mins",
        type=int,
        default=int(os.environ.get("STALL_THRESHOLD_TEXT_MINS", "30")),
        help="Minutes past started_at before a text_decision_analysis_runs row is flagged (default: 30).",
    )
    parser.add_argument(
        "--lock-stall-mins",
        type=int,
        default=int(os.environ.get("STALL_THRESHOLD_LOCK_MINS", "30")),
        help="Minutes past run_lock_until expiry before a model_training_runs / v2_ingest_batches row is flagged (default: 30).",
    )
    args = parser.parse_args()

    if not args.database_url:
        print(
            "WARNING: check_stalled_runs.py: DATABASE_URL not set — skipping stall check.",
            file=sys.stderr,
        )
        return 0

    try:
        text_rows, model_rows, batch_rows = _query_stalled(
            args.database_url, args.text_stall_mins, args.lock_stall_mins
        )
    except Exception as exc:
        print(
            f"WARNING: check_stalled_runs.py: DB query failed ({exc}) — skipping stall check.",
            file=sys.stderr,
        )
        return 0

    section = format_stall_section(text_rows, model_rows, batch_rows)
    if section:
        print(section, end="")

    return 0


if __name__ == "__main__":
    sys.exit(main())
