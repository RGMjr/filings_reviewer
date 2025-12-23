#!/usr/bin/env python3
"""
Re-extract specific companies and save results to CSV for manual review.

Compares new extractions with original gold standard and outputs statistics.

Usage:
    python3 scripts/reextract_to_csv.py --companies "Farfetch" "Samsara"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load .env configuration and ensure src imports work."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


if TYPE_CHECKING:
    from src.llm.openai_client import OpenAIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_gold_standard_companies(gold_dir: Path, filter_names: list = None) -> list:
    """Load gold standard company metadata, optionally filtered."""
    companies = []
    for company_dir in gold_dir.iterdir():
        if not company_dir.is_dir():
            continue
        metadata_file = company_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
                metadata["company_dir"] = company_dir

                # Filter if names provided
                if filter_names:
                    if any(name.lower() in metadata["company_name"].lower() for name in filter_names):
                        companies.append(metadata)
                else:
                    companies.append(metadata)
    return companies


def load_original_extractions(company_dir: Path) -> list:
    """Load original extracted values for comparison."""
    values_file = company_dir / "extracted_values.csv"
    if not values_file.exists():
        return []

    values = []
    with open(values_file, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            values.append(row)
    return values


def extract_from_filing(html_path: Path, llm_client: OpenAIClient) -> list:
    """Run extraction pipeline on a filing."""
    if not html_path.exists():
        logger.warning(f"HTML file not found: {html_path}")
        return []

    from src.extraction.html_segmenter import HTMLSegmenter
    from src.extraction.metric_classifier import MetricClassifier
    from src.extraction.value_extractor import ValueExtractor

    # Segment HTML
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(filing_id=0, html_path=str(html_path))
    logger.info(f"  Segmented into {len(segments)} segments")

    # Classify segments
    classifier = MetricClassifier()
    classified = []
    for seg in segments:
        classified_seg = classifier.classify_segment(seg)
        classified.append(classified_seg)

    # Filter to high-confidence segments
    high_conf = [
        seg for seg in classified
        if (seg.classifier_confidence and seg.classifier_confidence >= 0.5)
        or seg.contains_definition_flag
    ]
    logger.info(f"  {len(high_conf)} high-confidence segments")

    # Extract values
    extractor = ValueExtractor(llm_client=llm_client)
    all_values = []
    for seg in high_conf[:50]:  # Limit to prevent runaway
        try:
            values = extractor.extract_from_segment(seg, company_id=0)
            all_values.extend(values)
        except Exception as e:
            logger.warning(f"  Extraction error: {e}")

    logger.info(f"  Extracted {len(all_values)} values")
    return all_values


def save_extractions_to_csv(values: list, output_path: Path, company_name: str):
    """Save extracted values to CSV file."""
    fieldnames = [
        "metric_id", "metric_name", "value_numeric", "value_text", "unit",
        "period_start", "period_end", "period_type", "cohort_type", "cohort_bucket_raw",
        "extraction_method", "qa_status", "source_text_preview"
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for val in values:
            # Get source text preview
            source_preview = ""
            if hasattr(val, 'source_segment') and val.source_segment:
                source_preview = val.source_segment.raw_text[:200] if val.source_segment.raw_text else ""

            row = {
                "metric_id": val.metric_id,
                "metric_name": getattr(val, 'metric_name', val.metric_id),
                "value_numeric": val.value_numeric,
                "value_text": val.value_text,
                "unit": val.unit,
                "period_start": val.period_start,
                "period_end": val.period_end,
                "period_type": val.period_type,
                "cohort_type": val.cohort_type,
                "cohort_bucket_raw": val.cohort_bucket_raw,
                "extraction_method": val.extraction_method,
                "qa_status": val.qa_status,
                "source_text_preview": source_preview
            }
            writer.writerow(row)

    logger.info(f"  Saved {len(values)} extractions to {output_path}")


def compare_extractions(original: list, new: list) -> dict:
    """Compare original and new extractions, return detailed comparison."""
    comparison = {
        "original_count": len(original),
        "new_count": len(new),
        "by_metric_original": defaultdict(int),
        "by_metric_new": defaultdict(int),
    }

    for val in original:
        metric_id = val.get("metric_id", "unknown")
        comparison["by_metric_original"][metric_id] += 1

    for val in new:
        metric_id = val.metric_id
        comparison["by_metric_new"][metric_id] += 1

    return comparison


def print_comparison(company_name: str, comparison: dict):
    """Print detailed comparison statistics."""
    print(f"\n{'='*70}")
    print(f"COMPARISON: {company_name}")
    print(f"{'='*70}")

    orig = comparison["original_count"]
    new = comparison["new_count"]
    change = new - orig

    print("\n  Total Extractions:")
    print(f"    Original (gold standard): {orig}")
    print(f"    New (with validation):    {new}")
    print(f"    Change:                   {change:+d} ({change/orig*100 if orig else 0:+.1f}%)")

    # Combine all metrics
    all_metrics = set(comparison["by_metric_original"].keys()) | set(comparison["by_metric_new"].keys())

    print("\n  By Metric:")
    print(f"    {'Metric ID':<40} {'Original':>10} {'New':>10} {'Change':>10}")
    print(f"    {'-'*40} {'-'*10} {'-'*10} {'-'*10}")

    for metric in sorted(all_metrics):
        orig_count = comparison["by_metric_original"].get(metric, 0)
        new_count = comparison["by_metric_new"].get(metric, 0)
        diff = new_count - orig_count
        if diff != 0 or orig_count > 0 or new_count > 0:
            print(f"    {metric:<40} {orig_count:>10} {new_count:>10} {diff:>+10}")


def main():
    prepare_environment()

    from src.llm.openai_client import OpenAIClient

    parser = argparse.ArgumentParser(description="Re-extract companies and save to CSV")
    parser.add_argument("--companies", nargs="+", required=True,
                        help="Company names to process (partial match)")
    args = parser.parse_args()

    # Paths
    base_dir = PROJECT_ROOT
    gold_dir = base_dir / "data" / "gold_standard"
    output_dir = base_dir / "data" / "reextraction_results"
    output_dir.mkdir(exist_ok=True)

    if not gold_dir.exists():
        print(f"Gold standard directory not found: {gold_dir}")
        return

    # Load filtered companies
    companies = load_gold_standard_companies(gold_dir, args.companies)
    logger.info(f"Found {len(companies)} matching companies")

    if not companies:
        print(f"No companies found matching: {args.companies}")
        return

    # Initialize LLM client
    llm_client = OpenAIClient()

    # Process each company
    all_comparisons = []

    for company in companies:
        print(f"\n{'='*70}")
        print(f"Processing: {company['company_name']}")
        print(f"{'='*70}")

        html_path = base_dir / company["local_path"]

        # Load original extractions
        original = load_original_extractions(company["company_dir"])
        logger.info(f"  Original extractions: {len(original)}")

        # Re-extract
        new_values = extract_from_filing(html_path, llm_client)

        # Save new extractions to CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        company_slug = company["company_name"].replace(" ", "_").replace(",", "")
        output_file = output_dir / f"{company_slug}_reextracted_{timestamp}.csv"
        save_extractions_to_csv(new_values, output_file, company["company_name"])

        # Compare
        comparison = compare_extractions(original, new_values)
        comparison["company"] = company["company_name"]
        comparison["output_file"] = str(output_file)
        all_comparisons.append(comparison)

        # Print comparison
        print_comparison(company["company_name"], comparison)

    # Overall summary
    print(f"\n{'='*70}")
    print("OVERALL SUMMARY")
    print(f"{'='*70}")

    total_original = sum(c["original_count"] for c in all_comparisons)
    total_new = sum(c["new_count"] for c in all_comparisons)

    print(f"\n  Total original extractions: {total_original}")
    print(f"  Total new extractions:      {total_new}")
    print(f"  Net change:                 {total_new - total_original:+d}")

    if total_original > 0:
        reduction_pct = (1 - total_new / total_original) * 100
        print(f"  Reduction:                  {reduction_pct:.1f}%")

    print(f"\n  Output files saved to: {output_dir}")
    for comp in all_comparisons:
        print(f"    - {comp['output_file']}")


if __name__ == "__main__":
    main()
