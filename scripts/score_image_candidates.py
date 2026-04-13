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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import joblib
import numpy as np
from dotenv import load_dotenv

from src.shared.image_features import engineer_features

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = ROOT / "data" / "image_model" / "relevance_model.joblib"


def normalize_db_row(row: dict) -> dict:
    """Convert a raw image_review_candidates DB row to the common feature dict format.

    The DB schema uses different column names than the training CSV, so this
    function maps them to the keys expected by engineer_features().
    """
    # Parse detected_keywords: Postgres TEXT[] arrives as a list or "{a,b}" string
    detected_keywords = row.get("detected_keywords") or []
    if isinstance(detected_keywords, str):
        detected_keywords = [
            k.strip()
            for k in detected_keywords.strip("{}").split(",")
            if k.strip()
        ]
    keyword_count = len(detected_keywords)

    preceding_text = row.get("preceding_text") or ""
    text_length = len(preceding_text)

    w = row.get("image_width")
    h = row.get("image_height")
    has_dimensions = int(w is not None and h is not None)
    image_area = (float(w) * float(h)) if has_dimensions else 0.0

    return {
        "cohort_confidence": row.get("cohort_confidence"),
        "cohort_keyword_nearby": row.get("cohort_keyword_nearby"),
        "keyword_count": keyword_count,
        "text_length": text_length,
        "preceding_text": preceding_text,
        "has_dimensions": has_dimensions,
        "image_area": image_area,
        # classification is not stored on SEC candidates — leave blank
        "classification": row.get("classification") or "",
        "detection_tier": row.get("detection_tier"),
        # DB uses image_src; shared module expects filename
        "filename": row.get("image_src") or "",
        # All rows in image_review_candidates are SEC images
        "source": "sec",
    }


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
    parser.add_argument(
        "--auto-reject-threshold", type=float, default=None, metavar="THRESHOLD",
        help="Candidates scoring below this threshold are marked review_status='auto_rejected'. "
             "Only applied to pending candidates. Requires migration 20 to be applied first. "
             "Example: --auto-reject-threshold 0.05",
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

    X = engineer_features([normalize_db_row(c) for c in candidates])
    scores = model.predict_proba(X)[:, 1]

    # Distribution summary
    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    logger.info("Score distribution:")
    logger.info("  Mean: %.3f | Min: %.3f | Max: %.3f", scores.mean(), scores.min(), scores.max())
    for t in thresholds:
        n = (scores >= t).sum()
        logger.info("  >= %.1f: %d candidates (%.1f%%)", t, n, 100 * n / len(scores))

    auto_reject_threshold = args.auto_reject_threshold
    if auto_reject_threshold is not None:
        n_would_reject = sum(
            1 for s, c in zip(scores, candidates, strict=True)
            if s < auto_reject_threshold and c.get("review_status") == "pending"
        )
        logger.info("Auto-reject threshold: %.3f — would reject %d pending candidates",
                    auto_reject_threshold, n_would_reject)

    if args.dry_run:
        logger.info("Dry run — not writing to DB")
        # Print top candidates
        ranked = sorted(zip(scores, candidates, strict=True), key=lambda x: -x[0])
        logger.info("\nTop 10 by predicted relevance:")
        for score, c in ranked[:10]:
            logger.info("  %.3f | %s | %s | tier=%s",
                        score, c.get("image_candidate_id"),
                        c.get("image_src", ""), c.get("detection_tier", ""))
        if auto_reject_threshold is not None:
            logger.info("\nCandidates that would be auto-rejected (score < %.3f, pending only):",
                        auto_reject_threshold)
            reject_ranked = sorted(
                [(s, c) for s, c in zip(scores, candidates, strict=True)
                 if s < auto_reject_threshold and c.get("review_status") == "pending"],
                key=lambda x: x[0],
            )
            for score, c in reject_ranked[:20]:
                logger.info("  %.4f | %s | tier=%s",
                            score, c.get("image_src", ""), c.get("detection_tier", ""))
        return

    # Batch update: write predicted_relevance and optionally auto-reject pending candidates
    update_sql = """
        UPDATE image_review_candidates
        SET predicted_relevance = %(score)s
        WHERE image_candidate_id = %(candidate_id)s
    """
    auto_reject_sql = """
        UPDATE image_review_candidates
        SET review_status = 'auto_rejected'
        WHERE image_candidate_id = %(candidate_id)s
          AND review_status = 'pending'
    """
    updated = 0
    auto_rejected = 0
    for cand, score in zip(candidates, scores, strict=True):
        db.execute(update_sql, {
            "score": round(float(score), 4),
            "candidate_id": cand["image_candidate_id"],
        })
        updated += 1
        if auto_reject_threshold is not None and score < auto_reject_threshold:
            db.execute(auto_reject_sql, {"candidate_id": cand["image_candidate_id"]})
            auto_rejected += 1

    logger.info("Updated %d candidates with predicted_relevance scores", updated)
    if auto_reject_threshold is not None:
        logger.info("Auto-rejected %d pending candidates (score < %.3f)",
                    auto_rejected, auto_reject_threshold)


if __name__ == "__main__":
    main()
