#!/usr/bin/env python3
"""
Export extracted data for gold standard evaluation.

This script exports extracted metric values and definitions for selected filings
in a format suitable for manual review and gold standard labeling.

Usage:
    python scripts/export_for_evaluation.py --filing-ids 22299,12087,26434
    python scripts/export_for_evaluation.py --top 10  # Export top 10 by value count
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


def get_metric_values(db: DatabaseAdapter, filing_id: int) -> list:
    """Get all extracted metric values for a filing."""
    query = """
        SELECT
            mv.metric_value_id,
            mv.metric_id,
            m.display_name as metric_name,
            mv.value_numeric,
            mv.value_text,
            mv.unit,
            mv.period_start,
            mv.period_end,
            mv.period_type,
            mv.source_type,
            mv.extraction_method,
            ss.raw_text as source_text,
            ss.section_heading
        FROM metric_values mv
        JOIN metrics m ON mv.metric_id = m.metric_id
        LEFT JOIN source_segments ss ON mv.source_segment_id = ss.source_segment_id
        WHERE mv.filing_id = %s
        ORDER BY mv.metric_id, mv.period_end DESC NULLS LAST
    """
    return db.query(query, [filing_id])


def get_definitions(db: DatabaseAdapter, filing_id: int) -> list:
    """Get all extracted definitions for a filing."""
    query = """
        SELECT
            md.metric_definition_id,
            md.metric_id,
            m.display_name as metric_name,
            md.definition_text_normalized,
            md.methodology_text_normalized,
            md.definition_raw_text,
            ss.raw_text as source_text,
            ss.section_heading
        FROM metric_definitions md
        JOIN metrics m ON md.metric_id = m.metric_id
        LEFT JOIN source_segments ss ON md.definition_segment_id = ss.source_segment_id
        WHERE md.filing_id = %s
        ORDER BY md.metric_id
    """
    return db.query(query, [filing_id])


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


def export_filing_for_review(db: DatabaseAdapter, filing: dict, output_dir: Path):
    """Export a single filing's data for manual review."""
    filing_id = filing["filing_id"]
    company = filing["company_name"].replace(" ", "_").replace("/", "-")

    # Create company subdirectory
    company_dir = output_dir / company
    company_dir.mkdir(exist_ok=True)

    # Get extracted data
    values = get_metric_values(db, filing_id)
    definitions = get_definitions(db, filing_id)

    # Export filing metadata
    metadata = {
        "filing_id": filing_id,
        "company_name": filing["company_name"],
        "cik": filing["cik"],
        "form_type": filing["form_type"],
        "accession_number": filing["accession_number"],
        "sec_url": filing["sec_html_url"],
        "local_path": filing["html_storage_path"],
        "export_date": datetime.now().isoformat(),
        "num_values_extracted": len(values),
        "num_definitions_extracted": len(definitions),
    }

    with open(company_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    # Export metric values for review
    values_file = company_dir / "extracted_values.csv"
    with open(values_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "review_status",  # Human fills: correct, incorrect, partial, missed
                "notes",  # Human notes
                "metric_value_id",
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
                "section_heading",
                "source_text_preview",  # First 500 chars
            ]
        )
        for v in values:
            source_preview = (v["source_text"] or "")[:500]
            writer.writerow(
                [
                    "",  # review_status - to be filled
                    "",  # notes - to be filled
                    v["metric_value_id"],
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
                    v["section_heading"],
                    source_preview,
                ]
            )

    # Export definitions for review
    defs_file = company_dir / "extracted_definitions.csv"
    with open(defs_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "review_status",  # Human fills: correct, incorrect, partial, missed
                "notes",
                "metric_definition_id",
                "metric_id",
                "metric_name",
                "definition_normalized",
                "methodology_normalized",
                "section_heading",
                "source_text_preview",
            ]
        )
        for d in definitions:
            source_preview = (d["source_text"] or d["definition_raw_text"] or "")[:500]
            writer.writerow(
                [
                    "",
                    "",
                    d["metric_definition_id"],
                    d["metric_id"],
                    d["metric_name"],
                    d["definition_text_normalized"],
                    d["methodology_text_normalized"],
                    d["section_heading"],
                    source_preview,
                ]
            )

    # Create review template for missed items
    missed_file = company_dir / "missed_items_template.csv"
    with open(missed_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "item_type",  # value or definition
                "metric_id",  # e.g., DAU, MAU, ARR
                "metric_name",
                "value_numeric",  # for values
                "value_text",  # for values or definition text
                "period",  # e.g., FY2023, Q1 2024
                "source_location",  # section or page reference
                "notes",
            ]
        )
        # Leave empty for human to fill

    print(f"  Exported: {company}")
    print(f"    - {len(values)} metric values")
    print(f"    - {len(definitions)} definitions")

    return {
        "company": filing["company_name"],
        "values": len(values),
        "definitions": len(definitions),
    }


def export_v2_filing_for_review(db: DatabaseAdapter, filing: dict, output_dir: Path):
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

    logger.info(f"  Exported {len(facts)} V2 facts to {values_file}")


def get_top_filings(db: DatabaseAdapter, limit: int) -> list:
    """Get filing IDs with most extracted values."""
    query = """
        SELECT f.filing_id
        FROM filings f
        JOIN metric_values mv ON f.filing_id = mv.filing_id
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
        help="Export top N filings by extracted value count",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/gold_standard",
        help="Output directory for exported files",
    )
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Export from V2 pipeline tables (v2_metric_facts)",
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
        if args.v2:
            export_v2_filing_for_review(db, filing, output_dir)
        else:
            result = export_filing_for_review(db, filing, output_dir)
            summary.append(result)

    # Write summary
    summary_file = output_dir / "export_summary.json"
    with open(summary_file, "w") as f:
        json.dump(
            {
                "export_date": datetime.now().isoformat(),
                "num_filings": len(filings),
                "filings": summary,
                "total_values": sum(s["values"] for s in summary),
                "total_definitions": sum(s["definitions"] for s in summary),
            },
            f,
            indent=2,
        )

    print(f"\n{'=' * 60}")
    print("EXPORT COMPLETE")
    print(f"{'=' * 60}")
    print(f"Output directory: {output_dir}")
    print(f"Total filings: {len(filings)}")
    print(f"Total values: {sum(s['values'] for s in summary)}")
    print(f"Total definitions: {sum(s['definitions'] for s in summary)}")
    print("\nReview instructions:")
    print("1. Open each company's extracted_values.csv")
    print("2. Fill 'review_status' column: correct, incorrect, partial")
    print("3. Add notes for any issues found")
    print("4. Add missed items to missed_items_template.csv")


if __name__ == "__main__":
    main()
