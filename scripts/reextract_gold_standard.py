#!/usr/bin/env python3
"""
Re-extract all gold standard companies and compare with original extractions.

This script:
1. Reads each gold standard company's filing HTML
2. Runs the extraction pipeline with current code
3. Compares new extractions to original
4. Reports on what changed (especially rejected extractions)

Usage:
    python3 scripts/reextract_gold_standard.py
    python3 scripts/reextract_gold_standard.py --company "Samsara"
"""

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.extraction.html_segmenter import HTMLSegmenter
from src.extraction.metric_classifier import MetricClassifier
from src.extraction.value_extractor import ValueExtractor
from src.llm.openai_client import OpenAIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_gold_standard_companies(gold_dir: Path) -> list:
    """Load all gold standard company metadata."""
    companies = []
    for company_dir in gold_dir.iterdir():
        if not company_dir.is_dir():
            continue
        metadata_file = company_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
                metadata["company_dir"] = company_dir
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

    # Segment HTML
    segmenter = HTMLSegmenter()
    # Use a positive dummy filing_id to pass validation
    segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))
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


def compare_extractions(original: list, new: list) -> dict:
    """Compare original and new extractions."""
    comparison = {
        "original_count": len(original),
        "new_count": len(new),
        "by_metric": defaultdict(lambda: {"original": 0, "new": 0}),
    }

    for val in original:
        metric_id = val.get("metric_id", "unknown")
        comparison["by_metric"][metric_id]["original"] += 1

    for val in new:
        metric_id = val.metric_id
        comparison["by_metric"][metric_id]["new"] += 1

    return comparison


def main():
    parser = argparse.ArgumentParser(description="Re-extract gold standard companies")
    parser.add_argument("--company", help="Filter to specific company (partial match)")
    parser.add_argument("--dry-run", action="store_true", help="Don't use LLM, just show what would be extracted")
    args = parser.parse_args()

    # Paths
    base_dir = Path(__file__).parent.parent
    gold_dir = base_dir / "data" / "gold_standard"

    if not gold_dir.exists():
        print(f"Gold standard directory not found: {gold_dir}")
        return

    # Load companies
    companies = load_gold_standard_companies(gold_dir)
    logger.info(f"Found {len(companies)} gold standard companies")

    if args.company:
        companies = [c for c in companies if args.company.lower() in c["company_name"].lower()]
        logger.info(f"Filtered to {len(companies)} companies matching '{args.company}'")
    else:
        # Default to the new companies we care about
        targets = ["Slack Technologies", "Farfetch Ltd", "Samsara Vision Inc."]
        companies = [c for c in companies if c["company_name"] in targets]
        logger.info(f"Filtered to {len(companies)} target companies: {targets}")

    if not companies:
        print("No companies to process")
        return

    # Initialize LLM client
    if not args.dry_run:
        llm_client = OpenAIClient()
    else:
        llm_client = None

    # Process each company
    results = []
    for company in companies:
        print(f"\n{'='*60}")
        print(f"Processing: {company['company_name']}")
        print(f"{'='*60}")

        if "local_path" not in company:
            logger.warning(f"  Missing 'local_path' in metadata for {company['company_name']}, skipping.")
            continue

        html_path = base_dir / company["local_path"]

        # Load original extractions
        original = load_original_extractions(company["company_dir"])
        logger.info(f"  Original extractions: {len(original)}")

        if args.dry_run:
            print("  [DRY RUN - skipping extraction]")
            continue

        # Re-extract
        new_values = extract_from_filing(html_path, llm_client)

        # Compare
        comparison = compare_extractions(original, new_values)
        comparison["company"] = company["company_name"]
        results.append(comparison)

        # Print summary
        print(f"\n  Comparison:")
        print(f"    Original: {comparison['original_count']} extractions")
        print(f"    New:      {comparison['new_count']} extractions")
        print(f"    Change:   {comparison['new_count'] - comparison['original_count']:+d}")

        if comparison["by_metric"]:
            print(f"\n  By metric:")
            for metric_id, counts in sorted(comparison["by_metric"].items()):
                orig = counts["original"]
                new = counts["new"]
                change = new - orig
                if change != 0:
                    print(f"    {metric_id}: {orig} → {new} ({change:+d})")

    # Overall summary
    if results:
        print(f"\n{'='*60}")
        print("OVERALL SUMMARY")
        print(f"{'='*60}")

        total_original = sum(r["original_count"] for r in results)
        total_new = sum(r["new_count"] for r in results)

        print(f"Total original extractions: {total_original}")
        print(f"Total new extractions:      {total_new}")
        print(f"Net change:                 {total_new - total_original:+d}")

        if total_new < total_original:
            reduction_pct = (1 - total_new / total_original) * 100
            print(f"Reduction:                  {reduction_pct:.1f}%")
            print("\nThis reduction likely indicates the validation is rejecting bad extractions.")


if __name__ == "__main__":
    main()
