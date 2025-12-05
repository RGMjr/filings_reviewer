#!/usr/bin/env python3
"""
Re-run extraction after section heading fix.

This script:
1. Clears existing extraction data (source_segments, metric_values, etc.)
2. Re-runs the extraction pipeline to get correct section headings
"""

import os
import sys
import signal
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Per-filing timeout (5 minutes max)
FILING_TIMEOUT_SECONDS = 300


class TimeoutError(Exception):
    """Raised when filing processing exceeds timeout."""
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Filing processing timed out")


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.llm.openai_client import OpenAIClient


def clear_extraction_data(db: DatabaseAdapter):
    """Clear all extraction data to allow fresh re-extraction."""
    print("\n=== Clearing existing extraction data ===")

    # Get counts before clearing
    counts_before = {}
    for table in ['metric_values', 'metric_definitions', 'filing_metric_incidence', 'source_segments']:
        result = db.query(f"SELECT COUNT(*) as cnt FROM {table}")
        counts_before[table] = result[0]['cnt'] if result else 0
        print(f"  {table}: {counts_before[table]} rows")

    # Clear in order (respecting foreign keys)
    print("\nDeleting data...")
    db.execute("DELETE FROM metric_values")
    db.execute("DELETE FROM metric_definitions")
    db.execute("DELETE FROM filing_metric_incidence")
    db.execute("DELETE FROM source_segments")

    print("Data cleared successfully.\n")
    return counts_before


def get_filings_to_process(db: DatabaseAdapter) -> List[Dict[str, Any]]:
    """Get all fetched filings for re-extraction."""
    sql = """
    SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        f.html_storage_path
    FROM companies c
    JOIN filings f ON c.company_id = f.company_id
    WHERE f.processing_status = 'fetched'
      AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
      AND f.html_storage_path IS NOT NULL
    ORDER BY c.company_name
    """
    return db.query(sql)


def run_extraction(db: DatabaseAdapter, filings: List[Dict[str, Any]]):
    """Run extraction on all filings."""
    print(f"\n=== Starting extraction on {len(filings)} filings ===\n")

    # Initialize pipeline
    llm_client = OpenAIClient()
    pipeline = ExtractionPipeline(db, llm_client)

    results = {
        'success': [],
        'failed': [],
        'timeout': [],
    }

    total_metrics = 0
    total_definitions = 0

    for i, filing in enumerate(filings, 1):
        company = filing['company_name']
        filing_id = filing['filing_id']
        html_path = filing['html_storage_path']

        print(f"[{i}/{len(filings)}] {company}...", end=" ", flush=True)

        # Set timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(FILING_TIMEOUT_SECONDS)

        try:
            result = pipeline.process_filing(filing_id)
            signal.alarm(0)  # Cancel timeout

            if result and result.success:
                metrics = result.num_values
                defs = result.num_definitions
                total_metrics += metrics
                total_definitions += defs
                print(f"OK ({metrics} values, {defs} defs)")
                results['success'].append(company)
            else:
                error_msg = result.error if result else "No result"
                print(f"FAILED: {error_msg}")
                results['failed'].append(company)

        except TimeoutError:
            signal.alarm(0)
            print("TIMEOUT")
            results['timeout'].append(company)

        except Exception as e:
            signal.alarm(0)
            print(f"ERROR: {e}")
            results['failed'].append(company)

    return results, total_metrics, total_definitions


def main():
    print("=" * 60)
    print("RE-EXTRACTION WITH SECTION HEADING FIX")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Connect to database
    db_url = os.getenv('DATABASE_URL', 'postgresql://localhost/filings_analysis')
    db = DatabaseAdapter(db_url)

    try:
        # Step 1: Clear existing data
        counts_before = clear_extraction_data(db)

        # Step 2: Get filings to process
        filings = get_filings_to_process(db)
        print(f"Found {len(filings)} filings to process")

        if not filings:
            print("No filings found!")
            return

        # Step 3: Run extraction
        results, total_metrics, total_definitions = run_extraction(db, filings)

        # Step 4: Summary
        print("\n" + "=" * 60)
        print("EXTRACTION COMPLETE")
        print("=" * 60)
        print(f"Success: {len(results['success'])}")
        print(f"Failed:  {len(results['failed'])}")
        print(f"Timeout: {len(results['timeout'])}")
        print(f"\nTotal metrics extracted: {total_metrics}")
        print(f"Total definitions extracted: {total_definitions}")

        if results['timeout']:
            print(f"\nTimed out companies: {', '.join(results['timeout'])}")
        if results['failed']:
            print(f"\nFailed companies: {', '.join(results['failed'])}")

        # Verify section headings improved
        print("\n=== Verifying section heading fix ===")
        toc_check = db.query("""
            SELECT COUNT(*) as cnt
            FROM source_segments
            WHERE LOWER(section_heading) = 'table of contents'
        """)
        toc_count = toc_check[0]['cnt'] if toc_check else 0

        total_check = db.query("SELECT COUNT(*) as cnt FROM source_segments WHERE section_heading IS NOT NULL")
        total_with_heading = total_check[0]['cnt'] if total_check else 0

        print(f"Segments with 'Table of Contents' heading: {toc_count}")
        print(f"Total segments with headings: {total_with_heading}")

        if toc_count == 0:
            print("SUCCESS: No 'Table of Contents' headings found!")
        else:
            print(f"WARNING: Still have {toc_count} 'Table of Contents' headings")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

    print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
