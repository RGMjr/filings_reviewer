"""
V2 Extraction Pipeline for SEC Filings Metric Extraction.

This module implements a unified extraction pipeline with:
- Structure-first extraction (DOM parsing before LLM)
- Full table reconstruction with colspan/rowspan resolution
- Image/chart extraction via OCR and vision models
- Complete provenance tracking via MetricFact and EvidencePack

Architecture:
    SEC HTML Filing
        ↓
    [Stage 1: Ingestion & Parsing] → Segments with XPath locators
        ↓
    [Stage 2: Section Classification] → MD&A, Risk Factors, etc.
        ↓
    [Stage 3: Table Reconstruction] → header_path, stub_path per cell
        ↓
    [Stage 4: Image Triage] → chart, table_image, decorative
        ↓
    [Stage 5: OCR & Chart Extraction] → labeled values only
        ↓
    [Stage 6: Metric Candidate Generation] → YAML taxonomy matching
        ↓
    [Stage 7: Value Binding] → structural link required
        ↓
    [Stage 8: Period Inference] → from header_path or context
        ↓
    [Stage 9: MetricFact Construction] → with evidence_pack
        ↓
    [Stage 10: Deduplication] → by identity tuple
        ↓
    [Stage 11: Validation & Review Routing] → confidence-based

Design Principles (from PRD synthesis):
    1. Structure-first, LLM-second: DOM parsing → rules → embedding → LLM fallback
    2. No value without provenance: Every MetricFact has evidence_pack
    3. Fail closed: Ambiguous extraction → flag for review, don't guess
    4. Charts only when labeled: Never interpolate from axis pixels

See: /Users/rgmarkey/.claude/plans/deep-conjuring-treehouse.md for full architecture
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
