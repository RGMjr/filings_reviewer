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

    max_keyword_distance: int = 120
    """Maximum character distance between number and metric keyword."""

    # =========================================================================
    # L4 Enhancement: Post-Value Keyword Distance Multiplier
    # =========================================================================

    post_value_distance_multiplier: float = 0.9
    """Base multiplier applied to effective distance for keywords appearing AFTER values.

    SEC filings typically list metrics BEFORE their values (e.g., "Net Revenue of $1.2M").
    When keywords are equidistant from a number, this multiplier gives preference to
    pre-value keywords. A value of 0.9 means post-value keywords need to be 10% closer
    to win. L4 enhancement.

    Note: Context-dependent multipliers override this base value when specific patterns
    are detected (parenthetical text, tables, etc.)."""

    # =========================================================================
    # L4 Context-Dependent Multipliers (Option C Implementation)
    # =========================================================================

    use_context_dependent_multipliers: bool = True
    """Enable context-dependent multiplier logic. When True, different multipliers
    are applied based on the textual context (bullets, tables, parentheticals).
    When False, uses post_value_distance_multiplier for all contexts. L4 enhancement."""

    # Context-specific multipliers (applied to post-value keywords)
    # Values < 1.0 penalize post-value (prefer pre-value)
    # Values > 1.0 boost post-value (prefer post-value)
    # Value = 1.0 means no preference

    multiplier_bullet_points: float = 0.9
    """Multiplier for post-value keywords in bullet points.
    Bullet points typically list metrics before values. Default: 0.9 (prefer pre-value)."""

    multiplier_parenthetical: float = 1.15
    """Multiplier for post-value keywords in parenthetical text.
    Parentheticals often clarify values: "33% (gross margin)".
    Default: 1.15 (prefer post-value)."""

    multiplier_tables: float = 0.85
    """Multiplier for post-value keywords in tables.
    Table headers appear before/above values. Default: 0.85 (strong pre-value preference)."""

    multiplier_copula_verb: float = 0.9
    """Multiplier for post-value keywords in sentences with copula verbs (is/was/were).
    "Gross margin was 33%" structure puts metric before value.
    Default: 0.9 (prefer pre-value)."""

    multiplier_preposition: float = 1.1
    """Multiplier for post-value keywords in prepositional phrases.
    "33% of revenue" or "33% for margin" puts metric after value.
    Default: 1.1 (prefer post-value)."""

    multiplier_default: float = 0.9
    """Default multiplier when no specific context detected.
    Default: 0.9 (slight pre-value preference)."""

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

    metric_distance_overrides: dict[str, int] = field(default_factory=dict)
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
    # L2 Enhancement: Table of Contents Filtering Settings
    # =========================================================================

    toc_proximity_chars: int = 300
    """Character distance to search backwards for TOC headers. L2 enhancement."""

    toc_dot_leader_window: int = 50
    """Character distance to search backwards for dot leader patterns. L2 enhancement."""

    # =========================================================================
    # HRV-10/HRV-11: Financial Statement Filtering Settings (2025-12-26)
    # =========================================================================

    filter_financial_statements: bool = True
    """Whether to filter financial statement line items (income statement, balance sheet, cash flow).

    HRV-10/HRV-11 enhancement: Detects financial statement contexts and filters out
    accounting line items (Revenue, Cost of Revenue, Total Assets, etc.) that are
    not customer metrics. Eliminates ~60% of false positives in typical S-1 filings."""

    financial_statement_proximity_chars: int = 500
    """Character distance to search backwards for financial statement headers. HRV-10 enhancement."""

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

    confidence_format_mismatch_penalty: float = 0.25
    """Penalty when number format conflicts with metric expectation.

    Applied when a metric has expected formats defined but the number's
    format doesn't match. For example, currency values ($94,348) matched
    to margin metrics (which expect percentages) receive this penalty.
    This helps filter false positives where "gross profit" values are
    incorrectly matched to "gross profit margin" keywords.
    """

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
    # P1.5 Sentence Detection Settings
    # =========================================================================

    detect_sentences: bool = True
    """Enable sentence boundary detection. P1.5 enhancement."""

    respect_sentence_boundaries: bool = True
    """Filter keywords from different sentences than the number. P1.5 enhancement."""

    sentence_detection_for_tables: bool = False
    """Enable sentence detection for table segments. Default False (high FN risk)."""

    # =========================================================================
    # P1.6 Same-Sentence Deduplication Preference
    # =========================================================================

    prefer_same_sentence_in_dedup: bool = True
    """Prefer same-sentence matches during deduplication. P1.6 enhancement.

    When True, candidates where the keyword and value are in the same sentence
    are preferred over cross-sentence matches during deduplication, even if
    the cross-sentence match has slightly higher confidence. This reduces
    false positives where a value is incorrectly associated with a metric
    keyword from a subsequent sentence.

    When False, deduplication uses pure confidence-based selection."""

    # =========================================================================
    # L1 Respectively Pattern Detection Settings
    # =========================================================================

    detect_respectively_patterns: bool = False
    """Enable detection of 'respectively' patterns for period association. L1 enhancement.

    Off by default for gradual rollout. When enabled, patterns like:
    "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively"
    will enrich candidates with detected_period field."""

    respectively_min_confidence: float = 0.6
    """Minimum confidence threshold for respectively pattern enrichment. L1 enhancement.

    Range: 0.5-1.0
    - 0.9-1.0: Very high - Perfect pattern structure
    - 0.8-0.9: High - Strong pattern structure
    - 0.7-0.8: Medium - Adequate pattern structure
    - 0.5-0.7: Low - Manual review recommended"""

    detect_all_respectively_patterns: bool = True
    """Enable detection of ALL respectively patterns in a segment (L1-P1.2).

    When False: Only first pattern detected (backward compatible)
    When True: All patterns detected (15-25% recall improvement)

    Real-world filings average 1.4 patterns per segment with 'respectively'.
    Default: True (recommended for production)"""

    # =========================================================================
    # Performance Tuning Settings
    # =========================================================================

    batch_size: int = 100
    """Batch size for database operations."""

    cache_word_positions: bool = True
    """Whether to cache word positions for context extraction (P1.2 optimization)."""

    def to_confidence_weights(self) -> dict[str, float]:
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
            "format_mismatch_penalty": self.confidence_format_mismatch_penalty,
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
        # P1.5 enhancements (enabled for precision)
        detect_sentences=True,
        respect_sentence_boundaries=True,
        sentence_detection_for_tables=False,
        # P1.6 enhancement (enabled for precision)
        prefer_same_sentence_in_dedup=True,
        # L1 enhancements (enabled with high confidence threshold)
        detect_respectively_patterns=True,
        respectively_min_confidence=0.7,  # Higher threshold for precision
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
        # P1.5 enhancements (disabled for recall - want all matches)
        detect_sentences=False,
        respect_sentence_boundaries=False,
        sentence_detection_for_tables=False,
        # P1.6 enhancement (disabled for recall - use pure confidence)
        prefer_same_sentence_in_dedup=False,
        # L1 enhancements (enabled with low threshold for recall)
        detect_respectively_patterns=True,
        respectively_min_confidence=0.5,  # Lower threshold for recall
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
        # P1.5 enhancements (disabled for speed)
        detect_sentences=False,
        respect_sentence_boundaries=False,
        sentence_detection_for_tables=False,
        # P1.6 enhancement (enabled - no performance cost)
        prefer_same_sentence_in_dedup=True,
        # L1 enhancements (disabled for speed)
        detect_respectively_patterns=False,  # Skip pattern detection
    )
