"""
Human-in-the-loop review system for metric extraction.

This module provides tools for:
- Generating candidate metrics for human review
- Recording review decisions
- Analyzing patterns in accepted vs rejected candidates
- Generating improved extraction rules
"""

from src.review.candidate_generator import (
    CandidateGenerator,
    generate_candidates_for_filing,
)
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
)

__all__ = [
    # Models
    "CandidateFeatures",
    "ReviewCandidate",
    "ReviewDecision",
    "LearnedPattern",
    "ProcessingStats",
    # Exceptions
    "CandidateGenerationError",
    "SegmentProcessingError",
    "NumberProcessingError",
    # Feature extraction
    "FeatureExtractor",
    "compute_features",
    "determine_number_format",
    "DEFINITION_PATTERNS",
    "PERIOD_PATTERNS",
    "RISK_FACTORS_PATTERNS",
    # Candidate generation
    "CandidateGenerator",
    "generate_candidates_for_filing",
]
