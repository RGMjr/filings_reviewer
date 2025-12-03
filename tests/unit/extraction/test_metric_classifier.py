"""
Unit tests for MetricClassifier.

Tests the classification of segments for metric content.
"""

import pytest

from src.extraction.metric_classifier import MetricClassifier
from src.extraction.models import SourceSegment


@pytest.fixture
def classifier():
    """Create a MetricClassifier instance."""
    return MetricClassifier()


@pytest.fixture
def sample_segment():
    """Create a sample SourceSegment."""
    return SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text="Sample text for testing",
    )


def test_classifier_initialization(classifier):
    """Test that classifier initializes properly."""
    assert classifier is not None
    assert len(classifier._definition_regex) > 0
    assert len(classifier._methodology_regex) > 0
    assert len(classifier._metric_patterns) > 0


def test_has_definition_flag(classifier, sample_segment):
    """Test definition detection."""
    # Text with definition indicator
    sample_segment.raw_text = (
        "We define daily active users as users who log in once per day."
    )
    result = classifier.classify_segment(sample_segment)
    assert result.contains_definition_flag is True

    # Text without definition indicator
    sample_segment.raw_text = "Our platform has grown significantly."
    result = classifier.classify_segment(sample_segment)
    assert result.contains_definition_flag is False


def test_has_methodology_flag(classifier, sample_segment):
    """Test methodology detection."""
    # Text with methodology indicator
    sample_segment.raw_text = "Revenue is calculated as the sum of all transactions."
    result = classifier.classify_segment(sample_segment)
    assert result.contains_methodology_flag is True

    # Text without methodology indicator
    sample_segment.raw_text = "We have many happy customers."
    result = classifier.classify_segment(sample_segment)
    assert result.contains_methodology_flag is False


def test_has_numeric_disclosure_flag(classifier, sample_segment):
    """Test numeric disclosure detection."""
    # Text with numbers and metric keywords
    sample_segment.raw_text = "We had 1,500 active customers in Q4 2024."
    result = classifier.classify_segment(sample_segment)
    assert result.contains_numeric_disclosure_flag is True

    # Text with numbers but no metric keywords
    sample_segment.raw_text = "The year 2024 was great, page 123."
    result = classifier.classify_segment(sample_segment)
    assert result.contains_numeric_disclosure_flag is False

    # Text with metric keywords but no numbers
    sample_segment.raw_text = "Our customers are very satisfied."
    result = classifier.classify_segment(sample_segment)
    assert result.contains_numeric_disclosure_flag is False


def test_identify_candidate_metrics_dau(classifier, sample_segment):
    """Test identification of Daily Active Users metric."""
    sample_segment.raw_text = "Our DAU grew to 10,000 users."
    result = classifier.classify_segment(sample_segment)

    assert "cm_daily_active_users" in result.candidate_metric_ids


def test_identify_candidate_metrics_mau(classifier, sample_segment):
    """Test identification of Monthly Active Users metric."""
    sample_segment.raw_text = "We had 50,000 monthly active users in December."
    result = classifier.classify_segment(sample_segment)

    assert "cm_monthly_active_users" in result.candidate_metric_ids


def test_identify_candidate_metrics_cac(classifier, sample_segment):
    """Test identification of Customer Acquisition Cost metric."""
    sample_segment.raw_text = "Our customer acquisition cost is $100 per user."
    result = classifier.classify_segment(sample_segment)

    assert "cm_customer_acquisition_cost" in result.candidate_metric_ids


def test_identify_candidate_metrics_arpu(classifier, sample_segment):
    """Test identification of ARPU metric."""
    sample_segment.raw_text = "Average revenue per user (ARPU) was $25 per month."
    result = classifier.classify_segment(sample_segment)

    assert "cm_revenue_per_customer" in result.candidate_metric_ids


def test_identify_candidate_metrics_retention(classifier, sample_segment):
    """Test identification of retention metric."""
    sample_segment.raw_text = "Customer retention rate improved to 95%."
    result = classifier.classify_segment(sample_segment)

    assert "cm_customer_retention_rate" in result.candidate_metric_ids


def test_identify_candidate_metrics_churn(classifier, sample_segment):
    """Test identification of churn metric."""
    sample_segment.raw_text = "Our churn rate decreased to 5% annually."
    result = classifier.classify_segment(sample_segment)

    assert "cm_customer_churn_rate" in result.candidate_metric_ids


def test_identify_candidate_metrics_nrr(classifier, sample_segment):
    """Test identification of Net Revenue Retention."""
    sample_segment.raw_text = "Net revenue retention (NRR) was 120%."
    result = classifier.classify_segment(sample_segment)

    assert "cm_net_revenue_retention" in result.candidate_metric_ids


def test_identify_multiple_candidate_metrics(classifier, sample_segment):
    """Test identification of multiple metrics in one segment."""
    sample_segment.raw_text = "We had 10,000 DAU and 50,000 MAU with an ARPU of $25."
    result = classifier.classify_segment(sample_segment)

    # Should identify multiple metrics
    assert "cm_daily_active_users" in result.candidate_metric_ids
    assert "cm_monthly_active_users" in result.candidate_metric_ids
    assert "cm_revenue_per_customer" in result.candidate_metric_ids
    assert len(result.candidate_metric_ids) >= 3


def test_no_candidate_metrics_for_generic_text(classifier, sample_segment):
    """Test that generic text doesn't match specific metrics."""
    sample_segment.raw_text = "This is a general paragraph about our company."
    result = classifier.classify_segment(sample_segment)

    assert result.candidate_metric_ids == []


def test_confidence_score_numeric_disclosure(classifier, sample_segment):
    """Test confidence score for numeric disclosure."""
    sample_segment.raw_text = "We had 1,500 customers in Q4."
    result = classifier.classify_segment(sample_segment)

    # Should have some confidence due to numeric disclosure
    assert result.classifier_confidence > 0.0


def test_confidence_score_definition_and_numeric(classifier, sample_segment):
    """Test higher confidence for definition + numeric."""
    sample_segment.raw_text = "We define active customers as users who made a purchase. We had 1,000 active customers."
    result = classifier.classify_segment(sample_segment)

    # Should have higher confidence with both flags
    assert result.classifier_confidence > 0.3


def test_confidence_score_all_signals(classifier, sample_segment):
    """Test highest confidence for all signals present."""
    sample_segment.raw_text = "We define DAU as daily active users, calculated as unique logins per day. We had 10,000 DAU."
    result = classifier.classify_segment(sample_segment)

    # Should have high confidence with all signals
    assert result.classifier_confidence > 0.5
    assert result.contains_definition_flag is True
    assert result.contains_methodology_flag is True
    assert result.contains_numeric_disclosure_flag is True


def test_classify_batch(classifier):
    """Test batch classification of multiple segments."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="We had 1,000 DAU.",
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="Revenue was $10M.",
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=2,
            raw_text="General company information.",
        ),
    ]

    results = classifier.classify_batch(segments)

    assert len(results) == 3
    # First segment should have DAU metric
    assert "cm_daily_active_users" in results[0].candidate_metric_ids
    # Third segment should have no metrics
    assert results[2].candidate_metric_ids == []


def test_case_insensitive_matching(classifier, sample_segment):
    """Test that matching is case-insensitive."""
    # Lowercase
    sample_segment.raw_text = "our dau was 10,000 users."
    result1 = classifier.classify_segment(sample_segment)

    # Uppercase
    sample_segment.raw_text = "OUR DAU WAS 10,000 USERS."
    result2 = classifier.classify_segment(sample_segment)

    # Mixed case
    sample_segment.raw_text = "Our DAU was 10,000 Users."
    result3 = classifier.classify_segment(sample_segment)

    # All should identify the same metric
    assert "cm_daily_active_users" in result1.candidate_metric_ids
    assert "cm_daily_active_users" in result2.candidate_metric_ids
    assert "cm_daily_active_users" in result3.candidate_metric_ids


def test_number_pattern_matching(classifier, sample_segment):
    """Test various number formats are detected."""
    test_cases = [
        "We had 500 customers.",  # Simple number (no comma needed under 1000)
        "We had 1,000 customers.",  # Comma-separated
        "We had 1.5 million customers.",  # Decimal with word
        "Customer growth was 25% year over year.",  # Percentage with metric keyword
        "Revenue was 100,000 from users.",  # Larger number with metric
    ]

    for text in test_cases:
        sample_segment.raw_text = text
        result = classifier.classify_segment(sample_segment)
        assert result.contains_numeric_disclosure_flag is True, f"Failed for: {text}"


def test_definition_patterns(classifier, sample_segment):
    """Test various definition patterns are detected."""
    test_cases = [
        "We define active users as...",
        "MAU is defined as monthly active users.",
        "The definition of churn rate is...",
        "Retention refers to the percentage of...",
        "ARPU means average revenue per user.",
    ]

    for text in test_cases:
        sample_segment.raw_text = text
        result = classifier.classify_segment(sample_segment)
        assert result.contains_definition_flag is True, f"Failed for: {text}"


def test_methodology_patterns(classifier, sample_segment):
    """Test various methodology patterns are detected."""
    test_cases = [
        "Revenue is calculated as total sales.",
        "Churn is calculated by dividing lost customers by total customers.",
        "The calculation uses the following formula.",
        "NRR is computed as (beginning ARR + expansion - contraction - churn) / beginning ARR.",
        "This is determined by summing all transactions.",
    ]

    for text in test_cases:
        sample_segment.raw_text = text
        result = classifier.classify_segment(sample_segment)
        assert result.contains_methodology_flag is True, f"Failed for: {text}"


def test_segment_with_no_text(classifier, sample_segment):
    """Test handling of empty text."""
    sample_segment.raw_text = ""
    result = classifier.classify_segment(sample_segment)

    assert result.contains_definition_flag is False
    assert result.contains_methodology_flag is False
    assert result.contains_numeric_disclosure_flag is False
    assert result.candidate_metric_ids == []
    assert result.classifier_confidence >= 0.0


def test_cohort_metrics(classifier, sample_segment):
    """Test identification of cohort-based metrics."""
    sample_segment.raw_text = (
        "Revenue by cohort shows strong growth in the 2024 cohort."
    )
    result = classifier.classify_segment(sample_segment)

    assert "cm_revenue_by_cohort" in result.candidate_metric_ids


def test_ltv_cac_ratio(classifier, sample_segment):
    """Test identification of LTV:CAC ratio."""
    sample_segment.raw_text = (
        "Our LTV:CAC ratio is 3:1, indicating healthy unit economics."
    )
    result = classifier.classify_segment(sample_segment)

    assert "cm_ltv_to_cac_ratio" in result.candidate_metric_ids
