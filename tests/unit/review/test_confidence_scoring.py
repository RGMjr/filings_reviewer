"""
Unit tests for confidence_scoring module.

Tests the ConfidenceScorer class which computes multi-signal
confidence scores for review candidates.
"""

import pytest

from src.review.confidence_scoring import METRIC_EXPECTED_FORMATS, ConfidenceScorer
from src.review.models import CandidateFeatures

# =============================================================================
# ConfidenceScorer Tests
# =============================================================================


class TestConfidenceScorer:
    """Tests for ConfidenceScorer class."""

    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer(max_keyword_distance=100)

    @pytest.fixture
    def base_features(self):
        """Basic features for testing."""
        return CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            value_magnitude=4.0,
            surrounding_numbers_count=1,
        )

    def test_score_in_valid_range(self, scorer, base_features):
        """Confidence score should be between 0.0 and 1.0."""
        score = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        assert 0.0 <= score <= 1.0

    def test_closer_distance_higher_confidence(self, scorer, base_features):
        """Closer keyword distance should increase confidence."""
        score_close = scorer.compute_confidence(
            keyword_distance=5,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        score_far = scorer.compute_confidence(
            keyword_distance=80,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        assert score_close > score_far

    def test_keyword_before_bonus(self, scorer, base_features):
        """Keyword position 'before' should give slight bonus."""
        features_before = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_after = CandidateFeatures(
            keyword_distance=20,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        score_before = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_before,
        )
        score_after = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="after",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_after,
        )
        assert score_before > score_after

    def test_definition_language_bonus(self, scorer):
        """Definition language should significantly increase confidence."""
        features_no_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_with_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,
            has_period_mention=False,
            number_format="integer",
        )

        score_no_def = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_no_def,
        )
        score_with_def = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_with_def,
        )
        assert score_with_def > score_no_def
        # Definition language bonus is 0.20
        assert score_with_def - score_no_def == pytest.approx(0.20, abs=0.01)

    def test_period_mention_bonus(self, scorer):
        """Period mention should slightly increase confidence."""
        features_no_period = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_with_period = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=True,
            number_format="integer",
        )

        score_no_period = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_no_period,
        )
        score_with_period = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_with_period,
        )
        assert score_with_period > score_no_period

    def test_risk_factors_penalty(self, scorer):
        """Risk factors section should significantly decrease confidence."""
        features_normal = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_risk = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=True,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        score_normal = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_normal,
        )
        score_risk = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_risk,
        )
        assert score_risk < score_normal
        # Risk factors penalty is 0.25
        assert score_normal - score_risk == pytest.approx(0.25, abs=0.01)

    def test_format_match_bonus(self, scorer):
        """Matching number format should increase confidence."""
        # NRR expects percentage format
        features_mismatch = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",  # Wrong format for NRR
        )
        features_match = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="percentage",  # Correct format for NRR
        )

        score_mismatch = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="net revenue retention",
            metric_id="cm_nrr",
            features=features_mismatch,
        )
        score_match = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="net revenue retention",
            metric_id="cm_nrr",
            features=features_match,
        )
        assert score_match > score_mismatch

    def test_specific_keyword_bonus(self, scorer, base_features):
        """Multi-word specific keywords should increase confidence."""
        score_generic = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        score_specific = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="active customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        assert score_specific > score_generic

    def test_surrounding_numbers_penalty(self, scorer):
        """Many surrounding numbers should decrease confidence."""
        features_few = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            surrounding_numbers_count=1,
        )
        features_many = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            surrounding_numbers_count=15,
        )

        score_few = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_few,
        )
        score_many = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_many,
        )
        assert score_many < score_few

    def test_table_without_definition_penalty(self, scorer):
        """Table context without definition language should decrease confidence."""
        features_no_table = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_table = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        score_no_table = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_no_table,
        )
        score_table = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_table,
        )
        assert score_table < score_no_table

    def test_table_with_definition_no_penalty(self, scorer):
        """Table context WITH definition language should not have table penalty."""
        features_table_with_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=True,  # Has definition
            has_period_mention=False,
            number_format="integer",
        )
        features_para_with_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,  # Has definition
            has_period_mention=False,
            number_format="integer",
        )

        score_table = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_table_with_def,
        )
        score_para = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_para_with_def,
        )
        # Should be equal since definition language negates table penalty
        assert score_table == score_para

    def test_score_clamped_to_zero(self, scorer):
        """Score should never go below 0.0 even with many penalties."""
        features_bad = CandidateFeatures(
            keyword_distance=100,  # Max distance
            keyword_position="after",
            is_in_table=True,
            is_in_risk_factors=True,  # Penalty
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            surrounding_numbers_count=20,  # Max penalty
        )

        score = scorer.compute_confidence(
            keyword_distance=100,
            keyword_position="after",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_bad,
        )
        assert score >= 0.0

    def test_score_clamped_to_one(self, scorer):
        """Score should never exceed 1.0 even with many bonuses."""
        features_great = CandidateFeatures(
            keyword_distance=0,  # Perfect distance
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,  # Bonus
            has_period_mention=True,  # Bonus
            number_format="percentage",  # Match for NRR
            surrounding_numbers_count=0,
        )

        score = scorer.compute_confidence(
            keyword_distance=0,
            keyword_position="before",
            keyword="net revenue retention",  # Specific keyword
            metric_id="cm_nrr",
            features=features_great,
        )
        assert score <= 1.0

    def test_is_specific_keyword_detection(self, scorer):
        """Test specific keyword pattern detection."""
        assert scorer._is_specific_keyword("active customers") is True
        assert scorer._is_specific_keyword("Active Customers") is True  # Case insensitive
        assert scorer._is_specific_keyword("net revenue retention") is True
        assert scorer._is_specific_keyword("customers") is False
        assert scorer._is_specific_keyword("retention") is False


class TestMetricExpectedFormats:
    """Tests for METRIC_EXPECTED_FORMATS constant."""

    def test_metric_expected_formats_not_empty(self):
        """Should have expected formats defined."""
        assert len(METRIC_EXPECTED_FORMATS) > 0

    def test_all_formats_are_valid(self):
        """All format values should be valid format types."""
        valid_formats = {"integer", "decimal", "percentage", "currency"}
        for metric_id, formats in METRIC_EXPECTED_FORMATS.items():
            for fmt in formats:
                assert fmt in valid_formats, f"Invalid format '{fmt}' for {metric_id}"

    def test_revenue_metrics_expect_currency(self):
        """Revenue metrics should expect currency format."""
        assert "currency" in METRIC_EXPECTED_FORMATS.get("cm_arr", [])
        assert "currency" in METRIC_EXPECTED_FORMATS.get("cm_mrr", [])
        assert "currency" in METRIC_EXPECTED_FORMATS.get("cm_cac", [])

    def test_retention_metrics_expect_percentage(self):
        """Retention metrics should expect percentage format."""
        assert "percentage" in METRIC_EXPECTED_FORMATS.get("cm_nrr", [])
        assert "percentage" in METRIC_EXPECTED_FORMATS.get("cm_grr", [])
        assert "percentage" in METRIC_EXPECTED_FORMATS.get("cm_churn_rate", [])
