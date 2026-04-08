#!/usr/bin/env python3
"""
Score image review candidates using the trained relevance model.

Loads the trained model from data/image_model/relevance_model.joblib,
scores all (or unscored) candidates in the database, and writes
predicted_relevance back to image_review_candidates.

Usage:
    # Score only unscored candidates (default)
    python3 scripts/score_image_candidates.py

    # Rescore all candidates (overwrite existing scores)
    python3 scripts/score_image_candidates.py --rescore-all

    # Dry run — print scores without writing to DB
    python3 scripts/score_image_candidates.py --dry-run
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = ROOT / "data" / "image_model" / "relevance_model.joblib"

SEC_CHART_FILENAME_RE = re.compile(r"^g\d+", re.IGNORECASE)


def engineer_features(rows: list[dict]) -> np.ndarray:
    """Build feature matrix from image_review_candidates rows.

    Must be kept in sync with train_image_relevance_model.py.
    """
    X = []
    for r in rows:
        cohort_confidence = float(r.get("cohort_confidence") or 0.0)
        cohort_keyword_nearby = int(bool(r.get("cohort_keyword_nearby")))
        detected_keywords = r.get("detected_keywords") or []
        if isinstance(detected_keywords, str):
            detected_keywords = [
                k.strip()
                for k in detected_keywords.strip("{}").split(",")
                if k.strip()
            ]
        keyword_count = len(detected_keywords)

        preceding_text = r.get("preceding_text") or ""
        text_length = len(preceding_text)

        w = r.get("image_width")
        h = r.get("image_height")
        has_dimensions = int(w is not None and h is not None)
        area = (float(w) * float(h)) if has_dimensions else 0.0
        image_area_clipped = min(area, 1_000_000) / 1_000_000

        # classification is not stored on SEC candidates — leave blank
        classification = (r.get("classification") or "").lower()
        is_chart_classification = int(classification == "chart")
        is_unknown_classification = int(classification == "unknown")

        tier = r.get("detection_tier") or ""
        is_tier_1 = int(tier == "tier_1_cohort")
        is_tier_2 = int(tier == "tier_2_large")

        filename = (r.get("image_src") or "").lower()
        filename_has_chart_hint = int(
            "chart" in filename
            or "graph" in filename
            or bool(SEC_CHART_FILENAME_RE.match(filename))
        )

        text_short = int(text_length < 100)
        text_medium = int(100 <= text_length < 500)
        text_long = int(text_length >= 500)

        X.append([
            cohort_confidence,
            cohort_keyword_nearby,
            keyword_count,
            text_long,
            text_medium,
            text_short,
            has_dimensions,
            image_area_clipped,
            is_chart_classification,
            is_unknown_classification,
            is_tier_1,
            is_tier_2,
            filename_has_chart_hint,
        ])
    return np.array(X, dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score image candidates with relevance model"
    )
    parser.add_argument("--model", type=str, default=str(DEFAULT_MODEL),
                        help="Path to trained model file")
    parser.add_argument("--rescore-all", action="store_true",
                        help="Rescore all candidates, not just unscored ones")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print scores without writing to DB")
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

    # Fetch candidates to score
    if args.rescore_all:
        sql = "SELECT * FROM image_review_candidates ORDER BY image_candidate_id"
        logger.info("Fetching all candidates...")
    else:
        sql = "SELECT * FROM image_review_candidates WHERE predicted_relevance IS NULL ORDER BY image_candidate_id"
        logger.info("Fetching unscored candidates...")

    candidates = db.query(sql)
    logger.info("Found %d candidates to score", len(candidates))

    if not candidates:
        logger.info("Nothing to score.")
        return

    X = engineer_features(candidates)
    scores = model.predict_proba(X)[:, 1]

    # Distribution summary
    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    logger.info("Score distribution:")
    logger.info("  Mean: %.3f | Min: %.3f | Max: %.3f", scores.mean(), scores.min(), scores.max())
    for t in thresholds:
        n = (scores >= t).sum()
        logger.info("  >= %.1f: %d candidates (%.1f%%)", t, n, 100 * n / len(scores))

    if args.dry_run:
        logger.info("Dry run — not writing to DB")
        # Print top candidates
        ranked = sorted(zip(scores, candidates, strict=True), key=lambda x: -x[0])
        logger.info("\nTop 10 by predicted relevance:")
        for score, c in ranked[:10]:
            logger.info("  %.3f | %s | %s | tier=%s",
                        score, c.get("image_candidate_id"),
                        c.get("image_src", ""), c.get("detection_tier", ""))
        return

    # Batch update
    update_sql = """
        UPDATE image_review_candidates
        SET predicted_relevance = %(score)s
        WHERE image_candidate_id = %(candidate_id)s
    """
    updated = 0
    for cand, score in zip(candidates, scores, strict=True):
        db.execute(update_sql, {
            "score": round(float(score), 4),
            "candidate_id": cand["image_candidate_id"],
        })
        updated += 1

    logger.info("Updated %d candidates with predicted_relevance scores", updated)


if __name__ == "__main__":
    main()
