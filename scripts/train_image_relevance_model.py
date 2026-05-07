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
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.shared.image_features import FEATURE_NAMES, engineer_features  # noqa: F401

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "image_model" / "training_data.csv"
DEFAULT_MODEL = ROOT / "data" / "image_model" / "relevance_model.joblib"
DEFAULT_REPORT = ROOT / "data" / "image_model" / "model_report.txt"


def precision_at_recall(precisions, recalls, target_recall: float) -> float:
    """Return precision at the threshold closest to target_recall."""
    for p, r in zip(precisions, recalls, strict=False):
        if r <= target_recall:
            return float(p)
    return float(precisions[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Train image relevance model")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT))
    parser.add_argument("--output", type=str, default=str(DEFAULT_MODEL))
    parser.add_argument("--report", type=str, default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--model-type",
        choices=["logistic", "gbt"],
        default="logistic",
        help="Model class to train (default: logistic). Use 'gbt' to evaluate "
        "HistGradientBoostingClassifier. Adopt gbt only if AUC>=+0.03 or AP>=+0.05 vs logistic.",
    )
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
    logger.info(
        "Class distribution: %d relevant (%.1f%%), %d not_relevant",
        n_pos,
        100 * n_pos / len(y),
        n_neg,
    )

    model_type = args.model_type
    logger.info("Model type: %s", model_type)

    if model_type == "gbt":
        # HistGradientBoostingClassifier: no scaling needed, handles mixed features well.
        # Conservative hyperparams to avoid overfitting on ~600 samples.
        pipeline = Pipeline(
            [
                (
                    "clf",
                    HistGradientBoostingClassifier(
                        max_iter=200,
                        max_depth=4,
                        min_samples_leaf=10,
                        learning_rate=0.1,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        )
    else:
        # Logistic regression with class weighting to handle imbalance
        pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=1000,
                        C=1.0,
                        solver="lbfgs",
                    ),
                ),
            ]
        )

    # Cross-validation to get unbiased probability estimates
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_prob_cv = cross_val_predict(pipeline, X, y, cv=cv, method="predict_proba")[:, 1]

    auc_roc = roc_auc_score(y, y_prob_cv)
    avg_precision = average_precision_score(y, y_prob_cv)
    precisions, recalls, thresholds = precision_recall_curve(y, y_prob_cv)

    p_at_80 = precision_at_recall(precisions, recalls, 0.80)
    p_at_90 = precision_at_recall(precisions, recalls, 0.90)
    p_at_95 = precision_at_recall(precisions, recalls, 0.95)

    # Find thresholds that give ~80%, ~90%, ~95% recall
    thresh_80 = None
    thresh_90 = None
    thresh_95 = None
    for t, _p, r in zip(thresholds, precisions, recalls, strict=False):
        if r <= 0.80 and thresh_80 is None:
            thresh_80 = t
        if r <= 0.90 and thresh_90 is None:
            thresh_90 = t
        if r <= 0.95 and thresh_95 is None:
            thresh_95 = t

    logger.info("Cross-validated metrics (5-fold stratified):")
    logger.info("  AUC-ROC:           %.3f", auc_roc)
    logger.info("  Avg precision:     %.3f", avg_precision)
    logger.info("  Precision@80%%recall: %.3f", p_at_80)
    logger.info("  Precision@90%%recall: %.3f", p_at_90)
    logger.info("  Precision@95%%recall: %.3f", p_at_95)
    if thresh_80 is not None:
        logger.info("  Score threshold for ~80%% recall: %.3f", thresh_80)
    if thresh_90 is not None:
        logger.info("  Score threshold for ~90%% recall: %.3f", thresh_90)
    if thresh_95 is not None:
        logger.info("  Score threshold for ~95%% recall: %.3f", thresh_95)

    # Fit on all data for deployment
    pipeline.fit(X, y)

    # Feature importances
    clf = pipeline.named_steps["clf"]
    if model_type == "gbt":
        # HistGradientBoostingClassifier removed feature_importances_ in recent sklearn;
        # use permutation importance on the full training set as a proxy.
        from sklearn.inspection import permutation_importance

        perm = permutation_importance(
            pipeline, X, y, n_repeats=10, random_state=42, scoring="average_precision"
        )
        importances = perm.importances_mean
        logger.info("\nFeature importances (GBT, permutation on train set):")
        feat_imp = sorted(
            zip(FEATURE_NAMES, importances, strict=True), key=lambda x: x[1], reverse=True
        )
        for name, imp in feat_imp:
            logger.info("  %s: %.4f", name, imp)
    else:
        coef = clf.coef_[0]
        logger.info("\nFeature importances (logistic regression coefficients):")
        feat_imp = sorted(
            zip(FEATURE_NAMES, coef, strict=True), key=lambda x: abs(x[1]), reverse=True
        )
        for name, c in feat_imp:
            logger.info("  %s: %+.3f", name, c)

    # Baseline comparison: what does the current tier system achieve?
    tier_1_mask = np.array([1 if r["detection_tier"] == "tier_1_cohort" else 0 for r in rows])
    tier_1_precision = y[tier_1_mask == 1].mean() if tier_1_mask.sum() > 0 else 0
    tier_1_recall = (y[tier_1_mask == 1].sum() / n_pos) if n_pos > 0 else 0
    logger.info("\nBaseline (tier_1_cohort only):")
    logger.info(
        "  Precision: %.3f | Recall: %.3f | Coverage: %d/%d images",
        tier_1_precision,
        tier_1_recall,
        tier_1_mask.sum(),
        len(rows),
    )

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
    report.write(f"  Relevant: {int(n_pos)} ({100 * n_pos / len(y):.1f}%)\n")
    report.write(f"  Not relevant: {int(n_neg)} ({100 * n_neg / len(y):.1f}%)\n\n")
    report.write("Cross-validated metrics (5-fold stratified):\n")
    report.write(f"  AUC-ROC:               {auc_roc:.3f}\n")
    report.write(f"  Avg precision (AP):    {avg_precision:.3f}\n")
    report.write(f"  Precision @ 80% recall: {p_at_80:.3f}\n")
    report.write(f"  Precision @ 90% recall: {p_at_90:.3f}\n")
    report.write(f"  Precision @ 95% recall: {p_at_95:.3f}\n")
    if thresh_80 is not None:
        report.write(f"  Score threshold for ~80% recall: {thresh_80:.3f}\n")
    if thresh_90 is not None:
        report.write(f"  Score threshold for ~90% recall: {thresh_90:.3f}\n")
    if thresh_95 is not None:
        report.write(f"  Score threshold for ~95% recall: {thresh_95:.3f}\n")
    report.write("\nBaseline (current tier_1_cohort system):\n")
    report.write(f"  Precision: {tier_1_precision:.3f}\n")
    report.write(f"  Recall:    {tier_1_recall:.3f}\n")
    report.write(f"  Coverage:  {tier_1_mask.sum()}/{len(rows)} candidates reviewed\n\n")
    report.write(f"Model type: {model_type}\n\n")
    if model_type == "gbt":
        report.write("Feature importances (GBT, permutation on train set):\n")
        for name, imp in feat_imp:
            report.write(f"  {name:35s}: {imp:.4f}\n")
    else:
        report.write("Feature coefficients:\n")
        for name, c in feat_imp:
            report.write(f"  {name:35s}: {c:+.3f}\n")

    report_path = Path(args.report)
    report_path.write_text(report.getvalue())
    logger.info("Report saved to %s", report_path)


if __name__ == "__main__":
    main()
