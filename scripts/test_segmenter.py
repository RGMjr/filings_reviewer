#!/usr/bin/env python3
"""
Test the HTML segmenter on a real filing.

This script demonstrates the segmentation of a filing and displays results.
"""

import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.html_segmenter import HTMLSegmenter
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def test_segmenter_on_filing(cik: str, accession_number: str):
    """Test segmenter on a specific filing."""
    # Connect to database
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)

    # Find the filing
    filing = db.query(
        """
        SELECT f.filing_id, f.company_id, c.company_name, f.form_type, f.filing_date, f.html_storage_path
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.cik = %s AND f.accession_number = %s
        """,
        (cik, accession_number)
    )

    if not filing:
        logger.error(f"Filing not found: CIK={cik}, AN={accession_number}")
        return

    filing = filing[0]
    logger.info(f"Found filing: {filing['company_name']} {filing['form_type']} {filing['filing_date']}")

    # Check if HTML file exists
    html_path = filing['html_storage_path']
    if not html_path or not Path(html_path).exists():
        logger.error(f"HTML file not found: {html_path}")
        return

    # Segment the filing
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(filing['filing_id'], html_path)

    # Display results
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"Segmentation Results: {len(segments)} segments")
    logger.info("=" * 80)

    # Count by type
    type_counts = {}
    for segment in segments:
        type_counts[segment.segment_type] = type_counts.get(segment.segment_type, 0) + 1

    logger.info("")
    logger.info("Segment Types:")
    for seg_type, count in sorted(type_counts.items()):
        logger.info(f"  {seg_type:20s}: {count:4d} segments")

    # Show first 5 segments
    logger.info("")
    logger.info("First 5 Segments:")
    logger.info("-" * 80)

    for i, segment in enumerate(segments[:5]):
        logger.info(f"\nSegment {i+1}:")
        logger.info(f"  Type: {segment.segment_type}")
        logger.info(f"  Section: {segment.section_path or '(none)'}")
        logger.info(f"  Text length: {len(segment.raw_text)} chars")
        logger.info(f"  Text preview: {segment.raw_text[:200]}...")

    logger.info("")
    logger.info("=" * 80)

    # Ask if user wants to insert into database
    response = input("\nInsert these segments into the database? (y/n): ")
    if response.lower() == 'y':
        insert_segments(db, segments)


def insert_segments(db: DatabaseAdapter, segments: list):
    """Insert segments into the database."""
    logger.info("Inserting segments into database...")

    for segment in segments:
        db.execute("""
            INSERT INTO source_segments (
                filing_id, segment_type, section_path, section_heading,
                sequence_index, raw_text, raw_html,
                contains_definition_flag, contains_methodology_flag,
                contains_numeric_disclosure_flag
            ) VALUES (
                %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
                %(sequence_index)s, %(raw_text)s, %(raw_html)s,
                %(contains_definition_flag)s, %(contains_methodology_flag)s,
                %(contains_numeric_disclosure_flag)s
            )
        """, segment.to_dict())

    logger.info(f"✓ Inserted {len(segments)} segments")


def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Usage: python3 test_segmenter.py <CIK> <ACCESSION_NUMBER>")
        print("")
        print("Example: python3 test_segmenter.py 0001561550 0001193125-16-550418")
        sys.exit(1)

    cik = sys.argv[1]
    accession_number = sys.argv[2]

    test_segmenter_on_filing(cik, accession_number)


if __name__ == "__main__":
    main()
