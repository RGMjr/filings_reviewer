"""
Formula configuration for segment enrichment scoring.

This module provides a configurable dataclass for all formula weights used
in richness score calculation. By centralizing constants here, we enable:
- A/B testing different weight combinations
- Easy experimentation without code changes
- Better documentation of formula components
- Simpler unit testing of formula variations

Created as part of GR-11 refactoring task.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormulaWeights:
    """
    Configurable weights for richness score calculation.

    All weights are frozen (immutable) after construction to prevent
    accidental modification during processing. Use the class methods
    to create preset configurations.

    Formula structure (theoretical max ~17.0, capped at 10.0):
    - Base confidence: classifier_confidence * confidence_multiplier
    - Metric density: min(metric_count * metric_count_multiplier, metric_count_cap)
    - Boolean flags: temporal, cohort, retention, SaaS, engagement, conversion
    - Tiered bonuses: definition, usage, platform (3 tiers each)
    - High-value metrics: high_value_per_metric * count (capped)
    - Images: min(image_count * image_multiplier, image_cap)

    Example:
        >>> weights = FormulaWeights.default()
        >>> weights.usage_with_count_bonus
        1.0
        >>> custom = FormulaWeights(usage_with_count_bonus=1.5)
        >>> custom.usage_with_count_bonus
        1.5
    """

    # =========================================================================
    # Base Score Multipliers
    # =========================================================================

    # Classifier confidence multiplier (max contribution: 3.0 = 1.0 * 3.0)
    confidence_multiplier: float = 3.0

    # Metric count multiplier and cap (max contribution: 2.0)
    metric_count_multiplier: float = 0.5
    metric_count_cap: float = 2.0

    # Image count multiplier and cap (max contribution: 1.5)
    image_multiplier: float = 0.5
    image_cap: float = 1.5

    # =========================================================================
    # Boolean Flag Bonuses
    # =========================================================================

    # Temporal trend bonus: segment discusses multiple time periods
    temporal_trend_bonus: float = 1.0

    # Cohort breakdown bonus: segment contains cohort analysis patterns
    cohort_breakdown_bonus: float = 1.5

    # Combination bonus: BOTH temporal AND cohort present
    temporal_cohort_combo_bonus: float = 0.5

    # Retention keyword bonus: NRR/NDRR/gross retention keywords
    retention_keyword_bonus: float = 1.0

    # SaaS indicator bonus: SaaS-specific terminology
    saas_indicator_bonus: float = 0.5

    # Engagement keyword bonus: session/time/engagement metrics (GR-7)
    engagement_keyword_bonus: float = 0.5

    # Conversion keyword bonus: conversion rate metrics (GR-7)
    conversion_keyword_bonus: float = 0.5

    # =========================================================================
    # Definition Bonus Tiers (GI-9)
    # =========================================================================

    # High-value metric definition (NRR, LTV, CAC, etc.)
    definition_high_value_bonus: float = 2.0

    # Definition with metric context (distinct_metric_count >= 2)
    definition_with_context_bonus: float = 1.5

    # Basic definition flag only
    definition_basic_bonus: float = 1.0

    # =========================================================================
    # Usage Keyword Bonus Tiers (GI-6, GI-10)
    # =========================================================================

    # Usage metric with numeric value (e.g., "10 million DAU")
    usage_with_count_bonus: float = 1.0

    # Usage keyword with definition or metric context
    usage_with_context_bonus: float = 0.75

    # Basic usage keyword only (DAU/MAU/WAU without context)
    usage_basic_bonus: float = 0.5

    # =========================================================================
    # Platform/Marketplace Bonus Tiers (GR-6)
    # =========================================================================

    # Platform metric with numeric value (e.g., "50M active listings")
    platform_with_count_bonus: float = 1.0

    # Platform keyword with definition or metric context
    platform_with_context_bonus: float = 0.75

    # Basic platform keyword only
    platform_basic_bonus: float = 0.5

    # =========================================================================
    # High-Value Metric Bonus (GI-7)
    # =========================================================================

    # Bonus per high-value metric (NRR, LTV/CAC, retention, cohort)
    high_value_per_metric: float = 0.5

    # Cap for high-value metric bonus
    high_value_cap: float = 1.5

    # =========================================================================
    # Score Boundaries
    # =========================================================================

    # Maximum richness score (final score is capped at this value)
    score_cap: float = 10.0

    # Goldmine threshold (segments >= this are considered goldmines)
    goldmine_threshold: float = 5.5

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def default(cls) -> FormulaWeights:
        """
        Return default weights matching current production behavior.

        These values match the hardcoded constants in segment_enricher.py
        prior to GR-11 refactoring. Using these weights produces identical
        richness scores to the original implementation.

        Returns:
            FormulaWeights with production defaults
        """
        return cls()

    @classmethod
    def high_precision(cls) -> FormulaWeights:
        """
        Return weights tuned for high precision (fewer false positives).

        Reduces bonuses for basic keyword matches while maintaining
        full credit for rich disclosures with numeric values.
        Useful for workflows prioritizing precision over recall.

        Returns:
            FormulaWeights with precision-focused adjustments
        """
        return cls(
            usage_basic_bonus=0.25,
            platform_basic_bonus=0.25,
            saas_indicator_bonus=0.25,
            engagement_keyword_bonus=0.25,
            conversion_keyword_bonus=0.25,
        )

    @classmethod
    def high_recall(cls) -> FormulaWeights:
        """
        Return weights tuned for high recall (fewer false negatives).

        Increases bonuses for keyword matches to capture more
        borderline segments. Useful for exploratory analysis
        or when recall is prioritized over precision.

        Returns:
            FormulaWeights with recall-focused adjustments
        """
        return cls(
            usage_basic_bonus=0.75,
            platform_basic_bonus=0.75,
            definition_basic_bonus=1.5,
            goldmine_threshold=5.0,
        )

    def __post_init__(self) -> None:
        """Validate weights after construction."""
        # Validate non-negative for all bonus values
        for field_name in [
            "confidence_multiplier",
            "metric_count_multiplier",
            "metric_count_cap",
            "image_multiplier",
            "image_cap",
            "temporal_trend_bonus",
            "cohort_breakdown_bonus",
            "temporal_cohort_combo_bonus",
            "retention_keyword_bonus",
            "saas_indicator_bonus",
            "engagement_keyword_bonus",
            "conversion_keyword_bonus",
            "definition_high_value_bonus",
            "definition_with_context_bonus",
            "definition_basic_bonus",
            "usage_with_count_bonus",
            "usage_with_context_bonus",
            "usage_basic_bonus",
            "platform_with_count_bonus",
            "platform_with_context_bonus",
            "platform_basic_bonus",
            "high_value_per_metric",
            "high_value_cap",
            "score_cap",
            "goldmine_threshold",
        ]:
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"FormulaWeights.{field_name} must be non-negative, got {value}")
