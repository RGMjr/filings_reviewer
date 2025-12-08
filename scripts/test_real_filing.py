#!/usr/bin/env python3
"""
Test script for processing a real filing with LLM-enhanced extraction.

This script:
1. Connects to the database
2. Initializes the LLM client
3. Processes a real filing from the corpus
4. Shows extraction results and cost summary
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.openai_client import OpenAIClient
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.infra.db import DatabaseAdapter


def test_real_filing(filing_id: int, use_llm: bool = True):
    """
    Process a real filing with optional LLM enhancement.

    Args:
        filing_id: Database filing ID to process
        use_llm: Whether to use LLM-enhanced extraction
    """
    print("=" * 80)
    print(f"Testing Real Filing Extraction - Filing ID {filing_id}")
    print(f"Mode: {'LLM-Enhanced' if use_llm else 'Rule-Based Only'}")
    print("=" * 80)
    print()

    # Initialize database
    print("1. Connecting to database...")
    db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("   ✗ ERROR: TEST_DATABASE_URL or DATABASE_URL not set")
        return False

    db = DatabaseAdapter(connection_string=db_url)
    print(f"   ✓ Database connected: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print()

    # Initialize LLM client if requested
    llm_client = None
    if use_llm:
        print("2. Initializing LLM client...")
        if not os.getenv("OPENAI_API_KEY"):
            print("   ✗ ERROR: OPENAI_API_KEY not set")
            return False

        llm_client = OpenAIClient(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=4096,
        )
        print(f"   ✓ LLM client initialized (model: {llm_client.model})")
        print()
    else:
        print("2. Skipping LLM initialization (rule-based mode)")
        print()

    # Initialize extraction pipeline
    print("3. Initializing extraction pipeline...")
    pipeline = ExtractionPipeline(db=db, llm_client=llm_client)
    print()

    # Get filing info
    print("4. Fetching filing metadata...")
    filing_info = db.query(
        """
        SELECT filing_id, company_id, cik, accession_number,
               html_storage_path, filing_date
        FROM filings
        WHERE filing_id = %(filing_id)s
        """,
        {"filing_id": filing_id}
    )

    if not filing_info:
        print(f"   ✗ Filing {filing_id} not found in database")
        return False

    filing = filing_info[0]
    print(f"   CIK: {filing['cik']}")
    print(f"   Accession: {filing['accession_number']}")
    print(f"   Filing Date: {filing['filing_date']}")
    print(f"   HTML Path: {filing['html_storage_path']}")
    print()

    # Check if HTML exists
    html_path = Path(filing['html_storage_path'])
    if not html_path.exists():
        print(f"   ✗ HTML file not found: {html_path}")
        return False

    file_size_mb = html_path.stat().st_size / (1024 * 1024)
    print(f"   HTML Size: {file_size_mb:.2f} MB")
    print()

    # Process the filing
    print("5. Processing filing...")
    print("-" * 80)

    result = pipeline.process_filing(filing_id)

    print("-" * 80)
    print()

    # Show results
    print("6. Extraction Results:")
    print("-" * 80)

    if result.success:
        print(f"   ✓ Extraction succeeded")
        print(f"   Source Segments: {result.num_segments}")
        print(f"   Metric Values: {result.num_values}")
        print(f"   Definitions: {result.num_definitions}")
        print(f"   Filing-Metric Incidences: {result.num_incidences}")
    else:
        print(f"   ✗ Extraction failed: {result.error}")
        return False

    print()

    # Show sample extracted values
    print("7. Sample Extracted Values:")
    print("-" * 80)

    values = db.query(
        """
        SELECT mv.metric_id, mv.value_text, mv.unit, mv.period_end,
               mv.extraction_method, mv.cohort_bucket_raw
        FROM metric_values mv
        WHERE mv.filing_id = %(filing_id)s
        ORDER BY mv.metric_value_id
        LIMIT 10
        """,
        {"filing_id": filing_id}
    )

    if values:
        for i, val in enumerate(values, 1):
            print(f"   {i}. {val['metric_id']}")
            print(f"      Value: {val['value_text']} {val['unit'] or ''}")
            if val['period_end']:
                print(f"      Period: {val['period_end']}")
            if val['cohort_bucket_raw']:
                print(f"      Cohort: {val['cohort_bucket_raw']}")
            print(f"      Method: {val['extraction_method']}")
            print()
    else:
        print("   (No values extracted)")
        print()

    # Show sample definitions
    print("8. Sample Extracted Definitions:")
    print("-" * 80)

    definitions = db.query(
        """
        SELECT md.metric_id, md.definition_text_normalized,
               md.alignment_flag
        FROM metric_definitions md
        WHERE md.filing_id = %(filing_id)s
        ORDER BY md.metric_definition_id
        LIMIT 5
        """,
        {"filing_id": filing_id}
    )

    if definitions:
        for i, defn in enumerate(definitions, 1):
            print(f"   {i}. {defn['metric_id']}")
            print(f"      Definition: {defn['definition_text_normalized'][:200]}...")
            print(f"      Alignment: {defn['alignment_flag']}")
            print()
    else:
        print("   (No definitions extracted)")
        print()

    # Show cost summary if LLM was used
    if llm_client:
        print("9. LLM Cost Summary:")
        print("-" * 80)

        summary = llm_client.get_cost_summary()

        print(f"   Total LLM Requests: {summary['total_requests']}")
        print(f"   Total Tokens: {summary['total_tokens']:,}")
        print(f"     Input Tokens: {summary['total_input_tokens']:,}")
        print(f"     Output Tokens: {summary['total_output_tokens']:,}")
        print(f"   Total Cost: ${summary['total_cost_usd']:.6f}")
        print(f"   Average Cost/Request: ${summary['avg_cost_per_request']:.6f}")
        print()

        # Extrapolate to full corpus
        if summary['total_requests'] > 0:
            cost_per_filing = summary['total_cost_usd']
            corpus_size = 106
            projected_cost = cost_per_filing * corpus_size

            print(f"   Cost for this filing: ${cost_per_filing:.6f}")
            print(f"   Projected cost for {corpus_size} filings: ${projected_cost:.2f}")
            print()

    print("=" * 80)
    print("✓ Test Complete!")
    print("=" * 80)

    return True


def main():
    """Run the test."""

    # Test with a known filing
    filing_id = 41000  # CIK 0002074878 - New America Acquisition I Corp.

    print("\n")
    print("=" * 80)
    print("Real Filing Test - LLM-Enhanced Extraction")
    print("=" * 80)
    print()
    print("This test will:")
    print("  1. Process a real SEC S-1 filing from the corpus")
    print("  2. Use LLM-enhanced extraction with rule-based fallback")
    print("  3. Show extraction results and cost breakdown")
    print()

    # Ask user to confirm
    response = input("Continue? [Y/n]: ").strip().lower()
    if response and response not in ['y', 'yes']:
        print("Test cancelled.")
        return False

    print()

    # Run the test
    success = test_real_filing(filing_id, use_llm=True)

    if success:
        print()
        print("Next steps:")
        print("  1. Review the extracted values and definitions")
        print("  2. Compare with manual review of the filing")
        print("  3. Assess extraction quality and accuracy")
        print("  4. Run additional filings to gather statistics")
        print()

    return success


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
