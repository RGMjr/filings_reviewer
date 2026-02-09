#!/usr/bin/env python3
"""
Evaluate extraction improvements by running on Farfetch filing
and comparing results with the gold standard.
"""

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load .env configuration and make the src package importable."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


def load_gold_standard(csv_path: Path) -> dict:
    """Load gold standard reviews and return as dict for lookup."""
    reviews = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("review_status"):
                # Column names may have whitespace
                value_text = row.get(" value_text ") or row.get("value_text") or ""
                key = (row["metric_id"], value_text.strip())
                reviews[key] = row["review_status"]
    return reviews


def main():
    prepare_environment()

    from src.extraction.html_segmenter import HTMLSegmenter
    from src.extraction.metric_classifier import MetricClassifier
    from src.extraction.value_extractor import ValueExtractor
    from src.llm.openai_client import OpenAIClient

    # Load Farfetch filing
    filing_path = PROJECT_ROOT / "data/gold_standard/Farfetch_Limited/filing.html"
    gold_path = PROJECT_ROOT / "data/gold_standard/Farfetch_Limited/extracted_values.csv"

    print(f"Loading filing: {filing_path}")
    print(f"Gold standard: {gold_path}")

    # Load gold standard
    gold_reviews = load_gold_standard(gold_path)
    print(f"Loaded {len(gold_reviews)} reviewed items from gold standard")

    # Segment the HTML
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(filing_id=12087, html_path=str(filing_path))
    print(f"Segmented into {len(segments)} segments")

    # Classify segments
    classifier = MetricClassifier()
    classified = []
    for seg in segments:
        classified_seg = classifier.classify_segment(seg)
        if classified_seg.contains_numeric_disclosure_flag and classified_seg.candidate_metric_ids:
            classified.append(classified_seg)

    print(f"Found {len(classified)} segments with potential metrics")

    # Initialize LLM
    client = OpenAIClient()
    extractor = ValueExtractor(llm_client=client)

    # Extract from all classified segments
    print("\nExtracting from all classified segments (may take a minute)...")
    all_values = []
    segments_processed = 0

    for seg in classified:
        if seg.segment_type == "table" and seg.raw_html:
            values = extractor.extract_from_table_with_llm(seg, company_id=1)
        else:
            values = extractor.extract_from_text_with_llm(seg, company_id=1)

        if values:
            all_values.extend(values)

        segments_processed += 1
        if segments_processed % 20 == 0:
            print(f"  Processed {segments_processed}/{len(classified)} segments, found {len(all_values)} values so far")

    print(f"\nTotal extracted: {len(all_values)} values")

    # Evaluate against gold standard
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)

    correct = 0
    incorrect = 0
    new_extractions = 0

    for v in all_values:
        key = (v.metric_id, v.value_text.strip() if v.value_text else "")
        if key in gold_reviews:
            if gold_reviews[key] == "correct":
                correct += 1
            else:
                incorrect += 1
        else:
            new_extractions += 1
            print(f"  NEW: {v.metric_id} = {v.value_text}")

    total = correct + incorrect + new_extractions
    if total > 0:
        precision = (correct / total) * 100
    else:
        precision = 0

    print("\nResults:")
    print(f"  Total extracted: {total}")
    print(f"  Correct (per gold standard): {correct}")
    print(f"  Incorrect (per gold standard): {incorrect}")
    print(f"  New extractions (not in gold): {new_extractions}")
    print(f"\n  PRECISION: {precision:.1f}%")
    print("  (Baseline was 10.3%)")

    if precision > 50:
        print(f"\n  SUCCESS: Precision improved from 10.3% to {precision:.1f}%")
    elif precision > 10.3:
        print(f"\n  IMPROVEMENT: Precision improved from 10.3% to {precision:.1f}%")
    else:
        print(f"\n  NO IMPROVEMENT: Precision is {precision:.1f}% (baseline: 10.3%)")

    # Show cost
    cost = client.get_cost_summary()
    print(f"\nTotal cost: ${cost.get('total_cost', 0):.4f}")
    print(f"Total tokens: {cost.get('total_tokens', 0):,}")


if __name__ == "__main__":
    main()
