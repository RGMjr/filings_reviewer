#!/usr/bin/env python3
"""
Full-page-scan OCR backfill.

Runs V2 extraction with ``enable_full_page_ocr=True`` over filings that
match the full-page-scan detection heuristic (effectively empty HTML
body + many page-shaped images, e.g. PayPal 8-Ks). Defaults to dry-run:
prints the candidate filings and an estimated cost, does not persist.

Usage::

    # Dry-run: list candidates + cost estimate (no DB writes, no vision calls)
    python3 scripts/backfill_full_page_ocr.py --dry-run

    # Commit mode: restrict to PayPal pre-2024 8-Ks and persist
    FULL_PAGE_OCR_ENABLED=true python3 scripts/backfill_full_page_ocr.py \\
        --confirm --cik 0001633917 --form-type 8-K --filing-date-before 2024-01-01

    # Commit mode: specific filing IDs
    FULL_PAGE_OCR_ENABLED=true python3 scripts/backfill_full_page_ocr.py \\
        --confirm --filing-ids 101,102,103

Safety gates:
- ``--confirm`` required for any DB writes; default is ``--dry-run``.
- ``FULL_PAGE_OCR_ENABLED=true`` required in the environment for ``--confirm``.
- Respects the ``v2_review_decisions`` guard in persistence; will not pass
  ``force=True`` unless ``--force-reextract`` is also supplied.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.extraction_v2.exceptions import ReviewedFilingError  # noqa: E402
from src.extraction_v2.persistence import V2PersistenceAdapter  # noqa: E402
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Rough cost model: gpt-4o full-page OCR ≈ $0.05/call.
# Two-pass on chart-bearing pages ≈ 1.3x average call budget per image.
COST_PER_CALL_USD: float = 0.05
MIXED_PAGE_MULTIPLIER: float = 1.3


@dataclass
class FilingCandidate:
    filing_id: int
    cik: str
    company_name: str
    form_type: str
    filing_date: date | None
    accession_number: str | None
    image_count: int
    segment_char_count: int
    review_decisions: int

    @property
    def estimated_cost(self) -> float:
        return self.image_count * COST_PER_CALL_USD * MIXED_PAGE_MULTIPLIER


CANDIDATE_SQL = """
WITH per_filing AS (
    SELECT
        f.filing_id,
        f.cik,
        c.company_name,
        f.form_type,
        f.filing_date,
        f.accession_number,
        (SELECT COUNT(*) FROM v2_image_assets i WHERE i.doc_id = f.filing_id) AS image_count,
        COALESCE(
            (SELECT SUM(LENGTH(COALESCE(segment_text, '')))::bigint
             FROM v2_segments s WHERE s.doc_id = f.filing_id),
            0
        ) AS segment_char_count,
        (SELECT COUNT(*) FROM v2_review_decisions rd
            JOIN v2_metric_facts mf ON rd.fact_id = mf.fact_id
         WHERE mf.doc_id = f.filing_id) AS review_decisions
    FROM filings f
    JOIN companies c ON c.company_id = f.company_id
    WHERE (%(cik)s::text IS NULL OR f.cik = %(cik)s::text)
      AND (%(form_type)s::text IS NULL OR f.form_type = %(form_type)s::text)
      AND (%(filing_date_before)s::date IS NULL OR f.filing_date < %(filing_date_before)s::date)
      AND (%(filing_ids)s::bigint[] IS NULL OR f.filing_id = ANY(%(filing_ids)s::bigint[]))
)
SELECT *
FROM per_filing
WHERE image_count >= 5
  AND image_count >= 1.5 * GREATEST(1, segment_char_count::float / 2000)
ORDER BY filing_date DESC NULLS LAST, filing_id;
"""


def find_candidates(
    db: DatabaseAdapter,
    *,
    cik: str | None,
    form_type: str | None,
    filing_date_before: date | None,
    filing_ids: list[int] | None,
) -> list[FilingCandidate]:
    params = {
        "cik": cik,
        "form_type": form_type,
        "filing_date_before": filing_date_before,
        "filing_ids": filing_ids or None,
    }
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute(CANDIDATE_SQL, params)
        rows = cur.fetchall()
        cols = [c.name for c in cur.description]

    def _get(row: Any, key: str) -> Any:
        """Tolerant accessor for tuple-row and dict-row cursors."""
        if isinstance(row, dict):
            return row.get(key)
        return row[cols.index(key)]

    return [
        FilingCandidate(
            filing_id=_get(r, "filing_id"),
            cik=_get(r, "cik") or "",
            company_name=_get(r, "company_name") or "",
            form_type=_get(r, "form_type") or "",
            filing_date=_get(r, "filing_date"),
            accession_number=_get(r, "accession_number"),
            image_count=int(_get(r, "image_count") or 0),
            segment_char_count=int(_get(r, "segment_char_count") or 0),
            review_decisions=int(_get(r, "review_decisions") or 0),
        )
        for r in rows
    ]


def print_candidate_report(candidates: list[FilingCandidate]) -> None:
    if not candidates:
        print("No filings match the full-page-scan detection heuristic.")
        return
    print(f"\n{len(candidates)} candidate filing(s):\n")
    print(
        f"  {'filing_id':>10}  {'form':<5}  {'date':<10}  "
        f"{'images':>6}  {'text_chars':>10}  {'reviews':>7}  "
        f"{'est_cost':>10}  company"
    )
    print(
        f"  {'-' * 10}  {'-' * 5}  {'-' * 10}  {'-' * 6}  {'-' * 10}  {'-' * 7}  {'-' * 10}  -------"
    )
    total_cost = 0.0
    for c in candidates:
        print(
            f"  {c.filing_id:>10}  {c.form_type:<5}  "
            f"{str(c.filing_date) if c.filing_date else '-':<10}  "
            f"{c.image_count:>6}  {c.segment_char_count:>10}  {c.review_decisions:>7}  "
            f"${c.estimated_cost:>8.2f}  {c.company_name[:40]}"
        )
        total_cost += c.estimated_cost
    print(
        f"\n  Estimated total cost: ~${total_cost:.2f} "
        f"(assumes ${COST_PER_CALL_USD}/call × images × {MIXED_PAGE_MULTIPLIER} mixed-page multiplier)"
    )


def process_filings(
    candidates: list[FilingCandidate],
    *,
    force_reextract: bool,
    min_confidence_auto_accept: float,
) -> dict[str, Any]:
    """Run V2 extraction on each candidate with full-page-OCR enabled."""
    from src.infra.paths import image_cache_dir
    from src.infra.sec_client import SECClient

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set")
    db = DatabaseAdapter(database_url)
    # image_cache_dir must be set so OCRExtractionStage._download_missing_images
    # can cache downloaded bytes under v2_image_assets.file_path. Without it,
    # get_image_cache_path() raises and the whole download path aborts.
    sec = SECClient(image_cache_dir=image_cache_dir())

    config = PipelineConfig(
        enable_full_page_ocr=True,
        min_confidence_auto_accept=min_confidence_auto_accept,
    )
    pipeline = V2Pipeline(config=config, sec_client=sec)
    adapter = V2PersistenceAdapter(db=db)

    results: list[dict[str, Any]] = []
    for c in candidates:
        if c.review_decisions > 0 and not force_reextract:
            results.append(
                {
                    "filing_id": c.filing_id,
                    "status": "skipped",
                    "reason": f"{c.review_decisions} review decisions present (use --force-reextract to override)",
                }
            )
            continue

        logger.info(
            "Backfill running: filing_id=%s cik=%s form=%s date=%s images=%d",
            c.filing_id,
            c.cik,
            c.form_type,
            c.filing_date,
            c.image_count,
        )
        try:
            filing_meta = lookup_filing(db, c.filing_id)
            html_path = _resolve_html_path(filing_meta, db)
            # Normalize presentation-prefixed accession for downstream callers
            # (pipeline.process uses it to build image-download URLs, which
            # must be plain SEC archive paths).
            accession_for_pipeline = _normalize_accession(c.accession_number or "")
            result = pipeline.process(
                html_path=html_path,
                filing_id=c.filing_id,
                cik=c.cik,
                accession_number=accession_for_pipeline,
                document_date=c.filing_date,
            )
            try:
                adapter.persist_pipeline_result(
                    result,
                    filing_id=c.filing_id,
                    force=force_reextract,
                )
                status = "ok"
                error = None
            except ReviewedFilingError as e:
                status = "skipped_reviewed"
                error = str(e)
            results.append(
                {
                    "filing_id": c.filing_id,
                    "status": status,
                    "facts": result.fact_count,
                    "duration_ms": result.total_duration_ms,
                    "error": error,
                }
            )
        except Exception as e:
            logger.exception("Backfill failed for filing_id=%s", c.filing_id)
            results.append(
                {
                    "filing_id": c.filing_id,
                    "status": "error",
                    "error": str(e),
                }
            )

    return {
        "processed": sum(1 for r in results if r["status"] == "ok"),
        "skipped": sum(1 for r in results if r["status"].startswith("skipped")),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }


def _normalize_accession(accession: str) -> str:
    """Return the bare SEC accession token for presentation-prefixed values.

    Rows onboarded via ``scripts/ingest_presentations.py`` (pre-2024 PayPal
    8-Ks are the motivating case) store ``presentation:<cik>/<acc>/<filename>``
    in ``filings.accession_number``. Downstream callers (``FilingFetcher``
    path-traversal guard, ``OCRExtractionStage`` image-URL construction)
    require the bare ``NNNNNNNNNN-NN-NNNNNN`` shape, so we unwrap here.
    Non-prefixed values pass through unchanged.
    """
    if not accession:
        return ""
    if accession.startswith("presentation:"):
        parts = accession[len("presentation:") :].split("/")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        raise ValueError(f"malformed presentation: accession {accession!r}")
    return accession


def lookup_filing(db: DatabaseAdapter, filing_id: int) -> dict[str, Any]:
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT filing_id, cik, accession_number, html_storage_path, sec_html_url "
            "FROM filings WHERE filing_id = %s",
            (filing_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"filing_id {filing_id} not found")
        # Project cursors return DictRow (key-accessible). Iterating a dict
        # yields keys, so `dict(zip(cols, row))` would map col->col. Copy
        # through key access instead.
        if isinstance(row, dict):
            return {k: row.get(k) for k in row}
        cols = [c.name for c in cur.description]
        return dict(zip(cols, row, strict=True))


def _resolve_html_path(filing: dict[str, Any], db: DatabaseAdapter) -> Path:
    """Return a local path to the filing's primary HTML, fetching if absent.

    Path A candidates frequently have `html_storage_path=NULL` because the
    original pre-2024 ingest was parse-only (no HTML retention, no image
    download). We heal on-demand by calling ``FilingFetcher.fetch_filing``
    here — it writes `primary.htm` to disk AND updates
    `filings.html_storage_path` in the DB.
    """
    stored = filing.get("html_storage_path")
    if stored:
        path = Path(stored)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            return path

    # Fall through to fetch: either no stored path, or disk missing.
    logger.info(
        "html_storage_path missing for filing_id=%s; fetching from SEC",
        filing["filing_id"],
    )
    from src.filing_fetcher.filing_fetcher import FilingFetcher
    from src.infra.sec_client import FilingMetadata

    if not filing.get("sec_html_url"):
        raise ValueError(f"filing_id {filing['filing_id']} has no sec_html_url; cannot fetch")

    accession_for_fetch = _normalize_accession(filing["accession_number"] or "")

    metadata = FilingMetadata(
        cik=filing["cik"],
        company_name="",  # Not needed for fetch
        form_type="",
        filing_date="",
        accession_number=accession_for_fetch,
        primary_doc_url=filing["sec_html_url"],
    )
    fetcher = FilingFetcher(db=db)
    content = fetcher.fetch_filing(metadata, fetch_txt=False)
    if content is None or not content.html_path:
        raise FileNotFoundError(
            f"FilingFetcher could not retrieve HTML for filing_id {filing['filing_id']}"
        )

    path = Path(content.html_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(
            f"HTML for filing_id {filing['filing_id']} not at {path} after fetch"
        )
    return path


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_int_list(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="List candidates + cost estimate only (default)",
    )
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Run extraction and persist results (disables --dry-run)",
    )

    parser.add_argument("--cik", help="Restrict to this CIK (e.g. 0001633917 for PayPal)")
    parser.add_argument("--form-type", help="Restrict to this form type (e.g. 8-K)")
    parser.add_argument(
        "--filing-date-before", help="Restrict to filings strictly before this date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--filing-ids",
        help="Comma-separated filing_ids to target (overrides cik/form/date filters)",
    )
    parser.add_argument(
        "--force-reextract",
        action="store_true",
        help="Pass force=True to persistence (ONLY when you accept "
        "that existing review decisions will be purged)",
    )
    parser.add_argument(
        "--min-confidence-auto-accept",
        type=float,
        default=0.90,
        help="Forwarded to PipelineConfig (default: 0.90)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Where to write JSON summary (default: logs/full_page_ocr_backfill_<ts>.json)",
    )

    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        return 2

    candidates = find_candidates(
        DatabaseAdapter(database_url),
        cik=args.cik,
        form_type=args.form_type,
        filing_date_before=_parse_date(args.filing_date_before),
        filing_ids=_parse_int_list(args.filing_ids),
    )

    print_candidate_report(candidates)

    if not args.confirm:
        print("\nDry-run mode. Pass --confirm (with FULL_PAGE_OCR_ENABLED=true) to actually run.")
        return 0

    if os.environ.get("FULL_PAGE_OCR_ENABLED", "").lower() not in {"1", "true", "yes"}:
        print(
            "\nERROR: --confirm requires FULL_PAGE_OCR_ENABLED=true in the environment.",
            file=sys.stderr,
        )
        return 2

    summary = process_filings(
        candidates,
        force_reextract=args.force_reextract,
        min_confidence_auto_accept=args.min_confidence_auto_accept,
    )

    out_path = args.output or f"logs/full_page_ocr_backfill_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(
        f"\nDone. processed={summary['processed']} "
        f"skipped={summary['skipped']} errors={summary['errors']}. "
        f"Summary written to {out}"
    )
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
