"""
Configuration for candidate generation and review system.

This module centralizes all configuration constants for the review system,
providing a single source of truth for tuning and customization.

Basic Usage:
    >>> from src.review import CandidateGenerator
    >>> from src.review.config import DEFAULT_CONFIG
    >>>
    >>> # Use default configuration
    >>> generator = CandidateGenerator()  # Uses DEFAULT_CONFIG internally
    >>> print(generator.config.max_keyword_distance)  # 100

Configuration Presets:
    >>> from src.review.config import (
    ...     get_high_precision_config,
    ...     get_high_recall_config,
    ...     get_fast_config,
    ... )
    >>>
    >>> # Minimize false positives
    >>> hp_generator = CandidateGenerator(config=get_high_precision_config())
    >>>
    >>> # Maximize recall (catch all potential metrics)
    >>> hr_generator = CandidateGenerator(config=get_high_recall_config())
    >>>
    >>> # Optimize for speed
    >>> fast_generator = CandidateGenerator(config=get_fast_config())

Custom Configuration:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Adjust parameters for your use case
    >>> custom_config = CandidateGenerationConfig(
    ...     max_keyword_distance=75,       # Moderate proximity
    ...     min_metric_value=50,           # Filter small numbers
    ...     apply_learned_rules=True,      # Use learned patterns
    ...     min_pattern_precision=0.80,    # High-confidence patterns
    ... )
    >>> generator = CandidateGenerator(config=custom_config)

Production Tuning:
    >>> # Start with a preset, then tune based on precision/recall metrics
    >>> config = get_high_precision_config()
    >>> config.max_keyword_distance = 75  # Adjust after testing
    >>> config.min_pattern_precision = 0.90  # Even stricter patterns
    >>> generator = CandidateGenerator(config=config)

See Also:
    - candidate_generator.CandidateGenerator for usage
    - helpers.generate_candidates_for_filing() for convenience wrapper
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CandidateGenerationConfig:
    """
    Configuration for candidate generation and review.

    This dataclass centralizes all tunable parameters for the review system,
    making it easier to experiment with different configurations and maintain
    consistency across components.
    """

    # =========================================================================
    # Keyword Proximity Settings
    # =========================================================================

    max_keyword_distance: int = 100
    """Maximum character distance between number and metric keyword."""

    # =========================================================================
    # P1 Enhancement Settings (Boundary Detection & Closest Keyword)
    # =========================================================================

    prefer_closest_keyword: bool = True
    """Sort by distance first (closest), then length (longest). P1 enhancement."""

    respect_bullet_boundaries: bool = True
    """Prefer keywords in same semantic boundary as number. P1 enhancement."""

    enable_boundary_detection: bool = True
    """Enable semantic boundary detection (bullets, lists, paragraphs). P1 enhancement."""

    log_ambiguous_matches: bool = True
    """Log when multiple keywords are equally close to a number. P1 enhancement."""

    ambiguity_threshold: int = 10
    """Character distance to consider keywords "equally close" for ambiguity logging."""

    metric_distance_overrides: Dict[str, int] = field(default_factory=dict)
    """Optional per-metric distance overrides. Format: {metric_id: distance}. For future use."""

    # =========================================================================
    # Context Extraction Settings
    # =========================================================================

    context_words: int = 40
    """Number of words to extract each direction from target position for context."""

    # =========================================================================
    # False Positive Filtering Settings
    # =========================================================================

    min_metric_value: int = 10
    """Minimum numeric value to consider as a metric (filters single-digit numbers)."""

    year_min: int = 1990
    """Minimum year value for filtering (numbers in year range filtered as dates)."""

    year_max: int = 2100
    """Maximum year value for filtering (numbers in year range filtered as dates)."""

    filter_false_positives: bool = True
    """Whether to apply false positive filtering (dates, years, page refs, etc.)."""

    filter_years: bool = True
    """Whether to filter numbers that look like years (1990-2100)."""

    # =========================================================================
    # Confidence Scoring Weights
    # =========================================================================

    confidence_base_score: float = 0.30
    """Starting confidence score for any candidate."""

    confidence_distance_max_weight: float = 0.25
    """Maximum bonus for close keyword distance."""

    confidence_position_before_bonus: float = 0.05
    """Bonus if keyword appears before the number."""

    confidence_definition_bonus: float = 0.20
    """Bonus for definition language ("we define X as...")."""

    confidence_period_bonus: float = 0.05
    """Bonus for period mentions (time context)."""

    confidence_format_match_bonus: float = 0.10
    """Bonus if number format matches metric type expectation."""

    confidence_specific_keyword_bonus: float = 0.10
    """Bonus for multi-word specific keywords."""

    confidence_risk_factors_penalty: float = 0.25
    """Penalty for risk factors section (high false positive area)."""

    confidence_surrounding_numbers_penalty_max: float = 0.15
    """Maximum penalty for many surrounding numbers (ambiguous context)."""

    confidence_table_ambiguity_penalty: float = 0.05
    """Penalty for table context without definition language."""

    # =========================================================================
    # Feature Computation Settings
    # =========================================================================

    compute_confidence: bool = True
    """Whether to compute confidence scores (can disable for performance)."""

    # =========================================================================
    # E2 Learned Rules Settings
    # =========================================================================

    apply_learned_rules: bool = True
    """Whether to apply learned patterns from E2 to filter candidates."""

    min_pattern_precision: float = 0.75
    """Minimum precision for learned patterns to be applied."""

    # =========================================================================
    # Performance Tuning Settings
    # =========================================================================

    batch_size: int = 100
    """Batch size for database operations."""

    cache_word_positions: bool = True
    """Whether to cache word positions for context extraction (P1.2 optimization)."""

    def to_confidence_weights(self) -> Dict[str, float]:
        """
        Export confidence scoring weights as a dictionary.

        Returns:
            Dictionary mapping weight names to values, for passing to ConfidenceScorer
        """
        return {
            "base_score": self.confidence_base_score,
            "distance_max_weight": self.confidence_distance_max_weight,
            "position_before_bonus": self.confidence_position_before_bonus,
            "definition_bonus": self.confidence_definition_bonus,
            "period_bonus": self.confidence_period_bonus,
            "format_match_bonus": self.confidence_format_match_bonus,
            "specific_keyword_bonus": self.confidence_specific_keyword_bonus,
            "risk_factors_penalty": self.confidence_risk_factors_penalty,
            "surrounding_numbers_penalty_max": self.confidence_surrounding_numbers_penalty_max,
            "table_ambiguity_penalty": self.confidence_table_ambiguity_penalty,
        }


# =============================================================================
# Default Configuration Instance
# =============================================================================

DEFAULT_CONFIG = CandidateGenerationConfig()
"""
Default configuration instance with production-tuned values.

Use this for standard candidate generation workflows. For custom configurations,
create a new instance of CandidateGenerationConfig with desired parameters.
"""


# =============================================================================
# Backward Compatibility Exports
# =============================================================================

# Export individual constants for backward compatibility
# (allows existing code to import directly without refactoring)

MAX_KEYWORD_DISTANCE = DEFAULT_CONFIG.max_keyword_distance
DEFAULT_CONTEXT_WORDS = DEFAULT_CONFIG.context_words
MIN_METRIC_VALUE = DEFAULT_CONFIG.min_metric_value
YEAR_MIN = DEFAULT_CONFIG.year_min
YEAR_MAX = DEFAULT_CONFIG.year_max


# =============================================================================
# Configuration Presets
# =============================================================================


def get_high_precision_config() -> CandidateGenerationConfig:
    """
    Configuration optimized for high precision (fewer false positives).

    Use when you want to minimize review burden at cost of some recall.
    Stricter proximity, higher minimum values, and higher pattern precision.

    Returns:
        CandidateGenerationConfig instance tuned for high precision
    """
    return CandidateGenerationConfig(
        max_keyword_distance=50,  # Stricter proximity requirement
        min_metric_value=100,  # Filter small numbers more aggressively
        filter_false_positives=True,
        filter_years=True,
        apply_learned_rules=True,
        min_pattern_precision=0.85,  # Only use high-confidence patterns
        compute_confidence=True,
        cache_word_positions=True,
        # P1 enhancements (all enabled for precision)
        prefer_closest_keyword=True,
        respect_bullet_boundaries=True,
        enable_boundary_detection=True,
        log_ambiguous_matches=True,
        ambiguity_threshold=5,  # Stricter threshold for high precision
    )


def get_high_recall_config() -> CandidateGenerationConfig:
    """
    Configuration optimized for high recall (more candidates).

    Use when you want to catch all potential metrics at cost of more false positives.
    Looser proximity, lower minimum values, and disabled filtering.

    Returns:
        CandidateGenerationConfig instance tuned for high recall
    """
    return CandidateGenerationConfig(
        max_keyword_distance=150,  # Looser proximity allows distant matches
        min_metric_value=1,  # Keep all numbers, even small ones
        filter_false_positives=False,  # Disable false positive filtering
        filter_years=False,  # Don't filter year-like numbers
        apply_learned_rules=False,  # Don't apply learned filtering
        compute_confidence=True,  # Still compute confidence for ranking
        cache_word_positions=True,
        # P1 enhancements (disabled for recall - want all matches)
        prefer_closest_keyword=False,  # Keep all matches regardless of distance
        respect_bullet_boundaries=False,  # Allow cross-boundary matches
        enable_boundary_detection=False,  # Don't detect boundaries
        log_ambiguous_matches=False,  # Reduce logging noise
        ambiguity_threshold=20,  # Larger threshold when logging is enabled
    )


def get_fast_config() -> CandidateGenerationConfig:
    """
    Configuration optimized for speed.

    Use for quick prototyping or when performance matters more than quality.
    Disables expensive computations like confidence scoring and boundary detection.

    Returns:
        CandidateGenerationConfig instance tuned for speed
    """
    return CandidateGenerationConfig(
        max_keyword_distance=100,  # Standard proximity
        min_metric_value=10,  # Standard minimum
        filter_false_positives=True,  # Keep basic filtering
        filter_years=True,
        apply_learned_rules=False,  # Skip pattern matching (can be slow)
        compute_confidence=False,  # Skip confidence computation (expensive)
        cache_word_positions=True,  # Enable caching for speed
        # P1 enhancements (minimal for speed)
        prefer_closest_keyword=True,  # Lightweight sorting improvement
        respect_bullet_boundaries=False,  # Skip boundary filtering (adds overhead)
        enable_boundary_detection=False,  # Skip boundary detection (adds overhead)
        log_ambiguous_matches=False,  # Skip logging (reduces I/O)
        ambiguity_threshold=10,  # Standard threshold
    )
