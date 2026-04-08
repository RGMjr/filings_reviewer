#!/usr/bin/env python3
"""
Train a logistic regression relevance model on human-labeled image review data.

Reads data/image_model/training_data.csv (produced by export_image_training_data.py),
engineers features, trains with stratified cross-validation, and saves the model.

Usage:
    python3 scripts/train_image_relevance_model.py
    python3 scripts/train_image_relevance_model.py --input data/image_model/training_data.csv
    python3 scripts/train_image_relevance_model.py --output data/image_model/relevance_model.joblib
"""

import argparse
import csv
import logging
import re
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "image_model" / "training_data.csv"
DEFAULT_MODEL = ROOT / "data" / "image_model" / "relevance_model.joblib"
DEFAULT_REPORT = ROOT / "data" / "image_model" / "model_report.txt"

# Filename patterns common in SEC auto-generated chart images
# e.g. g665122g20q37.jpg, g468383g1r55k94.jpg — letter 'g' prefix followed by digits
SEC_CHART_FILENAME_RE = re.compile(r"^g\d+", re.IGNORECASE)


def engineer_features(rows: list[dict]) -> np.ndarray:
    """Convert raw CSV rows to numeric feature matrix."""
    X = []
    for r in rows:
        cohort_confidence = float(r.get("cohort_confidence") or 0.0)
        cohort_keyword_nearby = int(r.get("cohort_keyword_nearby") or 0)
        keyword_count = int(r.get("keyword_count") or 0)
        text_length = int(r.get("text_length") or 0)
        has_dimensions = int(r.get("has_dimensions") or 0)
        image_area = float(r.get("image_area") or 0.0)
        # Clip area to reduce outlier influence; 1M px is ~1000x1000
        image_area_clipped = min(image_area, 1_000_000) / 1_000_000

        classification = (r.get("classification") or "").lower()
        is_chart_classification = int(classification == "chart")
        is_unknown_classification = int(classification == "unknown")

        tier = r.get("detection_tier") or ""
        is_tier_1 = int(tier == "tier_1_cohort")
        is_tier_2 = int(tier == "tier_2_large")

        filename = (r.get("filename") or "").lower()
        filename_has_chart_hint = int(
            "chart" in filename
            or "graph" in filename
            or bool(SEC_CHART_FILENAME_RE.match(filename))
        )

        # text_length bucketed: short (<100), medium (100-500), long (>500)
        text_short = int(text_length < 100)
        text_medium = int(100 <= text_length < 500)
        text_long = int(text_length >= 500)

        X.append([
            cohort_confidence,           # 0
            cohort_keyword_nearby,       # 1  (strongest signal)
            keyword_count,               # 2  (strongest signal)
            text_long,                   # 3
            text_medium,                 # 4
            text_short,                  # 5
            has_dimensions,              # 6
            image_area_clipped,          # 7
            is_chart_classification,     # 8
            is_unknown_classification,   # 9
            is_tier_1,                   # 10
            is_tier_2,                   # 11
            filename_has_chart_hint,     # 12
        ])
    return np.array(X, dtype=float)


FEATURE_NAMES = [
    "cohort_confidence",
    "cohort_keyword_nearby",
    "keyword_count",
    "text_long",
    "text_medium",
    "text_short",
    "has_dimensions",
    "image_area_clipped",
    "is_chart_classification",
    "is_unknown_classification",
    "is_tier_1",
    "is_tier_2",
    "filename_has_chart_hint",
]


def precision_at_recall(precisions, recalls, target_recall: float) -> float:
    """Return precision at the threshold closest to target_recall."""
    for p, r in zip(precisions, recalls, strict=False):
        if r <= target_recall:
            return float(p)
    return float(precisions[-1])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train image relevance logistic regression model"
    )
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT))
    parser.add_argument("--output", type=str, default=str(DEFAULT_MODEL))
    parser.add_argument("--report", type=str, default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Training data not found at %s", input_path)
        logger.error("Run scripts/export_image_training_data.py first.")
        sys.exit(1)

    rows = list(csv.DictReader(input_path.open(encoding="utf-8-sig")))
    # Only use decided rows (skip any that slipped through without a label)
    rows = [r for r in rows if r["decision"] in ("relevant", "not_relevant")]

    logger.info("Loaded %d labeled rows", len(rows))

    X = engineer_features(rows)
    y = np.array([1 if r["decision"] == "relevant" else 0 for r in rows])

    n_pos = y.sum()
    n_neg = len(y) - n_pos
    logger.info("Class distribution: %d relevant (%.1f%%), %d not_relevant",
                n_pos, 100 * n_pos / len(y), n_neg)

    # Logistic regression with class weighting to handle imbalance
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            C=1.0,
            solver="lbfgs",
        )),
    ])

    # Cross-validation to get unbiased probability estimates
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_prob_cv = cross_val_predict(pipeline, X, y, cv=cv, method="predict_proba")[:, 1]

    auc_roc = roc_auc_score(y, y_prob_cv)
    avg_precision = average_precision_score(y, y_prob_cv)
    precisions, recalls, thresholds = precision_recall_curve(y, y_prob_cv)

    p_at_80 = precision_at_recall(precisions, recalls, 0.80)
    p_at_90 = precision_at_recall(precisions, recalls, 0.90)
    p_at_95 = precision_at_recall(precisions, recalls, 0.95)

    # Find threshold that gives ~80% recall
    thresh_80 = None
    for t, _p, r in zip(thresholds, precisions, recalls, strict=False):
        if r <= 0.80:
            thresh_80 = t
            break

    logger.info("Cross-validated metrics (5-fold stratified):")
    logger.info("  AUC-ROC:           %.3f", auc_roc)
    logger.info("  Avg precision:     %.3f", avg_precision)
    logger.info("  Precision@80%%recall: %.3f", p_at_80)
    logger.info("  Precision@90%%recall: %.3f", p_at_90)
    logger.info("  Precision@95%%recall: %.3f", p_at_95)
    if thresh_80 is not None:
        logger.info("  Score threshold for ~80%% recall: %.3f", thresh_80)

    # Fit on all data for deployment
    pipeline.fit(X, y)

    # Feature coefficients (from the logistic regression step)
    coef = pipeline.named_steps["clf"].coef_[0]
    logger.info("\nFeature importances (logistic regression coefficients):")
    feat_imp = sorted(zip(FEATURE_NAMES, coef, strict=True), key=lambda x: abs(x[1]), reverse=True)
    for name, c in feat_imp:
        logger.info("  %s: %+.3f", name, c)

    # Baseline comparison: what does the current tier system achieve?
    tier_1_mask = np.array([
        1 if r["detection_tier"] == "tier_1_cohort" else 0 for r in rows
    ])
    tier_1_precision = y[tier_1_mask == 1].mean() if tier_1_mask.sum() > 0 else 0
    tier_1_recall = (y[tier_1_mask == 1].sum() / n_pos) if n_pos > 0 else 0
    logger.info("\nBaseline (tier_1_cohort only):")
    logger.info("  Precision: %.3f | Recall: %.3f | Coverage: %d/%d images",
                tier_1_precision, tier_1_recall,
                tier_1_mask.sum(), len(rows))

    # Save model
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_path)
    logger.info("\nModel saved to %s", output_path)

    # Write report
    report = StringIO()
    report.write("Image Relevance Model Report\n")
    report.write("=" * 40 + "\n\n")
    report.write(f"Training samples: {len(rows)}\n")
    report.write(f"  Relevant: {int(n_pos)} ({100*n_pos/len(y):.1f}%)\n")
    report.write(f"  Not relevant: {int(n_neg)} ({100*n_neg/len(y):.1f}%)\n\n")
    report.write("Cross-validated metrics (5-fold stratified):\n")
    report.write(f"  AUC-ROC:               {auc_roc:.3f}\n")
    report.write(f"  Avg precision (AP):    {avg_precision:.3f}\n")
    report.write(f"  Precision @ 80% recall: {p_at_80:.3f}\n")
    report.write(f"  Precision @ 90% recall: {p_at_90:.3f}\n")
    report.write(f"  Precision @ 95% recall: {p_at_95:.3f}\n")
    if thresh_80 is not None:
        report.write(f"  Score threshold for ~80% recall: {thresh_80:.3f}\n")
    report.write("\nBaseline (current tier_1_cohort system):\n")
    report.write(f"  Precision: {tier_1_precision:.3f}\n")
    report.write(f"  Recall:    {tier_1_recall:.3f}\n")
    report.write(f"  Coverage:  {tier_1_mask.sum()}/{len(rows)} candidates reviewed\n\n")
    report.write("Feature coefficients:\n")
    for name, c in feat_imp:
        report.write(f"  {name:35s}: {c:+.3f}\n")

    report_path = Path(args.report)
    report_path.write_text(report.getvalue())
    logger.info("Report saved to %s", report_path)


if __name__ == "__main__":
    main()
