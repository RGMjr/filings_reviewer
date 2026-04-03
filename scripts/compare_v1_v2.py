#!/usr/bin/env python3
"""
V1 vs V2 Extraction Comparison Tool.

Runs V2 extraction on filings that have V1 review candidates and produces a
report showing agreements, V2 gains (facts V1 missed), and V2 regressions
(facts V2 missed).

Usage:
    # Compare specific filing
    python3 scripts/compare_v1_v2.py --filing-id 42

    # Compare multiple filings
    python3 scripts/compare_v1_v2.py --filing-ids 42,43,44

    # Compare all filings with V1 candidates
    python3 scripts/compare_v1_v2.py --all

    # Limit how many are processed
    python3 scripts/compare_v1_v2.py --all --limit 10
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.extraction_v2.comparison import (  # noqa: E402
    FilingComparison,
    align,
    build_aggregate,
    find_filings_with_candidates,
    load_v1_candidates,
    load_v2_facts,
)
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def lookup_filing(
    db: DatabaseAdapter,
    filing_id: int | None = None,
    accession: str | None = None,
) -> dict:
    """Look up filing metadata from database."""
    if filing_id:
        rows = db.query(
            """
            SELECT f.filing_id, f.accession_number, f.form_type, f.filing_date,
                   f.html_storage_path, c.company_name, c.cik, c.company_id
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
                   f.html_storage_path, c.company_name, c.cik, c.company_id
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.accession_number = %(accession)s
            """,
            {"accession": accession},
        )
    else:
        raise ValueError("Either filing_id or accession is required")

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare V1 vs V2 extraction on SEC filings")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--filing-id", type=int, help="Single filing ID")
    group.add_argument("--filing-ids", type=str, help="Comma-separated filing IDs")
    group.add_argument("--all", action="store_true", help="All filings with V1 candidates")
    parser.add_argument(
        "--limit", type=int, default=None, help="Max filings to process (with --all)"
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Read persisted V2 facts from the database instead of re-running the V2 pipeline",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print per-filing detail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable not set")
        return 1

    db = DatabaseAdapter(db_url)
    pipeline = V2Pipeline(config=PipelineConfig()) if not args.from_db else None

    # Resolve filing list
    filings: list[dict] = []
    if args.filing_id:
        filings = [lookup_filing(db, filing_id=args.filing_id)]
    elif args.filing_ids:
        ids = [int(x.strip()) for x in args.filing_ids.split(",")]
        filings = [lookup_filing(db, filing_id=fid) for fid in ids]
    else:  # --all
        filings = find_filings_with_candidates(db, limit=args.limit)

    if not filings:
        logger.warning("No filings found to compare")
        return 0

    logger.info("Comparing V1 vs V2 for %d filing(s)", len(filings))

    comparisons: list[FilingComparison] = []

    for filing in filings:
        filing_id = filing["filing_id"]
        company = filing["company_name"]
        logger.info("Processing filing %d (%s)", filing_id, company)

        # Load V1 candidates
        v1_candidates = load_v1_candidates(db, filing_id)
        if not v1_candidates:
            logger.warning("No V1 candidates for filing %d, skipping", filing_id)
            continue

        if args.from_db:
            # Load persisted V2 facts from the database
            v2_facts = load_v2_facts(db, filing_id)
            if not v2_facts:
                logger.warning(
                    "No persisted V2 results for filing %d (%s), skipping",
                    filing_id,
                    company,
                )
                continue

            matches, v1_only, v2_only = align(v1_candidates, v2_facts)
            comparison = FilingComparison(
                filing_id=filing_id,
                company_name=company,
                accession_number=filing.get("accession_number", ""),
                v1_candidates=v1_candidates,
                v2_facts=v2_facts,
                matches=matches,
                v1_only=v1_only,
                v2_only=v2_only,
                v2_pipeline_ms=0,
                v2_pipeline_success=True,
            )
            comparisons.append(comparison)
        else:
            # Resolve HTML
            try:
                html_path = resolve_html_path(filing)
            except FileNotFoundError as e:
                logger.warning("Skipping filing %d: %s", filing_id, e)
                comparisons.append(
                    FilingComparison(
                        filing_id=filing_id,
                        company_name=company,
                        accession_number=filing.get("accession_number", ""),
                        v1_candidates=v1_candidates,
                        v2_facts=[],
                        matches=[],
                        v1_only=v1_candidates,
                        v2_only=[],
                        v2_pipeline_ms=0,
                        v2_pipeline_success=False,
                    )
                )
                continue

            # Run V2
            assert pipeline is not None
            result = pipeline.process(
                html_path=html_path,
                filing_id=filing_id,
                cik=str(filing.get("cik", "")),
                accession_number=filing.get("accession_number", ""),
            )

            if not result.success:
                logger.warning(
                    "V2 pipeline failed for filing %d: %s", filing_id, result.error_message
                )

            # Align
            matches, v1_only, v2_only = align(v1_candidates, result.facts)

            comparison = FilingComparison(
                filing_id=filing_id,
                company_name=company,
                accession_number=filing.get("accession_number", ""),
                v1_candidates=v1_candidates,
                v2_facts=result.facts,
                matches=matches,
                v1_only=v1_only,
                v2_only=v2_only,
                v2_pipeline_ms=result.total_duration_ms,
                v2_pipeline_success=result.success,
            )
            comparisons.append(comparison)

        if args.verbose:
            print(f"\n--- {company} (filing {filing_id}) ---")
            print(f"  V1 candidates: {len(v1_candidates)}")
            print(f"  V2 facts:      {len(comparison.v2_facts)}")
            print(f"  Matched:       {len(comparison.matches)}")
            print(f"  V1-only:       {len(comparison.v1_only)} (regressions)")
            print(f"  V2-only:       {len(comparison.v2_only)} (gains)")
            print(f"  Agreement:     {comparison.agreement_rate():.1%}")

    if not comparisons:
        logger.warning("No comparisons produced")
        return 0

    report = build_aggregate(comparisons)

    # Write JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = PROJECT_ROOT / "reports" / f"v1_v2_comparison_{timestamp}.json"
    report.to_json(output_path)
    logger.info("Report written to %s", output_path)

    # Print summary
    report.print_summary()

    return 0


if __name__ == "__main__":
    sys.exit(main())
