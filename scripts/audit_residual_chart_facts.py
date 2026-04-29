#!/usr/bin/env python3
"""
Audit residual chart facts after the chart-presence pivot (legacy-097).

Read-only. For each filing carrying `v2_metric_facts WHERE source_type='chart'`,
reports the work that would be lost / re-done under each drain option:

- Chart-fact reviewer-decision count (the 18 decisions targeted for abandonment)
- Total chart-classified v2_image_assets on the filing (re-review surface under
  the per-(image, metric) flow if we re-extract or surface the images for
  fresh confirmation)
- Existing v2_image_metric_confirmations (post-pivot reviewer work that would
  be at risk if we did a full re-extraction with force=True)
- Text-fact reviewer-decision count (also at risk under full re-extraction)

Output is a per-filing table + verdict on whether a surgical drain is safe
(no other reviewer work to disturb).

Usage:
    DATABASE_URL=... python3 scripts/audit_residual_chart_facts.py
    python3 scripts/audit_residual_chart_facts.py --database-url postgresql://...
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter

QUERY = """
WITH chart_filings AS (
    SELECT DISTINCT filing_id
    FROM v2_metric_facts
    WHERE source_type = 'chart'
),
chart_fact_counts AS (
    SELECT filing_id, COUNT(*) AS chart_fact_count
    FROM v2_metric_facts
    WHERE source_type = 'chart'
    GROUP BY filing_id
),
chart_fact_decisions AS (
    SELECT mf.filing_id, COUNT(*) AS chart_fact_decision_count
    FROM v2_review_decisions rd
    JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
    WHERE mf.source_type = 'chart'
    GROUP BY mf.filing_id
),
text_fact_decisions AS (
    SELECT mf.filing_id, COUNT(*) AS text_fact_decision_count
    FROM v2_review_decisions rd
    JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
    WHERE mf.source_type <> 'chart'
    GROUP BY mf.filing_id
),
chart_images AS (
    SELECT doc_id AS filing_id,
           COUNT(*) AS chart_image_count,
           COUNT(*) FILTER (WHERE detected_metrics IS NOT NULL
                            AND jsonb_typeof(detected_metrics) = 'array'
                            AND jsonb_array_length(detected_metrics) > 0)
               AS chart_images_with_detected_metrics
    FROM v2_image_assets
    WHERE classification = 'chart'
    GROUP BY doc_id
),
image_confirmations AS (
    SELECT ia.doc_id AS filing_id,
           COUNT(DISTINCT (imc.img_id, COALESCE(imc.detected_metric_id, imc.confirmed_metric_id, ''), imc.reviewer_id))
               AS image_metric_confirmation_count
    FROM v2_image_metric_confirmations imc
    JOIN v2_image_assets ia ON ia.img_id = imc.img_id
    GROUP BY ia.doc_id
)
SELECT
    f.filing_id,
    c.cik,
    c.ticker,
    f.form_type,
    f.filing_date,
    cfc.chart_fact_count,
    COALESCE(cfd.chart_fact_decision_count, 0) AS chart_fact_decisions,
    COALESCE(ci.chart_image_count, 0) AS chart_images_total,
    COALESCE(ci.chart_images_with_detected_metrics, 0) AS chart_images_with_detected,
    COALESCE(ic.image_metric_confirmation_count, 0) AS image_metric_confirmations,
    COALESCE(tfd.text_fact_decision_count, 0) AS text_fact_decisions
FROM chart_filings cf
JOIN filings f ON f.filing_id = cf.filing_id
JOIN companies c ON c.cik = f.cik
LEFT JOIN chart_fact_counts cfc ON cfc.filing_id = cf.filing_id
LEFT JOIN chart_fact_decisions cfd ON cfd.filing_id = cf.filing_id
LEFT JOIN chart_images ci ON ci.filing_id = cf.filing_id
LEFT JOIN image_confirmations ic ON ic.filing_id = cf.filing_id
LEFT JOIN text_fact_decisions tfd ON tfd.filing_id = cf.filing_id
ORDER BY chart_fact_decisions DESC, cfc.chart_fact_count DESC, f.filing_date DESC;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres connection string (default: $DATABASE_URL)",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("ERROR: --database-url or $DATABASE_URL required", file=sys.stderr)
        return 2

    db = DatabaseAdapter(args.database_url)
    rows = db.query(QUERY)

    if not rows:
        print("No filings carry residual chart facts. legacy-097 may already be drained.")
        return 0

    headers = [
        "filing_id",
        "ticker",
        "cik",
        "form",
        "date",
        "chart_facts",
        "fact_decs",
        "chart_imgs",
        "imgs_w_det",
        "img_confs",
        "text_decs",
    ]
    widths = [len(h) for h in headers]
    fmt_rows = []
    for r in rows:
        fmt = [
            str(r["filing_id"]),
            str(r["ticker"] or "")[:8],
            str(r["cik"]),
            str(r["form_type"] or "")[:8],
            str(r["filing_date"]),
            str(r["chart_fact_count"]),
            str(r["chart_fact_decisions"]),
            str(r["chart_images_total"]),
            str(r["chart_images_with_detected"]),
            str(r["image_metric_confirmations"]),
            str(r["text_fact_decisions"]),
        ]
        fmt_rows.append(fmt)
        for i, cell in enumerate(fmt):
            widths[i] = max(widths[i], len(cell))

    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for fmt in fmt_rows:
        print("  ".join(fmt[i].ljust(widths[i]) for i in range(len(fmt))))

    totals = {
        "filings": len(rows),
        "chart_facts": sum(r["chart_fact_count"] for r in rows),
        "chart_fact_decisions": sum(r["chart_fact_decisions"] for r in rows),
        "chart_images_total": sum(r["chart_images_total"] for r in rows),
        "chart_images_with_detected": sum(r["chart_images_with_detected"] for r in rows),
        "image_metric_confirmations": sum(r["image_metric_confirmations"] for r in rows),
        "text_fact_decisions": sum(r["text_fact_decisions"] for r in rows),
    }
    print()
    print("TOTALS")
    for k, v in totals.items():
        print(f"  {k}: {v}")

    surgical_safe = [
        r for r in rows if r["image_metric_confirmations"] == 0 and r["text_fact_decisions"] == 0
    ]
    risky = [r for r in rows if r not in surgical_safe]
    print()
    print("VERDICT")
    print(
        f"  Surgical-safe filings (no other reviewer work to disturb): {len(surgical_safe)} / {len(rows)}"
    )
    if risky:
        print("  Filings with other reviewer work at risk under full re-extraction:")
        for r in risky:
            print(
                f"    filing_id={r['filing_id']} {r['ticker']} {r['form_type']} {r['filing_date']}: "
                f"img_confs={r['image_metric_confirmations']} text_decs={r['text_fact_decisions']}"
            )

    re_review_surface = sum(r["chart_images_total"] for r in rows)
    print()
    print(
        f"Re-review surface under per-image flow: {re_review_surface} chart-classified images "
        f"across {len(rows)} filings (avg {re_review_surface / len(rows):.1f}/filing) "
        f"vs {totals['chart_fact_decisions']} chart-fact decisions abandoned."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
