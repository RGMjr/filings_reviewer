#!/usr/bin/env python3
"""Analyze image rejection patterns to calibrate auto-reject candidate scoring.

Queries v2_image_metric_confirmations ground-truth decisions and cross-tabulates
rejection rates against available image features (classification, relevance_score,
detection_tier, detected_metrics count).

Usage:
    python3 scripts/analyze_image_rejection_patterns.py
    python3 scripts/analyze_image_rejection_patterns.py --database-url "$DATABASE_URL"
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg.rows import dict_row

_QUERY = """
WITH image_labels AS (
  SELECT
    v.img_id,
    v.classification,
    v.relevance_score,
    v.predicted_relevance,
    COALESCE(jsonb_array_length(v.detected_metrics), 0)  AS detected_count,
    CASE
      WHEN v.classification = 'chart' AND v.relevance_score >= 0.6
        THEN 'tier_1_cohort'
      WHEN v.classification IN ('chart', 'table_image')
           AND COALESCE(v.width, 0) >= 300
           AND COALESCE(v.height, 0) >= 300
        THEN 'tier_2_large'
      ELSE 'tier_3_all'
    END AS detection_tier,
    -- Skip rows are deferred, not decided — exclude from labeled denominator
    COUNT(imc.id) FILTER (WHERE imc.decision != 'skip') AS substantive_decisions,
    BOOL_OR(
      (imc.decision = 'reject' AND imc.rejection_reason = 'no_relevant_metrics')
      OR (imc.decision = 'reject' AND imc.detected_metric_id IS NOT NULL)
    ) AS has_any_reject,
    BOOL_OR(imc.decision IN ('accept', 'correct', 'add')) AS has_any_positive
  FROM v2_image_assets v
  LEFT JOIN v2_image_metric_confirmations imc ON imc.img_id = v.img_id
  GROUP BY
    v.img_id, v.classification, v.relevance_score, v.predicted_relevance,
    v.detected_metrics, v.width, v.height
),
labeled AS (
  SELECT *,
    (has_any_reject AND NOT has_any_positive) AS fully_rejected
  FROM image_labels
  WHERE substantive_decisions > 0
)
SELECT * FROM labeled
"""


def _pct(n: int, d: int) -> str:
    if d == 0:
        return "  n/a"
    return f"{100 * n / d:5.1f}%"


def _print_table(title: str, rows: list[tuple], headers: tuple) -> None:
    print(f"\n{title}")
    print("-" * 60)
    col_widths = [
        max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt.format(*row))


def _bucket_relevance(score: float | None) -> str:
    if score is None:
        return "NULL"
    if score < 0.1:
        return "<0.10"
    if score < 0.2:
        return "0.10–0.20"
    if score < 0.3:
        return "0.20–0.30"
    if score < 0.5:
        return "0.30–0.50"
    if score < 0.7:
        return "0.50–0.70"
    return "≥0.70"


def _bucket_pred_relevance(score: float | None) -> str:
    if score is None:
        return "NULL"
    if score < 0.2:
        return "<0.20"
    if score < 0.4:
        return "0.20–0.40"
    if score < 0.6:
        return "0.40–0.60"
    return "≥0.60"


def _bucket_detected(count: int) -> str:
    if count == 0:
        return "0"
    if count == 1:
        return "1"
    return "2+"


def analyze(database_url: str) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(_QUERY)
            rows = cur.fetchall()

    total = len(rows)
    if total == 0:
        print('No labeled images found. Run against prod with --database-url "$DATABASE_URL".')
        sys.exit(0)

    rejected = sum(1 for r in rows if r["fully_rejected"])
    print(f"\nLabeled images:  {total}")
    print(f"Fully rejected:  {rejected} ({_pct(rejected, total)} rejection rate)")
    print(f"Has positive:    {total - rejected} ({_pct(total - rejected, total)})")

    # --- Per-dimension analysis ---

    def tabulate(dim_fn, dim_name: str) -> None:
        buckets: dict[str, list[int, int]] = {}  # bucket -> [total, rejected]
        for r in rows:
            b = dim_fn(r)
            if b not in buckets:
                buckets[b] = [0, 0]
            buckets[b][0] += 1
            if r["fully_rejected"]:
                buckets[b][1] += 1
        table_rows = sorted(
            [(b, n, rej, _pct(rej, n)) for b, (n, rej) in buckets.items()],
            key=lambda x: -x[1],
        )
        _print_table(dim_name, table_rows, (dim_name, "labeled", "rejected", "reject%"))

    tabulate(lambda r: r["detection_tier"], "Detection Tier")
    tabulate(lambda r: r["classification"] or "NULL", "Classification")
    tabulate(lambda r: _bucket_relevance(r["relevance_score"]), "Relevance Score")
    tabulate(lambda r: _bucket_detected(r["detected_count"]), "Detected Metrics Count")
    tabulate(lambda r: _bucket_pred_relevance(r["predicted_relevance"]), "Predicted Relevance")

    # --- Key combination: tier_3_all AND detected_count == 0 ---
    combo_rows = [
        r for r in rows if r["detection_tier"] == "tier_3_all" and r["detected_count"] == 0
    ]
    combo_total = len(combo_rows)
    combo_rej = sum(1 for r in combo_rows if r["fully_rejected"])
    print("\nKey combination: tier_3_all ∩ detected_metrics=0")
    print(f"  Labeled: {combo_total}  Rejected: {combo_rej}  ({_pct(combo_rej, combo_total)})")

    # --- Top-5 highest-precision reject buckets (for scoring rule) ---
    bucket_stats: list[tuple[str, int, int]] = []
    for dim_name, dim_fn in [
        ("tier", lambda r: r["detection_tier"]),
        ("class", lambda r: r["classification"] or "NULL"),
        ("rel_score", lambda r: _bucket_relevance(r["relevance_score"])),
        ("detected_ct", lambda r: _bucket_detected(r["detected_count"])),
        ("pred_rel", lambda r: _bucket_pred_relevance(r["predicted_relevance"])),
    ]:
        agg: dict[str, list[int, int]] = {}
        for r in rows:
            b = f"{dim_name}={dim_fn(r)}"
            if b not in agg:
                agg[b] = [0, 0]
            agg[b][0] += 1
            if r["fully_rejected"]:
                agg[b][1] += 1
        for b, (n, rej) in agg.items():
            if n >= 10:  # only meaningful buckets
                bucket_stats.append((b, n, rej))

    top5 = sorted(bucket_stats, key=lambda x: (-x[2] / x[1], -x[1]))[:5]
    _print_table(
        "Top-5 highest-precision reject buckets (min 10 labeled images)",
        [(b, n, rej, _pct(rej, n)) for b, n, rej in top5],
        ("bucket", "labeled", "rejected", "reject%"),
    )

    # --- predicted_relevance coverage check ---
    pred_null = sum(1 for r in rows if r["predicted_relevance"] is None)
    pred_pct = 100 * (1 - pred_null / total) if total else 0
    if pred_pct < 5:
        print(
            f"\nNOTE: predicted_relevance coverage is {pred_pct:.1f}% ({total - pred_null}/{total} images)."
        )
        print(
            "      Cannot use predicted_relevance as a scoring feature — use rule-based features only."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string. Defaults to TEST_DATABASE_URL, then DATABASE_URL.",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("ERROR: No database URL found. Set TEST_DATABASE_URL or pass --database-url.")
        sys.exit(1)

    if "neon.tech" in args.database_url or (
        os.environ.get("DATABASE_URL")
        and args.database_url == os.environ["DATABASE_URL"]
        and "neon.tech" in os.environ["DATABASE_URL"]
    ):
        print("NOTE: Connecting to production database (read-only query).")

    analyze(args.database_url)


if __name__ == "__main__":
    main()
