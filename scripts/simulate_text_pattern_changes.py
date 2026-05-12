#!/usr/bin/env python3
"""
Simulate accepted exclusion-pattern recommendations against the gold-standard
corpus and persist R/P/F1 deltas + Tier-1 regression status.

Powers the "Simulate accepted recommendations" button on /v2/review/stats.
The script runs two validator passes (baseline + patched) on the subset of
gold-standard companies that carry any of the affected metrics, then persists
one text_pattern_simulation_runs row and one text_pattern_simulation_deltas
row per (rec, metric_id).

Usage:
    python3 scripts/simulate_text_pattern_changes.py \\
        --database-url "$TEST_DATABASE_URL"

    # Web-triggered invocation writes status back via --run-id:
    python3 scripts/simulate_text_pattern_changes.py \\
        --run-id <uuid> --database-url "$DATABASE_URL"

What it does:
  1. Resolve accepted recs: SELECT from text_pattern_recommendation_decisions
     WHERE decision='accepted' AND pr_number IS NULL.
  2. Filter to supported rule types: only rule='exclusion_pattern' is
     simulated. Other rule types are skipped (simulation_not_supported).
  3. Build a KeywordPatchOverride by appending each rec's decision_key
     (the phrase) to the metric's existing YAML exclusions. The override is
     existing + [phrase, ...] for each affected metric_id.
  4. Resolve affected companies: find which gold-standard companies have rows
     for any affected metric_id.
  5. Run baseline validation (no override) and patched validation on the
     same companies set.
  6. Re-run the patched validation a second time (gh-273 retry pattern).
     If both patched runs agree on tier1_presence_recall (within 0.0001
     epsilon), set runs_agree=True.
  7. Compute coverage stats per metric from the gold-standard CSV.
  8. Persist results in a single transaction.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import uuid as _uuid
from dataclasses import replace as dc_replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.rows import dict_row

from src.extraction_v2.config_hash import compute_config_hash
from src.extraction_v2.pipeline import KeywordPatchOverride, PipelineConfig
from src.gold_standard.v2_validator import GOLD_STANDARD_CSV, V2GoldStandardValidator
from src.infra.logging_config import configure_logging
from src.shared.keyword_config import get_exclusion_patterns

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# Phrases that get APPENDED (not replaced) to existing YAML exclusions.
# Only exclusion_pattern recs are simulated in v1.
_SUPPORTED_RULE = "exclusion_pattern"

# Agreement epsilon for gh-273 retry pattern.
_AGREEMENT_EPS = 0.0001

# Tier-1 regression floor: any drop larger than this (in absolute recall
# units) is a regression. Strict — even tiny drops count.
_REGRESSION_EPS = 0.0001


# ---------------------------------------------------------------------------
# Override construction
# ---------------------------------------------------------------------------


def _build_patched_override(recs: list[dict]) -> KeywordPatchOverride:
    """Build a KeywordPatchOverride from accepted exclusion_pattern recs.

    For each metric_id, the patched exclusion list is:
        existing YAML exclusions + [phrase1, phrase2, ...]

    This is an APPEND override (existing kept), not a replace override.
    The KeywordPatchOverride exclusion_patterns field replaces the full list
    per metric, so we must include the existing exclusions too.
    """
    # Group phrases by metric_id.
    by_metric: dict[str, list[str]] = {}
    for rec in recs:
        metric_id = rec["metric_id"]
        phrase = rec["decision_key"]
        by_metric.setdefault(metric_id, []).append(phrase)

    if not by_metric:
        return KeywordPatchOverride()

    existing = get_exclusion_patterns()
    patched: dict[str, list[str]] = {}
    for metric_id, new_phrases in by_metric.items():
        base = list(existing.get(metric_id) or [])
        patched[metric_id] = base + new_phrases

    return KeywordPatchOverride(exclusion_patterns=patched)


# ---------------------------------------------------------------------------
# Gold-standard CSV helpers
# ---------------------------------------------------------------------------


def _load_affected_companies(
    affected_metric_ids: set[str],
    max_companies: int | None,
) -> list[str]:
    """Return company names from the gold-standard CSV that have rows for any
    of the affected metric_ids.

    Returns an empty list if the CSV has no rows for the given metrics (not
    an error — the endpoint already validated that recs exist).
    """
    csv_path = GOLD_STANDARD_CSV
    if not csv_path.exists():
        logger.warning("Gold-standard CSV not found at %s — returning empty company list", csv_path)
        return []

    companies: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_metric = (row.get("Standard Metric Name") or "").strip()
            # Normalize: lowercase + underscores (mirrors v2_validator.normalize_metric_id)
            metric_id = _normalize_metric_id(raw_metric)
            if metric_id in affected_metric_ids:
                company = (row.get("Company") or "").strip()
                if company:
                    companies.add(company)

    result = sorted(companies)
    if max_companies is not None:
        result = result[:max_companies]
    logger.info(
        "Affected companies for metrics %s: %d (max_companies=%s)",
        sorted(affected_metric_ids),
        len(result),
        max_companies,
    )
    return result


def _compute_coverage(affected_metric_ids: set[str]) -> dict[str, dict]:
    """Return {metric_id: {coverage_filings, coverage_facts}} from the CSV.

    coverage_filings = distinct company names carrying this metric.
    coverage_facts = raw row count for this metric.
    """
    out: dict[str, dict] = {
        m: {"coverage_filings": 0, "coverage_facts": 0} for m in affected_metric_ids
    }
    csv_path = GOLD_STANDARD_CSV
    if not csv_path.exists():
        return out

    filing_sets: dict[str, set[str]] = {m: set() for m in affected_metric_ids}
    fact_counts: dict[str, int] = {m: 0 for m in affected_metric_ids}

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_metric = (row.get("Standard Metric Name") or "").strip()
            metric_id = _normalize_metric_id(raw_metric)
            if metric_id in affected_metric_ids:
                company = (row.get("Company") or "").strip()
                if company:
                    filing_sets[metric_id].add(company)
                fact_counts[metric_id] = fact_counts[metric_id] + 1

    for metric_id in affected_metric_ids:
        out[metric_id] = {
            "coverage_filings": len(filing_sets[metric_id]),
            "coverage_facts": fact_counts[metric_id],
        }
    return out


def _normalize_metric_id(raw: str) -> str:
    """Minimal normalization matching v2_validator.normalize_metric_id."""
    return raw.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _run_validation(
    override: KeywordPatchOverride | None,
    companies: list[str] | None,
) -> V2GoldStandardValidator:
    """Construct a validator with the given override and run validate_all.

    Returns the validator so the caller can call compute_metrics() on it.
    """
    base_config = PipelineConfig()
    config = dc_replace(base_config, keyword_override=override if override else None)
    validator = V2GoldStandardValidator(v2_config=config)
    # Trigger validation; results are stored in the returned validator.
    results = validator.validate_all(
        max_workers=1,
        companies=companies if companies else None,
    )
    # Attach results for compute_metrics below.
    validator._sim_results = results  # type: ignore[attr-defined]
    return validator


def _get_metrics(validator: V2GoldStandardValidator) -> AggregateMetrics:  # noqa: F821
    return validator.compute_metrics(validator._sim_results)  # type: ignore[attr-defined]


def _presence_recall_for_metric(agg, metric_id: str) -> float | None:
    scores = (agg.presence_by_metric or {}).get(metric_id)
    return scores.recall if scores is not None else None


def _presence_precision_for_metric(agg, metric_id: str) -> float | None:
    scores = (agg.presence_by_metric or {}).get(metric_id)
    return scores.precision if scores is not None else None


def _presence_f1_for_metric(agg, metric_id: str) -> float | None:
    scores = (agg.presence_by_metric or {}).get(metric_id)
    if scores is None:
        return None
    p, r = scores.precision, scores.recall
    return (2 * p * r / (p + r)) if (p + r) > 0 else 0.0


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _fetch_accepted_recs(conn: psycopg.Connection) -> list[dict]:
    """Return accepted recs that have not yet been shipped (pr_number IS NULL)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, metric_id, rule, decision_key
              FROM text_pattern_recommendation_decisions
             WHERE decision = 'accepted'
               AND pr_number IS NULL
             ORDER BY metric_id, decision_key
            """
        )
        return [dict(r) for r in cur.fetchall()]


def _mark_failed(database_url: str | None, run_id: str | None, error: str) -> None:
    """Best-effort UPDATE to flip the run row to status='failed'."""
    if not (database_url and run_id):
        return
    try:
        with psycopg.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE text_pattern_simulation_runs
                   SET status = 'failed',
                       error  = %(error)s,
                       completed_at = NOW()
                 WHERE id = %(run_id)s
                """,
                {"run_id": run_id, "error": error[:1000]},
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to mark simulation run %s failed: %s", run_id, exc)


def _ensure_run_row(conn: psycopg.Connection, *, run_id: str | None, triggered_by: str) -> str:
    """Insert a 'running' row when the script runs standalone (no --run-id).

    When invoked from the web endpoint, the caller pre-inserts the row and
    passes its UUID via --run-id; we just use that id.
    """
    if run_id:
        return run_id
    new_id = str(_uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO text_pattern_simulation_runs (id, status, triggered_by)
            VALUES (%(id)s, 'running', %(triggered_by)s)
            """,
            {"id": new_id, "triggered_by": triggered_by},
        )
    conn.commit()
    return new_id


def _persist(
    conn: psycopg.Connection,
    *,
    run_id: str,
    supported_recs: list[dict],
    all_recs: list[dict],
    baseline_agg,
    patched_agg,
    patched_agg2,
    affected_metric_ids: set[str],
    num_companies: int,
    coverage: dict[str, dict],
) -> None:
    """Write all results and flip the run row to 'succeeded'. Single transaction."""

    tier1_baseline = baseline_agg.tier1_presence_recall
    tier1_patched = patched_agg.tier1_presence_recall
    tier1_patched2 = patched_agg2.tier1_presence_recall

    tier2_baseline = baseline_agg.tier2_presence_recall
    tier2_patched = patched_agg.tier2_presence_recall

    # Tier-1 regression: any drop past the epsilon floor is a regression.
    if tier1_baseline is not None and tier1_patched is not None:
        tier1_regressed = (tier1_patched - tier1_baseline) < -_REGRESSION_EPS
    else:
        tier1_regressed = False

    # Both retry runs must agree within epsilon.
    if tier1_patched is not None and tier1_patched2 is not None:
        runs_agree = abs(tier1_patched - tier1_patched2) <= _AGREEMENT_EPS
    else:
        runs_agree = tier1_patched == tier1_patched2  # Both None → agree

    num_recs_simulated = len(supported_recs)

    with conn.cursor() as cur:
        # Update the run row with results.
        cur.execute(
            """
            UPDATE text_pattern_simulation_runs
               SET status                         = 'succeeded',
                   completed_at                   = NOW(),
                   num_recs_simulated             = %(num_recs)s,
                   num_companies_validated        = %(num_companies)s,
                   tier1_presence_recall_baseline = %(t1_base)s,
                   tier1_presence_recall_patched  = %(t1_patched)s,
                   tier2_presence_recall_baseline = %(t2_base)s,
                   tier2_presence_recall_patched  = %(t2_patched)s,
                   tier1_regressed                = %(regressed)s,
                   runs_agree                     = %(agree)s
             WHERE id = %(run_id)s
            """,
            {
                "run_id": run_id,
                "num_recs": num_recs_simulated,
                "num_companies": num_companies,
                "t1_base": tier1_baseline,
                "t1_patched": tier1_patched,
                "t2_base": tier2_baseline,
                "t2_patched": tier2_patched,
                "regressed": tier1_regressed,
                "agree": runs_agree,
            },
        )

        # Build delta rows: one per (rec, affected_metric_id).
        # For each supported rec, emit a delta for its own metric_id.
        for rec in supported_recs:
            metric_id = rec["metric_id"]
            cov = coverage.get(metric_id, {})
            cur.execute(
                """
                INSERT INTO text_pattern_simulation_deltas
                    (run_id, recommendation_decision_id, metric_id,
                     baseline_recall, baseline_precision, baseline_f1,
                     patched_recall,  patched_precision,  patched_f1,
                     coverage_filings, coverage_facts)
                VALUES
                    (%(run_id)s, %(rec_id)s, %(metric_id)s,
                     %(b_recall)s, %(b_prec)s, %(b_f1)s,
                     %(p_recall)s, %(p_prec)s, %(p_f1)s,
                     %(cov_filings)s, %(cov_facts)s)
                """,
                {
                    "run_id": run_id,
                    "rec_id": str(rec["id"]),
                    "metric_id": metric_id,
                    "b_recall": _presence_recall_for_metric(baseline_agg, metric_id),
                    "b_prec": _presence_precision_for_metric(baseline_agg, metric_id),
                    "b_f1": _presence_f1_for_metric(baseline_agg, metric_id),
                    "p_recall": _presence_recall_for_metric(patched_agg, metric_id),
                    "p_prec": _presence_precision_for_metric(patched_agg, metric_id),
                    "p_f1": _presence_f1_for_metric(patched_agg, metric_id),
                    "cov_filings": cov.get("coverage_filings"),
                    "cov_facts": cov.get("coverage_facts"),
                },
            )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _orchestrate(args: argparse.Namespace) -> None:
    """Connect, resolve, validate, persist."""
    if not args.database_url:
        raise RuntimeError(
            "No database URL available. Set $TEST_DATABASE_URL or pass --database-url."
        )

    with psycopg.connect(args.database_url, autocommit=False) as conn:
        run_id = _ensure_run_row(
            conn,
            run_id=args.run_id,
            triggered_by=args.triggered_by or "cli",
        )

        config_snapshot_hash = compute_config_hash()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE text_pattern_simulation_runs
                   SET config_snapshot_hash = %(hash)s
                 WHERE id = %(run_id)s
                """,
                {"hash": config_snapshot_hash, "run_id": run_id},
            )
        conn.commit()
        logger.info("Config snapshot hash: %s", config_snapshot_hash[:12])

        all_recs = _fetch_accepted_recs(conn)
        logger.info("Found %d accepted recs (pr_number IS NULL)", len(all_recs))

        supported_recs = [r for r in all_recs if r["rule"] == _SUPPORTED_RULE]
        unsupported_recs = [r for r in all_recs if r["rule"] != _SUPPORTED_RULE]
        if unsupported_recs:
            logger.info(
                "Skipping %d unsupported rec(s) (rules: %s) — simulation_not_supported",
                len(unsupported_recs),
                sorted({r["rule"] for r in unsupported_recs}),
            )

        affected_metric_ids = {r["metric_id"] for r in supported_recs}
        logger.info("Affected metric_ids: %s", sorted(affected_metric_ids))

        # Resolve affected companies from the gold-standard CSV.
        companies = _load_affected_companies(affected_metric_ids, args.max_companies)

        # Zero coverage is OK — record the run as succeeded with no deltas.
        if not companies and affected_metric_ids:
            logger.warning(
                "No gold-standard coverage for affected metrics — run will succeed "
                "with num_companies_validated=0"
            )

        # Coverage stats (cheap — CSV already loaded above).
        coverage = _compute_coverage(affected_metric_ids)

        # Build override.
        override = _build_patched_override(supported_recs) if supported_recs else None
        logger.info("Running baseline validation on %d companies...", len(companies))

        companies_arg = companies if companies else None

        # Baseline (no override).
        baseline_validator = _run_validation(None, companies_arg)
        baseline_agg = _get_metrics(baseline_validator)
        logger.info(
            "Baseline: tier1_presence_recall=%s",
            baseline_agg.tier1_presence_recall,
        )

        # Patched (first run).
        logger.info("Running patched validation (run 1)...")
        patched_validator1 = _run_validation(override, companies_arg)
        patched_agg1 = _get_metrics(patched_validator1)
        logger.info(
            "Patched run 1: tier1_presence_recall=%s",
            patched_agg1.tier1_presence_recall,
        )

        # Patched (second run — gh-273 retry pattern).
        logger.info("Running patched validation (run 2, gh-273 retry)...")
        patched_validator2 = _run_validation(override, companies_arg)
        patched_agg2 = _get_metrics(patched_validator2)
        logger.info(
            "Patched run 2: tier1_presence_recall=%s",
            patched_agg2.tier1_presence_recall,
        )

        _persist(
            conn,
            run_id=run_id,
            supported_recs=supported_recs,
            all_recs=all_recs,
            baseline_agg=baseline_agg,
            patched_agg=patched_agg1,
            patched_agg2=patched_agg2,
            affected_metric_ids=affected_metric_ids,
            num_companies=len(companies),
            coverage=coverage,
        )
        conn.commit()
        logger.info("Simulation complete. Run id: %s", run_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate accepted exclusion-pattern recommendations against the "
            "gold-standard corpus and persist R/P/F1 deltas."
        ),
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
            "Optional text_pattern_simulation_runs.id (UUID). When set, the script "
            "writes status/metrics/error back to that row (web-triggered invocation). "
            "When unset, the script inserts its own 'running' row at start (CLI use)."
        ),
    )
    parser.add_argument(
        "--triggered-by",
        type=str,
        default=None,
        help="Reviewer name / 'cli' / 'cron' — written to triggered_by when --run-id is unset.",
    )
    parser.add_argument(
        "--max-companies",
        type=int,
        default=None,
        help=(
            "Cap the number of gold-standard companies validated. Useful for "
            "development; production calls should omit this flag."
        ),
    )
    args = parser.parse_args()

    configure_logging(level="INFO")

    if args.run_id:
        try:
            _orchestrate(args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Simulation failed: %s", exc)
            _mark_failed(args.database_url, args.run_id, str(exc))
            sys.exit(1)
    else:
        _orchestrate(args)


if __name__ == "__main__":
    main()
