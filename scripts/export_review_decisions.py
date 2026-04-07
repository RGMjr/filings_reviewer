#!/usr/bin/env python3
"""
HRV-2: Export Review Decisions Script

Exports human review decisions from the database to CSV or JSON format,
matching the gold standard schema for easy comparison and analysis.

Usage:
    # Export all accepted decisions to CSV
    python scripts/export_review_decisions.py --status accepted --output accepted.csv

    # Export all decisions to stdout
    python scripts/export_review_decisions.py --status all

    # Export decisions for specific filing
    python scripts/export_review_decisions.py --filing-id 2 --output filing_2.csv

    # Export as JSON
    python scripts/export_review_decisions.py --status all --format json --output decisions.json
"""

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Output columns matching gold standard schema
OUTPUT_COLUMNS = [
    "document_url",
    "company",
    "metric_id",
    "is_new_metric",
    "text_variant",
    "raw_value",
    "scaled_value",
    "scale_unit",
    "period_start",
    "period_end",
    "definition",
    "source_quote",
    "segment_type",
    "is_definition_only",
    "value_context",
    "detection_difficulty",
    "notes",
    # Additional columns for review context
    "candidate_id",
    "decision",
    "decision_date",
    "reviewer_id",
    "rejection_category",
    "rejection_reason",
]

V2_OUTPUT_COLUMNS = [
    "document_url",
    "company",
    "cik",
    "accession_number",
    "metric_id",
    "value",
    "value_raw",
    "unit",
    "currency",
    "period_type",
    "period_start",
    "period_end",
    "scope",
    "scope_detail",
    "source_type",
    "confidence",
    "extraction_method",
    "source_quote",
    "fact_id",
    "decision",
    "decision_date",
    "reviewer_id",
    "rejection_category",
    "rejection_reason",
    "reviewer_notes",
    "review_time_seconds",
]


def format_decision_row(
    decision: dict,
    filing_url: str,
    company_name: str,
) -> dict:
    """
    Format a decision record into the output schema.

    Args:
        decision: Decision row from database query
        filing_url: URL to SEC filing
        company_name: Company name

    Returns:
        Dict with output columns
    """
    # Extract parsed value info
    parsed_value = decision.get("parsed_value")
    parsed_unit = decision.get("parsed_unit", "")

    # Determine scale
    scale_unit = ""
    scaled_value = ""
    if parsed_value is not None:
        if parsed_value >= 1_000_000_000:
            scale_unit = "billion"
            scaled_value = f"{parsed_value / 1_000_000_000:.2f}"
        elif parsed_value >= 1_000_000:
            scale_unit = "million"
            scaled_value = f"{parsed_value / 1_000_000:.2f}"
        elif parsed_value >= 1_000:
            scale_unit = "thousand"
            scaled_value = f"{parsed_value / 1_000:.2f}"
        else:
            scaled_value = str(parsed_value)

        if parsed_unit:
            scale_unit = f"{parsed_unit} {scale_unit}".strip()

    # Get segment type
    segment_type = decision.get("segment_type", "")

    # Build context/source quote - use context_text which has the surrounding text
    source_quote = decision.get("context_text", "")

    # Get metric ID - use assigned if available, otherwise suggested
    metric_id = decision.get("assigned_metric_id") or decision.get("suggested_metric_id", "")

    return {
        "document_url": filing_url,
        "company": company_name,
        "metric_id": metric_id,
        "is_new_metric": "",  # Would need to check against known metrics
        "text_variant": decision.get("triggering_keyword", ""),
        "raw_value": decision.get("raw_number_text", ""),
        "scaled_value": scaled_value,
        "scale_unit": scale_unit,
        "period_start": "",  # Would need period extraction
        "period_end": "",
        "definition": "",  # Would need definition extraction
        "source_quote": source_quote,
        "segment_type": segment_type,
        "is_definition_only": "",
        "value_context": "table_cell" if segment_type == "table" else "inline",
        "detection_difficulty": "",
        "notes": decision.get("reviewer_notes", ""),
        # Additional context columns
        "candidate_id": decision.get("candidate_id"),
        "decision": decision.get("decision"),
        "decision_date": str(decision.get("decision_created_at", ""))[:10],
        "reviewer_id": decision.get("reviewer_id", ""),
        "rejection_category": decision.get("rejection_category", ""),
        "rejection_reason": decision.get("rejection_reason", ""),
    }


def export_decisions(
    db,  # DatabaseAdapter
    status: str | None = None,
    filing_id: int | None = None,
) -> list[dict]:
    """
    Export review decisions from database.

    Args:
        db: Database adapter
        status: Filter by decision status ('accepted', 'rejected', None for all)
        filing_id: Filter to specific filing

    Returns:
        List of formatted decision dicts
    """
    # Build query to get decisions with full context
    conditions = []
    params: dict[str, Any] = {}

    if status and status != "all":
        if status == "accepted":
            conditions.append("rd.decision = 'accept'")
        elif status == "rejected":
            conditions.append("rd.decision = 'reject'")
        elif status == "reclassified":
            conditions.append("rd.decision = 'reclassify'")

    if filing_id:
        conditions.append("rc.filing_id = %(filing_id)s")
        params["filing_id"] = filing_id

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT
            rd.decision_id,
            rd.candidate_id,
            rd.decision,
            rd.assigned_metric_id,
            rd.rejection_reason,
            rd.rejection_category,
            rd.reviewer_notes,
            rd.reviewer_id,
            rd.created_at as decision_created_at,
            rc.filing_id,
            rc.source_segment_id,
            rc.raw_number_text,
            rc.parsed_value,
            rc.parsed_unit,
            rc.context_text,
            rc.triggering_keyword,
            rc.suggested_metric_id,
            ss.segment_type,
            f.sec_html_url,
            c.company_name
        FROM review_decisions rd
        JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
        LEFT JOIN source_segments ss ON rc.source_segment_id = ss.source_segment_id
        JOIN filings f ON rc.filing_id = f.filing_id
        JOIN companies c ON rc.company_id = c.company_id
        {where_clause}
        ORDER BY c.company_name, rd.created_at
    """

    rows = db.query(query, params)

    # Format each row
    formatted = []
    for row in rows:
        formatted_row = format_decision_row(
            row,
            row.get("sec_html_url", ""),
            row.get("company_name", ""),
        )
        formatted.append(formatted_row)

    return formatted


def get_v2_decisions(
    db,
    status: str | None = None,
    filing_id: int | None = None,
) -> list[dict]:
    """Export V2 review decisions from v2_review_decisions + v2_metric_facts."""
    conditions = []
    params: dict[str, Any] = {}

    if status and status != "all":
        if status == "accepted":
            conditions.append("rd.decision = 'accept'")
        elif status == "rejected":
            conditions.append("rd.decision = 'reject'")
        elif status == "reclassified":
            conditions.append("rd.decision = 'reclassify'")

    if filing_id:
        conditions.append("mf.doc_id = %(filing_id)s")
        params["filing_id"] = filing_id

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT
            rd.decision_id,
            rd.fact_id,
            rd.decision,
            rd.assigned_metric_id,
            rd.corrected_value,
            rd.rejection_reason,
            rd.rejection_category,
            rd.reviewer_notes,
            rd.reviewer_id,
            rd.review_time_seconds,
            rd.created_at as decision_created_at,
            mf.canonical_metric_id,
            mf.value,
            mf.value_raw,
            mf.unit,
            mf.currency,
            mf.period_type,
            mf.period_start,
            mf.period_end,
            mf.scope,
            mf.scope_detail,
            mf.source_type,
            mf.confidence,
            mf.extraction_method,
            mf.evidence_pack,
            mf.doc_id as filing_id,
            f.sec_html_url,
            f.accession_number,
            c.company_name,
            c.cik
        FROM v2_review_decisions rd
        JOIN v2_metric_facts mf ON rd.fact_id = mf.fact_id
        JOIN filings f ON mf.doc_id = f.filing_id
        JOIN companies c ON f.company_id = c.company_id
        {where_clause}
        ORDER BY c.company_name, rd.created_at
    """

    rows = db.query(query, params)

    formatted = []
    for row in rows:
        evidence = row.get("evidence_pack") or {}
        if isinstance(evidence, str):
            import json as _json

            try:
                evidence = _json.loads(evidence)
            except Exception:
                evidence = {}
        source_quote = evidence.get("snippet_html") or evidence.get("context_before", "")

        metric_id = row.get("assigned_metric_id") or row.get("canonical_metric_id", "")
        formatted.append(
            {
                "document_url": row.get("sec_html_url", ""),
                "company": row.get("company_name", ""),
                "cik": row.get("cik", ""),
                "accession_number": row.get("accession_number", ""),
                "metric_id": metric_id,
                "value": row.get("value", ""),
                "value_raw": row.get("value_raw", ""),
                "unit": row.get("unit", ""),
                "currency": row.get("currency", ""),
                "period_type": row.get("period_type", ""),
                "period_start": str(row.get("period_start", "") or ""),
                "period_end": str(row.get("period_end", "") or ""),
                "scope": row.get("scope", ""),
                "scope_detail": row.get("scope_detail", ""),
                "source_type": row.get("source_type", ""),
                "confidence": row.get("confidence", ""),
                "extraction_method": row.get("extraction_method", ""),
                "source_quote": source_quote,
                "fact_id": row.get("fact_id", ""),
                "decision": row.get("decision", ""),
                "decision_date": str(row.get("decision_created_at", ""))[:10],
                "reviewer_id": row.get("reviewer_id", ""),
                "rejection_category": row.get("rejection_category", ""),
                "rejection_reason": row.get("rejection_reason", ""),
                "reviewer_notes": row.get("reviewer_notes", ""),
                "review_time_seconds": row.get("review_time_seconds", ""),
            }
        )
    return formatted


def write_csv(
    decisions: list[dict], output_path: Path | None = None, columns: list[str] | None = None
):
    """Write decisions to CSV file or stdout."""
    columns = columns or OUTPUT_COLUMNS
    if output_path:
        f = open(output_path, "w", newline="", encoding="utf-8-sig")
    else:
        f = sys.stdout

    try:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(decisions)
    finally:
        if output_path:
            f.close()


def write_json(decisions: list[dict], output_path: Path | None = None):
    """Write decisions to JSON file or stdout."""
    if output_path:
        with open(output_path, "w") as f:
            json.dump(decisions, f, indent=2, default=str)
    else:
        print(json.dumps(decisions, indent=2, default=str))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export review decisions to CSV or JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export accepted decisions to CSV
  python scripts/export_review_decisions.py --status accepted --output accepted.csv

  # Export all decisions to stdout
  python scripts/export_review_decisions.py --status all

  # Export for specific filing
  python scripts/export_review_decisions.py --filing-id 2 --output filing_2.csv

  # Export as JSON
  python scripts/export_review_decisions.py --format json --output decisions.json
        """,
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--status",
        type=str,
        choices=["accepted", "rejected", "reclassified", "all"],
        default="all",
        help="Filter by decision status (default: all)",
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        help="Filter to specific filing",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["csv", "json"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Export from V2 tables (v2_review_decisions + v2_metric_facts)",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv("DATABASE_URL")

    if not db_url:
        print(
            "Error: DATABASE_URL not set. Use --database-url or set DATABASE_URL in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    # Connect to database
    from src.infra.db import DatabaseAdapter

    db = DatabaseAdapter(db_url)

    # Export decisions
    logger.info(f"Exporting decisions (status={args.status}, filing_id={args.filing_id})...")
    if args.v2:
        decisions = get_v2_decisions(db, status=args.status, filing_id=args.filing_id)
        columns = V2_OUTPUT_COLUMNS
    else:
        decisions = export_decisions(db, status=args.status, filing_id=args.filing_id)
        columns = OUTPUT_COLUMNS

    if not decisions:
        logger.warning("No decisions found matching criteria")
        sys.exit(0)

    logger.info(f"Found {len(decisions)} decisions")

    # Write output
    output_path = Path(args.output) if args.output else None

    if args.format == "json":
        write_json(decisions, output_path)
    else:
        write_csv(decisions, output_path, columns=columns)

    if output_path:
        logger.info(f"Written to {output_path}")


if __name__ == "__main__":
    main()
