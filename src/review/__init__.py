"""
Shared extraction library and V1 candidate generator.

This package has two roles:

1. **Shared extraction library (used by V2 pipeline):**
   - ``false_positive_filter`` — FalsePositiveFilter, used by
     ``src/extraction_v2/stages/false_positive_filter.py``
   - ``number_parsing`` — NumberMatch, used by
     ``src/extraction_v2/stages/value_binding.py``
   - ``respectively_parser`` — detect_respectively_pattern, used by
     ``src/extraction_v2/stages/value_binding.py``
   - ``boundary_detection`` — BoundaryDetector, used by
     ``src/shared/html_segmenter.py``

2. **V1 candidate generator (legacy):**
   - ``candidate_generator``, ``helpers``, ``pattern_analyzer``,
     ``confidence_scoring``, ``feature_extraction`` — write to the
     legacy ``review_candidates`` table; used by gold-standard fresh
     extractor and legacy scripts. Scheduled for removal with the
     ``review_candidates`` table migration.

Do NOT rename or move the shared modules (role 1) without coordinating
changes in ``src/extraction_v2/`` and ``src/shared/``.
See ``src/review/README.md`` for full details.
"""

from src.review.candidate_generator import CandidateGenerator
from src.review.confidence_scoring import METRIC_EXPECTED_FORMATS, ConfidenceScorer
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
from src.review.feature_extractor import (
    DEFINITION_PATTERNS,
    PERIOD_PATTERNS,
    RISK_FACTORS_PATTERNS,
    FeatureExtractor,
    compute_features,
    determine_number_format,
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
    # Confidence scoring
    "ConfidenceScorer",
    "METRIC_EXPECTED_FORMATS",
    # Feature extraction
    "FeatureExtractor",
    "compute_features",
    "determine_number_format",
    "DEFINITION_PATTERNS",
    "PERIOD_PATTERNS",
    "RISK_FACTORS_PATTERNS",
    # Candidate generation
    "CandidateGenerator",
    # Deduplication
    "deduplicate_candidates",
]
