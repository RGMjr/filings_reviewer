#!/usr/bin/env python3
"""
Check for unprocessed documents across transcript and presentation sources.

Polls HuggingFace and SEC EDGAR for available documents, then checks whether
each has already been ingested (via DB or local file proxy).

Usage:
    # Check both sources for default tickers
    python3 scripts/check_new_documents.py

    # Check only transcripts
    python3 scripts/check_new_documents.py --source transcript

    # Check specific tickers
    python3 scripts/check_new_documents.py --ticker CRM ADBE --source presentation

    # JSON output for scripting
    python3 scripts/check_new_documents.py --json

Environment variables:
    DATABASE_URL     PostgreSQL connection string (optional — uses file proxy if absent)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.infra.document_source import DocumentMetadata  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("check_new_documents")

DEFAULT_TICKERS = [
    "CRM", "ADBE", "MSFT", "INTU", "EA",
    "GDDY", "META", "GOOGL", "AMZN", "AAPL",
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DocumentStatus:
    ticker: str
    source: str         # "transcript" or "presentation"
    date: str           # ISO date string or "?"
    status: str         # "new" or "ingested"
    source_id: str = ""


@dataclass
class CheckResult:
    new: list[DocumentStatus] = field(default_factory=list)
    ingested: list[DocumentStatus] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DB / file dedup helpers
# ---------------------------------------------------------------------------


def _check_ingested_db(source_ids: list[str], db_url: str) -> set[str]:
    """Return the subset of source_ids that already exist in the DB."""
    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            with conn.cursor() as cur:
                # Check filings table using accession_number patterns
                # Transcripts: accession = "transcript:{ticker}:{date}:..."
                # Presentations: accession = "presentation:{source_id}"
                cur.execute(
                    """
                    SELECT accession_number
                    FROM filings
                    WHERE processing_status IN ('complete', 'processing')
                    """
                )
                rows = cur.fetchall()
                accessions: set[str] = {r["accession_number"] for r in rows}

                # Also check v2_documents for completed processing
                cur.execute(
                    """
                    SELECT f.accession_number
                    FROM v2_documents vd
                    JOIN filings f ON vd.filing_id = f.filing_id
                    WHERE vd.status = 'complete'
                    """
                )
                rows = cur.fetchall()
                accessions.update(r["accession_number"] for r in rows)

            ingested_source_ids: set[str] = set()
            for sid in source_ids:
                # Presentation source_ids are stored as "presentation:{source_id}"
                if f"presentation:{sid}" in accessions:
                    ingested_source_ids.add(sid)
                # Transcript source_ids don't map 1:1 to accessions, so we
                # mark as ingested only if we find an exact match
                elif sid in accessions:
                    ingested_source_ids.add(sid)
            return ingested_source_ids

        finally:
            conn.close()

    except Exception as exc:
        logger.warning("DB check failed: %s", exc)
        return set()


def _check_ingested_files(
    source_id: str,
    source_type: str,
    ticker: str,
    meta: DocumentMetadata,
) -> bool:
    """File-proxy dedup: check if annotation CSV exists for this document."""
    if source_type == "transcript":
        gold_dir = ROOT / "data" / "transcript_gold_standard"
        date_str = meta.document_date.isoformat() if meta.document_date else ""
        # Look for any CSV with ticker + date in the name
        if date_str:
            pattern = f"{ticker}*{date_str}*"
        else:
            pattern = f"{ticker}*"
        return any(gold_dir.glob(pattern))

    elif source_type == "presentation":
        gold_dir = ROOT / "data" / "presentation_gold_standard"
        date_str = meta.document_date.isoformat() if meta.document_date else ""
        if date_str:
            pattern = f"{ticker}*{date_str}*"
        else:
            pattern = f"{ticker}*"
        return any(gold_dir.glob(pattern))

    return False


# ---------------------------------------------------------------------------
# Main check logic
# ---------------------------------------------------------------------------


def check_documents(
    tickers: list[str],
    source_filter: str | None,
    db_url: str | None,
) -> CheckResult:
    result = CheckResult()

    for ticker in tickers:
        # --- Transcripts ---
        if source_filter in (None, "transcript"):
            try:
                from src.infra.huggingface_source import HuggingFaceTranscriptSource
                hf_source = HuggingFaceTranscriptSource()
                docs = hf_source.list_available(ticker=ticker)

                for meta in docs:
                    date_str = meta.document_date.isoformat() if meta.document_date else "?"
                    is_ingested = False

                    if db_url:
                        ingested_set = _check_ingested_db([meta.source_id], db_url)
                        is_ingested = meta.source_id in ingested_set
                    else:
                        is_ingested = _check_ingested_files(
                            meta.source_id, "transcript", ticker, meta
                        )

                    status = "ingested" if is_ingested else "new"
                    ds = DocumentStatus(
                        ticker=ticker,
                        source="transcript",
                        date=date_str,
                        status=status,
                        source_id=meta.source_id,
                    )
                    if is_ingested:
                        result.ingested.append(ds)
                    else:
                        result.new.append(ds)

            except Exception as exc:
                logger.error("Error checking transcripts for %s: %s", ticker, exc)
                result.errors.append({"ticker": ticker, "source": "transcript", "error": str(exc)})

        # --- Presentations ---
        if source_filter in (None, "presentation"):
            try:
                from src.infra.sec_presentation_source import SECPresentationSource
                sec_source = SECPresentationSource()
                docs = sec_source.list_available(ticker=ticker)

                for meta in docs:
                    date_str = meta.document_date.isoformat() if meta.document_date else "?"
                    is_ingested = False

                    if db_url:
                        ingested_set = _check_ingested_db([meta.source_id], db_url)
                        is_ingested = meta.source_id in ingested_set
                    else:
                        is_ingested = _check_ingested_files(
                            meta.source_id, "presentation", ticker, meta
                        )

                    status = "ingested" if is_ingested else "new"
                    ds = DocumentStatus(
                        ticker=ticker,
                        source="presentation",
                        date=date_str,
                        status=status,
                        source_id=meta.source_id,
                    )
                    if is_ingested:
                        result.ingested.append(ds)
                    else:
                        result.new.append(ds)

            except Exception as exc:
                logger.error("Error checking presentations for %s: %s", ticker, exc)
                result.errors.append({"ticker": ticker, "source": "presentation", "error": str(exc)})

    return result


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _print_table(result: CheckResult) -> None:
    all_docs = [
        *[(d, "new") for d in result.new],
        *[(d, "ingested") for d in result.ingested],
    ]
    # Sort by ticker, then source, then date
    all_docs.sort(key=lambda x: (x[0].ticker, x[0].source, x[0].date))

    if all_docs:
        print(f"{'TICKER':<8}  {'SOURCE':<14}  {'DATE':<12}  STATUS")
        print("-" * 55)
        for doc, _ in all_docs:
            print(f"{doc.ticker:<8}  {doc.source:<14}  {doc.date:<12}  {doc.status}")
        print()

    if result.errors:
        print("Errors:")
        for err in result.errors:
            print(f"  {err.get('ticker', '?')}  {err.get('source', '?')}  {err.get('error', '?')}")
        print()

    n_new = len(result.new)
    n_ingested = len(result.ingested)
    print(f"Summary: {n_new} new, {n_ingested} ingested", end="")
    if result.errors:
        print(f", {len(result.errors)} errors", end="")
    print()


def _print_json(result: CheckResult) -> None:
    output: dict[str, Any] = {
        "new": [
            {
                "ticker": d.ticker,
                "source": d.source,
                "date": d.date,
                "source_id": d.source_id,
            }
            for d in result.new
        ],
        "ingested": [
            {
                "ticker": d.ticker,
                "source": d.source,
                "date": d.date,
                "source_id": d.source_id,
            }
            for d in result.ingested
        ],
        "errors": result.errors,
    }
    print(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check for unprocessed documents across transcript and presentation sources.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source",
        choices=["transcript", "presentation"],
        default=None,
        help="Limit check to one source type (default: both)",
    )
    parser.add_argument(
        "--ticker",
        nargs="+",
        default=None,
        metavar="TICKER",
        help="One or more ticker symbols (default: built-in list of 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    tickers = [t.upper() for t in args.ticker] if args.ticker else DEFAULT_TICKERS
    db_url = os.environ.get("DATABASE_URL")

    result = check_documents(
        tickers=tickers,
        source_filter=args.source,
        db_url=db_url,
    )

    if args.json_output:
        _print_json(result)
    else:
        _print_table(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
