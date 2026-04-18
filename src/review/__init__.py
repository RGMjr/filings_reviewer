"""
Shared extraction library consumed by the V2 pipeline and web layer.

Key modules:
  - ``false_positive_filter`` — FalsePositiveFilter, used by
    ``src/extraction_v2/stages/false_positive_filter.py``.
  - ``number_parsing`` — NumberMatch / NumberParser, used by
    ``src/extraction_v2/stages/value_binding.py`` and V2 false-positive filter.
  - ``respectively_parser`` — detect_respectively_pattern, used by
    ``src/extraction_v2/stages/value_binding.py``.
  - ``boundary_detection`` — BoundaryDetector, used by
    ``src/shared/html_segmenter.py`` and keyword matching.
  - ``models`` — shared dataclasses and enum tuples imported by
    ``src/infra/db.py``, ``src/web/routes/api_unified.py``, and
    ``src/web/routes/review_unified.py``.

Do NOT rename or move these modules without coordinating changes in
``src/extraction_v2/``, ``src/shared/``, ``src/infra/``, and ``src/web/``.
"""

from src.review.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONTEXT_WORDS,
    MAX_KEYWORD_DISTANCE,
    MIN_METRIC_VALUE,
    YEAR_MAX,
    YEAR_MIN,
    CandidateGenerationConfig,
)
from src.review.deduplicator import deduplicate_candidates
from src.review.exceptions import (
    CandidateGenerationError,
    NumberProcessingError,
    SegmentProcessingError,
)
from src.review.models import (
    CandidateFeatures,
    LearnedPattern,
    ProcessingStats,
    ReviewCandidate,
    ReviewDecision,
    SegmentDict,
)

__all__ = [
    # Models
    "CandidateFeatures",
    "ReviewCandidate",
    "ReviewDecision",
    "LearnedPattern",
    "ProcessingStats",
    "SegmentDict",
    # Exceptions
    "CandidateGenerationError",
    "SegmentProcessingError",
    "NumberProcessingError",
    # Configuration
    "CandidateGenerationConfig",
    "DEFAULT_CONFIG",
    "DEFAULT_CONTEXT_WORDS",
    "MAX_KEYWORD_DISTANCE",
    "MIN_METRIC_VALUE",
    "YEAR_MIN",
    "YEAR_MAX",
    # Deduplication
    "deduplicate_candidates",
]
