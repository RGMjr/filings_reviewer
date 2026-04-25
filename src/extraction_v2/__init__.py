"""
V2 Extraction Pipeline for SEC Filings Metric Extraction.

Extracts metric **presence** (with advisory values where available) from SEC
filings. Primary output is per-(doc_id, canonical_metric_id) presence rows in
``v2_text_metric_presence``; per-value ``MetricFact`` rows are advisory
evidence under the chart-presence pivot (#86, 2026-04-23) and text-presence
pivot PR1 (#182). See ``docs/operations/text-pipeline-presence-pivot-plan.md``.

Pipeline stages (image stages and IMAGE_CLASSIFY are conditional):
    1. Ingestion & Parsing         → Segments with XPath locators
    2. Section Classification      → MD&A, Risk Factors, etc.
    3. Table Reconstruction        → header_path, stub_path per cell
    4. Image Triage                → chart, table_image, decorative
    5. OCR & Chart Extraction      → labeled values only
    5a. Chart Fact Bridge          → presence pairs to v2_image_assets.detected_metrics
    5b. Image Classify             → Vision metric-classifier; appends to v2_image_classifications
                                     (gated by ENABLE_METRIC_CLASSIFY)
    6. Metric Candidate Generation → YAML taxonomy matching
    7. Value Binding               → structural link required
    7.5. False Positive Filter     → 13 rule-based suppression rules
    8. Period Inference            → from header_path or context
    9. MetricFact Construction     → with evidence_pack
    9.5. Definition Extraction     → methodology / definition segments
    10. Deduplication              → by identity tuple
    11. Validation & Review Routing → confidence-based
    12. MetricPresenceStage (final) → aggregate facts/charts/definitions
                                     → v2_text_metric_presence (primary scoring surface)

Design Principles:
    1. Presence-first, values advisory: presence is the headline output;
       per-value facts are advisory evidence.
    2. Structure-first, LLM-second: DOM parsing → rules → embedding → LLM fallback.
    3. No claim without provenance: Every presence row carries
       evidence_segment_ids + advisory_fact_ids; every MetricFact has evidence_pack.
    4. Fail closed: Ambiguous extraction → flag for review, don't guess.
    5. Charts only when labeled: Never interpolate from axis pixels.
"""

__version__ = "2.0.0-rc1"

# Exceptions
from src.extraction_v2.exceptions import (
    ReviewedFilingError,
    V2FatalError,
    V2PipelineError,
    V2StageError,
    V2TransientError,
)

# Persistence layer
from src.extraction_v2.persistence import (
    PersistenceResult,
    V2PersistenceAdapter,
)

__all__ = [
    "ReviewedFilingError",
    "V2FatalError",
    "V2PipelineError",
    "V2StageError",
    "V2TransientError",
    "PersistenceResult",
    "V2PersistenceAdapter",
]
