#!/usr/bin/env python3
"""Test new prompts on Farfetch gold standard filing."""

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load .env configuration and make src package importable."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


def main():
    prepare_environment()

    from src.extraction.html_segmenter import HTMLSegmenter
    from src.extraction.metric_classifier import MetricClassifier
    from src.extraction.value_extractor import ValueExtractor
    from src.llm.openai_client import OpenAIClient

    # Load the Farfetch filing
    filing_path = PROJECT_ROOT / "data/filings/0001740915/000119312518252315/primary.htm"

    print(f"Loading filing: {filing_path}")

    # Segment the HTML
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(filing_id=12087, html_path=str(filing_path))
    print(f"Segmented into {len(segments)} segments")

    # Classify ALL segments to find ones with metrics
    classifier = MetricClassifier()
    classified = []
    for seg in segments:  # Check all segments
        classified_seg = classifier.classify_segment(seg)
        if classified_seg.contains_numeric_disclosure_flag and classified_seg.candidate_metric_ids:
            classified.append(classified_seg)

    print(f"Found {len(classified)} segments with potential metrics")

    # Initialize LLM
    client = OpenAIClient()
    extractor = ValueExtractor(llm_client=client)

    # Test on promising segments
    print("\n" + "="*80)
    print("Testing LLM extraction with NEW prompts on Farfetch F-1 filing")
    print("="*80)

    test_count = 0
    total_values = 0

    # Find segments that have actual numbers in them
    import re
    # Look for substantial numbers (millions, percentages, dollar amounts)
    substantial_number = re.compile(r'(\d+(?:,\d{3})+|\d+\s*(?:million|billion)|\d+(?:\.\d+)?%|\$\d)', re.IGNORECASE)

    # Search for segments with actual customer/metric data (based on gold standard)
    key_phrases = ['million consumers', 'million active', 'consumers', 'customers', 'active users',
                   'cohort', 'retention', 'orders per', 'average order']

    for seg in classified:
        text_lower = seg.raw_text.lower()
        # Look for segments with customer/user metrics
        has_key_phrase = any(phrase in text_lower for phrase in key_phrases)
        has_number = substantial_number.search(seg.raw_text)

        if seg.segment_type in ('paragraph', 'table') and len(seg.raw_text) > 150 and has_key_phrase and has_number:
            test_count += 1
            print(f"\n--- Segment {test_count} ({seg.segment_type}) ---")
            print(f"Metrics detected: {seg.candidate_metric_ids}")
            print(f"Text: {seg.raw_text[:500]}...")

            # Extract using LLM (company_id=1 is placeholder for testing)
            values = extractor.extract_from_text_with_llm(seg, company_id=1)

            if values:
                print(f"\nExtracted {len(values)} values:")
                total_values += len(values)
                for v in values:
                    quote = getattr(v, 'source_quote', None) or ''
                    print(f"  • {v.metric_id}: {v.value_text} {v.unit or ''}")
                    if quote:
                        print(f"    Quote: {quote[:100]}...")
            else:
                print("\n  No values extracted")

            if test_count >= 10:
                break

    print("\n" + "="*80)
    print(f"Summary: Extracted {total_values} values from {test_count} segments")
    print("="*80)
    cost = client.get_cost_summary()
    print(f"Total cost: ${cost.get('total_cost', 0):.4f}")
    print(f"Total tokens: {cost.get('total_tokens', 0):,}")


if __name__ == "__main__":
    main()
