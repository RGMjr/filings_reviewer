#!/usr/bin/env python3
"""
Debug Extraction Timing

Tests the extraction pipeline with detailed timing information to identify bottlenecks.
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
from src.extraction.html_segmenter import HTMLSegmenter
from src.extraction.metric_classifier import MetricClassifier
from src.extraction.value_extractor import ValueExtractor
from src.extraction.definition_extractor import DefinitionExtractor
from src.extraction.quality_scorer import QualityScorer
from src.llm.openai_client import OpenAIClient


def time_stage(stage_name: str, func, *args, **kwargs):
    """Time a stage and print results."""
    print(f"\n{'='*80}")
    print(f"STAGE: {stage_name}")
    print(f"{'='*80}")
    start = time.time()
    result = func(*args, **kwargs)
    elapsed = time.time() - start
    print(f"✓ Completed in {elapsed:.2f} seconds")
    return result, elapsed


def main():
    """Debug extraction timing on a single filing."""

    # Setup
    api_key = os.getenv('OPENAI_API_KEY')
    db_url = os.getenv('DATABASE_URL')

    if not api_key or not db_url:
        print("ERROR: Missing OPENAI_API_KEY or DATABASE_URL")
        sys.exit(1)

    db = DatabaseAdapter(db_url)
    llm_client = OpenAIClient(api_key=api_key)

    # Get a small filing to test (SDMS, INC - known to be fast)
    test_filing = db.query("""
        SELECT
            f.filing_id,
            f.html_storage_path,
            c.company_name,
            c.cik
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE c.cik = '0001598580'  -- SDMS, INC
          AND f.processing_status = 'fetched'
        LIMIT 1
    """)

    if not test_filing:
        print("ERROR: Could not find test filing")
        sys.exit(1)

    filing = test_filing[0]
    filing_id = filing['filing_id']
    filing_path = Path(filing['html_storage_path'])

    print(f"\n{'='*80}")
    print(f"DEBUGGING EXTRACTION TIMING")
    print(f"{'='*80}")
    print(f"Company: {filing['company_name']}")
    print(f"CIK: {filing['cik']}")
    print(f"Filing ID: {filing_id}")
    print(f"Path: {filing_path}")
    print(f"{'='*80}\n")

    timings = {}

    # Stage 1: HTML Segmentation
    segmenter = HTMLSegmenter()
    segments, timings['segmentation'] = time_stage(
        "1. HTML Segmentation",
        segmenter.segment_filing,
        filing_id,
        str(filing_path)
    )
    print(f"   Total segments: {len(segments)}")

    # Stage 2: Metric Classification
    classifier = MetricClassifier()
    classified, timings['classification'] = time_stage(
        "2. Metric Classification",
        classifier.classify_batch,
        segments
    )
    print(f"   Classified segments: {len(classified)}")

    # Print classification breakdown
    from collections import Counter
    metric_counts = Counter(c.metric_id for c in classified)
    print(f"\n   Top 10 metrics found:")
    for metric_id, count in metric_counts.most_common(10):
        print(f"     {metric_id:40s}: {count:3d} segments")

    # Stage 3: Value Extraction (LLM calls)
    value_extractor = ValueExtractor(llm_client)
    values, timings['value_extraction'] = time_stage(
        "3. Value Extraction (LLM)",
        value_extractor.extract_values,
        classified,
        filing_id,
        filing['company_name']
    )
    print(f"   Values extracted: {len(values)}")

    # Stage 4: Definition Extraction (LLM calls)
    definition_extractor = DefinitionExtractor(llm_client)
    definitions, timings['definition_extraction'] = time_stage(
        "4. Definition Extraction (LLM)",
        definition_extractor.extract_definitions,
        classified,
        filing_id,
        filing['company_name']
    )
    print(f"   Definitions extracted: {len(definitions)}")

    # Stage 5: Quality Scoring
    scorer = QualityScorer()
    scored, timings['quality_scoring'] = time_stage(
        "5. Quality Scoring",
        scorer.score_incidences,
        classified,
        values,
        definitions
    )
    print(f"   Incidences scored: {len(scored)}")

    # Summary
    total_time = sum(timings.values())

    print(f"\n{'='*80}")
    print(f"TIMING SUMMARY")
    print(f"{'='*80}")
    print(f"{'Stage':<40s} {'Time (s)':>10s} {'% of Total':>10s}")
    print(f"{'-'*80}")

    for stage, elapsed in timings.items():
        pct = (elapsed / total_time * 100) if total_time > 0 else 0
        print(f"{stage:<40s} {elapsed:>10.2f} {pct:>9.1f}%")

    print(f"{'-'*80}")
    print(f"{'TOTAL':<40s} {total_time:>10.2f} {100.0:>9.1f}%")
    print(f"{'='*80}\n")

    # Analysis
    print(f"\n{'='*80}")
    print(f"BOTTLENECK ANALYSIS")
    print(f"{'='*80}")

    slowest = max(timings.items(), key=lambda x: x[1])
    print(f"Slowest stage: {slowest[0]} ({slowest[1]:.2f}s)")

    if slowest[1] > 60:
        print(f"⚠️  WARNING: {slowest[0]} took over 1 minute!")
        print(f"   This stage is likely the bottleneck causing extraction failures.")

    if timings.get('value_extraction', 0) + timings.get('definition_extraction', 0) > 0.8 * total_time:
        print(f"\n⚠️  LLM stages account for {(timings.get('value_extraction', 0) + timings.get('definition_extraction', 0))/total_time*100:.1f}% of total time")
        print(f"   Consider:")
        print(f"   - Reducing number of segments sent to LLM")
        print(f"   - Increasing confidence threshold in classifier")
        print(f"   - Batching LLM calls more efficiently")

    if timings.get('classification', 0) > 0.3 * total_time:
        print(f"\n⚠️  Classification stage took {timings.get('classification', 0):.2f}s ({timings.get('classification', 0)/total_time*100:.1f}%)")
        print(f"   Phase 1 keyword expansion may be causing excessive pattern matching")
        print(f"   {len(classified)} segments classified - may be too many")

    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
