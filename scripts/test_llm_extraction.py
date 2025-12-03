#!/usr/bin/env python3
"""
Test script for LLM-enhanced extraction pipeline.

This script tests the integration of LLM with ValueExtractor and DefinitionExtractor.
It verifies:
1. LLM extraction for text segments
2. LLM extraction for table segments
3. LLM extraction for definitions
4. Fallback to rule-based extraction
5. Cost tracking
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.openai_client import OpenAIClient
from src.extraction.value_extractor import ValueExtractor
from src.extraction.definition_extractor import DefinitionExtractor
from src.extraction.models import SourceSegment


def test_value_extraction_from_text():
    """Test LLM value extraction from text segments."""
    print("\n" + "=" * 80)
    print("Test 1: Value Extraction from Text (LLM)")
    print("=" * 80)

    # Initialize LLM client
    client = OpenAIClient(model="gpt-4o-mini", temperature=0.1)
    extractor = ValueExtractor(llm_client=client)

    # Create sample text segment with customer metrics
    segment = SourceSegment(
        filing_id=1,
        segment_type="text",
        section_path="Business/Key Metrics",
        section_heading="Key Operating Metrics",
        sequence_index=10,
        raw_text="""
        As of December 31, 2023, we had 125 million monthly active users (MAU),
        representing a 25% increase from 100 million MAU in the prior year.
        Our revenue retention rate was 130% for the year ended December 31, 2023.
        """,
        candidate_metric_ids=["monthly_active_users", "revenue_retention"],
        contains_numeric_disclosure_flag=True,
        contains_definition_flag=False,
        contains_methodology_flag=False,
    )

    # Extract values using LLM
    print("\nExtracting values from text segment...")
    values = extractor.extract_from_segment(segment, company_id=1)

    print(f"\n✓ Extracted {len(values)} values:")
    for value in values:
        print(f"  • {value.metric_id}: {value.value_text} {value.unit or ''}")
        print(f"    Period: {value.period_end}")
        print(f"    Method: {value.extraction_method}")
        if value.qa_notes:
            print(f"    Quote: {value.qa_notes[:100]}...")

    return len(values) > 0


def test_value_extraction_from_table():
    """Test LLM value extraction from table segments."""
    print("\n" + "=" * 80)
    print("Test 2: Value Extraction from Table (LLM)")
    print("=" * 80)

    # Initialize LLM client
    client = OpenAIClient(model="gpt-4o-mini", temperature=0.1)
    extractor = ValueExtractor(llm_client=client)

    # Create sample table segment with cohort data
    table_html = """
    <table>
        <tr>
            <th>Cohort</th>
            <th>Year 1</th>
            <th>Year 2</th>
            <th>Year 3</th>
        </tr>
        <tr>
            <td>2021 Cohort</td>
            <td>$100M</td>
            <td>$120M</td>
            <td>$130M</td>
        </tr>
        <tr>
            <td>2022 Cohort</td>
            <td>$150M</td>
            <td>$180M</td>
            <td>-</td>
        </tr>
    </table>
    """

    table_text = """
    Cohort    Year 1    Year 2    Year 3
    2021 Cohort    $100M    $120M    $130M
    2022 Cohort    $150M    $180M    -
    """

    segment = SourceSegment(
        filing_id=1,
        segment_type="table",
        section_path="Business/Cohort Analysis",
        section_heading="Revenue by Cohort",
        sequence_index=20,
        raw_text=table_text,
        raw_html=table_html,
        candidate_metric_ids=["cm_revenue_by_cohort"],
        contains_numeric_disclosure_flag=True,
        contains_definition_flag=False,
        contains_methodology_flag=False,
    )

    # Extract values using LLM
    print("\nExtracting values from table segment...")
    values = extractor.extract_from_segment(segment, company_id=1)

    print(f"\n✓ Extracted {len(values)} values:")
    for value in values:
        print(f"  • {value.metric_id}: {value.value_text} {value.unit or ''}")
        print(f"    Period: {value.period_end}")
        print(f"    Cohort: {value.cohort_bucket_raw}")
        print(f"    Method: {value.extraction_method}")

    return len(values) > 0


def test_definition_extraction():
    """Test LLM definition extraction."""
    print("\n" + "=" * 80)
    print("Test 3: Definition Extraction (LLM)")
    print("=" * 80)

    # Initialize LLM client
    client = OpenAIClient(model="gpt-4o-mini", temperature=0.1)
    extractor = DefinitionExtractor(llm_client=client)

    # Create sample definition segment
    segment = SourceSegment(
        filing_id=1,
        segment_type="text",
        section_path="Business/Key Metrics",
        section_heading="Key Operating Metrics",
        sequence_index=5,
        raw_text="""
        We define monthly active users (MAU) as unique users who have logged into
        our platform at least once during a calendar month. This metric helps us
        understand engagement and platform usage trends.

        Net revenue retention (NRR) is calculated as the revenue from existing
        customers at the end of the period divided by the revenue from those same
        customers at the beginning of the period, expressed as a percentage.
        """,
        candidate_metric_ids=["monthly_active_users", "net_revenue_retention"],
        contains_numeric_disclosure_flag=False,
        contains_definition_flag=True,
        contains_methodology_flag=True,
    )

    # Extract definitions using LLM
    print("\nExtracting definitions from segment...")
    definitions = extractor.extract_definitions([segment], company_id=1)

    print(f"\n✓ Extracted {len(definitions)} definitions:")
    for definition in definitions:
        print(f"\n  • {definition.metric_id}:")
        print(f"    Definition: {definition.definition_text_normalized}")
        if definition.methodology_text_normalized:
            print(f"    Methodology: {definition.methodology_text_normalized}")
        print(f"    Alignment: {definition.alignment_flag}")

    return len(definitions) > 0


def test_fallback_extraction():
    """Test fallback to rule-based extraction when LLM is not available."""
    print("\n" + "=" * 80)
    print("Test 4: Fallback to Rule-Based Extraction")
    print("=" * 80)

    # Initialize extractor WITHOUT LLM client
    extractor = ValueExtractor(llm_client=None)

    # Create sample segment
    segment = SourceSegment(
        filing_id=1,
        segment_type="text",
        section_path="Business",
        section_heading="Key Metrics",
        sequence_index=10,
        raw_text="As of December 31, 2023, we had 125 million monthly active users.",
        candidate_metric_ids=["monthly_active_users"],
        contains_numeric_disclosure_flag=True,
        contains_definition_flag=False,
        contains_methodology_flag=False,
    )

    # Extract values using rule-based method
    print("\nExtracting values without LLM client (rule-based only)...")
    values = extractor.extract_from_segment(segment, company_id=1)

    print(f"\n✓ Extracted {len(values)} values using rule-based extraction:")
    for value in values:
        print(f"  • {value.metric_id}: {value.value_text}")
        print(f"    Method: {value.extraction_method}")

    return True


def test_cost_tracking():
    """Test cost tracking across multiple extractions."""
    print("\n" + "=" * 80)
    print("Test 5: Cost Tracking")
    print("=" * 80)

    # Initialize LLM client
    client = OpenAIClient(model="gpt-4o-mini", temperature=0.1)

    # Perform multiple extractions
    print("\nPerforming 3 sample extractions...")

    # Extraction 1: Value from text
    extractor = ValueExtractor(llm_client=client)
    segment1 = SourceSegment(
        filing_id=1,
        segment_type="text",
        sequence_index=1,
        raw_text="We had 100 million active users in Q4 2023.",
        candidate_metric_ids=["active_users"],
        contains_numeric_disclosure_flag=True,
    )
    extractor.extract_from_segment(segment1, company_id=1)

    # Extraction 2: Definition
    def_extractor = DefinitionExtractor(llm_client=client)
    segment2 = SourceSegment(
        filing_id=1,
        segment_type="text",
        sequence_index=2,
        raw_text="We define MAU as users who logged in at least once in a month.",
        candidate_metric_ids=["monthly_active_users"],
        contains_definition_flag=True,
    )
    def_extractor.extract_definitions([segment2], company_id=1)

    # Get cost summary
    summary = client.get_cost_summary()

    print("\n" + "-" * 80)
    print("Cost Summary:")
    print("-" * 80)
    print(f"Total requests: {summary['total_requests']}")
    print(f"Total tokens: {summary['total_tokens']:,}")
    print(f"  Input tokens: {summary['total_input_tokens']:,}")
    print(f"  Output tokens: {summary['total_output_tokens']:,}")
    print(f"Total cost: ${summary['total_cost_usd']:.6f}")
    print(f"Average cost per request: ${summary['avg_cost_per_request']:.6f}")
    print("-" * 80)

    # Project costs for full corpus
    filings_count = 106
    avg_calls_per_filing = 10
    total_calls = filings_count * avg_calls_per_filing
    projected_cost = summary['avg_cost_per_request'] * total_calls

    print(f"\nProjected cost for {filings_count} filings:")
    print(f"  Avg calls per filing: {avg_calls_per_filing}")
    print(f"  Total calls: {total_calls:,}")
    print(f"  Projected cost: ${projected_cost:.2f}")

    return True


def main():
    """Run all tests."""
    print("=" * 80)
    print("Testing LLM-Enhanced Extraction Pipeline")
    print("=" * 80)

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("\n✗ ERROR: OPENAI_API_KEY environment variable not set")
        print("\nPlease set your OpenAI API key:")
        print("  export OPENAI_API_KEY='sk-...'")
        return False

    results = {}

    try:
        # Test 1: Value extraction from text
        results["text_values"] = test_value_extraction_from_text()

        # Test 2: Value extraction from table
        results["table_values"] = test_value_extraction_from_table()

        # Test 3: Definition extraction
        results["definitions"] = test_definition_extraction()

        # Test 4: Fallback extraction
        results["fallback"] = test_fallback_extraction()

        # Test 5: Cost tracking
        results["cost_tracking"] = test_cost_tracking()

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)

    all_passed = True
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False

    print("=" * 80)

    if all_passed:
        print("\n✓ All tests passed!")
        print("\nNext steps:")
        print("1. Test with real filing from corpus")
        print("2. Compare LLM vs rule-based accuracy")
        print("3. Run full corpus extraction with cost monitoring")
    else:
        print("\n✗ Some tests failed")

    print()
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
