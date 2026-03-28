#!/usr/bin/env python3
"""
Batch Presentation Ingestion — Fetch and process investor presentations.

Fetches investor presentations from SEC 8-K filings, runs them through the V2
pipeline, and optionally persists results to the database.

Usage:
    # Dry run — show what would be ingested (no DB writes)
    python3 scripts/ingest_presentations.py --ticker CRM ADBE --dry-run

    # Persist to database
    python3 scripts/ingest_presentations.py --ticker CRM ADBE --persist

    # Limit presentations per ticker
    python3 scripts/ingest_presentations.py --ticker MSFT --limit 3 --dry-run

Environment variables:
    DATABASE_URL     PostgreSQL connection string (required for --persist)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _sigint_handler(signum: int, frame: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    print("\nInterrupt received — finishing current document then shutting down...", flush=True)

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction_v2.persistence import V2PersistenceAdapter  # noqa: E402
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline  # noqa: E402
from src.infra.company_mapping import get_company_info  # noqa: E402
from src.infra.document_source import DocumentMetadata  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_presentations")


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """Result for a single presentation."""

    source_id: str
    ticker: str
    document_date: date | None
    status: str  # "ingested", "skipped", "error"
    fact_count: int = 0
    filing_id: int | None = None
    error: str | None = None


@dataclass
class IngestSummary:
    """Aggregated results from a batch ingestion run."""

    results: list[IngestResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(1 for r in self.results if r.status == "ingested")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == "error")

    @property
    def total_facts(self) -> int:
        return sum(r.fact_count for r in self.results)

    def print_report(self) -> None:
        print()
        print("=" * 70)
        print("PRESENTATION INGESTION SUMMARY")
        print("=" * 70)
        print(f"  Ingested:    {self.ingested}")
        print(f"  Skipped:     {self.skipped}")
        print(f"  Errors:      {self.errors}")
        print(f"  Total facts: {self.total_facts}")
        print()
        if self.results:
            print("  Per-presentation breakdown:")
            for r in self.results:
                date_str = r.document_date.isoformat() if r.document_date else "?"
                source_label = r.source_id.split("/")[-1] if "/" in r.source_id else r.source_id
                if r.status == "ingested":
                    print(
                        f"    {r.ticker:6s}  {date_str}  {source_label}  "
                        f"{r.fact_count} facts  filing_id={r.filing_id}"
                    )
                elif r.status == "skipped":
                    print(
                        f"    {r.ticker:6s}  {date_str}  {source_label}"
                        f"  [skipped — already ingested]"
                    )
                else:
                    print(f"    {r.ticker:6s}  {date_str}  {source_label}  [ERROR: {r.error}]")
        print()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _get_or_create_company(conn: Any, ticker: str, company_name: str, cik: str | None) -> int:
    """Look up or create a companies record, returning company_id."""
    with conn.cursor() as cur:
        # Prefer lookup by CIK when available (authoritative)
        if cik:
            cur.execute(
                "SELECT company_id FROM companies WHERE cik = %(cik)s",
                {"cik": cik},
            )
            row = cur.fetchone()
            if row:
                return row["company_id"]

        # Fall back to ticker lookup
        cur.execute(
            "SELECT company_id FROM companies WHERE ticker = %(ticker)s",
            {"ticker": ticker},
        )
        row = cur.fetchone()
        if row:
            return row["company_id"]

        # Create a minimal company record.
        # Use real CIK if available; otherwise use a synthetic value.
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
        row = cur.fetchone()
        return row["company_id"]


def _upsert_presentation_filing(
    conn: Any,
    company_id: int,
    ticker: str,
    document_date: date | None,
    source_id: str,
    cik: str | None,
) -> int:
    """
    Create or update a filings record for an investor presentation.

    Uses source_id (which encodes cik/accession/filename) as the
    unique key via the accession_number column.
    Returns the filing_id.
    """
    # Encode source_id as the accession number for uniqueness
    accession = f"presentation:{source_id}"

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
                "accession_number": accession,
                "form_type": "8-K",
                "filing_date": document_date,
                "document_type": "investor_presentation",
                "ticker": ticker,
                "document_date": document_date,
                "transcript_source": "sec_edgar_presentation",
                "processing_status": "processing",
            },
        )
        row = cur.fetchone()
        return row["filing_id"]


def _is_already_ingested(conn: Any, source_id: str) -> bool:
    """Check if a presentation has already been processed (v2_documents record exists)."""
    accession = f"presentation:{source_id}"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM v2_documents vd
            JOIN filings f ON vd.filing_id = f.filing_id
            WHERE f.accession_number = %(accession)s
              AND vd.status = 'complete'
            LIMIT 1
            """,
            {"accession": accession},
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Core ingestion logic
# ---------------------------------------------------------------------------


def _process_one(
    source_id: str,
    ticker: str,
    metadata: DocumentMetadata,
    html_content: str,
    pipeline: V2Pipeline,
    db_adapter: Any | None,
    dry_run: bool,
) -> IngestResult:
    """Run the pipeline on one presentation and optionally persist results."""
    result = IngestResult(
        source_id=source_id,
        ticker=ticker,
        document_date=metadata.document_date,
        status="error",
    )

    # Write HTML to a temp file (pipeline.process() takes a Path)
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    try:
        pipe_result = pipeline.process(
            html_path=tmp_path,
            filing_id=-1,  # placeholder — replaced on persist
            document_type="investor_presentation",
            document_date=metadata.document_date,
        )
        result.fact_count = pipe_result.fact_count

        if dry_run or db_adapter is None:
            result.status = "ingested"
            logger.info(
                "[DRY-RUN] %s %s → %d facts",
                ticker,
                source_id.split("/")[-1] if "/" in source_id else source_id,
                result.fact_count,
            )
            return result

        # Persist to database
        company_info = get_company_info(ticker)
        company_name = (
            company_info.company_name if company_info else (metadata.company_name or ticker)
        )

        with db_adapter.transaction() as conn:
            company_id = _get_or_create_company(conn, ticker, company_name, cik=metadata.cik)
            filing_id = _upsert_presentation_filing(
                conn,
                company_id=company_id,
                ticker=ticker,
                document_date=metadata.document_date,
                source_id=source_id,
                cik=metadata.cik,
            )
            result.filing_id = filing_id

        # Re-run pipeline with the real filing_id for correct provenance
        pipe_result2 = pipeline.process(
            html_path=tmp_path,
            filing_id=filing_id,
            document_type="investor_presentation",
            document_date=metadata.document_date,
        )
        persist_result = V2PersistenceAdapter(db_adapter).persist_pipeline_result(
            pipe_result2,
            filing_id,
            document_type="investor_presentation",
            ticker=ticker,
            document_date=metadata.document_date,
            transcript_source="sec_edgar_presentation",
        )

        if persist_result.success:
            result.status = "ingested"
            result.fact_count = persist_result.facts_upserted
            logger.info(
                "Persisted %s %s: filing_id=%s, %d facts",
                ticker,
                source_id.split("/")[-1] if "/" in source_id else source_id,
                filing_id,
                result.fact_count,
            )
        else:
            errors = ", ".join(persist_result.errors or [])
            result.status = "error"
            result.error = f"persist failed: {errors}"

    except Exception as exc:
        logger.exception("Error processing %s: %s", source_id, exc)
        result.status = "error"
        result.error = str(exc)
    finally:
        tmp_path.unlink(missing_ok=True)

    return result


def _load_progress(progress_file: Path) -> set[str]:
    """Load set of tickers already marked 'done' from a progress file."""
    if not progress_file.exists():
        return set()
    try:
        entries = json.loads(progress_file.read_text())
        return {e["ticker"] for e in entries if e.get("status") == "done"}
    except (json.JSONDecodeError, OSError, KeyError):
        return set()


def _save_progress(progress_file: Path, ticker: str, count: int) -> None:
    """Append a done entry to the progress file (create if missing)."""
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if progress_file.exists():
        try:
            entries = json.loads(progress_file.read_text())
        except (json.JSONDecodeError, OSError):
            entries = []
    entries.append({
        "ticker": ticker,
        "status": "done",
        "count": count,
        "timestamp": datetime.now(UTC).isoformat(),
    })
    progress_file.write_text(json.dumps(entries, indent=2))


def run_ingestion(
    tickers: list[str],
    limit: int,
    dry_run: bool,
    db_url: str | None,
    max_failures: int = 10,
    resume: bool = False,
    progress_file: Path | None = None,
) -> IngestSummary:
    """
    Main ingestion loop.

    Args:
        tickers: List of ticker symbols to ingest
        limit: Max presentations per ticker
        dry_run: If True, skip DB writes
        db_url: PostgreSQL connection string (ignored if dry_run=True)
        max_failures: Exit after this many consecutive failures (circuit breaker)
        resume: Skip tickers already marked done in progress_file
        progress_file: Path to JSON progress checkpoint file

    Returns:
        IngestSummary with per-presentation results
    """
    global _shutdown_requested

    if progress_file is None:
        progress_file = Path("logs/ingest_presentations_progress.json")

    from src.infra.sec_presentation_source import SECPresentationSource

    source = SECPresentationSource()

    # Build database adapter
    db_adapter = None
    if not dry_run:
        if not db_url:
            raise ValueError("DATABASE_URL is required for non-dry-run ingestion.")
        from src.infra.db import DatabaseAdapter

        db_adapter = DatabaseAdapter(db_url)

    # Build pipeline (presentation mode)
    pipeline = V2Pipeline(config=PipelineConfig.for_presentation())

    summary = IngestSummary()
    consecutive_failures = 0

    # Resume: load already-done tickers
    done_tickers: set[str] = set()
    if resume:
        done_tickers = _load_progress(progress_file)
        if done_tickers:
            logger.info("Resuming: skipping %d already-done ticker(s): %s", len(done_tickers), sorted(done_tickers))

    for ticker in tickers:
        if _shutdown_requested:
            logger.info("Shutdown requested — stopping after current ticker")
            break

        if resume and ticker in done_tickers:
            logger.info("Skipping %s (already done per progress file)", ticker)
            continue

        logger.info("Listing presentations for %s from SEC EDGAR...", ticker)
        try:
            docs = source.list_available(ticker=ticker, limit=limit)
        except Exception as exc:
            logger.error("Failed to list presentations for %s: %s", ticker, exc)
            summary.results.append(
                IngestResult(
                    source_id=f"?:{ticker}",
                    ticker=ticker,
                    document_date=None,
                    status="error",
                    error=str(exc),
                )
            )
            consecutive_failures += 1
            if consecutive_failures >= max_failures:
                logger.error("Circuit breaker: %d consecutive failures — aborting", consecutive_failures)
                summary.print_report()
                sys.exit(2)
            continue

        logger.info("  Found %d presentation(s) for %s", len(docs), ticker)
        ticker_count = 0

        for meta in docs:
            if _shutdown_requested:
                logger.info("Shutdown requested — stopping after current document")
                break

            source_id = meta.source_id

            # Dedup check (only when we have a DB connection)
            if db_adapter and not dry_run:
                with db_adapter.get_connection() as conn:
                    if _is_already_ingested(conn, source_id):
                        logger.info(
                            "  Skipping %s — already ingested",
                            source_id,
                        )
                        summary.results.append(
                            IngestResult(
                                source_id=source_id,
                                ticker=ticker,
                                document_date=meta.document_date,
                                status="skipped",
                            )
                        )
                        consecutive_failures = 0
                        ticker_count += 1
                        continue

            # Fetch HTML
            try:
                html_content, fetched_meta = source.fetch(source_id)
                # Use fetched_meta if it has richer data
                if fetched_meta.document_date and not meta.document_date:
                    meta = fetched_meta
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", source_id, exc)
                summary.results.append(
                    IngestResult(
                        source_id=source_id,
                        ticker=ticker,
                        document_date=meta.document_date,
                        status="error",
                        error=str(exc),
                    )
                )
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    logger.error("Circuit breaker: %d consecutive failures — aborting", consecutive_failures)
                    summary.print_report()
                    sys.exit(2)
                continue

            result = _process_one(
                source_id=source_id,
                ticker=ticker,
                metadata=meta,
                html_content=html_content,
                pipeline=pipeline,
                db_adapter=db_adapter,
                dry_run=dry_run,
            )
            summary.results.append(result)

            if result.status == "error":
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    logger.error("Circuit breaker: %d consecutive failures — aborting", consecutive_failures)
                    summary.print_report()
                    sys.exit(2)
            else:
                consecutive_failures = 0
                ticker_count += 1

        # Checkpoint: save progress after each ticker
        _save_progress(progress_file, ticker, ticker_count)

        if _shutdown_requested:
            break

    if _shutdown_requested:
        logger.info("Graceful shutdown complete.")
        summary.print_report()
        sys.exit(0)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch ingest investor presentations from SEC 8-K filings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ticker",
        nargs="+",
        required=True,
        metavar="TICKER",
        help="One or more ticker symbols (e.g. CRM ADBE MSFT)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        metavar="N",
        help="Max presentations per ticker (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run pipeline but do not write to the database (default: True)",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Write results to the database (overrides --dry-run)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip tickers already completed per the progress file",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=10,
        metavar="N",
        help="Abort after N consecutive failures (circuit breaker, default: 10)",
    )
    return parser


def main() -> int:
    signal.signal(signal.SIGINT, _sigint_handler)

    parser = _build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --persist overrides --dry-run
    dry_run = not args.persist

    db_url = os.environ.get("DATABASE_URL")
    if not dry_run and not db_url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        print("  Set DATABASE_URL or omit --persist to use dry-run mode.", file=sys.stderr)
        return 1

    tickers = [t.upper() for t in args.ticker]

    if dry_run:
        logger.info("DRY-RUN mode — no database writes will occur")

    try:
        summary = run_ingestion(
            tickers=tickers,
            limit=args.limit,
            dry_run=dry_run,
            db_url=db_url,
            max_failures=args.max_failures,
            resume=args.resume,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary.print_report()
    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
