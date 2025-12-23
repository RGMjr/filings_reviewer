#!/usr/bin/env python3
"""
Re-run extraction pipeline on validation filings to test goldmine enrichment.

This script re-processes a curated set of filings to validate the goldmine
identification system (G1-G12 implementation).

Target filings:
- Farfetch Ltd (ID 31) - Gold standard for customer metrics
- Snowflake (ID 32) - SaaS cohort metrics
- Snap (ID 33) - Consumer tech metrics
- DocuSign (ID 34) - Enterprise SaaS
- Slack Technologies (ID 35) - Excellent cohort disclosure
- SUSHI GINZA ONODERA (ID 29) - Edge case / international

Usage:
    python scripts/rerun_goldmine_validation.py
    python scripts/rerun_goldmine_validation.py --filing-ids 31 32  # Specific filings only
    python scripts/rerun_goldmine_validation.py --dry-run  # Don't save to database
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load .env configuration and ensure src imports work."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default validation filings
DEFAULT_FILING_IDS = [31, 32, 33, 34, 35, 29]


def get_filing_info(db, filing_id):
    """Get filing metadata from database."""
    results = db.query('''
        SELECT
            f.filing_id,
            f.company_id,
            c.company_name,
            f.cik,
            f.form_type,
            f.html_storage_path
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.filing_id = %(filing_id)s
    ''', {'filing_id': filing_id})

    return results[0] if results else None


def clear_existing_data(db, filing_id, dry_run=False):
    """Delete existing extraction data for a filing."""
    if dry_run:
        logger.info(f"  [DRY RUN] Would delete existing data for filing {filing_id}")
        return

    # Delete in order to respect foreign keys
    db.execute("DELETE FROM metric_values WHERE filing_id = %(id)s", {'id': filing_id})
    db.execute("DELETE FROM metric_definitions WHERE filing_id = %(id)s", {'id': filing_id})
    db.execute("DELETE FROM source_segments WHERE filing_id = %(id)s", {'id': filing_id})
    logger.info("  Cleared existing extraction data")


def analyze_goldmine_results(db, filing_id, company_name):
    """Analyze and report goldmine detection results."""
    # Get all segments with richness scores
    segments = db.query('''
        SELECT
            source_segment_id,
            sequence_index,
            section_heading,
            segment_type,
            richness_score,
            metric_density,
            distinct_metric_count,
            contains_temporal_trend,
            contains_cohort_breakdown,
            contains_definition_flag,
            image_count,
            classifier_confidence,
            LEFT(raw_text, 200) as text_preview
        FROM source_segments
        WHERE filing_id = %(filing_id)s
        ORDER BY richness_score DESC NULLS LAST
    ''', {'filing_id': filing_id})

    if not segments:
        logger.warning(f"  No segments found for filing {filing_id}")
        return {}

    # Calculate statistics
    total_segments = len(segments)
    goldmines = [s for s in segments if (s['richness_score'] or 0) >= 6.0]
    high_goldmines = [s for s in segments if (s['richness_score'] or 0) >= 8.0]
    with_temporal = sum(1 for s in segments if s['contains_temporal_trend'])
    with_cohort = sum(1 for s in segments if s['contains_cohort_breakdown'])
    with_definition = sum(1 for s in segments if s['contains_definition_flag'])
    with_images = sum(1 for s in segments if (s['image_count'] or 0) > 0)

    # Calculate average richness
    richness_scores = [s['richness_score'] for s in segments if s['richness_score'] is not None]
    avg_richness = sum(richness_scores) / len(richness_scores) if richness_scores else 0

    stats = {
        'company': company_name,
        'filing_id': filing_id,
        'total_segments': total_segments,
        'goldmines': len(goldmines),
        'high_goldmines': len(high_goldmines),
        'with_temporal': with_temporal,
        'with_cohort': with_cohort,
        'with_definition': with_definition,
        'with_images': with_images,
        'avg_richness': avg_richness,
        'top_segments': segments[:5]
    }

    # Print summary
    logger.info(f"\n  {'─' * 50}")
    logger.info(f"  GOLDMINE ANALYSIS: {company_name}")
    logger.info(f"  {'─' * 50}")
    logger.info(f"  Total segments:     {total_segments}")
    logger.info(f"  Goldmines (≥6.0):   {len(goldmines)} ({100*len(goldmines)/total_segments:.1f}%)")
    logger.info(f"  High value (≥8.0):  {len(high_goldmines)}")
    logger.info(f"  With temporal:      {with_temporal}")
    logger.info(f"  With cohort:        {with_cohort}")
    logger.info(f"  With definition:    {with_definition}")
    logger.info(f"  With images:        {with_images}")
    logger.info(f"  Avg richness:       {avg_richness:.2f}")

    # Show top 5 goldmine segments
    if goldmines:
        logger.info("\n  Top 5 Goldmine Segments:")
        for i, seg in enumerate(segments[:5], 1):
            if seg['richness_score'] and seg['richness_score'] >= 6.0:
                flags = []
                if seg["contains_temporal_trend"]:
                    flags.append("T")
                if seg["contains_cohort_breakdown"]:
                    flags.append("C")
                if seg["contains_definition_flag"]:
                    flags.append("D")
                if seg["image_count"]:
                    flags.append(f'I:{seg["image_count"]}')
                flag_str = ' [' + ','.join(flags) + ']' if flags else ''

                logger.info(f"  {i}. Seq {seg['sequence_index']:3} | Score {seg['richness_score']:.1f}{flag_str}")
                logger.info(f"     Section: {seg['section_heading'][:50] if seg['section_heading'] else 'N/A'}")
                preview = seg['text_preview'][:100].replace('\n', ' ') if seg['text_preview'] else ''
                logger.info(f"     Text: {preview}...")

    return stats


def main():
    prepare_environment()

    from src.extraction.extraction_pipeline import ExtractionPipeline
    from src.infra.db import DatabaseAdapter
    from src.llm.openai_client import OpenAIClient

    parser = argparse.ArgumentParser(
        description="Re-run extraction pipeline on validation filings"
    )
    parser.add_argument(
        "--filing-ids",
        type=int,
        nargs="+",
        default=DEFAULT_FILING_IDS,
        help=f"Filing IDs to process (default: {DEFAULT_FILING_IDS})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save to database, just analyze"
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip extraction, only analyze existing data"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run without LLM (rule-based only)"
    )
    args = parser.parse_args()

    # Connect to database
    db_url = os.getenv("DATABASE_URL", "postgresql://dev:dev@localhost:5433/filings_analysis")
    db = DatabaseAdapter(db_url)

    # Initialize LLM client (optional)
    llm_client = None
    if not args.no_llm and not args.skip_extraction:
        try:
            llm_client = OpenAIClient()
            logger.info("✓ LLM client initialized")
        except Exception as e:
            logger.warning(f"LLM client not available: {e}")
            logger.info("  Proceeding with rule-based extraction only")

    # Print header
    logger.info("=" * 70)
    logger.info("GOLDMINE VALIDATION PIPELINE")
    logger.info("=" * 70)
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Filings: {args.filing_ids}")
    logger.info(f"Mode: {'Dry run' if args.dry_run else 'Full extraction'}")
    logger.info(f"LLM: {'Enabled' if llm_client else 'Disabled'}")
    logger.info("=" * 70)

    # Process each filing
    all_stats = []

    for filing_id in args.filing_ids:
        logger.info(f"\n{'═' * 70}")

        # Get filing info
        filing = get_filing_info(db, filing_id)
        if not filing:
            logger.error(f"Filing {filing_id} not found in database")
            continue

        logger.info(f"Processing: {filing['company_name']} (ID: {filing_id})")
        logger.info(f"HTML: {filing['html_storage_path']}")

        # Verify HTML exists
        if not Path(filing['html_storage_path']).exists():
            logger.error(f"  HTML file not found: {filing['html_storage_path']}")
            continue

        if not args.skip_extraction:
            # Clear existing data
            clear_existing_data(db, filing_id, dry_run=args.dry_run)

            if not args.dry_run:
                # Run extraction pipeline
                pipeline = ExtractionPipeline(db=db, llm_client=llm_client)
                logger.info("  Running extraction pipeline...")

                result = pipeline.process_filing(filing_id)

                if not result.success:
                    logger.error(f"  Extraction failed: {result.error}")
                    continue

                logger.info(f"  ✓ Extracted {result.num_segments} segments, {result.num_values} values")

        # Analyze goldmine results
        stats = analyze_goldmine_results(db, filing_id, filing['company_name'])
        if stats:
            all_stats.append(stats)

    # Print summary
    logger.info(f"\n{'═' * 70}")
    logger.info("SUMMARY")
    logger.info(f"{'═' * 70}")

    if all_stats:
        logger.info(f"\n{'Company':<35} {'Segs':>6} {'Gold':>6} {'High':>6} {'Temp':>6} {'Coh':>6} {'Avg':>6}")
        logger.info("-" * 70)
        for s in all_stats:
            logger.info(f"{s['company'][:35]:<35} {s['total_segments']:>6} {s['goldmines']:>6} "
                       f"{s['high_goldmines']:>6} {s['with_temporal']:>6} {s['with_cohort']:>6} "
                       f"{s['avg_richness']:>6.2f}")

        # Totals
        logger.info("-" * 70)
        logger.info(f"{'TOTAL':<35} {sum(s['total_segments'] for s in all_stats):>6} "
                   f"{sum(s['goldmines'] for s in all_stats):>6} "
                   f"{sum(s['high_goldmines'] for s in all_stats):>6} "
                   f"{sum(s['with_temporal'] for s in all_stats):>6} "
                   f"{sum(s['with_cohort'] for s in all_stats):>6}")

    logger.info(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
