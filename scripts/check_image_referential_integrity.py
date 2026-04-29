"""
Check referential integrity of v2_metric_facts chart-image linkage.

`img_id` is embedded in the JSONB `source_locator` column on v2_metric_facts
rather than stored as a first-class FK, so several classes of failure can
accumulate silently and leave chart-sourced facts without a visible preview
in the review UI (`unified_review.html` "Chart Evidence" block):

    (A) BLOCKING: source_type='chart' fact with null source_locator.img_id.
        `ChartFactBridgeStage` is supposed to set img_id on every emitted
        fact (chart_fact_bridge.py:134, 185, 244). A non-zero count here is
        a persistence-layer regression and fails CI.

    (B) WARNING: img_id present but does not resolve to any v2_image_assets
        row. Typically caused by image deletion/dedup migrations. Not a CI
        blocker today — flip to blocking once baseline reaches zero.

    (C) WARNING: asset row exists but the on-disk file is missing or lives
        outside the project data/ directory. Common with extraction caches
        rooted under TMPDIR (/var/folders/... on macOS) that the OS purges.
        `image_crop` returns 404 in both sub-cases, producing a broken-image
        icon in the UI. Not a CI blocker today.

Scope:
    - Read-only. No schema changes, no writes.
    - Does NOT modify facts, images, or files — diagnosis only.
    - Promoting img_id to a FK column is a separate workstream (Issue #24).

Usage:
    python3 scripts/check_image_referential_integrity.py              # report
    python3 scripts/check_image_referential_integrity.py --sample 20  # show N rows per class
    python3 scripts/check_image_referential_integrity.py --database-url <url>

Exit codes:
    0  no blocking violations
    1  blocking violation (class A) found OR DATABASE_URL unset / other failure
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

# (A) — chart-sourced facts that never should have been persisted without an img_id.
NULL_IMG_ID_SQL = """
    SELECT
        f.fact_id,
        f.filing_id,
        f.canonical_metric_id
      FROM v2_metric_facts f
     WHERE f.source_type = 'chart'
       AND (
            NOT (f.source_locator ? 'img_id')
            OR (f.source_locator->>'img_id') IS NULL
       )
     ORDER BY f.filing_id, f.canonical_metric_id, f.fact_id
"""

# (B) — img_id present but no matching asset row.
ORPHAN_SQL = """
    SELECT
        f.fact_id,
        f.filing_id,
        f.canonical_metric_id,
        f.source_type,
        f.source_locator->>'img_id' AS img_id
      FROM v2_metric_facts f
     WHERE f.source_locator ? 'img_id'
       AND (f.source_locator->>'img_id') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM v2_image_assets a
            WHERE a.img_id::text = (f.source_locator->>'img_id')
       )
     ORDER BY f.filing_id, f.canonical_metric_id, f.fact_id
"""

# (C) helper — every asset row with a declared file_path; existence is tested
# in Python because the DB has no visibility into the local filesystem.
ASSET_FILE_PATH_SQL = """
    SELECT img_id, doc_id, filename, file_path, classification
      FROM v2_image_assets
     WHERE file_path IS NOT NULL
"""


def _load_missing_files(db: DatabaseAdapter, data_dir: Path | None) -> tuple[int, list[dict]]:
    """Class (C): image rows whose file_path key is invalid or absent in storage.

    ``data_dir`` is retained as a parameter for CLI compatibility but is no longer
    used for validation — storage-key shape is enforced by
    :func:`src.infra.image_storage.validate_key` and presence by the active
    backend's ``exists()`` method. Legacy absolute-path rows (pre-R2 migration)
    fail ``validate_key`` and surface as reason=``invalid_key_shape``.
    """
    from src.infra.image_storage import (
        InvalidStorageKeyError,
        get_image_storage,
        validate_key,
    )

    rows = db.query(ASSET_FILE_PATH_SQL)
    missing: list[dict] = []
    storage = get_image_storage()
    for row in rows:
        key = row.get("file_path")
        if not key:
            continue
        try:
            validate_key(str(key))
        except InvalidStorageKeyError:
            missing.append({**row, "_reason": "invalid_key_shape"})
            continue
        try:
            if not storage.exists(str(key)):
                missing.append({**row, "_reason": "not_in_storage"})
        except Exception as exc:  # network / auth errors surface as misses
            logger.warning("Class (C) storage check failed for key=%s: %s", key, exc)
            missing.append({**row, "_reason": "storage_check_failed"})
    return len(rows), missing


def _print_samples(label: str, rows: list[dict], limit: int) -> None:
    if not rows:
        return
    sample = rows[: max(0, limit)]
    logger.warning("%s sample (%d of %d):", label, len(sample), len(rows))
    for r in sample:
        fields = " ".join(f"{k}={v}" for k, v in r.items() if not k.startswith("_"))
        reason = r.get("_reason")
        if reason:
            fields = f"{fields} reason={reason}"
        logger.warning("  %s", fields)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Max number of rows to print per class (default: 10).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL env var.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override project data/ directory when validating file paths "
        "(default: <repo>/data). Pass empty string to skip the under-data/ check.",
    )
    args = parser.parse_args()

    configure_logging(level="INFO")
    load_dotenv()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 1

    if args.data_dir == "":
        data_dir: Path | None = None
    elif args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    else:
        data_dir = (Path(__file__).parent.parent / "data").resolve()

    db = DatabaseAdapter(db_url)

    # (A) — blocking
    null_img_rows = db.query(NULL_IMG_ID_SQL)
    # (B) — warning
    orphan_rows = db.query(ORPHAN_SQL)
    # (C) — warning
    file_checked, file_missing = _load_missing_files(db, data_dir)

    exit_code = 0

    logger.info("=== Chart-image referential integrity ===")
    logger.info(
        "data_dir=%s (used for under-data/ validation; pass --data-dir '' to skip)",
        data_dir,
    )

    # Class A — blocking
    if null_img_rows:
        logger.error(
            "(A) BLOCKING: %d chart-sourced fact(s) have null source_locator.img_id "
            "(ChartFactBridgeStage invariant violated)",
            len(null_img_rows),
        )
        by_filing = Counter(r["filing_id"] for r in null_img_rows)
        for filing_id, count in sorted(by_filing.items(), key=lambda x: (-x[1], x[0])):
            logger.error("  filing_id=%s: %d fact(s)", filing_id, count)
        _print_samples("(A)", null_img_rows, args.sample)
        exit_code = 1
    else:
        logger.info("(A) OK: no chart-sourced facts with null img_id.")

    # Class B — warning
    if orphan_rows:
        by_filing = Counter(r["filing_id"] for r in orphan_rows)
        by_source = Counter(r["source_type"] for r in orphan_rows)
        logger.warning(
            "(B) WARN: %d fact(s) reference img_id values with no matching asset row "
            "(across %d filing(s), source_types=%s)",
            len(orphan_rows),
            len(by_filing),
            dict(by_source),
        )
        for filing_id, count in sorted(by_filing.items(), key=lambda x: (-x[1], x[0])):
            logger.warning("  filing_id=%s: %d fact(s)", filing_id, count)
        _print_samples("(B)", orphan_rows, args.sample)
    else:
        logger.info("(B) OK: no orphaned img_id references.")

    # Class C — warning
    if file_missing:
        reasons = Counter(r["_reason"] for r in file_missing)
        logger.warning(
            "(C) WARN: %d of %d v2_image_assets rows have file_path but the file is "
            "unreachable from data/ (reasons=%s)",
            len(file_missing),
            file_checked,
            dict(reasons),
        )
        _print_samples("(C)", file_missing, args.sample)
    else:
        logger.info("(C) OK: all %d assets resolve on disk under data/.", file_checked)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
