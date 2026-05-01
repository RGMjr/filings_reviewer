#!/usr/bin/env python3
"""
Mine human-review decisions on text-extracted facts for high-incidence
root-cause phrases.

Powers the "Update Text Pattern Analysis" button on /v2/review/stats. The
output is written to three tables (text_decision_analysis_runs,
text_decision_metric_summary, text_decision_phrase_findings) and rendered by
the stats page — there is no on-disk artifact (sidesteps Render disk
ephemerality, unlike the image-classifier retrain).

Usage:
    python3 scripts/analyze_text_decision_patterns.py \\
        --database-url "$TEST_DATABASE_URL"

    # Web-triggered invocation writes status back via --run-id:
    python3 scripts/analyze_text_decision_patterns.py \\
        --run-id <uuid> --database-url "$DATABASE_URL"

What it does:
  1. Resolve anchor = completed_at of the most recent succeeded run (None if
     there is no prior succeeded run, in which case the analysis covers all
     decisions ever).
  2. Pull v2_review_decisions joined to v2_metric_facts and v2_segments where
     created_at > anchor.
  3. Per canonical_metric_id: count by decision type, build a rejection-
     category histogram, build a top-correction-targets list, and mine
     n-grams (n in {1,2,3}) from rejection_reason + reviewer_notes + a window
     of segment_text. Suppress stopwords + the metric's own keyword tokens
     so the metric name itself doesn't dominate findings.
  4. Filter findings to those with occurrence_count >= MIN_OCCURRENCES and
     pct_of_decisions >= MIN_PCT, keep top TOP_N per (metric, decision_type,
     source_field).
  5. Capture up to 5 example {fact_id, filing_id} pairs per phrase for UI
     drill-down.
  6. INSERT all rows in a single transaction; UPDATE the run row to
     'succeeded' on the way out. Any unhandled exception flips the row to
     'failed' with the error text.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import uuid as _uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.rows import dict_row

from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# Tunables. Tightening these post-first-run is a config-only change (env
# overrides land in the API route, not here, so the script stays pure).
MIN_OCCURRENCES = 2
MIN_PCT = 10.0
TOP_N_PER_BUCKET = 15
MAX_EXAMPLES = 5
NGRAM_SIZES = (1, 2, 3)
SEGMENT_WINDOW_CHARS = 200

# Stopwords kept short and English-only — the corpus is SEC filings, so we
# strip articles/connectives and finance-noise tokens that show up in nearly
# every segment without telling us anything useful.
_STOPWORDS = frozenset(
    """
    a an and any as at be been being but by can could did do does each
    either few for from had has have having he her here him his how i if
    in into is it its just may me might more most must my no nor not now
    of off on only or our out over per s shall she should so some such
    t than that the their them then there these they this those through
    to too under until up upon us used we were what when where whether
    which while who whom why will with within without would you your
    company customer customers data financial fiscal include including
    information measure metric metrics period periods quarter quarters
    revenue revenues number percent total
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]+")


def _tokenize(text: str | None) -> list[str]:
    """Lower-cased alpha tokens, length >= 3, stopwords stripped."""
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]


def _ngrams(tokens: list[str], n: int) -> list[str]:
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _segment_window(segment_text: str | None, value_raw: str | None) -> str:
    """Return ±SEGMENT_WINDOW_CHARS around the first occurrence of value_raw.

    Falls back to the full segment_text (clipped to 2*window) if the value
    can't be located. Reduces noise from long segments containing many
    unrelated metrics.
    """
    if not segment_text:
        return ""
    if value_raw and value_raw.strip():
        idx = segment_text.find(value_raw.strip())
        if idx >= 0:
            start = max(0, idx - SEGMENT_WINDOW_CHARS)
            end = min(len(segment_text), idx + len(value_raw) + SEGMENT_WINDOW_CHARS)
            return segment_text[start:end]
    return segment_text[: 2 * SEGMENT_WINDOW_CHARS]


def _load_metric_keyword_tokens() -> dict[str, set[str]]:
    """Per-metric token blocklist so the metric's own name doesn't dominate
    its own findings. Returns {metric_id: {token, ...}}.

    Falls back to empty dict if the keyword config can't be loaded — better
    to surface noisy findings than to fail the run.
    """
    try:
        from src.shared.keyword_config import get_metric_keywords

        keywords = get_metric_keywords()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load metric_keywords.yaml: %s", exc)
        return {}

    out: dict[str, set[str]] = {}
    for metric_id, patterns in keywords.items():
        toks: set[str] = set()
        for pat in patterns or []:
            for t in _TOKEN_RE.findall((pat or "").lower()):
                if len(t) >= 3:
                    toks.add(t)
        out[metric_id] = toks
    return out


def _resolve_anchor(conn: psycopg.Connection) -> datetime | None:
    """Most recent succeeded run's completed_at, or None on first run."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT completed_at
              FROM text_decision_analysis_runs
             WHERE status = 'succeeded'
             ORDER BY completed_at DESC
             LIMIT 1
            """
        )
        row = cur.fetchone()
    return row["completed_at"] if row else None


def _fetch_decisions(
    conn: psycopg.Connection,
    *,
    anchor: datetime | None,
    max_decisions: int | None,
) -> list[dict]:
    """Pull v2_review_decisions joined to v2_metric_facts and v2_segments
    since anchor. anchor=None ⇒ all decisions ever.

    Joins to v2_segments via mf.source_locator->>'segment_id' so we can pull
    the raw segment text for n-gram mining.
    """
    sql = """
        SELECT
            rd.decision,
            rd.rejection_category,
            rd.rejection_reason,
            rd.reviewer_notes,
            rd.assigned_metric_id,
            mf.fact_id,
            mf.filing_id,
            mf.canonical_metric_id,
            mf.value_raw,
            s.segment_text
          FROM v2_review_decisions rd
          JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
          LEFT JOIN v2_segments s
            ON s.segment_id = (mf.source_locator->>'segment_id')::uuid
         WHERE (%(anchor)s::timestamptz IS NULL OR rd.created_at > %(anchor)s::timestamptz)
         ORDER BY rd.created_at ASC
    """
    if max_decisions is not None:
        sql += " LIMIT %(max_decisions)s"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"anchor": anchor, "max_decisions": max_decisions})
        return [dict(r) for r in cur.fetchall()]


def _build_metric_summary(decisions: list[dict]) -> list[dict]:
    """Group decisions by canonical_metric_id and roll up counts.

    Returns one dict per metric with keys: metric_id, total_decisions,
    accept_count, reject_count, correct_count, rejection_categories,
    top_correction_targets.
    """
    by_metric: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        by_metric[d["canonical_metric_id"]].append(d)

    summaries: list[dict] = []
    for metric_id, rows in by_metric.items():
        accept = sum(1 for r in rows if r["decision"] == "accept")
        reject = sum(1 for r in rows if r["decision"] == "reject")
        correct = sum(1 for r in rows if r["decision"] == "correct")

        cats = Counter(
            r["rejection_category"]
            for r in rows
            if r["decision"] == "reject" and r["rejection_category"]
        )
        targets = Counter(
            r["assigned_metric_id"]
            for r in rows
            if r["decision"] == "correct" and r["assigned_metric_id"]
        )

        summaries.append(
            {
                "metric_id": metric_id,
                "total_decisions": len(rows),
                "accept_count": accept,
                "reject_count": reject,
                "correct_count": correct,
                "rejection_categories": dict(cats),
                "top_correction_targets": [
                    {"target_metric_id": t, "count": c} for t, c in targets.most_common()
                ],
            }
        )
    return summaries


def _mine_phrases_for_metric(
    rows: list[dict],
    metric_id: str,
    *,
    decision_type: str,
    metric_keyword_tokens: set[str],
) -> list[dict]:
    """Compute high-incidence phrases for one (metric, decision_type) bucket.

    For each source field (rejection_reason / reviewer_notes / segment_text),
    counts n-grams across all matching decisions, filters by occurrence and
    decision-share thresholds, and keeps top TOP_N_PER_BUCKET.

    Returns a list of finding dicts ready for INSERT.
    """
    relevant = [r for r in rows if r["decision"] == decision_type]
    n_decisions = len(relevant)
    if n_decisions == 0:
        return []

    findings: list[dict] = []

    for source_field in ("rejection_reason", "reviewer_notes", "segment_text"):
        # Map phrase → {count, ngram_size, examples}
        counts: dict[str, int] = Counter()
        sizes: dict[str, int] = {}
        examples: dict[str, list[dict]] = defaultdict(list)
        # Track decisions that contributed to each phrase to avoid
        # double-counting when the same phrase appears twice in one row.
        contributing: dict[str, set[str]] = defaultdict(set)

        for row in relevant:
            if source_field == "segment_text":
                text = _segment_window(row.get("segment_text"), row.get("value_raw"))
            else:
                text = row.get(source_field) or ""
            tokens = [t for t in _tokenize(text) if t not in metric_keyword_tokens]

            seen_in_row: set[str] = set()
            for n in NGRAM_SIZES:
                for phrase in _ngrams(tokens, n):
                    if phrase in seen_in_row:
                        continue
                    seen_in_row.add(phrase)
                    counts[phrase] += 1
                    sizes[phrase] = n
                    fact_key = str(row["fact_id"])
                    if fact_key not in contributing[phrase]:
                        contributing[phrase].add(fact_key)
                        if len(examples[phrase]) < MAX_EXAMPLES:
                            examples[phrase].append(
                                {
                                    "fact_id": str(row["fact_id"]),
                                    "filing_id": int(row["filing_id"]),
                                }
                            )

        # Filter and rank.
        ranked = sorted(
            ((phrase, cnt) for phrase, cnt in counts.items() if cnt >= MIN_OCCURRENCES),
            key=lambda x: (-x[1], x[0]),
        )

        kept = 0
        for phrase, cnt in ranked:
            pct = round(100.0 * cnt / n_decisions, 2)
            if pct < MIN_PCT:
                continue
            findings.append(
                {
                    "metric_id": metric_id,
                    "decision_type": decision_type,
                    "phrase": phrase,
                    "phrase_ngram_size": sizes[phrase],
                    "source_field": source_field,
                    "occurrence_count": cnt,
                    "pct_of_decisions": pct,
                    "examples": examples[phrase],
                }
            )
            kept += 1
            if kept >= TOP_N_PER_BUCKET:
                break

    return findings


def _persist(
    conn: psycopg.Connection,
    *,
    run_id: str,
    summaries: list[dict],
    findings: list[dict],
    num_decisions: int,
) -> None:
    """Write summary + finding rows; UPDATE the run to 'succeeded'.

    Single transaction so a partial-write doesn't leave an inconsistent
    snapshot under a 'succeeded' row.
    """
    import json

    with conn.cursor() as cur:
        if summaries:
            cur.executemany(
                """
                INSERT INTO text_decision_metric_summary
                    (run_id, metric_id, total_decisions, accept_count,
                     reject_count, correct_count, rejection_categories,
                     top_correction_targets)
                VALUES
                    (%(run_id)s, %(metric_id)s, %(total_decisions)s,
                     %(accept_count)s, %(reject_count)s, %(correct_count)s,
                     %(rejection_categories)s::jsonb,
                     %(top_correction_targets)s::jsonb)
                """,
                [
                    {
                        "run_id": run_id,
                        "metric_id": s["metric_id"],
                        "total_decisions": s["total_decisions"],
                        "accept_count": s["accept_count"],
                        "reject_count": s["reject_count"],
                        "correct_count": s["correct_count"],
                        "rejection_categories": json.dumps(s["rejection_categories"]),
                        "top_correction_targets": json.dumps(s["top_correction_targets"]),
                    }
                    for s in summaries
                ],
            )

        if findings:
            cur.executemany(
                """
                INSERT INTO text_decision_phrase_findings
                    (run_id, metric_id, decision_type, phrase,
                     phrase_ngram_size, source_field, occurrence_count,
                     pct_of_decisions, examples)
                VALUES
                    (%(run_id)s, %(metric_id)s, %(decision_type)s,
                     %(phrase)s, %(phrase_ngram_size)s, %(source_field)s,
                     %(occurrence_count)s, %(pct_of_decisions)s,
                     %(examples)s::jsonb)
                """,
                [
                    {
                        "run_id": run_id,
                        "metric_id": f["metric_id"],
                        "decision_type": f["decision_type"],
                        "phrase": f["phrase"],
                        "phrase_ngram_size": f["phrase_ngram_size"],
                        "source_field": f["source_field"],
                        "occurrence_count": f["occurrence_count"],
                        "pct_of_decisions": float(f["pct_of_decisions"]),
                        "examples": json.dumps(f["examples"]),
                    }
                    for f in findings
                ],
            )

        cur.execute(
            """
            UPDATE text_decision_analysis_runs
               SET status = 'succeeded',
                   completed_at = NOW(),
                   num_decisions_analyzed = %(num_decisions)s,
                   num_metrics_analyzed = %(num_metrics)s
             WHERE id = %(run_id)s
            """,
            {
                "run_id": run_id,
                "num_decisions": num_decisions,
                "num_metrics": len(summaries),
            },
        )


def _mark_failed(database_url: str | None, run_id: str | None, error: str) -> None:
    """Best-effort UPDATE to flip the row to status='failed'."""
    if not (database_url and run_id):
        return
    try:
        with psycopg.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE text_decision_analysis_runs
                   SET status = 'failed',
                       error = %(error)s,
                       completed_at = NOW()
                 WHERE id = %(run_id)s
                """,
                {"run_id": run_id, "error": error[:1000]},
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to mark run %s failed: %s", run_id, exc)


def _ensure_run_row(conn: psycopg.Connection, *, run_id: str | None, triggered_by: str) -> str:
    """Insert a row when the script runs standalone (CLI) without --run-id.

    When invoked from the web endpoint, the caller has already INSERTed the
    'running' row and passes its UUID via --run-id; we just use that id and
    leave the row alone.
    """
    if run_id:
        return run_id
    new_id = str(_uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO text_decision_analysis_runs (id, status, triggered_by)
            VALUES (%(id)s, 'running', %(triggered_by)s)
            """,
            {"id": new_id, "triggered_by": triggered_by},
        )
    conn.commit()
    return new_id


def _orchestrate(args: argparse.Namespace) -> None:
    """Connect, mine, write. Caller wraps in try/except for run-id mode."""
    if not args.database_url:
        raise RuntimeError(
            "No database URL available. Set $TEST_DATABASE_URL or pass --database-url."
        )

    metric_keyword_tokens = _load_metric_keyword_tokens()

    with psycopg.connect(args.database_url, autocommit=False) as conn:
        run_id = _ensure_run_row(conn, run_id=args.run_id, triggered_by=args.triggered_by or "cli")

        anchor = _resolve_anchor(conn)
        logger.info("Anchor for analysis: %s", anchor or "(lifetime, no prior succeeded run)")

        decisions = _fetch_decisions(conn, anchor=anchor, max_decisions=args.max_decisions)
        logger.info("Pulled %d decisions for analysis", len(decisions))

        summaries = _build_metric_summary(decisions)
        logger.info("Rolled up %d distinct metrics", len(summaries))

        # Group decisions by metric once for n-gram mining.
        by_metric: dict[str, list[dict]] = defaultdict(list)
        for d in decisions:
            by_metric[d["canonical_metric_id"]].append(d)

        findings: list[dict] = []
        for metric_id, rows in by_metric.items():
            tokens_to_block = metric_keyword_tokens.get(metric_id, set())
            for decision_type in ("reject", "correct"):
                findings.extend(
                    _mine_phrases_for_metric(
                        rows,
                        metric_id,
                        decision_type=decision_type,
                        metric_keyword_tokens=tokens_to_block,
                    )
                )
        logger.info("Mined %d phrase findings", len(findings))

        _persist(
            conn,
            run_id=run_id,
            summaries=summaries,
            findings=findings,
            num_decisions=len(decisions),
        )
        conn.commit()

        logger.info("Analysis complete. Run id: %s", run_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mine human-review decisions for high-incidence root-cause phrases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.environ.get("TEST_DATABASE_URL"),
        help=(
            "Database connection string. Defaults to $TEST_DATABASE_URL. "
            "Pass the Neon URL for production runs."
        ),
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help=(
            "Optional text_decision_analysis_runs.id (UUID). When set, the "
            "script writes status/metrics/error back to that row; the row is "
            "presumed to already exist (web-triggered invocation). When unset, "
            "the script inserts its own 'running' row at start (CLI use)."
        ),
    )
    parser.add_argument(
        "--triggered-by",
        type=str,
        default=None,
        help="Reviewer name / 'cli' / 'cron' — written to triggered_by when --run-id is unset.",
    )
    parser.add_argument(
        "--max-decisions",
        type=int,
        default=None,
        help=(
            "Cap the number of decisions pulled per run. Useful on a large "
            "first run; default unlimited."
        ),
    )
    args = parser.parse_args()

    configure_logging(level="INFO")

    if args.run_id:
        # Wrap so any exception flips the row to 'failed'.
        try:
            _orchestrate(args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Analysis failed: %s", exc)
            _mark_failed(args.database_url, args.run_id, str(exc))
            sys.exit(1)
    else:
        _orchestrate(args)


if __name__ == "__main__":
    main()
