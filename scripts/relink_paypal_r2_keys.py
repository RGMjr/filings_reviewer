"""
Repair `v2_image_assets.file_path` rows that legacy-103 NULL'd by relinking
them to their canonical R2 storage key (when the bytes still exist in R2).

Reads the JSON output of ``audit_paypal_r2_orphans.py`` and, for each row in
the ``relinkable`` bucket, runs::

    UPDATE v2_image_assets
       SET file_path = %(canonical_key)s
     WHERE img_id = %(img_id)s

The script is **gated by both flags**:

  - ``--apply``: required for any DB write. Without it, prints what would be
    updated and exits.
  - ``FILINGS_REVIEWER_ALLOW_PROD_WRITES=1``: required when ``DATABASE_URL``
    points at prod, mirroring the convention from ``R2Storage.put_bytes``.

Usage:

    # Dry-run (default)
    python3 scripts/relink_paypal_r2_keys.py --audit audit.json

    # Apply against local Docker
    DATABASE_URL="$TEST_DATABASE_URL" \\
      python3 scripts/relink_paypal_r2_keys.py --audit audit.json --apply

    # Apply against prod (requires explicit user confirmation per CLAUDE.md)
    FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \\
      python3 scripts/relink_paypal_r2_keys.py --audit audit.json --apply

Per ``.claude/rules/infrastructure.md``: confirm with the user before
pointing this at prod ``DATABASE_URL``.

Exit codes:
    0  dry-run completed OR apply succeeded
    1  setup error / refusal (no audit, missing prod-write guard, etc.)
    2  partial failure (some UPDATEs raised)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.image_storage import (  # noqa: E402
    InvalidStorageKeyError,
    validate_key,
)
from src.infra.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)


def _looks_like_prod(db_url: str) -> bool:
    """Heuristic for prod DATABASE_URL — same shape as `.claude/rules/infrastructure.md`."""
    return ".neon.tech" in db_url


def relink(db: DatabaseAdapter, rows: list[dict], *, apply: bool) -> tuple[int, int]:
    """Returns (succeeded, failed) counts."""
    succeeded = 0
    failed = 0
    for row in rows:
        img_id = row.get("img_id")
        canonical = row.get("canonical_key")
        if not (img_id and canonical):
            logger.warning("Skipping row missing img_id/canonical_key: %s", row)
            failed += 1
            continue
        try:
            validate_key(str(canonical))
        except InvalidStorageKeyError:
            logger.warning(
                "Skipping row with invalid canonical_key shape: img_id=%s key=%s",
                img_id,
                canonical,
            )
            failed += 1
            continue

        if not apply:
            logger.info(
                "[DRY-RUN] would set file_path=%s where img_id=%s (filing_id=%s)",
                canonical,
                img_id,
                row.get("filing_id"),
            )
            succeeded += 1
            continue

        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE v2_image_assets
                           SET file_path = %(canonical)s
                         WHERE img_id = %(img_id)s
                           AND file_path IS NULL
                        """,
                        {"canonical": canonical, "img_id": img_id},
                    )
                    rowcount = cur.rowcount
            if rowcount == 0:
                logger.warning(
                    "No rows updated for img_id=%s (file_path may already be set; refresh audit)",
                    img_id,
                )
                failed += 1
            else:
                succeeded += 1
                logger.info(
                    "Relinked img_id=%s file_path=%s (filing_id=%s)",
                    img_id,
                    canonical,
                    row.get("filing_id"),
                )
        except Exception as exc:
            logger.error("Failed to relink img_id=%s: %s", img_id, exc)
            failed += 1
    return succeeded, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit",
        required=True,
        help="Path to JSON output of audit_paypal_r2_orphans.py.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL env var.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run the UPDATEs. Without this flag, prints planned changes only.",
    )
    args = parser.parse_args()

    configure_logging(level="INFO")
    load_dotenv()

    audit_path = Path(args.audit)
    if not audit_path.exists():
        logger.error("Audit file not found: %s", audit_path)
        return 1

    report = json.loads(audit_path.read_text())
    relinkable = report.get("relinkable") or []
    if not relinkable:
        logger.info("No relinkable rows in %s — nothing to do.", audit_path)
        return 0

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set (and --database-url not passed)")
        return 1

    if args.apply and _looks_like_prod(db_url):
        if os.environ.get("FILINGS_REVIEWER_ALLOW_PROD_WRITES") != "1":
            logger.error(
                "Refusing to apply against prod DATABASE_URL without "
                "FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 (matches R2Storage.put_bytes guard)."
            )
            return 1

    db = DatabaseAdapter(db_url)
    logger.info(
        "Relink plan: %d row(s) (apply=%s, db=%s)",
        len(relinkable),
        args.apply,
        "prod" if _looks_like_prod(db_url) else "non-prod",
    )

    succeeded, failed = relink(db, relinkable, apply=args.apply)
    logger.info("Relink result: %d succeeded, %d failed", succeeded, failed)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
