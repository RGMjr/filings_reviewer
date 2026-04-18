"""
Backfill v2_image_assets.detected_keywords for historical rows.

Populates detected_keywords by scanning (nearby_text + ' ' + ocr_text) against
every active metric's patterns in config/metric_keywords.yaml. Idempotent —
skips rows where detected_keywords IS NOT NULL, so safe to re-run.

Usage:
    python3 scripts/backfill_image_keywords.py              # apply
    python3 scripts/backfill_image_keywords.py --dry-run    # preview only
    python3 scripts/backfill_image_keywords.py --limit 100  # cap rows processed
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.shared.keyword_config import match_nearby_text

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the first 10 computed rows without writing.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of rows processed (default: all unpopulated rows).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL env var.",
    )
    args = parser.parse_args()

    configure_logging(level="INFO")
    load_dotenv()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 1

    db = DatabaseAdapter(db_url)

    limit_clause = f"LIMIT {int(args.limit)}" if args.limit else ""
    select_sql = f"""
        SELECT img_id, nearby_text, ocr_text
          FROM v2_image_assets
         WHERE detected_keywords IS NULL
         ORDER BY created_at, img_id
         {limit_clause}
    """

    rows = db.query(select_sql)
    total = len(rows)
    logger.info("Found %d rows with NULL detected_keywords", total)
    if total == 0:
        logger.info("Nothing to backfill.")
        return 0

    computed: list[tuple[list[str] | None, str]] = []
    for row in rows:
        text = ((row.get("nearby_text") or "") + " " + (row.get("ocr_text") or "")).strip()
        matches = match_nearby_text(text) or None
        computed.append((matches, str(row["img_id"])))

    if args.dry_run:
        logger.info("DRY RUN - sample of first 10 computed rows:")
        for matches, img_id in computed[:10]:
            logger.info("  %s -> %s", img_id, matches)
        nonempty = sum(1 for m, _ in computed if m)
        logger.info(
            "Would update %d rows (%d with matches, %d empty -> NULL)",
            total, nonempty, total - nonempty,
        )
        return 0

    update_sql = """
        UPDATE v2_image_assets
           SET detected_keywords = %s::text[]
         WHERE img_id = %s
    """

    written = 0
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(computed), BATCH_SIZE):
                batch = computed[i : i + BATCH_SIZE]
                cur.executemany(update_sql, batch)
                conn.commit()
                written += len(batch)
                logger.info("Updated %d / %d rows", written, total)

    logger.info("Backfill complete: %d rows updated", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
