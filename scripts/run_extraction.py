#!/usr/bin/env python3
"""
Run the metric extraction pipeline on filings.

This script runs the end-to-end extraction pipeline to extract customer metrics
from SEC filing HTML and write results to the analysis database.
"""

import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extraction.extraction_pipeline import ExtractionPipeline
from infra.db import DatabaseAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    # Connect to database
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)

    # Create pipeline
    pipeline = ExtractionPipeline(db)

    # Option 1: Process a specific filing
    if len(sys.argv) > 1:
        filing_id = int(sys.argv[1])
        logger.info(f"Processing single filing: {filing_id}")
        result = pipeline.process_filing(filing_id)

        if result.success:
            logger.info("")
            logger.info("✓ Extraction complete!")
            logger.info(f"  Segments: {result.num_segments}")
            logger.info(f"  Values: {result.num_values}")
            logger.info(f"  Definitions: {result.num_definitions}")
            logger.info(f"  Incidences: {result.num_incidences}")
        else:
            logger.error(f"✗ Extraction failed: {result.error}")
            sys.exit(1)

    # Option 2: Process batch of filings
    else:
        # Find filings to process
        filings = db.query("""
            SELECT f.filing_id, c.company_name, f.form_type
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.html_storage_path IS NOT NULL
            AND f.is_in_scope_phase1 = TRUE
            AND NOT EXISTS (
                SELECT 1 FROM source_segments s WHERE s.filing_id = f.filing_id
            )
            LIMIT 10
        """)

        if not filings:
            logger.info("No filings to process")
            return

        logger.info(f"Found {len(filings)} filings to process:")
        for f in filings:
            logger.info(f"  - {f['company_name']} ({f['form_type']}) [ID: {f['filing_id']}]")

        logger.info("")

        # Process batch
        filing_ids = [f['filing_id'] for f in filings]
        stats = pipeline.process_batch(filing_ids)

        logger.info("")
        if stats['failed'] == 0:
            logger.info("✓ All filings processed successfully!")
        else:
            logger.warning(f"⚠ {stats['failed']} filings failed to process")


if __name__ == "__main__":
    main()
