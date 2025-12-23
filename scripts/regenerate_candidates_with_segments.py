#!/usr/bin/env python3
"""
Regenerate Review Candidates with Proper source_segment_id Links

Problem: All 213 review_candidates have NULL source_segment_id, preventing
table HTML display and proper table row matching.

Solution:
1. Export existing review decisions for preservation
2. Delete all broken candidates (cascades to decisions)
3. Regenerate candidates using CandidateGenerator with proper segment links
4. Restore review decisions by matching to new candidates

Usage:
    # Preview what will happen (dry run)
    python scripts/regenerate_candidates_with_segments.py --dry-run

    # Execute regeneration
    python scripts/regenerate_candidates_with_segments.py

    # Regenerate specific filings only
    python scripts/regenerate_candidates_with_segments.py --filing-ids 31,32
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.review.candidate_generator import CandidateGenerator
from src.review.config import get_high_recall_config

logger = logging.getLogger(__name__)


def export_review_decisions(db: DatabaseAdapter, output_path: str) -> int:
    """
    Export all review decisions with matching criteria for recovery.

    Args:
        db: DatabaseAdapter instance
        output_path: Path to save JSON export

    Returns:
        Number of decisions exported
    """
    query = """
        SELECT
            rd.decision_id,
            rd.candidate_id,
            rd.decision,
            rd.assigned_metric_id,
            rd.rejection_category,
            rd.rejection_reason,
            rd.reviewer_notes,
            rd.reviewer_id,
            rd.review_time_seconds,
            rd.created_at,
            -- Candidate matching criteria
            rc.filing_id,
            rc.company_id,
            rc.char_position,
            rc.parsed_value,
            rc.parsed_unit,
            rc.triggering_keyword,
            rc.keyword_distance,
            rc.keyword_position,
            rc.suggested_metric_id,
            LEFT(rc.context_text, 100) as context_preview,
            rc.features
        FROM review_decisions rd
        JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
        ORDER BY rd.created_at
    """

    decisions = db.query(query)

    # Convert to JSON-serializable format
    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "total_decisions": len(decisions),
        "decisions": [
            {
                **{k: (str(v) if isinstance(v, (datetime,)) else v)
                   for k, v in d.items()}
            }
            for d in decisions
        ]
    }

    with open(output_path, 'w') as f:
        json.dump(export_data, f, indent=2, default=str)

    logger.info(f"Exported {len(decisions)} review decisions to {output_path}")
    return len(decisions)


def get_affected_filings(db: DatabaseAdapter, filing_ids: Optional[List[int]] = None) -> List[Dict]:
    """
    Get filings that have review candidates.

    Args:
        db: DatabaseAdapter instance
        filing_ids: Optional list of specific filing IDs

    Returns:
        List of filing dicts with metadata
    """
    query = """
        SELECT
            c.company_name,
            f.filing_id,
            f.company_id,
            f.accession_number,
            COUNT(DISTINCT rc.candidate_id) as num_candidates,
            COUNT(DISTINCT rd.decision_id) as num_decisions,
            COUNT(DISTINCT ss.source_segment_id) as num_segments
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        LEFT JOIN review_candidates rc ON f.filing_id = rc.filing_id
        LEFT JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
        LEFT JOIN source_segments ss ON f.filing_id = ss.filing_id
        WHERE 1=1
    """

    params: Dict = {}
    if filing_ids:
        query += " AND f.filing_id = ANY(%(filing_ids)s)"
        params["filing_ids"] = filing_ids

    query += """
        GROUP BY c.company_name, f.filing_id, f.company_id, f.accession_number
    """

    # Only filter by existing candidates if no specific IDs requested
    if not filing_ids:
        query += " HAVING COUNT(DISTINCT rc.candidate_id) > 0"

    query += """
        ORDER BY COUNT(DISTINCT rd.decision_id) DESC, COUNT(DISTINCT rc.candidate_id) DESC
    """

    return db.query(query, params)


def delete_candidates(db: DatabaseAdapter, filing_ids: Optional[List[int]] = None) -> Tuple[int, int]:
    """
    Delete review candidates (cascades to decisions).

    Args:
        db: DatabaseAdapter instance
        filing_ids: Optional list of filing IDs to limit deletion

    Returns:
        Tuple of (candidates_deleted, decisions_deleted)
    """
    # Count before deletion
    if filing_ids:
        candidates_count = db.query(
            "SELECT COUNT(*) as count FROM review_candidates WHERE filing_id = ANY(%(filing_ids)s)",
            {"filing_ids": filing_ids}
        )[0]["count"]
        decisions_count = db.query(
            """SELECT COUNT(DISTINCT rd.decision_id) as count
               FROM review_decisions rd
               JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
               WHERE rc.filing_id = ANY(%(filing_ids)s)""",
            {"filing_ids": filing_ids}
        )[0]["count"]
    else:
        candidates_count = db.query("SELECT COUNT(*) as count FROM review_candidates")[0]["count"]
        decisions_count = db.query("SELECT COUNT(*) as count FROM review_decisions")[0]["count"]

    # Delete candidates (cascades to decisions)
    if filing_ids:
        db.execute(
            "DELETE FROM review_candidates WHERE filing_id = ANY(%(filing_ids)s)",
            {"filing_ids": filing_ids}
        )
    else:
        db.execute("DELETE FROM review_candidates")

    logger.info(f"Deleted {candidates_count} candidates and {decisions_count} decisions")
    return candidates_count, decisions_count


def regenerate_candidates_for_filing(
    db: DatabaseAdapter,
    filing_id: int,
    company_id: int
) -> int:
    """
    Regenerate candidates for a single filing.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing to process
        company_id: Company ID

    Returns:
        Number of candidates generated
    """
    # Load segments from database
    segments_query = """
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
    """
    segments = db.query(segments_query, {"filing_id": filing_id})

    if not segments:
        logger.warning(f"No segments found for filing {filing_id}")
        return 0

    logger.info(f"  Found {len(segments)} segments")

    # Generate candidates with high recall config
    # Use High Recall but with strict filtering enabled
    config = get_high_recall_config()
    config.filter_false_positives = True
    config.filter_years = True  # Filter 1990-2030 unless currency
    config.min_metric_value = 10 # Baseline
    
    generator = CandidateGenerator(config=config)
    candidates = generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
        db=db,
    )

    logger.info(f"  Generated {len(candidates)} candidates")

    # Insert candidates
    if candidates:
        candidate_dicts = [c.to_dict() for c in candidates]
        db.bulk_insert_review_candidates(candidate_dicts)
        logger.info(f"  Inserted {len(candidates)} candidates into database")

    return len(candidates)


def attempt_decision_recovery(
    db: DatabaseAdapter,
    decisions_export_path: str
) -> Tuple[int, int]:
    """
    Attempt to restore review decisions by matching to new candidates.

    Matching criteria:
    - Same filing_id
    - Same parsed_value (±0.01%)
    - Same triggering_keyword
    - Same suggested_metric_id (or both NULL)

    Args:
        db: DatabaseAdapter instance
        decisions_export_path: Path to exported decisions JSON

    Returns:
        Tuple of (decisions_recovered, decisions_lost)
    """
    with open(decisions_export_path) as f:
        export_data = json.load(f)

    original_decisions = export_data["decisions"]
    recovered = 0
    lost = 0

    for decision in original_decisions:
        # Find matching candidate
        match_query = """
            SELECT candidate_id
            FROM review_candidates
            WHERE filing_id = %(filing_id)s
              AND triggering_keyword = %(triggering_keyword)s
              AND ABS(parsed_value - %(parsed_value)s) / NULLIF(%(parsed_value)s, 0) < 0.0001
              AND (
                  (suggested_metric_id = %(suggested_metric_id)s)
                  OR (suggested_metric_id IS NULL AND %(suggested_metric_id)s IS NULL)
              )
            LIMIT 1
        """

        matches = db.query(match_query, {
            "filing_id": decision["filing_id"],
            "triggering_keyword": decision["triggering_keyword"],
            "parsed_value": decision["parsed_value"],
            "suggested_metric_id": decision["suggested_metric_id"],
        })

        if matches:
            # Recreate decision using insert_review_decision to ensure status update
            new_candidate_id = matches[0]["candidate_id"]
            db.insert_review_decision(
                candidate_id=new_candidate_id,
                decision=decision["decision"],
                assigned_metric_id=decision["assigned_metric_id"],
                rejection_category=decision["rejection_category"],
                rejection_reason=decision["rejection_reason"],
                reviewer_notes=decision["reviewer_notes"],
                reviewer_id=decision["reviewer_id"],
                review_time_seconds=decision["review_time_seconds"],
            )
            recovered += 1
            logger.debug(f"Recovered decision {decision['decision_id']} -> new candidate {new_candidate_id}")
        else:
            lost += 1
            logger.warning(
                f"Could not recover decision {decision['decision_id']}: "
                f"{decision['decision']} for {decision['triggering_keyword']} = {decision['parsed_value']}"
            )

    logger.info(f"Decision recovery: {recovered} recovered, {lost} lost")
    return recovered, lost


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate review candidates with proper source_segment_id"
    )
    parser.add_argument(
        "--filing-ids",
        type=str,
        help="Comma-separated filing IDs to regenerate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--skip-recovery",
        action="store_true",
        help="Skip attempting to recover review decisions",
    )
    parser.add_argument(
        "--export-path",
        type=str,
        default="review_decisions_backup.json",
        help="Path for decision export backup (default: review_decisions_backup.json)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database URL (default: from DATABASE_URL env var)",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()

    # Configure logging
    configure_logging(level="INFO")

    # Connect to database
    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 1

    db = DatabaseAdapter(db_url)
    logger.info("Connected to database")

    # Parse filing IDs
    filing_ids = None
    if args.filing_ids:
        filing_ids = [int(fid.strip()) for fid in args.filing_ids.split(",")]
        logger.info(f"Targeting specific filings: {filing_ids}")

    # Get affected filings
    filings = get_affected_filings(db, filing_ids)
    if not filings:
        logger.error("No filings with candidates found")
        return 1

    # Display summary
    print("\n" + "=" * 70)
    print("CANDIDATE REGENERATION PLAN")
    print("=" * 70)
    print(f"\nFilings to process: {len(filings)}")

    total_candidates = sum(f["num_candidates"] for f in filings)
    total_decisions = sum(f["num_decisions"] for f in filings)
    total_segments = sum(f["num_segments"] for f in filings)

    print(f"Current candidates: {total_candidates}")
    print(f"Review decisions: {total_decisions}")
    print(f"Available segments: {total_segments}")

    print("\nFilings:")
    for f in filings:
        print(f"  {f['filing_id']:3d} | {f['company_name']:25s} | "
              f"Candidates: {f['num_candidates']:3d} | "
              f"Decisions: {f['num_decisions']:2d} | "
              f"Segments: {f['num_segments']:3d}")

    if args.dry_run:
        print("\n*** DRY RUN - No changes will be made ***")
        print("\nWhat would happen:")
        print(f"1. Export {total_decisions} review decisions to {args.export_path}")
        print(f"2. Delete {total_candidates} candidates (cascades to {total_decisions} decisions)")
        print(f"3. Regenerate candidates from {total_segments} segments")
        if not args.skip_recovery:
            print(f"4. Attempt to recover {total_decisions} review decisions")
        return 0

    # Confirm
    print("\n" + "=" * 70)
    response = input("Proceed with regeneration? (yes/no): ")
    if response.lower() not in ["yes", "y"]:
        print("Aborted")
        return 0

    # Step 1: Export decisions
    print("\n" + "-" * 70)
    print("Step 1: Exporting review decisions...")
    print("-" * 70)
    num_exported = export_review_decisions(db, args.export_path)
    print(f"✓ Exported {num_exported} decisions to {args.export_path}")

    # Step 2: Delete candidates
    print("\n" + "-" * 70)
    print("Step 2: Deleting broken candidates...")
    print("-" * 70)
    candidates_deleted, decisions_deleted = delete_candidates(db, filing_ids)
    print(f"✓ Deleted {candidates_deleted} candidates and {decisions_deleted} decisions")

    # Step 3: Regenerate candidates
    print("\n" + "-" * 70)
    print("Step 3: Regenerating candidates with proper segment links...")
    print("-" * 70)

    total_generated = 0
    for filing in filings:
        logger.info(f"Processing {filing['company_name']} (filing {filing['filing_id']})...")
        num_generated = regenerate_candidates_for_filing(
            db,
            filing["filing_id"],
            filing["company_id"]
        )
        total_generated += num_generated

    print(f"✓ Generated {total_generated} new candidates")

    # Step 4: Attempt decision recovery
    recovered = 0
    lost = 0
    if not args.skip_recovery and num_exported > 0:
        print("\n" + "-" * 70)
        print("Step 4: Attempting to recover review decisions...")
        print("-" * 70)
        recovered, lost = attempt_decision_recovery(db, args.export_path)
        print(f"✓ Recovered {recovered} decisions, lost {lost}")

        if lost > 0:
            print(f"\n⚠ WARNING: {lost} decisions could not be recovered")
            print(f"  See {args.export_path} for the original decision data")

    # Final summary
    print("\n" + "=" * 70)
    print("REGENERATION COMPLETE")
    print("=" * 70)
    print(f"\nOld candidates: {candidates_deleted}")
    print(f"New candidates: {total_generated}")
    print(f"Change: {total_generated - candidates_deleted:+d}")

    if not args.skip_recovery:
        print(f"\nDecisions before: {decisions_deleted}")
        print(f"Decisions recovered: {recovered}")
        print(f"Decisions lost: {lost}")

    print(f"\nBackup saved to: {args.export_path}")
    print("\nNext steps:")
    print("1. Test table display in review interface")
    print("2. Verify table row matching is working correctly")
    print("3. Review candidates to restore lost decisions (if any)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
