#!/usr/bin/env python3
"""
Score V2 image review candidates with the trained relevance model.

Loads the model from data/image_model/relevance_model.joblib, scores rows from
v2_image_assets, and writes predicted_relevance back keyed on img_id. Non-chart
images (decorative / logo / signature) are excluded from the queue and skipped.

Usage:
    # Score only unscored rows (default)
    python3 scripts/score_image_candidates.py

    # Rescore all rows (overwrite existing scores)
    python3 scripts/score_image_candidates.py --rescore-all

    # Dry run — print scores without writing
    python3 scripts/score_image_candidates.py --dry-run

    # Auto-reject pending rows below a threshold
    python3 scripts/score_image_candidates.py --auto-reject-threshold 0.05
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
from dotenv import load_dotenv

from src.shared.image_features import engineer_features, v2_row_to_features_input

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = ROOT / "data" / "image_model" / "relevance_model.joblib"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score v2_image_assets rows with the image relevance model"
    )
    parser.add_argument("--model", type=str, default=str(DEFAULT_MODEL),
                        help="Path to trained model file")
    parser.add_argument("--rescore-all", action="store_true",
                        help="Rescore all rows, not just unscored ones")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print scores without writing to DB")
    parser.add_argument(
        "--auto-reject-threshold", type=float, default=None, metavar="THRESHOLD",
        help="Rows scoring below this are marked review_status='auto_rejected'. "
             "Only applied to pending rows. Example: --auto-reject-threshold 0.05",
    )
    parser.add_argument("--database-url", type=str)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    model_path = Path(args.model)
    if not model_path.exists():
        logger.error("Model not found at %s", model_path)
        logger.error("Run scripts/train_image_relevance_model.py first.")
        sys.exit(1)

    model = joblib.load(model_path)
    logger.info("Loaded model from %s", model_path)

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    from src.infra.db import DatabaseAdapter
    db = DatabaseAdapter(db_url)

    base_where = (
        "classification NOT IN ('decorative', 'logo', 'signature') "
        "AND filename IS NOT NULL AND filename != ''"
    )
    if args.rescore_all:
        sql = f"""
            SELECT img_id, filename, nearby_text, classification,
                   relevance_score, width, height, review_status
            FROM v2_image_assets
            WHERE {base_where}
            ORDER BY img_id
        """
        logger.info("Fetching all v2_image_assets rows...")
    else:
        sql = f"""
            SELECT img_id, filename, nearby_text, classification,
                   relevance_score, width, height, review_status
            FROM v2_image_assets
            WHERE predicted_relevance IS NULL AND {base_where}
            ORDER BY img_id
        """
        logger.info("Fetching unscored v2_image_assets rows...")

    rows = db.query(sql)
    logger.info("Found %d rows to score", len(rows))

    if not rows:
        logger.info("Nothing to score.")
        return

    X = engineer_features([v2_row_to_features_input(r) for r in rows])
    scores = model.predict_proba(X)[:, 1]

    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    logger.info("Score distribution:")
    logger.info("  Mean: %.3f | Min: %.3f | Max: %.3f", scores.mean(), scores.min(), scores.max())
    for t in thresholds:
        n = (scores >= t).sum()
        logger.info("  >= %.1f: %d rows (%.1f%%)", t, n, 100 * n / len(scores))

    auto_reject_threshold = args.auto_reject_threshold
    if auto_reject_threshold is not None:
        n_would_reject = sum(
            1 for s, r in zip(scores, rows, strict=True)
            if s < auto_reject_threshold and r.get("review_status") == "pending"
        )
        logger.info("Auto-reject threshold: %.3f — would reject %d pending rows",
                    auto_reject_threshold, n_would_reject)

    if args.dry_run:
        logger.info("Dry run — not writing to DB")
        ranked = sorted(zip(scores, rows, strict=True), key=lambda x: -x[0])
        logger.info("\nTop 10 by predicted relevance:")
        for score, r in ranked[:10]:
            logger.info("  %.3f | %s | %s | classification=%s",
                        score, r.get("img_id"),
                        r.get("filename", ""), r.get("classification", ""))
        if auto_reject_threshold is not None:
            logger.info("\nRows that would be auto-rejected (score < %.3f, pending only):",
                        auto_reject_threshold)
            reject_ranked = sorted(
                [(s, r) for s, r in zip(scores, rows, strict=True)
                 if s < auto_reject_threshold and r.get("review_status") == "pending"],
                key=lambda x: x[0],
            )
            for score, r in reject_ranked[:20]:
                logger.info("  %.4f | %s | classification=%s",
                            score, r.get("filename", ""), r.get("classification", ""))
        return

    update_sql = """
        UPDATE v2_image_assets
        SET predicted_relevance = %(score)s
        WHERE img_id = %(img_id)s
    """
    auto_reject_sql = """
        UPDATE v2_image_assets
        SET review_status = 'auto_rejected'
        WHERE img_id = %(img_id)s
          AND review_status = 'pending'
    """
    updated = 0
    auto_rejected = 0
    for row, score in zip(rows, scores, strict=True):
        db.execute(update_sql, {
            "score": round(float(score), 4),
            "img_id": row["img_id"],
        })
        updated += 1
        if auto_reject_threshold is not None and score < auto_reject_threshold:
            db.execute(auto_reject_sql, {"img_id": row["img_id"]})
            auto_rejected += 1

    logger.info("Updated %d rows with predicted_relevance scores", updated)
    if auto_reject_threshold is not None:
        logger.info("Auto-rejected %d pending rows (score < %.3f)",
                    auto_rejected, auto_reject_threshold)


if __name__ == "__main__":
    main()
