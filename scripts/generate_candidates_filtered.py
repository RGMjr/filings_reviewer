#!/usr/bin/env python3
"""
Generate review candidates for 1–5 actual filings selected by filters.

Filters supported:
- Company name (ILIKE partial match, comma-separated)
- Industry/SIC code(s)
- Filing date range (start/end)
- Form type (S-1/S-1A/F-1/F-1A)

Usage:
    # 1–3 specific companies (partial names), up to 5 filings
    python scripts/generate_candidates_filtered.py \
        --companies "Snowflake, DocuSign" --limit 3

    # High-yield industries by SIC code (e.g., SaaS)
    python scripts/generate_candidates_filtered.py \
        --sic "7372,7371,7373" --limit 5

    # Date range selection
    python scripts/generate_candidates_filtered.py \
        --start-date 2020-01-01 --end-date 2020-12-31 --limit 5

    # Combine filters (company + date window)
    python scripts/generate_candidates_filtered.py \
        --companies "Shopify" --start-date 2015-01-01 --end-date 2021-12-31 --limit 2

Notes:
- Only filings with existing source_segments are processed (no mocks).
- Generates candidates into review_candidates for use in the human reviewer UI.
- Open http://127.0.0.1:5002/filings to review after generation.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infra.db import DatabaseAdapter  # noqa: E402
from src.infra.logging_config import configure_logging  # noqa: E402
from src.review.candidate_generator import CandidateGenerator  # noqa: E402
from src.review.config import get_high_recall_config  # noqa: E402

logger = logging.getLogger(__name__)


def parse_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD into date, or return None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format '{value}', expected YYYY-MM-DD") from None


def build_filings_query(
    companies: list[str] | None,
    sic_codes: list[str] | None,
    start_date: date | None,
    end_date: date | None,
    form_types: list[str] | None,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Construct parameterized SQL to select filings with segments using filters."""
    base = (
        """
        SELECT
            f.filing_id,
            f.company_id,
            f.form_type,
            f.filing_date,
            c.company_name,
            c.industry_code
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE 1=1
          AND f.is_in_scope_phase1 = true
          AND EXISTS (
                SELECT 1 FROM source_segments ss WHERE ss.filing_id = f.filing_id
          )
        """
    )

    params: dict[str, Any] = {}

    # Company filters (ILIKE partial matches, OR across provided names)
    if companies:
        ors = []
        for idx, name in enumerate(companies):
            key = f"company_name_{idx}"
            ors.append(f"c.company_name ILIKE %({key})s")
            params[key] = f"%{name.strip()}%"
        base += " AND (" + " OR ".join(ors) + ")"

    # SIC/industry filters
    if sic_codes:
        base += " AND c.industry_code = ANY(%(sic_codes)s)"
        params["sic_codes"] = sic_codes

    # Date range filters
    if start_date:
        base += " AND f.filing_date >= %(start_date)s"
        params["start_date"] = start_date
    if end_date:
        base += " AND f.filing_date <= %(end_date)s"
        params["end_date"] = end_date

    # Form type filters (exact match list)
    if form_types:
        base += " AND f.form_type = ANY(%(form_types)s)"
        params["form_types"] = form_types

    base += " ORDER BY f.filing_date DESC"
    base += " LIMIT %(limit)s"
    params["limit"] = limit

    return base, params


def generate_for_filing(db: DatabaseAdapter, filing_id: int, company_id: int) -> int:
    """Generate and insert candidates for one filing."""
    segments = db.query(
        """
        SELECT
            source_segment_id,
            filing_id,
            segment_type,
            raw_text,
            raw_html,
            section_heading,
            section_path
        FROM source_segments
        WHERE filing_id = %(filing_id)s
        ORDER BY sequence_index
        """,
        {"filing_id": filing_id},
    )

    if not segments:
        logger.warning(f"No segments found for filing {filing_id}")
        return 0

    gen = CandidateGenerator(config=get_high_recall_config())
    candidates = gen.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
        db=db,
    )

    if not candidates:
        return 0

    db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
    return len(candidates)


def main() -> int:
    load_dotenv()
    configure_logging(level="INFO")

    parser = argparse.ArgumentParser(
        description="Generate review candidates for selected actual filings",
    )
    parser.add_argument(
        "--companies",
        type=str,
        help="Comma-separated company names (partial matches, case-insensitive)",
    )
    parser.add_argument(
        "--sic",
        type=str,
        help="Comma-separated SIC/industry codes (e.g., '7372,7371')",
    )
    parser.add_argument("--start-date", type=parse_date, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=parse_date, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--forms",
        type=str,
        default="S-1,S-1/A,F-1,F-1/A",
        help="Comma-separated form types to include (default: S-1,S-1/A,F-1,F-1/A)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum filings to process (recommended: 1–5)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database connection string (defaults to DATABASE_URL)",
    )

    args = parser.parse_args()

    if args.limit < 1 or args.limit > 50:
        logger.warning("Limit out of range; clamping to 1–50")
        args.limit = max(1, min(args.limit, 50))

    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://dev:dev@localhost:5433/filings_analysis"
    )
    db = DatabaseAdapter(db_url)

    companies = [s.strip() for s in (args.companies or "").split(",") if s.strip()]
    sic_codes = [s.strip() for s in (args.sic or "").split(",") if s.strip()]
    form_types = [s.strip() for s in (args.forms or "").split(",") if s.strip()]

    query, params = build_filings_query(
        companies=companies or None,
        sic_codes=sic_codes or None,
        start_date=args.start_date,
        end_date=args.end_date,
        form_types=form_types or None,
        limit=args.limit,
    )

    logger.info("Selecting filings with filters...")
    filings = db.query(query, params)

    if not filings:
        logger.warning("No filings matched filters (or no segments yet).")
        logger.info("Ensure HTML was fetched and segmentation completed for these filings.")
        return 1

    logger.info(f"Found {len(filings)} filings to process")
    total = 0

    for f in filings:
        logger.info(
            f"Processing {f['company_name']} | {f['form_type']} | {str(f['filing_date'])} (filing_id={f['filing_id']})"
        )
        n = generate_for_filing(db, f["filing_id"], f["company_id"])
        logger.info(f"  Generated {n} candidates")
        total += n

    logger.info("\n" + "=" * 70)
    logger.info("GENERATION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Total candidates generated: {total}")
    logger.info("Review UI:")
    for f in filings:
        logger.info(f"  http://127.0.0.1:5002/review/{f['filing_id']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
