"""
V1 metric extraction pipeline — DEPRECATED.

This package is retired. Active code should import from src.shared or
src.extraction_v2. The pipeline orchestration (ExtractionPipeline,
MetricClassifier, etc.) is dead code kept for historical reference.

Remaining known external dependency:
  src/gold_standard/fresh_extractor.py — uses HTMLSegmenter for V1-style
  re-segmentation during gold standard validation (intentional).
"""
