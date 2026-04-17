#!/usr/bin/env python3
"""
One-shot migration: V1 image review state → V2 tables.

Copies three pieces of state from the V1 image review tables into the V2-native
equivalents introduced in Phase B of the V1 deprecation plan:

  1. `image_review_candidates.review_status`       → `v2_image_assets.review_status`
  2. `image_review_candidates.predicted_relevance` → `v2_image_assets.predicted_relevance`
  3. `image_review_decisions`                      → `v2_image_review_decisions`

Join key: `(image_review_candidates.filing_id, image_review_candidates.image_src)`
      ==  `(v2_image_assets.doc_id,            v2_image_assets.filename)`.
A composite key is required because bare filenames (e.g. `mdaa2.jpg`) collide
across filings.

Idempotent: re-running is safe. Status/relevance updates are overwrites from V1
(V1 is the authoritative source during migration). Decision inserts rely on
`v2_image_review_decisions.img_id UNIQUE` via `ON CONFLICT DO NOTHING`.

Usage:
    python3 scripts/migrate_image_decisions_to_v2.py --dry-run
    python3 scripts/migrate_image_decisions_to_v2.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)


def preview_counts(db: DatabaseAdapter) -> dict:
    """Count rows that will be touched. Also counts V1 rows with no V2 match."""
    status_to_copy = db.query(
        """
        SELECT COUNT(*) AS n
        FROM image_review_candidates c
        JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        WHERE c.review_status != 'pending' OR c.predicted_relevance IS NOT NULL
        """
    )[0]["n"]

    decisions_to_copy = db.query(
        """
        SELECT COUNT(*) AS n
        FROM image_review_decisions d
        JOIN image_review_candidates c
            ON c.image_candidate_id = d.image_candidate_id
        JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        LEFT JOIN v2_image_review_decisions vd
            ON vd.img_id = v.img_id
        WHERE vd.image_decision_id IS NULL
        """
    )[0]["n"]

    unmatched_candidates = db.query(
        """
        SELECT COUNT(*) AS n
        FROM image_review_candidates c
        LEFT JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        WHERE v.img_id IS NULL
        """
    )[0]["n"]

    unmatched_decisions = db.query(
        """
        SELECT COUNT(*) AS n
        FROM image_review_decisions d
        JOIN image_review_candidates c
            ON c.image_candidate_id = d.image_candidate_id
        LEFT JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        WHERE v.img_id IS NULL
        """
    )[0]["n"]

    return {
        "status_to_copy": status_to_copy,
        "decisions_to_copy": decisions_to_copy,
        "unmatched_candidates": unmatched_candidates,
        "unmatched_decisions": unmatched_decisions,
    }


def log_unmatched_samples(db: DatabaseAdapter, limit: int = 10) -> None:
    """Print up to `limit` V1 candidates and decisions that have no V2 match."""
    sample_cands = db.query(
        """
        SELECT c.filing_id, c.image_src, c.review_status
        FROM image_review_candidates c
        LEFT JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        WHERE v.img_id IS NULL
        ORDER BY c.filing_id, c.image_candidate_id
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    if sample_cands:
        logger.info("  Sample unmatched V1 candidates (first %d):", len(sample_cands))
        for row in sample_cands:
            logger.info("    filing_id=%s image_src=%s status=%s",
                        row["filing_id"], row["image_src"], row["review_status"])

    sample_decs = db.query(
        """
        SELECT d.image_decision_id, c.filing_id, c.image_src, d.decision
        FROM image_review_decisions d
        JOIN image_review_candidates c ON c.image_candidate_id = d.image_candidate_id
        LEFT JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        WHERE v.img_id IS NULL
        ORDER BY c.filing_id, d.image_decision_id
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    if sample_decs:
        logger.info("  Sample orphan V1 decisions (first %d):", len(sample_decs))
        for row in sample_decs:
            logger.info("    decision_id=%s filing_id=%s image_src=%s decision=%s",
                        row["image_decision_id"], row["filing_id"],
                        row["image_src"], row["decision"])


def copy_review_status_and_relevance(db: DatabaseAdapter) -> int:
    """Copy V1 `review_status` + `predicted_relevance` to V2. Returns row count."""
    rows = db.query(
        """
        UPDATE v2_image_assets v
        SET review_status       = c.review_status,
            predicted_relevance = c.predicted_relevance
        FROM image_review_candidates c
        WHERE v.doc_id   = c.filing_id
          AND v.filename = c.image_src
          AND (
                v.review_status       IS DISTINCT FROM c.review_status
             OR v.predicted_relevance IS DISTINCT FROM c.predicted_relevance
          )
        RETURNING v.img_id
        """
    )
    return len(rows)


def copy_decisions(db: DatabaseAdapter) -> int:
    """Copy V1 decisions to V2 keyed on img_id. Returns inserted row count."""
    rows = db.query(
        """
        INSERT INTO v2_image_review_decisions (
            img_id, decision, chart_type, rejection_reason,
            reviewer_id, reviewer_notes, review_time_seconds, created_at
        )
        SELECT
            v.img_id, d.decision, d.chart_type, d.rejection_reason,
            d.reviewer_id, d.reviewer_notes, d.review_time_seconds, d.created_at
        FROM image_review_decisions d
        JOIN image_review_candidates c
            ON c.image_candidate_id = d.image_candidate_id
        JOIN v2_image_assets v
            ON v.doc_id = c.filing_id AND v.filename = c.image_src
        ON CONFLICT (img_id) DO NOTHING
        RETURNING image_decision_id
        """
    )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--database-url", type=str)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    # Sanity: are V1 tables present?
    v1_present = db.query(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'image_review_candidates'
        ) AS present
        """
    )[0]["present"]
    if not v1_present:
        logger.info("image_review_candidates not present — nothing to migrate. Exiting.")
        return

    counts = preview_counts(db)
    logger.info("Migration preview:")
    logger.info("  V1 candidates with review state to copy: %d", counts["status_to_copy"])
    logger.info("  V1 decisions to copy into V2:            %d", counts["decisions_to_copy"])
    logger.info("  V1 candidates with no V2 match:          %d", counts["unmatched_candidates"])
    logger.info("  V1 decisions with no V2 match:           %d", counts["unmatched_decisions"])

    if counts["unmatched_candidates"] or counts["unmatched_decisions"]:
        log_unmatched_samples(db)

    if args.dry_run:
        logger.info("Dry run — no changes made.")
        return

    status_updated = copy_review_status_and_relevance(db)
    logger.info("Updated review_status/predicted_relevance on %d v2_image_assets rows",
                status_updated)

    decisions_inserted = copy_decisions(db)
    logger.info("Inserted %d v2_image_review_decisions rows", decisions_inserted)

    # Post-run sanity
    post = preview_counts(db)
    if post["status_to_copy"] != 0:
        logger.warning(
            "  %d V1 candidates still differ from V2 after update "
            "(likely race with concurrent V1 writes)",
            post["status_to_copy"],
        )


if __name__ == "__main__":
    main()
