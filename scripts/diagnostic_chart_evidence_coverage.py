"""
One-off diagnostic for the "missing Chart Evidence preview" issue in the V2
review UI.

The UI renders a Chart Evidence image block only when `source_locator.img_id`
is present (`src/web/templates/unified_review.html:337-355`). A fact can end
up without a visible chart preview through any of these classes:

  (A) source_type='chart' fact with null source_locator.img_id — never should
      happen given chart_fact_bridge.py always sets it; non-zero here means a
      persistence-layer bug.
  (B) source_type='chart' fact whose img_id does not resolve to a
      v2_image_assets row (orphaned).
  (C) v2_image_assets row whose file_path is set but the file is missing on
      disk — image_crop returns 404.
  (D) Tier-1 chart-native metrics (e.g. cm_revenue_by_cohort) with facts
      whose source_type != 'chart' — value came from prose / chart-caption
      text, so the fact has no img_id at all.
  (E) Filings with chart-class images but zero chart-sourced facts — signals
      chart OCR failure (malformed JSON before 2026-04-17 fix).

Read-only. Does not mutate any DB or filesystem state.

Usage:
    python3 scripts/diagnostic_chart_evidence_coverage.py
    python3 scripts/diagnostic_chart_evidence_coverage.py --company Box
    python3 scripts/diagnostic_chart_evidence_coverage.py --sample 20
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

# Chart-native Tier-1 metrics — those where the underlying value is almost
# always sourced from a chart rather than text/tables. Mirrors the set used
# by v2_validator._derive_chart_native_metrics; kept explicit here so the
# diagnostic does not depend on gold-standard loading.
CHART_NATIVE_TIER1 = (
    "cm_revenue_by_cohort",
    "cm_balance_by_cohort",
    "cm_transactions_by_cohort",
    "cm_gross_margin_by_cohort",
    "cm_ltv_to_cac_ratio_by_cohort",
    "cm_revenue_concentration",
)


def _count_chart_facts_with_null_img_id(db: DatabaseAdapter) -> list[dict]:
    """Class (A): source_type='chart' facts missing source_locator.img_id."""
    sql = """
        SELECT
            f.fact_id,
            f.filing_id,
            f.canonical_metric_id,
            f.source_locator
          FROM v2_metric_facts f
         WHERE f.source_type = 'chart'
           AND (
                NOT (f.source_locator ? 'img_id')
                OR (f.source_locator->>'img_id') IS NULL
           )
    """
    return db.query(sql)


def _count_orphaned_img_id_refs(db: DatabaseAdapter) -> list[dict]:
    """Class (B): img_id in source_locator that does not match any asset row."""
    sql = """
        SELECT
            f.fact_id,
            f.filing_id,
            f.canonical_metric_id,
            f.source_type,
            f.source_locator->>'img_id' AS img_id
          FROM v2_metric_facts f
         WHERE f.source_locator ? 'img_id'
           AND (f.source_locator->>'img_id') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM v2_image_assets a
                WHERE a.img_id::text = (f.source_locator->>'img_id')
           )
    """
    return db.query(sql)


def _check_missing_image_files(db: DatabaseAdapter) -> tuple[int, int, list[dict]]:
    """Class (C): v2_image_assets rows whose file_path is not on disk.

    Returns (checked, missing, sample_rows).
    """
    rows = db.query(
        """
        SELECT img_id, filing_id, filename, file_path
          FROM v2_image_assets
         WHERE file_path IS NOT NULL
        """
    )
    missing: list[dict] = []
    for row in rows:
        path = row.get("file_path")
        if not path:
            continue
        if not Path(path).exists():
            missing.append(row)
    return len(rows), len(missing), missing


def _chart_native_tier1_source_mix(db: DatabaseAdapter) -> list[dict]:
    """Class (D): for chart-native Tier-1 metrics, per-metric source_type mix."""
    sql = """
        SELECT
            f.canonical_metric_id,
            f.source_type,
            COUNT(*) AS n
          FROM v2_metric_facts f
         WHERE f.canonical_metric_id = ANY(%(metrics)s)
         GROUP BY f.canonical_metric_id, f.source_type
         ORDER BY f.canonical_metric_id, f.source_type
    """
    return db.query(sql, {"metrics": list(CHART_NATIVE_TIER1)})


def _chart_image_vs_fact_rate(db: DatabaseAdapter) -> list[dict]:
    """Class (E): filings with chart-class images but zero chart-sourced facts."""
    sql = """
        WITH chart_imgs AS (
            SELECT filing_id, COUNT(*) AS n_chart_imgs
              FROM v2_image_assets
             WHERE classification = 'chart'
             GROUP BY filing_id
        ),
        chart_facts AS (
            SELECT filing_id, COUNT(*) AS n_chart_facts
              FROM v2_metric_facts
             WHERE source_type = 'chart'
             GROUP BY filing_id
        )
        SELECT
            ci.filing_id,
            ci.n_chart_imgs,
            COALESCE(cf.n_chart_facts, 0) AS n_chart_facts
          FROM chart_imgs ci
          LEFT JOIN chart_facts cf USING (filing_id)
         WHERE COALESCE(cf.n_chart_facts, 0) = 0
         ORDER BY ci.n_chart_imgs DESC
    """
    return db.query(sql)


def _find_company_filing_facts(
    db: DatabaseAdapter, company_pattern: str, metric_id: str
) -> list[dict]:
    """Specific lookup for user's Box example."""
    sql = """
        SELECT
            c.company_name AS company_name,
            c.ticker,
            fi.filing_id,
            fi.form_type AS filing_type,
            fi.filing_date,
            f.fact_id,
            f.canonical_metric_id,
            f.value,
            f.value_raw,
            f.source_type,
            f.source_locator,
            f.confidence,
            f.review_status
          FROM v2_metric_facts f
          JOIN filings fi ON fi.filing_id = f.filing_id
          JOIN companies c ON c.company_id = fi.company_id
         WHERE c.company_name ILIKE %(company)s
           AND f.canonical_metric_id = %(metric)s
         ORDER BY fi.filing_date DESC, f.value
    """
    return db.query(sql, {"company": f"%{company_pattern}%", "metric": metric_id})


def _print_section(title: str) -> None:
    logger.info("")
    logger.info("=" * 72)
    logger.info(title)
    logger.info("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL")
    parser.add_argument(
        "--company",
        default="Box",
        help="Company-name substring for the targeted lookup (default: Box).",
    )
    parser.add_argument(
        "--metric",
        default="cm_revenue_by_cohort",
        help="Metric for the targeted lookup (default: cm_revenue_by_cohort).",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Max rows to print per sample block (default: 10).",
    )
    args = parser.parse_args()

    configure_logging(level="INFO")
    load_dotenv()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 1

    db = DatabaseAdapter(db_url)

    # (A) chart facts with null img_id
    _print_section("(A) source_type='chart' facts with null source_locator.img_id")
    a_rows = _count_chart_facts_with_null_img_id(db)
    logger.info("count: %d", len(a_rows))
    for row in a_rows[: args.sample]:
        logger.info(
            "  fact_id=%s filing_id=%s metric=%s",
            row["fact_id"],
            row["filing_id"],
            row["canonical_metric_id"],
        )

    # (B) orphaned img_id refs
    _print_section("(B) orphaned source_locator.img_id (no matching v2_image_assets row)")
    b_rows = _count_orphaned_img_id_refs(db)
    logger.info("count: %d", len(b_rows))
    by_source = {}
    for row in b_rows:
        by_source[row["source_type"]] = by_source.get(row["source_type"], 0) + 1
    for st, n in sorted(by_source.items()):
        logger.info("  source_type=%s: %d", st, n)
    for row in b_rows[: args.sample]:
        logger.info(
            "  fact_id=%s filing_id=%s metric=%s source_type=%s img_id=%s",
            row["fact_id"],
            row["filing_id"],
            row["canonical_metric_id"],
            row["source_type"],
            row["img_id"],
        )

    # (C) missing image files on disk
    _print_section("(C) v2_image_assets rows with file_path set but file missing on disk")
    c_checked, c_missing_count, c_missing_rows = _check_missing_image_files(db)
    logger.info("checked=%d missing=%d", c_checked, c_missing_count)
    for row in c_missing_rows[: args.sample]:
        logger.info(
            "  img_id=%s filing_id=%s filename=%s path=%s",
            row["img_id"],
            row["filing_id"],
            row["filename"],
            row["file_path"],
        )

    # (D) chart-native Tier-1 source-type mix
    _print_section("(D) chart-native Tier-1 metric fact source-type mix")
    d_rows = _chart_native_tier1_source_mix(db)
    totals: dict[str, dict[str, int]] = {}
    for row in d_rows:
        m = row["canonical_metric_id"]
        totals.setdefault(m, {})[row["source_type"]] = int(row["n"])
    for metric in CHART_NATIVE_TIER1:
        mix = totals.get(metric, {})
        total = sum(mix.values())
        chart_n = mix.get("chart", 0)
        non_chart = total - chart_n
        logger.info(
            "  %s: total=%d chart=%d non-chart=%d  breakdown=%s",
            metric,
            total,
            chart_n,
            non_chart,
            ", ".join(f"{k}={v}" for k, v in sorted(mix.items())) or "(none)",
        )

    # (E) filings with chart images but no chart facts
    _print_section("(E) filings with chart-class images but zero chart-sourced facts")
    e_rows = _chart_image_vs_fact_rate(db)
    logger.info("affected filings: %d", len(e_rows))
    for row in e_rows[: args.sample]:
        logger.info(
            "  filing_id=%s n_chart_imgs=%d n_chart_facts=%d",
            row["filing_id"],
            row["n_chart_imgs"],
            row["n_chart_facts"],
        )

    # Targeted: company + metric lookup
    _print_section(f"targeted: company ILIKE '%{args.company}%' metric={args.metric}")
    t_rows = _find_company_filing_facts(db, args.company, args.metric)
    logger.info("count: %d", len(t_rows))
    for row in t_rows:
        loc = row["source_locator"] or {}
        img_id = loc.get("img_id") if isinstance(loc, dict) else None
        logger.info(
            "  %s %s %s filing_id=%s value=%s raw=%s source_type=%s img_id=%s status=%s",
            row["company_name"],
            row["ticker"],
            row["filing_type"],
            row["filing_id"],
            row["value"],
            row["value_raw"],
            row["source_type"],
            img_id,
            row["review_status"],
        )

    _print_section("summary")
    logger.info("(A) chart facts null img_id: %d", len(a_rows))
    logger.info("(B) orphaned img_id refs   : %d", len(b_rows))
    logger.info("(C) missing on-disk images : %d / %d", c_missing_count, c_checked)
    logger.info("(D) see per-metric mix above")
    logger.info("(E) zero-chart-fact filings: %d", len(e_rows))

    return 0


if __name__ == "__main__":
    sys.exit(main())
