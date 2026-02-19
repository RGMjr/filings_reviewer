"""
Integration tests for config module API discoverability.

These tests demonstrate how different components use the config system together,
serving as executable documentation for common configuration patterns.

Note: Unit tests in test_config.py provide comprehensive functional coverage.
These integration tests focus on multi-component usage patterns and API examples.
"""

from src.review.candidate_generator import CandidateGenerator
from src.review.confidence_scoring import ConfidenceScorer
from src.review.config import (
    DEFAULT_CONFIG,
    CandidateGenerationConfig,
    get_fast_config,
    get_high_precision_config,
    get_high_recall_config,
)


class TestConfigPresetIntegration:
    """Integration tests showing preset usage with CandidateGenerator."""

    def test_high_precision_preset_with_generator(self):
        """
        Example: Using high precision preset for production workflows.

        Use case: Minimize false positives in final extraction pipeline.
        """
        # Get high precision config
        config = get_high_precision_config()

        # Initialize generator with preset
        generator = CandidateGenerator(config=config)

        # Verify key precision settings applied
        assert generator.config.max_keyword_distance == 50  # Stricter proximity
        assert generator.config.min_metric_value == 100  # Higher threshold
        assert generator.config.min_pattern_precision == 0.85  # High confidence only
        assert generator.config.prefer_closest_keyword is True  # P1 enhancement
        assert generator.config.respect_bullet_boundaries is True  # P1 enhancement

    def test_high_recall_preset_with_generator(self):
        """
        Example: Using high recall preset for exploratory analysis.

        Use case: Discover all potential metrics during initial review phase.
        """
        # Get high recall config
        config = get_high_recall_config()

        # Initialize generator with preset
        generator = CandidateGenerator(config=config)

        # Verify key recall settings applied
        assert generator.config.max_keyword_distance == 150  # Looser proximity
        assert generator.config.min_metric_value == 1  # Keep small numbers
        assert generator.config.filter_false_positives is False  # No filtering
        assert generator.config.apply_learned_rules is False  # No pattern filtering
        assert generator.config.prefer_closest_keyword is False  # Keep all matches
        assert generator.config.respect_bullet_boundaries is False  # Allow cross-boundary

    def test_fast_preset_with_generator(self):
        """
        Example: Using fast preset for prototyping or batch processing.

        Use case: Quick candidate generation for testing or large-scale processing.
        """
        # Get fast config
        config = get_fast_config()

        # Initialize generator with preset
        generator = CandidateGenerator(config=config)

        # Verify speed optimizations applied
        assert generator.config.compute_confidence is False  # Skip expensive scoring
        assert generator.config.apply_learned_rules is False  # Skip pattern matching
        assert generator.config.enable_boundary_detection is False  # Skip boundary detection
        assert generator.config.cache_word_positions is True  # Enable caching


class TestConfigConfidenceScorerIntegration:
    """Integration test showing config → confidence scorer workflow."""

    def test_config_to_confidence_weights_integration(self):
        """
        Example: Using config to initialize ConfidenceScorer.

        Use case: Consistent weight configuration across system components.
        """
        # Create custom config with specific confidence weights
        config = CandidateGenerationConfig(
            confidence_base_score=0.60,  # Custom base score
            confidence_distance_max_weight=0.25,  # Custom distance weight
            confidence_definition_bonus=0.20,  # Custom definition bonus
        )

        # Initialize ConfidenceScorer with config
        scorer = ConfidenceScorer(config=config)

        # Verify weights propagated correctly from config
        assert scorer.BASE_SCORE == 0.60
        assert scorer.DISTANCE_MAX_WEIGHT == 0.25
        assert scorer.DEFINITION_BONUS == 0.20

        # Verify other weights use config values
        assert scorer.POSITION_BEFORE_BONUS == config.confidence_position_before_bonus
        assert scorer.PERIOD_BONUS == config.confidence_period_bonus


class TestConfigRuntimeSwitching:
    """Integration test showing config switching at runtime."""

    def test_switching_configs_between_filings(self):
        """
        Example: Using different configs for different filing types.

        Use case: Apply strict config for tech IPOs, relaxed config for bio/pharma.
        """
        # Initialize with default config
        generator = CandidateGenerator()
        assert generator.config.max_keyword_distance == DEFAULT_CONFIG.max_keyword_distance

        # Switch to high precision for tech filing
        tech_config = get_high_precision_config()
        generator.config = tech_config
        assert generator.config.max_keyword_distance == 50  # Stricter

        # Switch to high recall for bio/pharma filing
        bio_config = get_high_recall_config()
        generator.config = bio_config
        assert generator.config.max_keyword_distance == 150  # Looser

        # Demonstrates runtime config flexibility


class TestCustomConfigMultiComponent:
    """Integration test showing custom config with multiple components."""

    def test_custom_config_for_specialized_workflow(self):
        """
        Example: Building a custom config for a specialized extraction workflow.

        Use case: Financial services filing with specific requirements:
        - Strict proximity (financial numbers are dense)
        - Boundary-aware matching (prevent cross-section contamination)
        - High pattern precision (minimize false positives)
        - Confidence scoring enabled (need ranking)
        """
        # Build custom config
        custom_config = CandidateGenerationConfig(
            # Proximity tuning
            max_keyword_distance=60,  # Tight proximity for dense financial text
            # P1 enhancements
            prefer_closest_keyword=True,  # Distance-first sorting
            respect_bullet_boundaries=True,  # Prevent cross-boundary matches
            enable_boundary_detection=True,  # Detect semantic boundaries
            log_ambiguous_matches=True,  # Log for debugging
            ambiguity_threshold=5,  # Strict ambiguity threshold
            # Filtering tuning
            min_metric_value=1000,  # Financial metrics are large
            filter_false_positives=True,  # Enable FP filtering
            filter_years=True,  # Filter years
            # Pattern learning tuning
            apply_learned_rules=True,  # Apply learned patterns
            min_pattern_precision=0.90,  # Very high confidence only
            # Confidence scoring
            compute_confidence=True,  # Need confidence for ranking
            # Performance
            cache_word_positions=True,  # Enable caching
        )

        # Initialize generator with custom config
        generator = CandidateGenerator(config=custom_config)

        # Verify all settings applied
        assert generator.config.max_keyword_distance == 60
        assert generator.config.min_metric_value == 1000
        assert generator.config.min_pattern_precision == 0.90
        assert generator.config.prefer_closest_keyword is True
        assert generator.config.respect_bullet_boundaries is True
        assert generator.config.enable_boundary_detection is True

        # Initialize confidence scorer with same config
        scorer = ConfidenceScorer(config=custom_config)

        # Verify scorer uses config weights
        assert scorer.BASE_SCORE == custom_config.confidence_base_score
        assert scorer.DISTANCE_MAX_WEIGHT == custom_config.confidence_distance_max_weight

        # Demonstrates end-to-end custom config workflow
