"""
Unit tests for configuration module.

Tests for configuration dataclass, presets, and P1 enhancements.
"""

import pytest

from src.review.config import (
    CandidateGenerationConfig,
    DEFAULT_CONFIG,
    get_high_precision_config,
    get_high_recall_config,
    get_fast_config,
)


class TestCandidateGenerationConfig:
    """Tests for CandidateGenerationConfig dataclass."""

    def test_default_configuration_has_p1_parameters(self):
        """Default configuration should include P1 enhancement parameters."""
        config = CandidateGenerationConfig()

        # P1 parameters should be present with default values
        assert hasattr(config, "prefer_closest_keyword")
        assert hasattr(config, "respect_bullet_boundaries")
        assert hasattr(config, "enable_boundary_detection")
        assert hasattr(config, "log_ambiguous_matches")
        assert hasattr(config, "ambiguity_threshold")
        assert hasattr(config, "metric_distance_overrides")

        # Default values should enable P1 features
        assert config.prefer_closest_keyword is True
        assert config.respect_bullet_boundaries is True
        assert config.enable_boundary_detection is True
        assert config.log_ambiguous_matches is True
        assert config.ambiguity_threshold == 10
        assert config.metric_distance_overrides == {}

    def test_p1_parameters_can_be_customized(self):
        """P1 parameters should be customizable."""
        config = CandidateGenerationConfig(
            prefer_closest_keyword=False,
            respect_bullet_boundaries=False,
            enable_boundary_detection=False,
            log_ambiguous_matches=False,
            ambiguity_threshold=5,
            metric_distance_overrides={"cm_arr": 50},
        )

        assert config.prefer_closest_keyword is False
        assert config.respect_bullet_boundaries is False
        assert config.enable_boundary_detection is False
        assert config.log_ambiguous_matches is False
        assert config.ambiguity_threshold == 5
        assert config.metric_distance_overrides == {"cm_arr": 50}

    def test_default_config_instance(self):
        """DEFAULT_CONFIG should be a valid configuration instance."""
        assert isinstance(DEFAULT_CONFIG, CandidateGenerationConfig)
        assert DEFAULT_CONFIG.max_keyword_distance == 100
        assert DEFAULT_CONFIG.prefer_closest_keyword is True
        assert DEFAULT_CONFIG.respect_bullet_boundaries is True

    def test_to_confidence_weights(self):
        """to_confidence_weights() should export weight dictionary."""
        config = CandidateGenerationConfig()
        weights = config.to_confidence_weights()

        # Should be a dictionary
        assert isinstance(weights, dict)

        # Should contain expected keys
        expected_keys = {
            "base_score",
            "distance_max_weight",
            "position_before_bonus",
            "definition_bonus",
            "period_bonus",
            "format_match_bonus",
            "specific_keyword_bonus",
            "risk_factors_penalty",
            "surrounding_numbers_penalty_max",
            "table_ambiguity_penalty",
        }
        assert set(weights.keys()) == expected_keys


class TestConfigurationPresets:
    """Tests for configuration presets."""

    def test_high_precision_preset_enables_p1_features(self):
        """High precision preset should enable all P1 features."""
        config = get_high_precision_config()

        # Should enable P1 enhancements for better precision
        assert config.prefer_closest_keyword is True
        assert config.respect_bullet_boundaries is True
        assert config.enable_boundary_detection is True
        assert config.log_ambiguous_matches is True

        # Should have stricter ambiguity threshold
        assert config.ambiguity_threshold == 5

        # Other high-precision settings
        assert config.max_keyword_distance == 50
        assert config.min_metric_value == 100
        assert config.min_pattern_precision == 0.85

    def test_high_recall_preset_disables_p1_features(self):
        """High recall preset should disable P1 features to maximize recall."""
        config = get_high_recall_config()

        # Should disable P1 enhancements to maximize recall
        assert config.prefer_closest_keyword is False
        assert config.respect_bullet_boundaries is False
        assert config.enable_boundary_detection is False
        assert config.log_ambiguous_matches is False

        # Larger ambiguity threshold when enabled
        assert config.ambiguity_threshold == 20

        # Other high-recall settings
        assert config.max_keyword_distance == 150
        assert config.min_metric_value == 1
        assert config.filter_false_positives is False

    def test_fast_preset_minimizes_overhead(self):
        """Fast preset should minimize computational overhead."""
        config = get_fast_config()

        # Should disable expensive P1 features
        assert config.respect_bullet_boundaries is False  # Skip boundary filtering
        assert config.enable_boundary_detection is False  # Skip boundary detection
        assert config.log_ambiguous_matches is False  # Skip logging

        # But keep lightweight improvements
        assert config.prefer_closest_keyword is True  # Lightweight sorting

        # Other fast settings
        assert config.compute_confidence is False  # Skip expensive computation
        assert config.cache_word_positions is True  # Enable caching


class TestBackwardCompatibility:
    """Tests for backward compatibility exports."""

    def test_individual_constants_exported(self):
        """Individual constants should be exported for backward compatibility."""
        from src.review.config import (
            MAX_KEYWORD_DISTANCE,
            DEFAULT_CONTEXT_WORDS,
            MIN_METRIC_VALUE,
            YEAR_MIN,
            YEAR_MAX,
        )

        # Should match DEFAULT_CONFIG values
        assert MAX_KEYWORD_DISTANCE == DEFAULT_CONFIG.max_keyword_distance
        assert DEFAULT_CONTEXT_WORDS == DEFAULT_CONFIG.context_words
        assert MIN_METRIC_VALUE == DEFAULT_CONFIG.min_metric_value
        assert YEAR_MIN == DEFAULT_CONFIG.year_min
        assert YEAR_MAX == DEFAULT_CONFIG.year_max
