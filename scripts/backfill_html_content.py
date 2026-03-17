#!/usr/bin/env python3
"""
Backfill html_content column for existing filings.

Run this against local or Neon DB before Render cutover to populate
html_content from disk files for filings that were fetched before
the cloud migration.

Usage:
    DATABASE_URL=<url> python3 scripts/backfill_html_content.py
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 10


def backfill_html_content(db: DatabaseAdapter) -> None:
    rows = db.query(
        """
        SELECT filing_id, html_storage_path
        FROM filings
        WHERE html_fetched_at IS NOT NULL
          AND html_content IS NULL
          AND html_storage_path IS NOT NULL
        ORDER BY filing_id
        """
    )

    logger.info(f"Found {len(rows)} filings to backfill")

    backfilled = 0
    skipped = 0
    errors = 0
    batch: list[dict] = []

    for i, row in enumerate(rows, 1):
        filing_id = row["filing_id"]
        html_path = row["html_storage_path"]

        if not html_path or not Path(html_path).exists():
            logger.warning(f"  [{i}] Filing {filing_id}: file missing at {html_path}")
            skipped += 1
            continue

        try:
            content = Path(html_path).read_text(encoding="utf-8")
            batch.append({"filing_id": filing_id, "html_content": content})

            if len(batch) >= BATCH_SIZE:
                _flush_batch(db, batch)
                backfilled += len(batch)
                logger.info(
                    f"  Committed batch up to filing {filing_id} ({backfilled} total)"
                )
                batch = []

        except Exception as e:
            logger.error(f"  [{i}] Filing {filing_id}: error reading {html_path}: {e}")
            errors += 1

    if batch:
        _flush_batch(db, batch)
        backfilled += len(batch)
        logger.info(f"  Committed final batch ({backfilled} total)")

    logger.info(
        f"\nDone. Backfilled: {backfilled}, "
        f"Skipped (file missing): {skipped}, "
        f"Errors: {errors}"
    )


def _flush_batch(db: DatabaseAdapter, batch: list[dict]) -> None:
    for params in batch:
        db.execute(
            "UPDATE filings SET html_content = %(html_content)s WHERE filing_id = %(filing_id)s",
            params,
        )


if __name__ == "__main__":
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)

    db = DatabaseAdapter(database_url)
    backfill_html_content(db)
