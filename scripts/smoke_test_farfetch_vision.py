#!/usr/bin/env python3
"""Smoke test: run V2 pipeline with image/chart extraction on Farfetch filing."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from src.extraction_v2.models import SourceType  # noqa: E402
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig  # noqa: E402

config = PipelineConfig(
    enable_image_extraction=True,
    enable_chart_extraction=True,
    vision_provider="claude",
    vision_model="claude-haiku-4-5-20251001",
    min_confidence_auto_accept=0.80,
)
pipeline = V2Pipeline(config=config)

filing_path = PROJECT_ROOT / "data" / "gold_standard" / "Farfetch_Limited" / "filing.html"
print(f"Processing: {filing_path}")
result = pipeline.process(html_path=filing_path, filing_id=0)

print(f"\nStatus: {'SUCCESS' if result.success else 'FAILED'}")
print(f"Duration: {result.total_duration_ms:,}ms")
print(f"Facts: {result.fact_count} total ({result.auto_accepted_count} auto-accepted, {result.pending_review_count} pending)")
print(f"Images: {len(result.images)}, Tables: {len(result.tables)}")

# Image results
print("\n--- Image Results ---")
for img in result.images:
    line = f"  {img.filename:<30} {img.classification.value:<12} rel={img.relevance_score:.2f}"
    if img.extraction_meta:
        m = img.extraction_meta
        line += f"  model={m.vision_model or '-'}  cost=${m.cost_usd or 0:.4f}  skip={m.skip_reason or 'none'}"
    print(line)

# All facts
print("\n--- Facts ---")
for fact in sorted(result.facts, key=lambda f: f.canonical_metric_id):
    src = "chart" if fact.source_type == SourceType.CHART else "text"
    print(f"  [{src}] {fact.canonical_metric_id:<35} {str(fact.value):<15} conf={fact.confidence:.2f}")

if result.error_message:
    print(f"\nError: {result.error_message}")
for sr in result.stage_results:
    if not sr.success:
        print(f"  Stage {sr.stage.value} FAILED: {sr.errors}")
