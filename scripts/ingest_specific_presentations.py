#!/usr/bin/env python3
"""
Ingest 7 specific presentations into the V2 database for web UI review.

These presentations exist as preannotated CSV files in the gold standard but
have not been ingested into the database. The standard ingest_presentations.py
uses list_available() which is impractical for historical filings (2013, 2018).
This script ingests directly from local cached HTML files, or fetches from
EDGAR for ADBE (which has no local cache).

Usage:
    python3 scripts/ingest_specific_presentations.py --dry-run    # preview
    python3 scripts/ingest_specific_presentations.py --persist     # write to DB

Environment variables:
    DATABASE_URL     PostgreSQL connection string (required for --persist)
    SEC_USER_AGENT   Required for EDGAR access (only needed for ADBE download)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction_v2.persistence import V2PersistenceAdapter  # noqa: E402
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline  # noqa: E402
from src.infra.document_source import DocumentMetadata  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_specific_presentations")

GOLD_STANDARD_DIR = ROOT / "data" / "presentation_gold_standard"
PRESENTATIONS_DIR = ROOT / "data" / "presentations"

TARGETS = [
    "ADBE_2019-01-24",
    "INTU_2026-02-26",
    "META_2025-12-12",
    "NOW_2013-07-31",
    "TRUP_2018-02-13",
    "TRUP_2018-05-01",
    "TRUP_2018-08-02",
]

# ADBE source_id (CIK zero-padded to 10 digits, accession re-dashed)
ADBE_SOURCE_ID = "0000796343/0000796343-19-000008/exhibit991-pressrelease.htm"
ADBE_CIK = "0000796343"


# ---------------------------------------------------------------------------
# DB helpers (inlined from ingest_presentations.py)
# ---------------------------------------------------------------------------


def _get_or_create_company(conn: Any, ticker: str, company_name: str, cik: str | None) -> int:
    with conn.cursor() as cur:
        if cik:
            cur.execute("SELECT company_id FROM companies WHERE cik = %(cik)s", {"cik": cik})
            row = cur.fetchone()
            if row:
                return row["company_id"]
        cur.execute("SELECT company_id FROM companies WHERE ticker = %(ticker)s", {"ticker": ticker})
        row = cur.fetchone()
        if row:
            return row["company_id"]
        effective_cik = cik or f"presentation:{ticker}"
        cur.execute(
            """
            INSERT INTO companies (company_name, ticker, cik, created_at)
            VALUES (%(company_name)s, %(ticker)s, %(cik)s, NOW())
            ON CONFLICT (cik) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                ticker = COALESCE(EXCLUDED.ticker, companies.ticker)
            RETURNING company_id
            """,
            {"company_name": company_name, "ticker": ticker, "cik": effective_cik},
        )
        return conn.cursor().fetchone()["company_id"] if False else cur.fetchone()["company_id"]


def _upsert_presentation_filing(
    conn: Any, company_id: int, ticker: str, document_date: date | None, source_id: str, cik: str | None
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (
                company_id, accession_number, form_type, filing_date,
                document_type, ticker, document_date, transcript_source,
                processing_status, updated_at
            )
            VALUES (
                %(company_id)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
                %(document_type)s, %(ticker)s, %(document_date)s, %(transcript_source)s,
                %(processing_status)s, NOW()
            )
            ON CONFLICT (company_id, accession_number) DO UPDATE SET
                document_type = EXCLUDED.document_type,
                ticker = EXCLUDED.ticker,
                document_date = EXCLUDED.document_date,
                transcript_source = EXCLUDED.transcript_source,
                processing_status = EXCLUDED.processing_status,
                updated_at = NOW()
            RETURNING filing_id
            """,
            {
                "company_id": company_id,
                "accession_number": f"presentation:{source_id}",
                "form_type": "8-K",
                "filing_date": document_date,
                "document_type": "investor_presentation",
                "ticker": ticker,
                "document_date": document_date,
                "transcript_source": "sec_edgar_presentation",
                "processing_status": "processing",
            },
        )
        return cur.fetchone()["filing_id"]


def _is_already_ingested(conn: Any, source_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM v2_documents vd
            JOIN filings f ON vd.filing_id = f.filing_id
            WHERE f.accession_number = %(accession)s AND vd.status = 'complete'
            LIMIT 1
            """,
            {"accession": f"presentation:{source_id}"},
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _parse_date_from_key(key: str) -> date:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", key)
    if not m:
        raise ValueError(f"Cannot parse date from key: {key}")
    return date.fromisoformat(m.group(1))


def _load_meta_json(html_path: Path) -> dict:
    """Load the .meta.json sidecar for a cached HTML file.

    Cache files are named foo.htm.html; the meta is at foo.htm.meta.json.
    Strip the trailing .html suffix, then replace the .htm suffix with .htm.meta.json.
    """
    # html_path: .../ex991q42017earningsrelease.htm.html
    # base:      .../ex991q42017earningsrelease.htm
    base = Path(str(html_path).removesuffix(".html"))
    meta_path = Path(str(base) + ".meta.json")
    if not meta_path.exists():
        raise FileNotFoundError(f"No .meta.json found at {meta_path}")
    return json.loads(meta_path.read_text())


def ingest_all(dry_run: bool, db_url: str | None) -> None:
    file_index = json.loads((GOLD_STANDARD_DIR / "_file_index.json").read_text())

    db_adapter = None
    if not dry_run:
        from src.infra.db import DatabaseAdapter
        db_adapter = DatabaseAdapter(db_url)

    pipeline = V2Pipeline(config=PipelineConfig.for_presentation())

    results = []
    for key in TARGETS:
        logger.info("Processing %s ...", key)
        doc_date = _parse_date_from_key(key)

        try:
            # --- Get HTML and metadata ---
            if key == "ADBE_2019-01-24":
                # ADBE has no local cache -- fetch from EDGAR
                from src.infra.sec_presentation_source import SECPresentationSource
                source = SECPresentationSource(cache_dir=PRESENTATIONS_DIR)
                source._cik_to_ticker_cache[ADBE_CIK] = "ADBE"
                html_content, fetched_meta = source.fetch(ADBE_SOURCE_ID)
                source_id = ADBE_SOURCE_ID
                ticker = "ADBE"
                company_name = fetched_meta.company_name or "Adobe Inc."
                cik = ADBE_CIK
            else:
                local_path = ROOT / file_index[key]
                html_content = local_path.read_text(encoding="utf-8")
                meta = _load_meta_json(local_path)
                source_id = meta["source_id"]
                ticker = meta["ticker"]
                company_name = meta["company_name"] or ticker
                cik = meta["cik"]

            _metadata = DocumentMetadata(
                source_id=source_id,
                source="sec_edgar_presentation",
                company_name=company_name,
                ticker=ticker,
                cik=cik,
                document_type="investor_presentation",
                document_date=doc_date,
                form_type="8-K",
            )

            # --- Dedup check ---
            if db_adapter:
                with db_adapter.get_connection() as conn:
                    if _is_already_ingested(conn, source_id):
                        logger.info("  Skipping %s — already ingested", key)
                        results.append((key, "skipped", 0))
                        continue

            # --- Write HTML to temp file for pipeline ---
            with tempfile.NamedTemporaryFile(suffix=".html", mode="w", encoding="utf-8", delete=False) as tmp:
                tmp.write(html_content)
                tmp_path = Path(tmp.name)

            try:
                if dry_run or db_adapter is None:
                    pipe_result = pipeline.process(
                        html_path=tmp_path,
                        filing_id=0,
                        document_type="investor_presentation",
                        document_date=doc_date,
                    )
                    logger.info("  [DRY-RUN] %s → %d facts", key, pipe_result.fact_count)
                    results.append((key, "dry-run", pipe_result.fact_count))
                else:
                    with db_adapter.transaction() as conn:
                        company_id = _get_or_create_company(conn, ticker, company_name, cik)
                        filing_id = _upsert_presentation_filing(
                            conn, company_id, ticker, doc_date, source_id, cik
                        )

                    pipe_result = pipeline.process(
                        html_path=tmp_path,
                        filing_id=filing_id,
                        document_type="investor_presentation",
                        document_date=doc_date,
                    )
                    persist_result = V2PersistenceAdapter(db_adapter).persist_pipeline_result(
                        pipe_result,
                        filing_id,
                        document_type="investor_presentation",
                        ticker=ticker,
                        document_date=doc_date,
                        transcript_source="sec_edgar_presentation",
                    )

                    if persist_result.success:
                        logger.info(
                            "  Persisted %s: filing_id=%d, %d facts",
                            key, filing_id, persist_result.facts_upserted,
                        )
                        results.append((key, "ingested", persist_result.facts_upserted))
                    else:
                        errors = ", ".join(persist_result.errors or [])
                        logger.error("  Persist failed for %s: %s", key, errors)
                        results.append((key, "error", 0))
            finally:
                tmp_path.unlink(missing_ok=True)

        except Exception as exc:
            logger.exception("Error processing %s: %s", key, exc)
            results.append((key, "error", 0))

    # Summary
    print()
    print("=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    for key, status, facts in results:
        print(f"  {key:<30s}  {status:<10s}  {facts} facts")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest 7 specific presentations into V2 DB.")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Run pipeline but do not write to DB (default)")
    parser.add_argument("--persist", action="store_true",
                        help="Write results to database (overrides --dry-run)")
    args = parser.parse_args()

    dry_run = not args.persist
    db_url = os.environ.get("DATABASE_URL")

    if not dry_run and not db_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    if dry_run:
        logger.info("DRY-RUN mode — no database writes")

    ingest_all(dry_run=dry_run, db_url=db_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
