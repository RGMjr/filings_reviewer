#!/usr/bin/env python3
"""
Pipeline Pre-Annotation Script for Investor Presentations and SEC Filings.

Downloads investor presentations from SEC 8-K filings via SECPresentationSource,
or fetches registration/periodic filings (S-1, F-1, 10-K, 10-Q) via SECClient,
runs them through the V2 pipeline, and writes pre-annotation CSVs for human review.

Also supports local PDF/HTML files via --files for offline annotation workflows.

Unlike preannotate_transcript.py (which uses an LLM), this script uses the
rule-based V2 pipeline directly. Output CSVs contain one row per extracted
MetricFact with empty disposition/disposition_reason columns for human review.

Usage:
    # 8-K investor presentations (default)
    python3 scripts/preannotate_presentations.py --ticker CRM ADBE MSFT --limit 2

    # S-1 registration filing
    python3 scripts/preannotate_presentations.py --ticker DDOG --filing-type S-1

    # Local PDF or HTML files
    python3 scripts/preannotate_presentations.py --files filing.pdf --ticker DDOG --date 2019-09-19

Output:
    data/presentation_gold_standard/{TICKER}_{DATE}_preannotated.csv         (8-K)
    data/presentation_gold_standard/{TICKER}_{FORM}_{DATE}_preannotated.csv  (non-8-K)
    data/presentation_gold_standard/_file_index.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env before any src imports that read environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from src.extraction_v2.models import MetricFact, SectionType  # noqa: E402
from src.extraction_v2.pipeline import PipelineConfig, PipelineResult, V2Pipeline  # noqa: E402
from src.infra.sec_presentation_source import SECPresentationSource  # noqa: E402

logger = logging.getLogger("preannotate_presentations")

# Output directory for gold standard CSVs
OUTPUT_DIR = ROOT / "data" / "presentation_gold_standard"

# Non-8-K filing types supported via the registration/periodic filing path
_SEC_FILING_TYPES = {"S-1", "F-1", "10-K", "10-Q"}

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
    source_type: str = "presentation",
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

    # Raw text from evidence pack snippet (strip HTML tags roughly)
    raw_text = ""
    if fact.evidence_pack and fact.evidence_pack.snippet_html:
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
        "source_type": fact.source_type.value if fact.source_type else source_type,
        "raw_text": raw_text,
        "confidence": confidence,
        "section": section,
        "is_trap": "False",
        "disposition": "",
        "disposition_reason": "",
    }


# ---------------------------------------------------------------------------
# Image candidate serialization
# ---------------------------------------------------------------------------


def _serialize_images(
    images: list,  # list[ImageAsset]
    cik: str,
    accession_number: str,
) -> list[dict]:
    """Serialize ImageAsset list to JSON-serializable dicts with EDGAR image URLs."""
    cik_stripped = cik.lstrip("0") or "0"
    accession_clean = accession_number.replace("-", "")
    base_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accession_clean}/"
        if cik and accession_number
        else ""
    )

    result = []
    for img in images:
        if img.relevance_score <= 0.0:
            continue
        result.append({
            "img_id": img.img_id,
            "filename": img.filename,
            "image_url": base_url + img.filename if base_url and img.filename else "",
            "classification": img.classification.value if img.classification else "unknown",
            "relevance_score": img.relevance_score,
            "nearby_text": img.nearby_text or "",
            "section_type": img.section_type.value if img.section_type else "unknown",
            "ocr_text": img.ocr_text or "",
            "dom_locator": img.dom_locator or "",
            "width": img.width,
            "height": img.height,
        })
    return result


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
    document_type: str = "investor_presentation",
    source_type: str = "presentation",
    cik: str = "",
    accession_number: str = "",
) -> tuple[list[dict[str, str]], Path | None, list[dict]]:
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
            cik=cik,
            accession_number=accession_number,
            document_type=document_type,
            document_date=doc_date,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    segment_map = _build_segment_section_map(result)

    rows = []
    for fact in result.facts:
        row = _fact_to_row(fact, company, ticker, date_str, segment_map, source_type=source_type)
        rows.append(row)

    image_candidates = _serialize_images(result.images, cik, accession_number)

    return rows, html_cache_path, image_candidates


# ---------------------------------------------------------------------------
# Non-8-K SEC filing fetch helper
# ---------------------------------------------------------------------------


def _fetch_sec_filing_html(
    source: SECPresentationSource,
    ticker: str,
    filing_type: str,
) -> tuple[str, str, str, str, str, str] | None:
    """
    Fetch HTML for a non-8-K SEC filing (S-1, F-1, 10-K, 10-Q).

    Returns (html_content, company_name, date_str, html_cache_path_str, cik, accession_number)
    or None on failure. The HTML is cached at source.cache_dir / ticker / accession / filename.
    """
    cik, company_name = source._resolve_ticker(ticker)
    if cik is None:
        print(f"[{ticker}] ERROR: could not resolve ticker to CIK", file=sys.stderr)
        return None

    company = company_name or ticker

    meta = source._sec_client.get_latest_registration_filing(
        cik, form_types=[filing_type, f"{filing_type}/A"]
    )
    if meta is None:
        print(
            f"[{ticker}] ERROR: no {filing_type} filing found in EDGAR", file=sys.stderr
        )
        return None

    filename = meta.primary_doc_url.split("/")[-1]
    html_cache_path, _ = source._cache_paths(ticker.upper(), meta.accession_number, filename)
    date_str = meta.filing_date[:10] if meta.filing_date else "unknown"

    # Return cached HTML if available
    if html_cache_path.exists():
        logger.debug("Cache hit for %s/%s/%s", ticker, meta.accession_number, filename)
        html_content = html_cache_path.read_text(encoding="utf-8")
        return html_content, company, date_str, str(html_cache_path), cik, meta.accession_number

    # Download from EDGAR
    print(
        f"[{ticker}] Downloading {filing_type} ({meta.accession_number}/{filename})...",
        file=sys.stderr,
    )
    html_content = source._download_htm(meta.cik, meta.accession_number, filename)
    if html_content is None:
        print(f"[{ticker}] ERROR: could not download HTML for {filing_type}", file=sys.stderr)
        return None

    # Cache the HTML
    html_cache_path.parent.mkdir(parents=True, exist_ok=True)
    html_cache_path.write_text(html_content, encoding="utf-8")
    logger.debug("Cached filing HTML to %s", html_cache_path)

    return html_content, company, date_str, str(html_cache_path), cik, meta.accession_number


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_preannotation(
    tickers: list[str],
    limit: int,
    filing_type: str = "8-K",
    files: list[str] | None = None,
    date: str | None = None,
) -> dict[str, str]:
    """
    Fetch and pre-annotate presentations or filings for the given tickers.

    Returns the file_index mapping key → html_path string.

    Key format:
        8-K:      ``{TICKER}_{DATE}``
        non-8-K:  ``{TICKER}_{FORM}_{DATE}``
        --files:  ``{TICKER}_{FORM}_{DATE}``
    """
    source = SECPresentationSource()

    # Choose pipeline config based on filing type
    if filing_type == "8-K":
        pipeline = V2Pipeline(config=PipelineConfig.for_presentation())
        document_type = "investor_presentation"
        csv_source_type = "presentation"
    else:
        pipeline = V2Pipeline(config=PipelineConfig())
        document_type = "sec_filing"
        csv_source_type = "filing"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing file index if present
    index_path = OUTPUT_DIR / "_file_index.json"
    file_index: dict[str, str] = {}
    if index_path.exists():
        try:
            file_index = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            file_index = {}

    url_index_path = OUTPUT_DIR / "_url_index.json"
    url_index: dict[str, str] = {}
    if url_index_path.exists():
        try:
            url_index = json.loads(url_index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            url_index = {}

    # ------------------------------------------------------------------
    # --files path: process local files for a single ticker
    # ------------------------------------------------------------------
    if files:
        # Caller has already validated that tickers has exactly one entry
        # and date is set.
        ticker = tickers[0].upper()
        date_str = date or "unknown"
        index_key = f"{ticker}_{filing_type}_{date_str}"
        csv_path = OUTPUT_DIR / f"{index_key}_preannotated.csv"

        if csv_path.exists():
            print(f"[{ticker}] Skipping {index_key} — CSV already exists", file=sys.stderr)
            return file_index

        all_rows: list[dict[str, str]] = []
        last_cache_path: str | None = None

        for file_path_str in files:
            file_path = Path(file_path_str)
            print(f"[{ticker}] Processing local file: {file_path}", file=sys.stderr)

            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                from src.extraction_v2.presentation_converter import (
                    convert_presentation_to_html,
                )

                html_str, _pdf_meta = convert_presentation_to_html(pdf_path=file_path)
            elif suffix in (".htm", ".html"):
                html_str = file_path.read_text(encoding="utf-8")
            else:
                print(
                    f"[{ticker}] Skipping unsupported file type: {file_path.suffix}",
                    file=sys.stderr,
                )
                continue

            # Cache HTML under source.cache_dir/local/
            cache_stem = f"{ticker}_{date_str}_{file_path.stem}.html"
            local_cache_path = source.cache_dir / "local" / cache_stem
            if not local_cache_path.exists():
                local_cache_path.parent.mkdir(parents=True, exist_ok=True)
                local_cache_path.write_text(html_str, encoding="utf-8")
                logger.debug("Cached local file HTML to %s", local_cache_path)

            last_cache_path = str(local_cache_path)

            try:
                rows, _, _images = _process_presentation(
                    source_id=str(file_path),
                    ticker=ticker,
                    company=ticker,
                    date_str=date_str,
                    html_content=html_str,
                    pipeline=pipeline,
                    html_cache_path=local_cache_path,
                    document_type=document_type,
                    source_type=csv_source_type,
                )
                all_rows.extend(rows)
            except Exception as exc:
                print(
                    f"[{ticker}] ERROR running pipeline on {file_path}: {exc}", file=sys.stderr
                )
                continue

        # Write combined CSV for all local files
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)

        print(f"[{ticker}] Wrote {len(all_rows)} rows to {csv_path}", file=sys.stderr)

        if last_cache_path:
            file_index[index_key] = last_cache_path
            index_path.write_text(
                json.dumps(file_index, indent=2, sort_keys=True), encoding="utf-8"
            )

        return file_index

    # ------------------------------------------------------------------
    # Non-8-K SEC filing path
    # ------------------------------------------------------------------
    if filing_type != "8-K":
        for ticker in tickers:
            ticker_upper = ticker.upper()
            print(
                f"\n[{ticker_upper}] Fetching {filing_type} from SEC EDGAR...", file=sys.stderr
            )

            result = _fetch_sec_filing_html(source, ticker_upper, filing_type)
            if result is None:
                continue

            html_content, company, date_str, html_cache_path_str, cik, accession = result
            index_key = f"{ticker_upper}_{filing_type}_{date_str}"
            filing_filename = Path(html_cache_path_str).name.replace(".html", "")
            cik_stripped = cik.lstrip("0") or "0"
            accession_clean = accession.replace("-", "")
            edgar_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}"
                f"/{accession_clean}/{filing_filename}"
            )

            # Idempotency check
            csv_path = OUTPUT_DIR / f"{index_key}_preannotated.csv"
            if csv_path.exists():
                print(
                    f"[{ticker_upper}] Skipping {index_key} — CSV already exists",
                    file=sys.stderr,
                )
                continue

            print(
                f"[{ticker_upper}] Running V2 pipeline on {index_key}...", file=sys.stderr
            )

            try:
                rows, _, image_candidates = _process_presentation(
                    source_id=index_key,
                    ticker=ticker_upper,
                    company=company,
                    date_str=date_str,
                    html_content=html_content,
                    pipeline=pipeline,
                    html_cache_path=Path(html_cache_path_str),
                    document_type=document_type,
                    source_type=csv_source_type,
                    cik=cik,
                    accession_number=accession,
                )
            except Exception as exc:
                print(
                    f"[{ticker_upper}] ERROR running pipeline on {index_key}: {exc}",
                    file=sys.stderr,
                )
                continue

            # Write CSV
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)

            print(f"[{ticker_upper}] Wrote {len(rows)} rows to {csv_path}", file=sys.stderr)

            file_index[index_key] = html_cache_path_str
            index_path.write_text(
                json.dumps(file_index, indent=2, sort_keys=True), encoding="utf-8"
            )

            url_index[index_key] = edgar_url
            url_index_path.write_text(
                json.dumps(url_index, indent=2, sort_keys=True), encoding="utf-8"
            )

            if image_candidates:
                img_json_path = OUTPUT_DIR / f"{index_key}_image_candidates.json"
                img_json_path.write_text(
                    json.dumps(image_candidates, indent=2), encoding="utf-8"
                )

        return file_index

    # ------------------------------------------------------------------
    # 8-K path (existing behavior — unchanged)
    # ------------------------------------------------------------------
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
            ticker_cache_key = source._cik_to_ticker_cache.get(cik, ticker)
            html_cache_path, _ = source._cache_paths(ticker_cache_key, accession, filename)

            print(f"[{ticker}] Running V2 pipeline on {index_key}...", file=sys.stderr)

            try:
                rows, _, image_candidates = _process_presentation(
                    source_id=source_id,
                    ticker=ticker,
                    company=company,
                    date_str=date_str,
                    html_content=html_content,
                    pipeline=pipeline,
                    html_cache_path=html_cache_path if html_cache_path.exists() else None,
                    document_type=document_type,
                    source_type=csv_source_type,
                    cik=cik,
                    accession_number=accession,
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

            # Update URL index
            accession_clean = accession.replace("-", "")
            cik_stripped = cik.lstrip("0") or "0"
            url_index[index_key] = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accession_clean}/{filename}"
            )
            url_index_path.write_text(
                json.dumps(url_index, indent=2, sort_keys=True), encoding="utf-8"
            )

            if image_candidates:
                img_json_path = OUTPUT_DIR / f"{index_key}_image_candidates.json"
                img_json_path.write_text(
                    json.dumps(image_candidates, indent=2), encoding="utf-8"
                )

    return file_index


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-annotate investor presentations and SEC filings using the V2 pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ticker",
        nargs="+",
        required=True,
        metavar="TICKER",
        help="One or more ticker symbols (e.g. CRM ADBE MSFT). "
        "When --files is used, exactly one ticker is required.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        metavar="N",
        help="Max presentations per ticker (default: 2; ignored for non-8-K filing types)",
    )
    parser.add_argument(
        "--filing-type",
        choices=["8-K", "S-1", "F-1", "10-K", "10-Q"],
        default="8-K",
        metavar="TYPE",
        dest="filing_type",
        help="Filing type to fetch: 8-K (default), S-1, F-1, 10-K, or 10-Q",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        metavar="PATH",
        help="Local PDF or HTML files to process. "
        "Requires --ticker (single value) and --date.",
    )
    parser.add_argument(
        "--date",
        metavar="DATE",
        help="Filing date (YYYY-MM-DD). Required when --files is used.",
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

    # Validate --files constraints
    if args.files:
        if len(args.ticker) != 1:
            parser.error("--files requires exactly one --ticker value")
        if not args.date:
            parser.error("--files requires --date (e.g. --date 2019-09-19)")

    tickers = [t.upper() for t in args.ticker]

    if args.files:
        print(
            f"Pre-annotating local files for {tickers[0]} "
            f"(filing-type={args.filing_type}, date={args.date})",
            file=sys.stderr,
        )
    else:
        print(
            f"Pre-annotating {args.filing_type} filings for: {', '.join(tickers)} "
            f"(limit={args.limit})",
            file=sys.stderr,
        )

    file_index = run_preannotation(
        tickers=tickers,
        limit=args.limit,
        filing_type=args.filing_type,
        files=args.files,
        date=args.date,
    )

    print(
        f"\nDone. File index written to {OUTPUT_DIR / '_file_index.json'} "
        f"({len(file_index)} entries total)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
