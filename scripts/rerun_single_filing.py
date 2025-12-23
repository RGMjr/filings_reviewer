#!/usr/bin/env python3
"""
Re-run extraction on a single filing to test fixes.

Usage:
    python scripts/rerun_single_filing.py --filing-id 12087
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load .env configuration and make src imports available."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


def main():
    prepare_environment()

    from src.extraction.extraction_pipeline import ExtractionPipeline
    from src.infra.db import DatabaseAdapter
    from src.llm.openai_client import OpenAIClient

    parser = argparse.ArgumentParser(
        description="Re-run extraction on a single filing"
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        help="Filing ID to re-extract",
    )
    parser.add_argument(
        "--html-path",
        type=str,
        help="Path to HTML file (creates new filing record if needed)",
    )
    parser.add_argument(
        "--company-name",
        type=str,
        default="Test Company",
        help="Company name (used with --html-path)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save to database, just print results",
    )
    args = parser.parse_args()

    if not args.filing_id and not args.html_path:
        parser.error("Must specify either --filing-id or --html-path")

    # Connect to database
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)

    # Handle --html-path option: create company/filing records if needed
    if args.html_path:
        html_path = Path(args.html_path)
        if not html_path.exists():
            print(f"HTML file not found: {html_path}")
            return

        # Check if company exists, create if not
        company_results = db.query(
            "SELECT company_id FROM companies WHERE company_name = %s",
            [args.company_name]
        )
        if company_results:
            company_id = company_results[0]["company_id"]
        else:
            # Create company record
            db.execute(
                """INSERT INTO companies (cik, company_name, ticker, industry_code)
                   VALUES (%s, %s, %s, %s)""",
                ["0000000001", args.company_name, "TEST", "7370"]
            )
            company_results = db.query(
                "SELECT company_id FROM companies WHERE company_name = %s",
                [args.company_name]
            )
            company_id = company_results[0]["company_id"]
            print(f"Created company record: {args.company_name} (ID: {company_id})")

        # Check if filing exists, create if not
        filing_results = db.query(
            "SELECT filing_id FROM filings WHERE html_storage_path = %s",
            [str(html_path)]
        )
        if filing_results:
            filing_id = filing_results[0]["filing_id"]
        else:
            # Create filing record
            db.execute(
                """INSERT INTO filings (company_id, form_type, accession_number, filing_date,
                   html_storage_path, processing_status)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [company_id, "S-1", "0000000000-00-000000", "2024-01-01",
                 str(html_path), "fetched"]
            )
            filing_results = db.query(
                "SELECT filing_id FROM filings WHERE html_storage_path = %s",
                [str(html_path)]
            )
            filing_id = filing_results[0]["filing_id"]
            print(f"Created filing record: ID {filing_id}")

        filing = {
            "filing_id": filing_id,
            "company_id": company_id,
            "company_name": args.company_name,
            "html_storage_path": str(html_path),
        }
    else:
        # Get filing info by ID
        query = """
            SELECT
                f.filing_id,
                f.company_id,
                c.company_name,
                f.html_storage_path
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.filing_id = %s
        """
        results = db.query(query, [args.filing_id])

        if not results:
            print(f"Filing {args.filing_id} not found!")
            return

        filing = results[0]
    print(f"\n{'='*60}")
    print(f"Re-extracting: {filing['company_name']}")
    print(f"Filing ID: {filing['filing_id']}")
    print(f"HTML Path: {filing['html_storage_path']}")
    print(f"{'='*60}\n")

    # Delete existing extractions for this filing
    if not args.dry_run:
        print("Deleting existing metric values...")
        db.execute(
            "DELETE FROM metric_values WHERE filing_id = %s",
            [args.filing_id]
        )
        print("Deleting existing metric definitions...")
        db.execute(
            "DELETE FROM metric_definitions WHERE filing_id = %s",
            [args.filing_id]
        )
        print("Deleting existing source segments...")
        db.execute(
            "DELETE FROM source_segments WHERE filing_id = %s",
            [args.filing_id]
        )
        print("Done.\n")

    # Verify HTML file exists
    html_path = Path(filing['html_storage_path'])
    if not html_path.exists():
        print(f"HTML file not found: {html_path}")
        return

    # Initialize LLM client
    llm_client = OpenAIClient()

    # Run extraction pipeline
    pipeline = ExtractionPipeline(db=db, llm_client=llm_client)

    print("Running extraction pipeline...")
    # Get the filing_id from the filing dict (whether passed as arg or created from HTML)
    filing_id = filing['filing_id']
    result = pipeline.process_filing(filing_id=filing_id)

    print(f"\n{'='*60}")
    print("EXTRACTION RESULTS")
    print(f"{'='*60}")

    if not result.success:
        print(f"FAILED: {result.error}")
        return

    print(f"Segments extracted: {result.num_segments}")
    print(f"Metric values: {result.num_values}")
    print(f"Definitions: {result.num_definitions}")
    print(f"Quality incidences: {result.num_incidences}")

    # Query database for metric breakdown
    if result.num_values > 0:
        print("\nMetric breakdown (from database):")
        breakdown = db.query("""
            SELECT metric_id, COUNT(*) as count
            FROM metric_values
            WHERE filing_id = %s
            GROUP BY metric_id
            ORDER BY count DESC
        """, [filing_id])
        for row in breakdown:
            print(f"  {row['metric_id']}: {row['count']}")

    if args.dry_run:
        print("\n[DRY RUN - results not saved to database]")
    else:
        print("\nResults saved to database.")


if __name__ == "__main__":
    main()
