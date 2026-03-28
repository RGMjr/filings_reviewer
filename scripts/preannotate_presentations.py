#!/usr/bin/env python3
"""
Pipeline Pre-Annotation Script for Investor Presentations.

Downloads investor presentations from SEC 8-K filings via SECPresentationSource,
runs them through the V2 pipeline with PipelineConfig.for_presentation(), and
writes pre-annotation CSVs for human review.

Unlike preannotate_transcript.py (which uses an LLM), this script uses the
rule-based V2 pipeline directly. Output CSVs contain one row per extracted
MetricFact with empty disposition/disposition_reason columns for human review.

Usage:
    python3 scripts/preannotate_presentations.py --ticker CRM ADBE MSFT --limit 2

Output:
    data/presentation_gold_standard/{TICKER}_{DATE}_preannotated.csv
    data/presentation_gold_standard/_file_index.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction_v2.models import MetricFact, SectionType  # noqa: E402
from src.extraction_v2.pipeline import PipelineConfig, PipelineResult, V2Pipeline  # noqa: E402
from src.infra.sec_presentation_source import SECPresentationSource  # noqa: E402

logger = logging.getLogger("preannotate_presentations")

# Output directory for gold standard CSVs
OUTPUT_DIR = ROOT / "data" / "presentation_gold_standard"

# CSV column order — must match transcript gold standard schema
CSV_FIELDNAMES = [
    "company",
    "ticker",
    "date",
    "metric_id",
    "value",
    "unit",
    "period",
    "source_type",
    "raw_text",
    "confidence",
    "section",
    "is_trap",
    "disposition",
    "disposition_reason",
]


# ---------------------------------------------------------------------------
# Section type lookup
# ---------------------------------------------------------------------------


def _build_segment_section_map(result: PipelineResult) -> dict[str, str]:
    """Build a mapping from segment_id to section_type string from pipeline result."""
    return {seg.segment_id: seg.section_type.value for seg in result.segments if seg.segment_id}


def _get_section_for_fact(fact: MetricFact, segment_map: dict[str, str]) -> str:
    """Resolve the section_type for a MetricFact via its source_locator."""
    segment_id = fact.source_locator.segment_id
    if segment_id and segment_id in segment_map:
        return segment_map[segment_id]
    return SectionType.UNKNOWN.value


# ---------------------------------------------------------------------------
# Period string formatting
# ---------------------------------------------------------------------------


def _format_period(fact: MetricFact) -> str:
    """Format period_start / period_end into a human-readable period string."""
    if fact.period_end and fact.period_start:
        # If same year/quarter, use compact form
        if fact.period_start == fact.period_end:
            return fact.period_end.isoformat()
        return f"{fact.period_start.isoformat()} to {fact.period_end.isoformat()}"
    if fact.period_end:
        return fact.period_end.isoformat()
    if fact.period_start:
        return fact.period_start.isoformat()
    return fact.period_type.value if fact.period_type else ""


# ---------------------------------------------------------------------------
# Core conversion: MetricFact → CSV row dict
# ---------------------------------------------------------------------------


def _fact_to_row(
    fact: MetricFact,
    company: str,
    ticker: str,
    date_str: str,
    segment_map: dict[str, str],
) -> dict[str, str]:
    """Convert a MetricFact to a CSV row dict."""
    # Metric ID — strip cm_ prefix if present for consistency? Keep as-is.
    metric_id = fact.canonical_metric_id

    # Value — use raw string if available, otherwise format the float
    if fact.value_raw:
        value = fact.value_raw
    elif fact.value is not None:
        # Format as integer if whole number, otherwise as float
        if fact.value == int(fact.value):
            value = str(int(fact.value))
        else:
            value = str(fact.value)
    else:
        value = ""

    # Unit
    unit = fact.unit.value if fact.unit else ""

    # Period
    period = _format_period(fact)

    # Source type — always "presentation" for this script
    source_type = "presentation"

    # Raw text from evidence pack snippet (strip HTML tags roughly)
    raw_text = ""
    if fact.evidence_pack and fact.evidence_pack.snippet_html:
        # Strip basic HTML tags for readability
        import re

        raw_text = re.sub(r"<[^>]+>", "", fact.evidence_pack.snippet_html).strip()
        raw_text = raw_text[:300]  # cap length

    # Confidence — convert 0-1 float to HIGH/MEDIUM/LOW label
    conf_val = fact.confidence
    if conf_val >= 0.8:
        confidence = "HIGH"
    elif conf_val >= 0.5:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # Section from segment lookup
    section = _get_section_for_fact(fact, segment_map)

    return {
        "company": company,
        "ticker": ticker,
        "date": date_str,
        "metric_id": metric_id,
        "value": value,
        "unit": unit,
        "period": period,
        "source_type": source_type,
        "raw_text": raw_text,
        "confidence": confidence,
        "section": section,
        "is_trap": "False",
        "disposition": "",
        "disposition_reason": "",
    }


# ---------------------------------------------------------------------------
# Single-presentation processing
# ---------------------------------------------------------------------------


def _process_presentation(
    source_id: str,
    ticker: str,
    company: str,
    date_str: str,
    html_content: str,
    pipeline: V2Pipeline,
    html_cache_path: Path | None,
) -> tuple[list[dict[str, str]], Path | None]:
    """
    Run V2 pipeline on HTML content and return (rows, html_path).

    Writes HTML to a temp file for pipeline.process(), which expects a Path.
    Returns the list of CSV row dicts and the path to the cached HTML file.
    """
    from datetime import date as date_cls

    # Parse date string for pipeline
    doc_date: date_cls | None = None
    if date_str:
        try:
            doc_date = date_cls.fromisoformat(date_str)
        except ValueError:
            pass

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(html_content)
        tmp_path = Path(tmp.name)

    try:
        result = pipeline.process(
            html_path=tmp_path,
            filing_id=-1,
            document_type="investor_presentation",
            document_date=doc_date,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    segment_map = _build_segment_section_map(result)

    rows = []
    for fact in result.facts:
        row = _fact_to_row(fact, company, ticker, date_str, segment_map)
        rows.append(row)

    return rows, html_cache_path


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_preannotation(
    tickers: list[str],
    limit: int,
) -> dict[str, str]:
    """
    Fetch and pre-annotate presentations for the given tickers.

    Returns the file_index mapping ``{TICKER}_{DATE}`` → html_path string.
    """
    source = SECPresentationSource()
    pipeline = V2Pipeline(config=PipelineConfig.for_presentation())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing file index if present
    index_path = OUTPUT_DIR / "_file_index.json"
    file_index: dict[str, str] = {}
    if index_path.exists():
        try:
            file_index = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            file_index = {}

    for ticker in tickers:
        print(f"\n[{ticker}] Listing presentations from SEC EDGAR...", file=sys.stderr)

        try:
            docs = source.list_available(ticker=ticker, limit=limit)
        except Exception as exc:
            print(f"[{ticker}] ERROR listing presentations: {exc}", file=sys.stderr)
            continue

        print(f"[{ticker}] Found {len(docs)} presentation(s)", file=sys.stderr)

        for meta in docs:
            source_id = meta.source_id
            date_str = meta.document_date.isoformat() if meta.document_date else "unknown"
            index_key = f"{ticker}_{date_str}"
            company = meta.company_name or ticker

            # Idempotency check — skip if CSV already exists
            csv_path = OUTPUT_DIR / f"{index_key}_preannotated.csv"
            if csv_path.exists():
                print(f"[{ticker}] Skipping {index_key} — CSV already exists", file=sys.stderr)
                continue

            print(f"[{ticker}] Fetching {source_id} (date={date_str})...", file=sys.stderr)

            try:
                html_content, fetched_meta = source.fetch(source_id)
                # Use enriched metadata if available
                if fetched_meta.document_date and not meta.document_date:
                    date_str = fetched_meta.document_date.isoformat()
                    index_key = f"{ticker}_{date_str}"
                if fetched_meta.company_name:
                    company = fetched_meta.company_name
            except Exception as exc:
                print(f"[{ticker}] ERROR fetching {source_id}: {exc}", file=sys.stderr)
                continue

            # Determine HTML cache path for the file index
            # SECPresentationSource caches to data/presentations/{ticker}/{accession}/{file}.html
            cik, accession, filename = SECPresentationSource._parse_source_id(source_id)
            ticker_cache_key = SECPresentationSource._cik_to_ticker_cache.get(cik, ticker)
            html_cache_path, _ = source._cache_paths(ticker_cache_key, accession, filename)

            print(f"[{ticker}] Running V2 pipeline on {index_key}...", file=sys.stderr)

            try:
                rows, _ = _process_presentation(
                    source_id=source_id,
                    ticker=ticker,
                    company=company,
                    date_str=date_str,
                    html_content=html_content,
                    pipeline=pipeline,
                    html_cache_path=html_cache_path if html_cache_path.exists() else None,
                )
            except Exception as exc:
                print(f"[{ticker}] ERROR running pipeline on {source_id}: {exc}", file=sys.stderr)
                continue

            # Write CSV
            csv_path = OUTPUT_DIR / f"{index_key}_preannotated.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

            print(f"[{ticker}] Wrote {len(rows)} rows to {csv_path}", file=sys.stderr)

            # Update file index
            file_index[index_key] = str(html_cache_path)

            # Persist file index after each presentation (safe progress)
            index_path.write_text(
                json.dumps(file_index, indent=2, sort_keys=True), encoding="utf-8"
            )

    return file_index


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-annotate investor presentations using the V2 pipeline.",
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
        default=2,
        metavar="N",
        help="Max presentations per ticker (default: 2)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    tickers = [t.upper() for t in args.ticker]

    print(
        f"Pre-annotating presentations for: {', '.join(tickers)} (limit={args.limit})",
        file=sys.stderr,
    )

    file_index = run_preannotation(tickers=tickers, limit=args.limit)

    print(
        f"\nDone. File index written to {OUTPUT_DIR / '_file_index.json'} "
        f"({len(file_index)} entries total)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
