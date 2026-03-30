#!/usr/bin/env python3
"""
Export Image Review Decisions Script

Exports human image review decisions from the database to CSV or JSON format.

Usage:
    # Export all relevant decisions to CSV
    python3 scripts/export_image_decisions.py --status relevant --output relevant.csv

    # Export all decisions to stdout
    python3 scripts/export_image_decisions.py --status all

    # Export decisions for specific filing
    python3 scripts/export_image_decisions.py --filing-id 2 --output filing_2.csv

    # Export by detection tier
    python3 scripts/export_image_decisions.py --detection-tier tier_1_cohort

    # Export as JSON
    python3 scripts/export_image_decisions.py --format json --output decisions.json
"""

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "image_candidate_id",
    "filing_id",
    "company",
    "accession_number",
    "image_src",
    "image_url",
    "image_width",
    "image_height",
    "detection_tier",
    "cohort_confidence",
    "decision",
    "chart_type",
    "rejection_reason",
    "reviewer_notes",
    "review_time_seconds",
    "decision_date",
]


def format_decision_row(decision: dict, company_name: str) -> dict:
    """
    Format a decision record into the output schema.

    Args:
        decision: Decision row from database query
        company_name: Company name

    Returns:
        Dict with output columns
    """
    return {
        "image_candidate_id": decision.get("image_candidate_id"),
        "filing_id": decision.get("filing_id"),
        "company": company_name,
        "accession_number": decision.get("accession_number", ""),
        "image_src": decision.get("image_src", ""),
        "image_url": decision.get("image_url", ""),
        "image_width": decision.get("image_width", ""),
        "image_height": decision.get("image_height", ""),
        "detection_tier": decision.get("detection_tier", ""),
        "cohort_confidence": decision.get("cohort_confidence", ""),
        "decision": decision.get("decision", ""),
        "chart_type": decision.get("chart_type", ""),
        "rejection_reason": decision.get("rejection_reason", ""),
        "reviewer_notes": decision.get("reviewer_notes", ""),
        "review_time_seconds": decision.get("review_time_seconds", ""),
        "decision_date": str(decision.get("created_at", ""))[:10],
    }


def export_decisions(
    db,  # DatabaseAdapter
    status: str | None = None,
    filing_id: int | None = None,
    detection_tier: str | None = None,
) -> list[dict]:
    """
    Export image review decisions from database.

    Args:
        db: Database adapter
        status: Filter by decision status ('relevant', 'not_relevant', None/'all' for all)
        filing_id: Filter to specific filing
        detection_tier: Filter by detection tier

    Returns:
        List of formatted decision dicts
    """
    conditions = []
    params: dict[str, Any] = {}

    if status and status != "all":
        if status == "relevant":
            conditions.append("ird.decision = 'relevant'")
        elif status == "not_relevant":
            conditions.append("ird.decision = 'not_relevant'")

    if filing_id:
        conditions.append("irc.filing_id = %(filing_id)s")
        params["filing_id"] = filing_id

    if detection_tier:
        conditions.append("irc.detection_tier = %(detection_tier)s")
        params["detection_tier"] = detection_tier

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT
            ird.image_decision_id,
            ird.image_candidate_id,
            ird.decision,
            ird.chart_type,
            ird.rejection_reason,
            ird.reviewer_notes,
            ird.reviewer_id,
            ird.review_time_seconds,
            ird.created_at,
            irc.filing_id,
            irc.image_src,
            irc.image_url,
            irc.image_width,
            irc.image_height,
            irc.detection_tier,
            irc.cohort_confidence,
            f.accession_number,
            c.company_name
        FROM image_review_decisions ird
        JOIN image_review_candidates irc ON ird.image_candidate_id = irc.image_candidate_id
        JOIN filings f ON irc.filing_id = f.filing_id
        JOIN companies c ON irc.company_id = c.company_id
        {where_clause}
        ORDER BY c.company_name, ird.created_at
    """

    rows = db.query(query, params)

    formatted = []
    for row in rows:
        formatted_row = format_decision_row(row, row.get("company_name", ""))
        formatted.append(formatted_row)

    return formatted


def write_csv(decisions: list[dict], output_path: Path | None = None) -> None:
    """Write decisions to CSV file or stdout."""
    if output_path:
        f = open(output_path, "w", newline="", encoding="utf-8-sig")
    else:
        f = sys.stdout

    try:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(decisions)
    finally:
        if output_path:
            f.close()


def write_json(decisions: list[dict], output_path: Path | None = None) -> None:
    """Write decisions to JSON file or stdout."""
    if output_path:
        with open(output_path, "w") as f:
            json.dump(decisions, f, indent=2, default=str)
    else:
        print(json.dumps(decisions, indent=2, default=str))


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export image review decisions to CSV or JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export relevant decisions to CSV
  python3 scripts/export_image_decisions.py --status relevant --output relevant.csv

  # Export all decisions to stdout
  python3 scripts/export_image_decisions.py --status all

  # Export for specific filing
  python3 scripts/export_image_decisions.py --filing-id 2 --output filing_2.csv

  # Export by detection tier
  python3 scripts/export_image_decisions.py --detection-tier tier_1_cohort

  # Export as JSON
  python3 scripts/export_image_decisions.py --format json --output decisions.json
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
        choices=["relevant", "not_relevant", "all"],
        default="all",
        help="Filter by decision status (default: all)",
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        help="Filter to specific filing",
    )
    parser.add_argument(
        "--detection-tier",
        type=str,
        choices=["tier_1_cohort", "tier_2_large", "tier_3_all", "seed_list"],
        help="Filter by detection tier",
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
    logger.info(
        f"Exporting image decisions (status={args.status}, "
        f"filing_id={args.filing_id}, detection_tier={args.detection_tier})..."
    )
    decisions = export_decisions(db, args.status, args.filing_id, args.detection_tier)

    if not decisions:
        logger.warning("No decisions found matching criteria")
        sys.exit(0)

    logger.info(f"Found {len(decisions)} decisions")

    # Write output
    output_path = Path(args.output) if args.output else None

    if args.format == "json":
        write_json(decisions, output_path)
    else:
        write_csv(decisions, output_path)

    if output_path:
        logger.info(f"Written to {output_path}")


if __name__ == "__main__":
    main()
