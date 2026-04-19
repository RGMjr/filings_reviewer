"""
Check referential integrity of v2_metric_facts.source_locator.img_id.

`img_id` is embedded in the JSONB `source_locator` column on v2_metric_facts
rather than stored as a first-class FK, so orphan references (img_id pointing
at a v2_image_assets row that no longer exists) can accumulate silently. This
script scans for them and exits non-zero when any are found, so it can be
wired into a nightly cron.

Scope:
    - Read-only. No schema changes, no writes.
    - Does NOT modify facts or images — diagnosis only.
    - Promoting img_id to a FK column is a separate workstream (Issue #24).

Usage:
    python3 scripts/check_image_referential_integrity.py              # report
    python3 scripts/check_image_referential_integrity.py --sample 20  # show N orphan rows
    python3 scripts/check_image_referential_integrity.py --database-url <url>

Exit codes:
    0  no orphans found
    1  orphans found OR DATABASE_URL unset / other failure
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

ORPHAN_SQL = """
    SELECT
        f.fact_id,
        f.doc_id,
        f.canonical_metric_id,
        f.source_locator->>'img_id' AS img_id
      FROM v2_metric_facts f
     WHERE f.source_locator ? 'img_id'
       AND (f.source_locator->>'img_id') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM v2_image_assets a
            WHERE a.img_id::text = (f.source_locator->>'img_id')
       )
     ORDER BY f.doc_id, f.canonical_metric_id, f.fact_id
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Max number of orphan rows to print as a sample (default: 10).",
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
    rows = db.query(ORPHAN_SQL)
    total = len(rows)

    if total == 0:
        logger.info("No orphan img_id references found.")
        return 0

    by_doc = Counter(r["doc_id"] for r in rows)
    logger.warning("Found %d orphan img_id references across %d doc(s):", total, len(by_doc))
    for doc_id, count in sorted(by_doc.items(), key=lambda x: (-x[1], x[0])):
        logger.warning("  doc_id=%s: %d orphan fact(s)", doc_id, count)

    sample = rows[: max(0, args.sample)]
    if sample:
        logger.warning("Sample (%d of %d):", len(sample), total)
        for r in sample:
            logger.warning(
                "  fact_id=%s doc_id=%s metric=%s img_id=%s",
                r["fact_id"],
                r["doc_id"],
                r["canonical_metric_id"],
                r["img_id"],
            )

    return 1


if __name__ == "__main__":
    sys.exit(main())
