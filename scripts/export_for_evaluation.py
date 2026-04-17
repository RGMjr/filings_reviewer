#!/usr/bin/env python3
"""
Export extracted data for gold standard evaluation.

This script exports V2 extracted metric facts for selected filings
in a format suitable for manual review and gold standard labeling.

Usage:
    python scripts/export_for_evaluation.py --filing-ids 22299,12087,26434
    python scripts/export_for_evaluation.py --top 10  # Export top 10 by fact count
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)


def get_filing_info(db: DatabaseAdapter, filing_ids: list) -> list:
    """Get filing metadata."""
    placeholders = ",".join(["%s"] * len(filing_ids))
    query = f"""
        SELECT
            f.filing_id,
            c.company_name,
            c.cik,
            f.form_type,
            f.accession_number,
            f.sec_html_url,
            f.html_storage_path
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.filing_id IN ({placeholders})
        ORDER BY c.company_name
    """
    return db.query(query, filing_ids)


def get_v2_metric_facts(db: DatabaseAdapter, filing_id: int) -> list:
    """Get V2 extracted metric facts for a filing."""
    query = """
        SELECT
            mf.fact_id,
            mf.canonical_metric_id as metric_id,
            m.display_name as metric_name,
            mf.value as value_numeric,
            mf.value_raw as value_text,
            mf.unit,
            mf.period_start,
            mf.period_end,
            mf.period_type,
            mf.source_type,
            mf.extraction_method,
            mf.confidence,
            mf.review_status
        FROM v2_metric_facts mf
        JOIN metrics m ON mf.canonical_metric_id = m.metric_id
        WHERE mf.doc_id = %s
          AND mf.primary_fact_id IS NULL
        ORDER BY mf.canonical_metric_id, mf.period_end DESC NULLS LAST
    """
    return db.query(query, [filing_id])


def export_v2_filing_for_review(db: DatabaseAdapter, filing: dict, output_dir: Path) -> dict:
    """Export a single filing's V2 facts for manual review."""
    filing_id = filing["filing_id"]
    company = filing["company_name"].replace(" ", "_").replace("/", "-")

    company_dir = output_dir / company
    company_dir.mkdir(exist_ok=True)

    facts = get_v2_metric_facts(db, filing_id)

    metadata = {
        "filing_id": filing_id,
        "company_name": filing["company_name"],
        "cik": filing["cik"],
        "form_type": filing["form_type"],
        "accession_number": filing["accession_number"],
        "sec_url": filing["sec_html_url"],
        "local_path": filing.get("html_storage_path"),
        "export_date": datetime.now().isoformat(),
        "pipeline": "v2",
        "num_facts_extracted": len(facts),
    }

    with open(company_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    values_file = company_dir / "extracted_values.csv"
    with open(values_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "review_status",
                "notes",
                "fact_id",
                "metric_id",
                "metric_name",
                "value_numeric",
                "value_text",
                "unit",
                "period_start",
                "period_end",
                "period_type",
                "source_type",
                "extraction_method",
                "confidence",
                "v2_review_status",
            ]
        )
        for v in facts:
            writer.writerow(
                [
                    "",
                    "",
                    v["fact_id"],
                    v["metric_id"],
                    v["metric_name"],
                    v["value_numeric"],
                    v["value_text"],
                    v["unit"],
                    v["period_start"],
                    v["period_end"],
                    v["period_type"],
                    v["source_type"],
                    v["extraction_method"],
                    v["confidence"],
                    v["review_status"],
                ]
            )

    print(f"  Exported: {company}")
    print(f"    - {len(facts)} metric facts")

    return {"company": filing["company_name"], "facts": len(facts)}


def get_top_filings(db: DatabaseAdapter, limit: int) -> list:
    """Get filing IDs with most extracted V2 facts."""
    query = """
        SELECT f.filing_id
        FROM filings f
        JOIN v2_metric_facts mf ON f.filing_id = mf.filing_id
        WHERE f.processing_status = 'fetched'
        GROUP BY f.filing_id
        ORDER BY COUNT(*) DESC
        LIMIT %s
    """
    results = db.query(query, [limit])
    return [r["filing_id"] for r in results]


def main():
    parser = argparse.ArgumentParser(
        description="Export extracted data for gold standard evaluation"
    )
    parser.add_argument(
        "--filing-ids",
        type=str,
        help="Comma-separated list of filing IDs to export",
    )
    parser.add_argument(
        "--top",
        type=int,
        help="Export top N filings by extracted fact count",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/gold_standard",
        help="Output directory for exported files",
    )
    args = parser.parse_args()

    if not args.filing_ids and not args.top:
        parser.error("Must specify either --filing-ids or --top")

    # Connect to database
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)

    # Get filing IDs
    if args.filing_ids:
        filing_ids = [int(x.strip()) for x in args.filing_ids.split(",")]
    else:
        filing_ids = get_top_filings(db, args.top)

    print(f"\n{'=' * 60}")
    print("GOLD STANDARD EXPORT")
    print(f"{'=' * 60}")
    print(f"Exporting {len(filing_ids)} filings for manual review\n")

    # Get filing info
    filings = get_filing_info(db, filing_ids)

    if not filings:
        print("No filings found!")
        return

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Export each filing
    summary = []
    for filing in filings:
        result = export_v2_filing_for_review(db, filing, output_dir)
        summary.append(result)

    # Write summary
    summary_file = output_dir / "export_summary.json"
    with open(summary_file, "w") as f:
        json.dump(
            {
                "export_date": datetime.now().isoformat(),
                "num_filings": len(filings),
                "filings": summary,
                "total_facts": sum(s["facts"] for s in summary),
            },
            f,
            indent=2,
        )

    print(f"\n{'=' * 60}")
    print("EXPORT COMPLETE")
    print(f"{'=' * 60}")
    print(f"Output directory: {output_dir}")
    print(f"Total filings: {len(filings)}")
    print(f"Total facts: {sum(s['facts'] for s in summary)}")
    print("\nReview instructions:")
    print("1. Open each company's extracted_values.csv")
    print("2. Fill 'review_status' column: correct, incorrect, partial")
    print("3. Add notes for any issues found")


if __name__ == "__main__":
    main()
