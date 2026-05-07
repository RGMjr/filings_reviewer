#!/usr/bin/env python3
"""
Offline evaluation of Vision per-metric prediction scores.

Pulls (img_id, metric_id, predicted_score) from v2_image_classifications and
compares against ground-truth labels derived from v2_image_metric_confirmations.
Produces an AUC-ROC / average-precision report with a threshold sweep.

Usage:
    python3 scripts/evaluate_vision_metric_scores.py
    python3 scripts/evaluate_vision_metric_scores.py --output data/vision_score_eval/report.txt
    python3 scripts/evaluate_vision_metric_scores.py --dry-run
    python3 scripts/evaluate_vision_metric_scores.py --limit 500

Output:
    Plain-text report with overall AUC-ROC, average precision, a threshold sweep
    (0.1–0.9) reporting precision/recall/F1, and a per-metric breakdown for
    metrics with ≥30 positive labels.

Phase 2 of the image-classifier improvement plan.  Implementation of any
production filter is a Phase 2b decision gated on this report.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)

# Minimum positive labels in a metric bucket to include in the per-metric breakdown.
PER_METRIC_MIN_POSITIVES = 30

# Threshold sweep points.
THRESHOLDS = [round(t / 10, 1) for t in range(1, 10)]

# Default output path.
DEFAULT_OUTPUT = Path("data/vision_score_eval/report.txt")


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

_PREDICTIONS_SQL = """
WITH latest_classifications AS (
    -- One row per img_id: pick the most-recent classification run.
    SELECT DISTINCT ON (img_id)
        img_id,
        predicted_metrics
    FROM v2_image_classifications
    ORDER BY img_id, created_at DESC
),
-- Only include images that have at least one confirmation row.
images_with_confirmations AS (
    SELECT DISTINCT img_id
    FROM v2_image_metric_confirmations
),
-- Unnest the predicted_metrics JSONB array into (img_id, metric_id, score).
unnested AS (
    SELECT
        lc.img_id,
        (elem->>'metric_id')  AS metric_id,
        (elem->>'score')::float AS predicted_score
    FROM latest_classifications lc
    JOIN images_with_confirmations iwc USING (img_id),
    jsonb_array_elements(lc.predicted_metrics) AS elem
    WHERE jsonb_array_length(lc.predicted_metrics) > 0
)
SELECT img_id::text, metric_id, predicted_score
FROM unnested
{limit_clause}
ORDER BY img_id, metric_id
"""

_CONFIRMATIONS_SQL = """
SELECT
    img_id::text,
    detected_metric_id,
    confirmed_metric_id,
    decision,
    rejection_reason
FROM v2_image_metric_confirmations
WHERE img_id IN (
    SELECT DISTINCT img_id
    FROM v2_image_classifications
)
ORDER BY img_id, created_at
"""


# ---------------------------------------------------------------------------
# Label derivation
# ---------------------------------------------------------------------------


def build_label_map(
    confirmations: list[dict[str, Any]],
    all_vision_metrics_by_image: dict[str, set[str]],
) -> dict[tuple[str, str], int]:
    """
    Return a map of (img_id, metric_id) → label (0 or 1).

    Label rules (any-accept-wins):
      1. Sentinel reject (both IDs NULL, rejection_reason='no_relevant_metrics'):
         → label=0 for ALL Vision-predicted metrics on that image.
      2. decision in ('accept', 'correct', 'add') with confirmed_metric_id matching
         a Vision-predicted metric_id → label=1.
      3. decision='reject' with confirmed_metric_id or detected_metric_id matching
         a Vision-predicted metric_id → label=0.
    Any (img_id, metric_id) pair with at least one accept/correct/add
    confirmation wins label=1 regardless of other reject rows.
    """
    # Track positives and negatives separately; any positive wins.
    positives: set[tuple[str, str]] = set()
    negatives: set[tuple[str, str]] = set()

    for row in confirmations:
        img_id: str = row["img_id"]
        detected_mid: str | None = row["detected_metric_id"]
        confirmed_mid: str | None = row["confirmed_metric_id"]
        decision: str = row["decision"]
        rejection_reason: str | None = row["rejection_reason"]

        # Sentinel: "Reject all — no relevant metrics".
        is_sentinel = (
            decision == "reject"
            and detected_mid is None
            and confirmed_mid is None
            and rejection_reason == "no_relevant_metrics"
        )
        if is_sentinel:
            # All Vision-predicted metrics for this image get label=0 (unless
            # another confirmation positively accepts one).
            for metric_id in all_vision_metrics_by_image.get(img_id, set()):
                negatives.add((img_id, metric_id))
            continue

        # Accepting decisions.
        if decision in ("accept", "correct", "add") and confirmed_mid:
            positives.add((img_id, confirmed_mid))

        # Rejecting decisions — map to Vision-predicted metric via either ID.
        if decision == "reject":
            reject_metric = confirmed_mid or detected_mid
            if reject_metric:
                negatives.add((img_id, reject_metric))

    # Merge: positives override negatives.
    label_map: dict[tuple[str, str], int] = {}
    for key in negatives:
        label_map[key] = 0
    for key in positives:
        label_map[key] = 1

    return label_map


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def _prf1(y_true: list[int], y_pred: list[int]) -> tuple[float, float, float]:
    """Precision, recall, F1 at a threshold (binary predictions)."""
    tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == 1 and p == 0)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def _auc_roc(y_true: list[int], y_score: list[float]) -> float:
    """Trapezoidal AUC-ROC (no sklearn dependency)."""
    pairs = sorted(zip(y_score, y_true, strict=True), reverse=True)
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    auc = 0.0
    tp = 0
    fp = 0
    prev_fp = 0
    prev_tp = 0
    prev_score = None

    for score, label in pairs:
        if score != prev_score and prev_score is not None:
            # Accumulate trapezoid.
            auc += (fp - prev_fp) * (tp + prev_tp) / 2.0
            prev_fp = fp
            prev_tp = tp
        if label == 1:
            tp += 1
        else:
            fp += 1
        prev_score = score

    # Final trapezoid.
    auc += (fp - prev_fp) * (tp + prev_tp) / 2.0
    return auc / (n_pos * n_neg)


def _average_precision(y_true: list[int], y_score: list[float]) -> float:
    """Average precision (area under precision-recall curve, step interpolation)."""
    pairs = sorted(zip(y_score, y_true, strict=True), reverse=True)
    n_pos = sum(y_true)
    if n_pos == 0:
        return float("nan")

    ap = 0.0
    tp = 0
    for i, (_, label) in enumerate(pairs):
        if label == 1:
            tp += 1
            precision_at_i = tp / (i + 1)
            ap += precision_at_i
    return ap / n_pos


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _fmt(v: float, width: int = 6) -> str:
    if v != v:  # NaN
        return " " * (width - 3) + "n/a"
    return f"{v:{width}.4f}"


def generate_report(
    pairs: list[tuple[str, str, float, int]],  # (img_id, metric_id, score, label)
    *,
    dry_run: bool = False,
) -> str:
    """Produce the eval report text."""
    lines: list[str] = []
    sep = "=" * 72

    lines.append(sep)
    lines.append("Vision Per-Metric Score Calibration Eval")
    lines.append(sep)

    if dry_run:
        lines.append("[DRY RUN — no output written]")
        lines.append("")

    y_true = [label for _, _, _, label in pairs]
    y_score = [score for _, _, _, score in pairs]

    n_total = len(pairs)
    n_pos = sum(y_true)
    n_neg = n_total - n_pos

    lines.append(f"Total labeled (img_id, metric_id) pairs : {n_total}")
    lines.append(f"  Positives (label=1)                   : {n_pos}")
    lines.append(f"  Negatives (label=0)                   : {n_neg}")
    if n_total > 0:
        lines.append(f"  Positive rate                         : {n_pos / n_total:.1%}")
    lines.append("")

    if n_total == 0 or n_pos == 0:
        lines.append("WARNING: No labeled pairs found. Cannot compute metrics.")
        return "\n".join(lines)

    auc = _auc_roc(y_true, y_score)
    ap = _average_precision(y_true, y_score)

    lines.append(f"AUC-ROC          : {_fmt(auc)}")
    lines.append(f"Average Precision: {_fmt(ap)}")
    lines.append("")

    # Threshold sweep.
    lines.append("Threshold Sweep")
    lines.append("-" * 60)
    lines.append(
        f"{'Threshold':>10} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Predicted+':>12}"
    )
    lines.append("-" * 60)
    for thresh in THRESHOLDS:
        y_pred = [1 if s >= thresh else 0 for s in y_score]
        prec, rec, f1 = _prf1(y_true, y_pred)
        n_pred_pos = sum(y_pred)
        lines.append(f"{thresh:>10.1f} {prec:>10.4f} {rec:>10.4f} {f1:>10.4f} {n_pred_pos:>12}")
    lines.append("-" * 60)
    lines.append("")

    # Per-metric breakdown.
    by_metric: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for _, metric_id, score, label in pairs:
        by_metric[metric_id].append((score, label))

    eligible = [
        (mid, entries)
        for mid, entries in sorted(by_metric.items())
        if sum(label for _, label in entries) >= PER_METRIC_MIN_POSITIVES
    ]

    lines.append(f"Per-Metric Breakdown (metrics with ≥{PER_METRIC_MIN_POSITIVES} positives)")
    lines.append("-" * 72)
    if not eligible:
        lines.append(
            f"  No metric has ≥{PER_METRIC_MIN_POSITIVES} positive labels — "
            "more labeled data needed."
        )
    else:
        lines.append(f"  {'Metric':<40} {'N':>6} {'Pos':>6} {'AUC':>8} {'AP':>8}")
        lines.append("  " + "-" * 68)
        for mid, entries in eligible:
            mt = [label for _, label in entries]
            ms = [score for score, _ in entries]
            m_auc = _auc_roc(mt, ms)
            m_ap = _average_precision(mt, ms)
            lines.append(
                f"  {mid:<40} {len(entries):>6} {sum(mt):>6} {_fmt(m_auc, 8)} {_fmt(m_ap, 8)}"
            )
    lines.append("")

    lines.append(sep)
    lines.append("Interpretation")
    lines.append(sep)
    lines.append("AUC-ROC ≥ 0.80 AND a threshold with ≥95% recall AND ≥40% precision")
    lines.append("would trigger Phase 2b (production filter implementation).")
    lines.append("")
    lines.append("If AUC < 0.70: scores are not calibrated — do not filter.")
    lines.append("If 0.70 ≤ AUC < 0.80: marginal — review per-metric breakdown first.")
    lines.append("If AUC ≥ 0.80: proceed to Phase 2b gating decision.")
    lines.append(sep)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(db: Any, *, limit: int | None = None, dry_run: bool = False) -> str:
    """Pull data, derive labels, generate report. Returns the report text."""
    logger.info("Fetching Vision classification predictions...")

    limit_clause = f"LIMIT {limit}" if limit else ""
    predictions = db.query(_PREDICTIONS_SQL.format(limit_clause=limit_clause), {})
    logger.info("Fetched %d (img_id, metric_id) prediction rows", len(predictions))

    if not predictions:
        logger.warning("No predictions found — ensure ENABLE_METRIC_CLASSIFY=true has run.")
        return generate_report([], dry_run=dry_run)

    # Build set of Vision-predicted metrics per image for sentinel expansion.
    all_vision_metrics_by_image: dict[str, set[str]] = defaultdict(set)
    for row in predictions:
        all_vision_metrics_by_image[row["img_id"]].add(row["metric_id"])

    logger.info("Fetching reviewer confirmations...")
    confirmations = db.query(_CONFIRMATIONS_SQL, {})
    logger.info("Fetched %d confirmation rows", len(confirmations))

    label_map = build_label_map(
        [dict(r) for r in confirmations],
        all_vision_metrics_by_image,
    )
    logger.info("Derived %d (img_id, metric_id) labels", len(label_map))

    # Join predictions to labels (only keep pairs that have a label).
    pairs: list[tuple[str, str, float, int]] = []
    for row in predictions:
        key = (row["img_id"], row["metric_id"])
        if key in label_map:
            pairs.append((row["img_id"], row["metric_id"], row["predicted_score"], label_map[key]))

    logger.info(
        "Matched %d prediction rows to ground-truth labels (%d predictions had no label)",
        len(pairs),
        len(predictions) - len(pairs),
    )

    return generate_report(pairs, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline eval of Vision per-metric prediction scores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/evaluate_vision_metric_scores.py
  python3 scripts/evaluate_vision_metric_scores.py --output data/vision_score_eval/report.txt
  python3 scripts/evaluate_vision_metric_scores.py --dry-run
  python3 scripts/evaluate_vision_metric_scores.py --limit 500
        """,
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help=f"Output file path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run queries and compute metrics but do not write the output file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of prediction rows fetched (for testing)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Database connection string (default: DATABASE_URL env var)",
    )
    args = parser.parse_args()

    configure_logging(level="INFO")

    load_dotenv()
    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set. Use --database-url or set DATABASE_URL in .env")
        sys.exit(1)

    from src.infra.db import DatabaseAdapter

    db = DatabaseAdapter(db_url)

    try:
        report = run(db, limit=args.limit, dry_run=args.dry_run)
    finally:
        db.close()

    if args.dry_run:
        print(report)
        logger.info("Dry run — output not written.")
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)

    # Print a summary to stdout.
    for line in report.splitlines():
        if any(kw in line for kw in ("AUC-ROC", "Average Precision", "Total labeled", "WARNING")):
            print(line)


if __name__ == "__main__":
    main()
