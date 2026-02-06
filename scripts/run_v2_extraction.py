#!/usr/bin/env python3
"""
V2 Extraction Pipeline Runner.

Runs the V2 extraction pipeline on a filing and persists results to the database.

Usage:
    # By filing ID
    python scripts/run_v2_extraction.py --filing-id 1

    # By accession number
    python scripts/run_v2_extraction.py --accession 0001193125-21-186026

    # Dry run (no database persistence)
    python scripts/run_v2_extraction.py --filing-id 1 --dry-run

    # With custom confidence thresholds
    python scripts/run_v2_extraction.py --filing-id 1 --min-confidence 0.85
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.extraction_v2.persistence import V2PersistenceAdapter  # noqa: E402
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def lookup_filing(db: DatabaseAdapter, filing_id: int | None, accession: str | None) -> dict:
    """Look up filing metadata from database."""
    if filing_id:
        rows = db.query(
            """
            SELECT f.filing_id, f.accession_number, f.form_type, f.filing_date,
                   f.html_storage_path, c.company_name, c.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.filing_id = %(filing_id)s
            """,
            {"filing_id": filing_id},
        )
    elif accession:
        rows = db.query(
            """
            SELECT f.filing_id, f.accession_number, f.form_type, f.filing_date,
                   f.html_storage_path, c.company_name, c.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.accession_number = %(accession)s
            """,
            {"accession": accession},
        )
    else:
        raise ValueError("Either --filing-id or --accession is required")

    if not rows:
        raise ValueError(f"Filing not found: filing_id={filing_id}, accession={accession}")

    return rows[0]


def resolve_html_path(filing: dict) -> Path:
    """Resolve HTML file path for a filing."""
    storage_path = filing.get("html_storage_path")
    if storage_path:
        path = Path(storage_path)
        if path.exists():
            return path

    # Try gold standard directory
    company_name = filing["company_name"].replace(" ", "_")
    gold_path = PROJECT_ROOT / "data" / "gold_standard" / company_name / "filing.html"
    if gold_path.exists():
        return gold_path

    # Try data/filings directory
    accession = filing["accession_number"].replace("-", "")
    filings_path = PROJECT_ROOT / "data" / "filings" / accession / "primary.htm"
    if filings_path.exists():
        return filings_path

    raise FileNotFoundError(
        f"HTML file not found for filing {filing['filing_id']} "
        f"({filing['company_name']}). Checked: {storage_path}, {gold_path}, {filings_path}"
    )


def print_summary(result, filing: dict) -> None:
    """Print extraction summary."""
    print()
    print("=" * 70)
    print(f"V2 Extraction Summary: {filing['company_name']}")
    print(f"  Filing ID: {filing['filing_id']}")
    print(f"  Accession: {filing['accession_number']}")
    print(f"  Form Type: {filing.get('form_type', 'N/A')}")
    print("=" * 70)
    print(f"  Status:          {'SUCCESS' if result.success else 'FAILED'}")
    print(f"  Duration:        {result.total_duration_ms:,}ms")
    print(f"  Total Facts:     {result.fact_count}")
    print(f"  Auto-Accepted:   {result.auto_accepted_count}")
    print(f"  Pending Review:  {result.pending_review_count}")
    print(f"  Tables Found:    {len(result.tables)}")
    print(f"  Images Found:    {len(result.images)}")
    print(f"  Segments:        {len(result.segments)}")

    if result.facts:
        # Confidence distribution
        high = sum(1 for f in result.facts if f.confidence >= 0.85)
        medium = sum(1 for f in result.facts if 0.50 <= f.confidence < 0.85)
        low = sum(1 for f in result.facts if f.confidence < 0.50)
        print(f"\n  Confidence Distribution:")
        print(f"    High (>=0.85):  {high}")
        print(f"    Medium:         {medium}")
        print(f"    Low (<0.50):    {low}")

        # Metrics breakdown
        metric_counts: dict[str, int] = {}
        for fact in result.facts:
            metric_counts[fact.canonical_metric_id] = metric_counts.get(fact.canonical_metric_id, 0) + 1
        print(f"\n  Metrics Extracted:")
        for metric_id, count in sorted(metric_counts.items(), key=lambda x: -x[1]):
            print(f"    {metric_id}: {count}")

    if result.error_message:
        print(f"\n  Error: {result.error_message}")

    # Stage results summary
    failed_stages = [sr for sr in result.stage_results if not sr.success]
    if failed_stages:
        print(f"\n  Failed Stages:")
        for sr in failed_stages:
            print(f"    {sr.stage.value}: {sr.errors}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Run V2 extraction pipeline on a filing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--filing-id", type=int, help="Filing ID from database")
    group.add_argument("--accession", type=str, help="SEC accession number")

    parser.add_argument("--dry-run", action="store_true", help="Run pipeline but don't persist to database")
    parser.add_argument("--min-confidence", type=float, default=0.90, help="Min confidence for auto-accept (default: 0.90)")
    parser.add_argument("--no-images", action="store_true", help="Disable image extraction")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Connect to database
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    db = DatabaseAdapter(database_url)

    # Look up filing
    try:
        filing = lookup_filing(db, args.filing_id, args.accession)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve HTML path
    try:
        html_path = resolve_html_path(filing)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Processing: {filing['company_name']} (filing_id={filing['filing_id']})")
    logger.info(f"HTML path: {html_path}")

    # Configure pipeline
    config = PipelineConfig(
        enable_image_extraction=not args.no_images,
        enable_chart_extraction=not args.no_images,
        min_confidence_auto_accept=args.min_confidence,
    )

    # Run pipeline
    pipeline = V2Pipeline(config=config)
    result = pipeline.process(html_path=html_path, filing_id=filing["filing_id"])

    # Print summary
    print_summary(result, filing)

    # Persist results
    if not args.dry_run and result.success:
        logger.info("Persisting results to database...")
        adapter = V2PersistenceAdapter(db)
        persist_result = adapter.persist_pipeline_result(result, filing["filing_id"])

        if persist_result.success:
            print(f"\nPersisted to database: {persist_result.total_upserted} records")
            print(f"  Documents: {persist_result.documents_upserted}")
            print(f"  Segments:  {persist_result.segments_upserted}")
            print(f"  Tables:    {persist_result.tables_upserted}")
            print(f"  Cells:     {persist_result.cells_upserted}")
            print(f"  Images:    {persist_result.images_upserted}")
            print(f"  Facts:     {persist_result.facts_upserted}")
        else:
            print(f"\nERROR persisting results: {persist_result.errors}", file=sys.stderr)
            sys.exit(1)
    elif args.dry_run:
        print("\n(Dry run - results not persisted)")
    elif not result.success:
        print("\nPipeline failed - results not persisted", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
