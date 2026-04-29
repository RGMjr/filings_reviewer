"""
Upload filing HTML bytes to R2 long-haul storage and rewrite
``filings.html_storage_path`` to point at the R2 storage key.

Reads each row's HTML bytes from (in priority order):
  1. ``html_content`` (DB column populated by FilingFetcher / gh-299 migration);
  2. ``Path(html_storage_path).read_bytes()`` if the local file exists and is
     >= 15 KB (per ``feedback_zero_facts_can_be_pre_pipeline_failure``);
  3. SEC re-fetch via ``sec_html_url`` (with the existing ``SECClient._rate_limit``
     throttle), validated >= 15 KB.

R2 upload is verified via ``exists()`` HEAD before the column UPDATE; on UPDATE
failure the R2 key is left in place (orphans are cheap, lost data is not). The
selector is self-filtering, so re-running the script is idempotent.

Selector::

    SELECT filing_id, cik, accession_number, html_storage_path,
           html_content, sec_html_url
      FROM filings
     WHERE html_storage_path IS NOT NULL
       AND html_storage_path NOT LIKE 'filings/%/%/%'

Gates (mirrors ``scripts/relink_paypal_r2_keys.py`` /
``scripts/migrate_onedrive_html_paths.py``):

  - ``--apply``: required for any DB write or R2 upload.
  - ``--allow-prod``: required for ``--apply`` against ``*.neon.tech``.
  - ``FILINGS_REVIEWER_ALLOW_PROD_WRITES=1``: required for ``--apply`` against
    prod (enforced by ``R2FilingStorage.put_bytes`` itself; the script also
    refuses to start if the env var is missing).

Usage::

    # Dry-run (default, read-only)
    python3 scripts/migrate_filing_html_to_r2.py

    # Apply against local Docker (no prod gates)
    DATABASE_URL="$TEST_DATABASE_URL" \\
      python3 scripts/migrate_filing_html_to_r2.py --apply

    # Apply against prod (Neon)
    FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \\
      python3 scripts/migrate_filing_html_to_r2.py --apply --allow-prod

Exit codes:
    0  dry-run completed OR apply succeeded
    1  setup error / refusal
    2  partial failure (some rows could not be migrated)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.filing_storage import FilingStorage, get_filing_storage  # noqa: E402
from src.infra.image_storage import validate_key  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

_MIN_HTML_BYTES = 15_000  # per feedback_zero_facts_can_be_pre_pipeline_failure
_PROJECT_ROOT = Path(__file__).parent.parent


def _looks_like_prod(db_url: str) -> bool:
    return ".neon.tech" in db_url


def _compute_key(cik: str, accession_number: str) -> str:
    """``filings/<cik>/<accession>/primary.htm``. Validated via image_storage.validate_key."""
    key = f"filings/{cik}/{accession_number}/primary.htm"
    validate_key(key)
    return key


def _fetch_via_sec(sec_url: str, user_agent: str) -> bytes | None:
    """Re-fetch HTML via SEC, rate-limited. Returns bytes on success >= 15 KB."""
    from src.infra.sec_client import SECClient

    client = SECClient(user_agent=user_agent)
    client._rate_limit()
    resp = client.session.get(sec_url, timeout=30)
    resp.raise_for_status()
    data = resp.content
    if len(data) < _MIN_HTML_BYTES:
        logger.warning(
            "SEC re-fetch returned %d bytes (< %d minimum); treating as failure: %s",
            len(data),
            _MIN_HTML_BYTES,
            sec_url,
        )
        return None
    return data


def _resolve_bytes(
    row: dict, sec_user_agent: str, project_root: Path
) -> tuple[bytes | None, str | None]:
    """Return (bytes, source) or (None, None) on failure.

    Source is one of: 'html_content', 'disk', 'sec'.
    """
    filing_id = row["filing_id"]
    storage_path = row["html_storage_path"]
    html_content = row.get("html_content")
    sec_url = row.get("sec_html_url")

    # Source 1: html_content from DB (TEXT -> str -> utf-8 bytes).
    if html_content:
        data = html_content.encode("utf-8")
        if len(data) >= _MIN_HTML_BYTES:
            return data, "html_content"
        logger.warning(
            "filing_id=%s: html_content is %d bytes (< %d); falling through",
            filing_id,
            len(data),
            _MIN_HTML_BYTES,
        )

    # Source 2: local file at storage_path (could be data/filings/... or
    # data/gold_standard/... depending on legacy/gh-299 shape).
    if storage_path and not storage_path.startswith("filings/"):
        local = (
            project_root / storage_path
            if not Path(storage_path).is_absolute()
            else Path(storage_path)
        )
        if local.exists():
            try:
                data = local.read_bytes()
                if len(data) >= _MIN_HTML_BYTES:
                    return data, "disk"
                logger.warning(
                    "filing_id=%s: local file %s is %d bytes (< %d); falling through",
                    filing_id,
                    local,
                    len(data),
                    _MIN_HTML_BYTES,
                )
            except OSError as exc:
                logger.warning("filing_id=%s: failed reading %s: %s", filing_id, local, exc)

    # Source 3: SEC re-fetch.
    if sec_url:
        logger.info(
            "filing_id=%s: html_content/disk unavailable, falling back to SEC: %s",
            filing_id,
            sec_url,
        )
        try:
            data = _fetch_via_sec(sec_url, sec_user_agent)
            if data is not None:
                return data, "sec"
        except Exception as exc:
            logger.warning("filing_id=%s: SEC re-fetch failed: %s", filing_id, exc)

    return None, None


def migrate(
    db: DatabaseAdapter,
    rows: list[dict],
    storage: FilingStorage,
    *,
    apply: bool,
    sec_user_agent: str,
    project_root: Path = _PROJECT_ROOT,
) -> dict[str, int]:
    counts = {
        "audited": len(rows),
        "migrated": 0,
        "sec_fetched": 0,
        "skipped": 0,
        "failed": 0,
    }
    for row in rows:
        filing_id = row["filing_id"]
        cik = row["cik"]
        accession = row["accession_number"]

        key = _compute_key(cik, accession)
        data, source = _resolve_bytes(row, sec_user_agent, project_root)
        if data is None:
            logger.error(
                "filing_id=%s: no source bytes available "
                "(html_content/disk/SEC all failed); skipping",
                filing_id,
            )
            counts["skipped"] += 1
            continue

        if not apply:
            logger.info(
                "[DRY-RUN] filing_id=%s: would upload %d bytes (source=%s) -> R2 key %s "
                "and rewrite html_storage_path",
                filing_id,
                len(data),
                source,
                key,
            )
            if source == "sec":
                counts["sec_fetched"] += 1
            counts["migrated"] += 1
            continue

        # Apply path: upload + verify + UPDATE.
        try:
            storage.put_bytes(key, data, content_type="text/html")
        except Exception as exc:
            logger.error("filing_id=%s: R2 upload failed for %s: %s", filing_id, key, exc)
            counts["failed"] += 1
            continue

        try:
            if not storage.exists(key):
                logger.error(
                    "filing_id=%s: R2 HEAD verification failed for %s; leaving column untouched",
                    filing_id,
                    key,
                )
                counts["failed"] += 1
                continue
        except Exception as exc:
            logger.error(
                "filing_id=%s: R2 HEAD verification raised for %s: %s; leaving column untouched",
                filing_id,
                key,
                exc,
            )
            counts["failed"] += 1
            continue

        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE filings
                           SET html_storage_path = %(key)s
                         WHERE filing_id = %(filing_id)s
                        """,
                        {"key": key, "filing_id": filing_id},
                    )
                    rowcount = cur.rowcount
            if rowcount == 0:
                logger.warning(
                    "filing_id=%s: UPDATE matched 0 rows (concurrent change?); "
                    "R2 object orphaned at %s",
                    filing_id,
                    key,
                )
                counts["failed"] += 1
                continue
            if source == "sec":
                counts["sec_fetched"] += 1
            counts["migrated"] += 1
            logger.info(
                "filing_id=%s: migrated to R2 key %s (%d bytes, source=%s)",
                filing_id,
                key,
                len(data),
                source,
            )
        except Exception as exc:
            logger.error(
                "filing_id=%s: UPDATE failed: %s; R2 object orphaned at %s",
                filing_id,
                exc,
                key,
            )
            counts["failed"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL env var.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run uploads + UPDATEs. Without this flag, prints planned changes only.",
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        help="Required for --apply when DATABASE_URL points at *.neon.tech.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N rows (for staged rollouts / testing).",
    )
    args = parser.parse_args()

    configure_logging(level="INFO")
    load_dotenv()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set (and --database-url not passed)")
        return 1

    if args.apply and _looks_like_prod(db_url):
        if not args.allow_prod:
            logger.error("Refusing to apply against prod DATABASE_URL without --allow-prod.")
            return 1
        if os.environ.get("FILINGS_REVIEWER_ALLOW_PROD_WRITES") != "1":
            logger.error(
                "Refusing to apply against prod DATABASE_URL without "
                "FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 "
                "(matches R2FilingStorage.put_bytes / R2Storage guard)."
            )
            return 1

    sec_user_agent = os.getenv("SEC_USER_AGENT", "filings-reviewer info@example.com")

    db = DatabaseAdapter(db_url)
    storage = get_filing_storage()
    select_sql = """
        SELECT filing_id, cik, accession_number, html_storage_path,
               html_content, sec_html_url
          FROM filings
         WHERE html_storage_path IS NOT NULL
           AND html_storage_path NOT LIKE 'filings/%%/%%/%%'
         ORDER BY filing_id
    """
    if args.limit is not None:
        select_sql += f"\n LIMIT {int(args.limit)}"
    rows = db.query(select_sql)

    logger.info(
        "Migration plan: %d row(s) (apply=%s, db=%s, limit=%s, storage=%s)",
        len(rows),
        args.apply,
        "prod" if _looks_like_prod(db_url) else "non-prod",
        args.limit,
        type(storage).__name__,
    )

    if not rows:
        logger.info("No matching rows — nothing to do.")
        return 0

    counts = migrate(db, rows, storage, apply=args.apply, sec_user_agent=sec_user_agent)
    logger.info(
        "Migration result: audited=%d migrated=%d sec_fetched=%d skipped=%d failed=%d",
        counts["audited"],
        counts["migrated"],
        counts["sec_fetched"],
        counts["skipped"],
        counts["failed"],
    )
    return 0 if counts["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
