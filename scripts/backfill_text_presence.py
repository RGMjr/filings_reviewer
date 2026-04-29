#!/usr/bin/env python3
"""
Backfill ``v2_text_metric_presence`` for reviewed filings (PR2 follow-up).

Iterates filings that have any reviewer activity (``v2_review_decisions`` or
``v2_image_metric_confirmations``) and runs ``V2Pipeline.process`` then
``V2PersistenceAdapter.persist_pipeline_result(..., presence_only=True)`` to
populate the ``v2_text_metric_presence`` table. Skips fact persistence
entirely (so the reviewed-filing guard does not fire and reviewer decisions
are preserved).

Safety:
- Defaults to ``$TEST_DATABASE_URL``. Refuses to run against ``$DATABASE_URL``
  (Neon prod) unless ``--allow-prod`` is explicitly passed AND the user
  acknowledges via the env var ``ALLOW_PROD_BACKFILL=yes``.
- ``--limit N`` for smoke runs.
- ``--dry-run`` prints what it would do without writing.

Usage::

    # Smoke (one filing) against local DB:
    python3 scripts/backfill_text_presence.py --limit 1

    # Full local backfill, log to data/gold_standard/baselines/:
    python3 scripts/backfill_text_presence.py

    # All filings (not just reviewed) — useful for analytics / training:
    python3 scripts/backfill_text_presence.py --all-filings

This script is part of the text-presence pivot (see
``docs/operations/text-pipeline-presence-pivot-plan.md``).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.extraction_v2.exceptions import ReviewedFilingError  # noqa: E402
from src.extraction_v2.persistence import V2PersistenceAdapter  # noqa: E402
from src.extraction_v2.pipeline import V2Pipeline  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402

load_dotenv()

logger = logging.getLogger(__name__)


def _resolve_db_url(allow_prod: bool) -> str:
    """Pick the right DB URL with hard-coded prod guardrails."""
    test_url = os.environ.get("TEST_DATABASE_URL")
    prod_url = os.environ.get("DATABASE_URL")

    if not allow_prod:
        if not test_url:
            raise SystemExit(
                "TEST_DATABASE_URL is unset. Start local Postgres "
                "(`docker compose up -d`) or pass --allow-prod with "
                "ALLOW_PROD_BACKFILL=yes to use $DATABASE_URL."
            )
        return test_url

    if os.environ.get("ALLOW_PROD_BACKFILL", "").lower() != "yes":
        raise SystemExit(
            "--allow-prod requires ALLOW_PROD_BACKFILL=yes in the environment. "
            "This guard prevents accidental writes to Neon prod."
        )
    if not prod_url:
        raise SystemExit("DATABASE_URL is unset; cannot use --allow-prod.")
    return prod_url


def _select_filings(db: DatabaseAdapter, args: argparse.Namespace) -> list[dict]:
    """Return filings to process."""
    # v2_image_assets.filing_id is a BIGINT FK to filings.filing_id.
    # Renamed from doc_id in migration 202604291308 (gh-324).
    if args.all_filings:
        sql = """
            SELECT f.filing_id, f.cik, f.accession_number, f.html_storage_path,
                   f.filing_date, c.company_name, c.company_id
              FROM filings f
              JOIN companies c USING (company_id)
        """
        params: dict = {}
    else:
        sql = """
            SELECT DISTINCT f.filing_id, f.cik, f.accession_number,
                   f.html_storage_path, f.filing_date,
                   c.company_name, c.company_id
              FROM filings f
              JOIN companies c USING (company_id)
              LEFT JOIN v2_metric_facts mf ON mf.filing_id = f.filing_id
              LEFT JOIN v2_review_decisions rd ON rd.fact_id = mf.fact_id
              LEFT JOIN v2_image_assets ia ON ia.filing_id = f.filing_id
              LEFT JOIN v2_image_metric_confirmations imc ON imc.img_id = ia.img_id
             WHERE rd.decision_id IS NOT NULL OR imc.id IS NOT NULL
        """
        params = {}

    if args.filing_id is not None:
        sql += (
            " AND f.filing_id = %(filing_id)s"
            if not args.all_filings
            else " WHERE f.filing_id = %(filing_id)s"
        )
        params["filing_id"] = args.filing_id

    sql += " ORDER BY f.filing_id"

    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    return db.query(sql, params)


def _resolve_html(filing: dict, db: DatabaseAdapter) -> tuple[Path | None, str | None]:
    """Return (resolved_path, temp_path_to_clean_up).

    Tries html_storage_path first, then falls back to ``filings.html_content``
    written to a temp file (mirrors ``batch_v2_extraction.py`` behavior).
    """
    storage_path = filing.get("html_storage_path")
    if storage_path:
        p = Path(storage_path)
        if p.exists():
            return p, None

    rows = db.query(
        "SELECT html_content FROM filings "
        "WHERE filing_id = %(filing_id)s AND html_content IS NOT NULL",
        {"filing_id": filing["filing_id"]},
    )
    if rows and rows[0].get("html_content"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".htm", delete=False, encoding="utf-8")
        tmp.write(rows[0]["html_content"])
        tmp.close()
        return Path(tmp.name), tmp.name

    return None, None


def _process_one(
    filing: dict,
    db_url: str,
    pipeline: V2Pipeline,
    dry_run: bool,
) -> tuple[str, int]:
    """Process one filing; return (status, presences_upserted)."""
    db = DatabaseAdapter(db_url)
    html_path, temp_to_clean = _resolve_html(filing, db)
    try:
        if html_path is None:
            return "no_html", 0

        result = pipeline.process(
            html_path=html_path,
            filing_id=filing["filing_id"],
            cik=filing.get("cik") or "",
            accession_number=filing.get("accession_number") or "",
            document_date=filing.get("filing_date"),
        )
        if not result.success:
            return f"pipeline_failed: {result.error_message}", 0

        if dry_run:
            return f"dry_run (would upsert {len(result.presences)} presences)", len(
                result.presences
            )

        adapter = V2PersistenceAdapter(db_url=db_url)
        try:
            persistence_result = adapter.persist_pipeline_result(
                result,
                filing_id=filing["filing_id"],
                document_type="sec_filing",
                presence_only=True,
            )
        except ReviewedFilingError as e:  # pragma: no cover — presence_only bypasses fact path
            return f"reviewed_filing_error_unexpected: {e}", 0

        return "ok", persistence_result.presences_upserted
    finally:
        if temp_to_clean:
            try:
                os.unlink(temp_to_clean)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Process only first N filings")
    parser.add_argument("--filing-id", type=int, default=None, help="Process only this filing_id")
    parser.add_argument(
        "--all-filings",
        action="store_true",
        help="Process all filings, not just those with reviewer activity",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but skip persistence",
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        help="Allow $DATABASE_URL (Neon prod). Requires ALLOW_PROD_BACKFILL=yes env.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "gold_standard" / "baselines",
        help="Directory for run log",
    )
    args = parser.parse_args()

    db_url = _resolve_db_url(args.allow_prod)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.log_dir / f"presence_backfill_{datetime.now(UTC).strftime('%Y-%m-%d')}.log"

    file_handler = logging.FileHandler(log_path)
    stream_handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler.setFormatter(fmt)
    stream_handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler], force=True)

    logger.info("DB target: %s", db_url.split("@")[-1] if "@" in db_url else "<local>")
    logger.info("Log: %s", log_path)

    db = DatabaseAdapter(db_url)
    filings = _select_filings(db, args)
    logger.info("Selected %d filings", len(filings))

    pipeline = V2Pipeline()  # default config — ChartFactBridgeStage on; metric-classify off

    counts = {"ok": 0, "no_html": 0, "failed": 0, "skipped": 0}
    total_presences = 0
    start = time.time()

    for i, filing in enumerate(filings, start=1):
        fid = filing["filing_id"]
        company = filing.get("company_name", "?")
        try:
            status, presences = _process_one(filing, db_url, pipeline, args.dry_run)
        except Exception as e:
            logger.exception("Filing %s (%s) raised: %s", fid, company, e)
            counts["failed"] += 1
            continue

        if status == "ok" or status.startswith("dry_run"):
            counts["ok"] += 1
            total_presences += presences
            logger.info(
                "[%d/%d] filing %s (%s): %s, presences=%d",
                i,
                len(filings),
                fid,
                company,
                status,
                presences,
            )
        elif status == "no_html":
            counts["no_html"] += 1
            logger.warning(
                "[%d/%d] filing %s (%s): no HTML available", i, len(filings), fid, company
            )
        else:
            counts["failed"] += 1
            logger.error("[%d/%d] filing %s (%s): %s", i, len(filings), fid, company, status)

    elapsed = time.time() - start
    logger.info(
        "Done. %d ok, %d no_html, %d failed in %.1fs (%d presence rows upserted)",
        counts["ok"],
        counts["no_html"],
        counts["failed"],
        elapsed,
        total_presences,
    )

    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
