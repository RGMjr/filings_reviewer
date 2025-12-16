"""
Human-in-the-loop review system for metric extraction.

This module provides tools for:
- Generating candidate metrics for human review
- Recording review decisions
- Analyzing patterns in accepted vs rejected candidates
- Generating improved extraction rules
"""

from src.review.candidate_generator import CandidateGenerator
from src.review.config import (
    CandidateGenerationConfig,
    DEFAULT_CONFIG,
    DEFAULT_CONTEXT_WORDS,
    MAX_KEYWORD_DISTANCE,
    MIN_METRIC_VALUE,
    YEAR_MIN,
    YEAR_MAX,
)
from src.review.deduplicator import deduplicate_candidates
from src.review.confidence_scoring import ConfidenceScorer, METRIC_EXPECTED_FORMATS
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
