"""
Rewrite stale ``filings.html_storage_path`` values that point at OneDrive
cloud-only paths and populate ``html_content`` from the canonical local copy
(or via SEC re-fetch when the local file is missing). Tactical fix for gh-299;
gh-300 will replace ``html_storage_path`` semantics with R2 storage keys.

Selector:

    SELECT filing_id, html_storage_path, sec_html_url FROM filings
     WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%'

For each matching row:

  1. Strip the OneDrive prefix to derive the worktree-relative path
     (e.g. ``data/gold_standard/<Company>/filing.html``).
  2. If the local file resolves and is > 15 KB: read it, then UPDATE both
     ``html_storage_path`` (relative form) and ``html_content``.
  3. Otherwise, if ``sec_html_url`` is set: re-fetch via the existing
     SEC client (rate-limited), validate size > 15 KB, then UPDATE.
  4. Otherwise: log an error and leave the row unchanged.

Gates (mirrors ``scripts/relink_paypal_r2_keys.py``):

  - ``--apply``: required for any DB write.
  - ``FILINGS_REVIEWER_ALLOW_PROD_WRITES=1``: required when ``DATABASE_URL``
    points at prod (``*.neon.tech``), AND ``--allow-prod`` must be passed.

Usage::

    # Dry-run (default, read-only)
    python3 scripts/migrate_onedrive_html_paths.py

    # Apply against local Docker
    DATABASE_URL="$TEST_DATABASE_URL" \\
      python3 scripts/migrate_onedrive_html_paths.py --apply

    # Apply against prod (requires explicit user confirmation per CLAUDE.md)
    FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \\
      python3 scripts/migrate_onedrive_html_paths.py --apply --allow-prod

Exit codes:
    0  dry-run completed OR apply succeeded
    1  setup error / refusal
    2  partial failure (some rows could not be updated)
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_MIN_HTML_BYTES = 15_000  # per feedback_zero_facts_can_be_pre_pipeline_failure
_ONEDRIVE_PREFIX_RE = re.compile(r"^/Users/[^/]+/.*?OneDrive-CMASB/.*?/filings_reviewer/")


def _looks_like_prod(db_url: str) -> bool:
    return ".neon.tech" in db_url


def _derive_relative_path(onedrive_path: str) -> str | None:
    """Strip the OneDrive prefix; return the worktree-relative path or None."""
    match = _ONEDRIVE_PREFIX_RE.match(onedrive_path)
    if not match:
        return None
    return onedrive_path[match.end() :]


def _fetch_via_sec(sec_url: str, user_agent: str) -> str | None:
    """Re-fetch HTML via SEC, rate-limited. Returns text on success > 15 KB."""
    from src.infra.sec_client import SECClient  # local import to keep module light

    client = SECClient(user_agent=user_agent)
    client._rate_limit()
    resp = client.session.get(sec_url, timeout=30)
    resp.raise_for_status()
    text = resp.text
    if len(text) < _MIN_HTML_BYTES:
        logger.warning(
            "SEC re-fetch returned %d bytes (< %d minimum); treating as failure: %s",
            len(text),
            _MIN_HTML_BYTES,
            sec_url,
        )
        return None
    return text


def _process_row(
    row: dict,
    *,
    apply: bool,
    sec_user_agent: str,
    project_root: Path,
) -> str:
    """Returns one of: 'rewritten', 'fetched_from_sec', 'failed'."""
    filing_id = row["filing_id"]
    onedrive_path = row["html_storage_path"]
    sec_url = row.get("sec_html_url")

    relative = _derive_relative_path(onedrive_path)
    if not relative:
        logger.error(
            "filing_id=%s: could not strip OneDrive prefix from %s",
            filing_id,
            onedrive_path,
        )
        return "failed"

    local_path = project_root / relative
    content: str | None = None
    source: str | None = None

    if local_path.exists():
        try:
            content = local_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("filing_id=%s: failed reading %s: %s", filing_id, local_path, exc)
            content = None
        if content is not None and len(content) < _MIN_HTML_BYTES:
            logger.warning(
                "filing_id=%s: local file is %d bytes (< %d); ignoring",
                filing_id,
                len(content),
                _MIN_HTML_BYTES,
            )
            content = None
        if content is not None:
            source = "disk"

    if content is None and sec_url:
        logger.info(
            "filing_id=%s: local file missing/short, falling back to SEC: %s",
            filing_id,
            sec_url,
        )
        try:
            content = _fetch_via_sec(sec_url, sec_user_agent)
        except Exception as exc:
            logger.warning("filing_id=%s: SEC re-fetch failed: %s", filing_id, exc)
            content = None
        if content is not None:
            source = "sec"

    if content is None:
        logger.error(
            "filing_id=%s: no content from disk (path=%s exists=%s) or SEC (sec_url=%s); skipping",
            filing_id,
            local_path,
            local_path.exists(),
            sec_url,
        )
        return "failed"

    if not apply:
        logger.info(
            "[DRY-RUN] filing_id=%s: would set html_storage_path=%s, "
            "html_content=%d bytes (source=%s)",
            filing_id,
            relative,
            len(content),
            source,
        )
        return "rewritten" if source == "disk" else "fetched_from_sec"

    return "_to_apply", relative, content, source, filing_id  # type: ignore[return-value]


def migrate(
    db: DatabaseAdapter,
    rows: list[dict],
    *,
    apply: bool,
    sec_user_agent: str,
    project_root: Path = _PROJECT_ROOT,
) -> dict[str, int]:
    counts = {"audited": len(rows), "rewritten": 0, "fetched_from_sec": 0, "failed": 0}
    for row in rows:
        result = _process_row(
            row,
            apply=apply,
            sec_user_agent=sec_user_agent,
            project_root=project_root,
        )

        if isinstance(result, str):
            if result == "rewritten":
                counts["rewritten"] += 1
            elif result == "fetched_from_sec":
                counts["fetched_from_sec"] += 1
            else:
                counts["failed"] += 1
            continue

        # apply path: tuple ('_to_apply', relative, content, source, filing_id)
        _, relative, content, source, filing_id = result
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE filings
                           SET html_storage_path = %(rel)s,
                               html_content = %(content)s
                         WHERE filing_id = %(filing_id)s
                        """,
                        {"rel": relative, "content": content, "filing_id": filing_id},
                    )
                    rowcount = cur.rowcount
            if rowcount == 0:
                logger.warning(
                    "filing_id=%s: UPDATE matched 0 rows (concurrent change?)",
                    filing_id,
                )
                counts["failed"] += 1
                continue
            if source == "disk":
                counts["rewritten"] += 1
            else:
                counts["fetched_from_sec"] += 1
            logger.info(
                "filing_id=%s: rewrote html_storage_path=%s + populated html_content "
                "(%d bytes, source=%s)",
                filing_id,
                relative,
                len(content),
                source,
            )
        except Exception as exc:
            logger.error("filing_id=%s: UPDATE failed: %s", filing_id, exc)
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
        help="Actually run the UPDATEs. Without this flag, prints planned changes only.",
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
                "(matches R2Storage.put_bytes / relink_paypal_r2_keys guard)."
            )
            return 1

    sec_user_agent = os.getenv("SEC_USER_AGENT", "filings-reviewer info@example.com")

    db = DatabaseAdapter(db_url)
    select_sql = """
        SELECT filing_id, html_storage_path, sec_html_url
          FROM filings
         WHERE html_storage_path LIKE '/Users/%%/OneDrive-CMASB/%%'
         ORDER BY filing_id
    """
    if args.limit is not None:
        select_sql += f"\n LIMIT {int(args.limit)}"
    rows = db.query(select_sql)

    logger.info(
        "Migration plan: %d row(s) (apply=%s, db=%s, limit=%s)",
        len(rows),
        args.apply,
        "prod" if _looks_like_prod(db_url) else "non-prod",
        args.limit,
    )

    if not rows:
        logger.info("No matching rows — nothing to do.")
        return 0

    counts = migrate(db, rows, apply=args.apply, sec_user_agent=sec_user_agent)
    logger.info(
        "Migration result: audited=%d rewritten=%d fetched_from_sec=%d failed=%d",
        counts["audited"],
        counts["rewritten"],
        counts["fetched_from_sec"],
        counts["failed"],
    )
    return 0 if counts["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
