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


# ===== CMASB Boost Tests (Phase 3.3) =====


def test_cmasb_core_metric_confidence_boost(classifier, sample_segment):
    """Test that CMASB core metrics receive +0.2 confidence boost."""
    # Use a core metric keyword with segment > 100 chars to avoid short-text penalty
    sample_segment.raw_text = (
        "We acquired 10,000 new customers in Q4 2024, representing significant growth "
        "over the prior quarter when we added 7,500 customers. This strong customer acquisition "
        "demonstrates the effectiveness of our sales and marketing initiatives."
    )
    sample_segment.sequence_index = 100

    result = classifier.classify_segment(sample_segment)

    # Should identify the core metric
    assert "cm_new_customers_acquired" in result.candidate_metric_ids

    # Should have boosted confidence
    # Base: 0.3 (numeric) + 0.3 (single candidate) + 0.2 (CMASB core) = 0.8
    # No short-text penalty since > 100 chars
    assert result.classifier_confidence >= 0.7


def test_cmasb_extended_metric_confidence_boost(classifier, sample_segment):
    """Test that CMASB extended metrics receive +0.1 confidence boost."""
    # Use an extended metric keyword with segment > 100 chars to avoid short-text penalty
    sample_segment.raw_text = (
        "Our customer retention rate improved to 95% in 2024, up from 92% in the prior year. "
        "This improvement reflects our enhanced customer success initiatives and product improvements."
    )
    sample_segment.sequence_index = 200

    result = classifier.classify_segment(sample_segment)

    # Should identify the extended metric
    assert "cm_customer_retention_rate" in result.candidate_metric_ids

    # Should have moderate boost
    # Base: 0.3 (numeric) + 0.3 (single candidate) + 0.1 (CMASB extended) = 0.7
    # No short-text penalty since > 100 chars
    assert result.classifier_confidence >= 0.6


def test_cmasb_non_priority_no_boost(classifier, sample_segment):
    """Test that non-priority metrics don't receive CMASB boost."""
    # Use a generic metric keyword that's not in CMASB lists
    sample_segment.raw_text = "Our total revenue was $100 million."

    result = classifier.classify_segment(sample_segment)

    # Might identify generic revenue metric but no CMASB boost
    # Base: 0.3 (numeric) + metric candidates boost (varies)
    # Should be lower than CMASB-boosted segments
    assert result.classifier_confidence < 0.7


# ===== Confidence Score Tests (Phase 3.3) =====


def test_confidence_score_short_segment_penalty(classifier, sample_segment):
    """Test that short segments receive confidence penalty."""
    # Short segment < 100 chars
    sample_segment.raw_text = "We define MRR as monthly recurring revenue."

    result = classifier.classify_segment(sample_segment)

    # Should be classified
    assert result.contains_definition_flag is True

    # Confidence calculation:
    # 0.2 (definition) + 0.3 (single candidate) + 0.1 (CMASB extended boost) = 0.6
    # With short penalty: 0.6 * 0.7 = 0.42
    # Note: MRR is now a CMASB_EXTENDED_METRIC so gets +0.1 boost
    assert 0.4 <= result.classifier_confidence <= 0.5


def test_confidence_score_caps_at_one(classifier, sample_segment):
    """Test that confidence score caps at 1.0."""
    # Create segment with all positive signals
    sample_segment.raw_text = (
        "We define new customers acquired as individuals who made their first "
        "purchase during the period. This metric is calculated as the number "
        "of unique customer IDs making their first transaction. "
        "In Q4 2024, we acquired 50,000 new customers, up from 30,000 in Q3."
    )

    result = classifier.classify_segment(sample_segment)

    # Should hit maximum confidence
    # definition + methodology + numeric + specific metric + CMASB boost
    # But should cap at 1.0
    assert result.classifier_confidence <= 1.0
    assert result.classifier_confidence >= 0.8


def test_confidence_score_single_candidate_boost(classifier, sample_segment):
    """Test that single candidate metric gets +0.3 boost."""
    # Segment with very specific metric mention (must be >100 chars to avoid short-text penalty)
    sample_segment.raw_text = (
        "New customers acquired totaled 10,000 in 2024, representing strong growth from the prior "
        "year when we added only 7,500 customers. This metric demonstrates our market traction."
    )

    result = classifier.classify_segment(sample_segment)

    # Should identify exactly one metric
    assert len(result.candidate_metric_ids) == 1

    # Should have single-candidate boost
    # Base: 0.3 (numeric) + 0.3 (single) + 0.2 (CMASB) = 0.8
    assert result.classifier_confidence >= 0.7


def test_confidence_score_two_candidates_boost(classifier, sample_segment):
    """Test that two candidate metrics get +0.2 boost."""
    # Segment mentioning two metrics
    sample_segment.raw_text = (
        "We track active customers and customer retention rate to measure engagement."
    )

    result = classifier.classify_segment(sample_segment)

    # Should identify two metrics
    assert len(result.candidate_metric_ids) >= 2

    # Should have two-candidate boost (0.2)
    # Less than single-candidate boost (0.3)
    assert result.classifier_confidence > 0.0


# ===== Validation Tests (Phase 3.3) =====


def test_validation_invalid_segment_raises(classifier):
    """Test that validation raises for invalid segment."""
    from src.extraction.exceptions import ValidationError
    from src.extraction.models import SourceSegment

    # Create segment with None raw_text
    invalid_segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text=None  # Invalid!
    )

    with pytest.raises(ValidationError):
        classifier.classify_segment(invalid_segment, validate=True)


def test_validation_can_be_disabled(classifier):
    """Test that validation can be disabled."""
    from src.extraction.models import SourceSegment

    # Create segment with None raw_text
    invalid_segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text=None
    )

    # Should raise AttributeError (not ValidationError) when validation disabled
    with pytest.raises(AttributeError):
        classifier.classify_segment(invalid_segment, validate=False)


# ===== Metrics Collection Tests (Phase 3.3) =====


def test_metrics_collection(classifier):
    """Test that metrics are collected during batch classification."""
    from src.extraction.models import SourceSegment

    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="We define daily active users (DAU) as unique users who log in daily."
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="Revenue per customer is calculated as total revenue divided by customer count."
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=2,
            raw_text="We had 100,000 active customers as of December 31, 2024."
        ),
    ]

    result = classifier.classify_batch(segments)
    metrics = classifier.get_metrics()

    # Metrics should exist
    assert metrics is not None
    assert metrics.total_segments == 3

    # Should track definitions
    assert metrics.definitions >= 1

    # Should track methodologies
    assert metrics.methodologies >= 1

    # Should track numeric disclosures
    assert metrics.numeric_disclosures >= 1

    # Should have positive average confidence
    assert metrics.avg_confidence() > 0.0

    # Should track metric IDs
    assert len(metrics.metric_id_counts) > 0

    # Should have parse time
    assert metrics.classification_time_seconds > 0.0

    # Summary should be informative
    summary = metrics.summary()
    assert "segments" in summary
    assert "3" in summary


def test_metrics_top_metrics(classifier):
    """Test that top_metrics() returns most common metrics."""
    from src.extraction.metric_classifier import ClassificationMetrics

    metrics = ClassificationMetrics()
    metrics.metric_id_counts = {
        "cm_new_customers_acquired": 10,
        "cm_revenue_per_customer": 8,
        "cm_total_customers": 5,
        "cm_churn_rate": 3,
        "cm_retention_rate": 1,
    }

    top_3 = metrics.top_metrics(3)

    # Should return top 3 in descending order
    assert len(top_3) == 3
    assert top_3[0] == ("cm_new_customers_acquired", 10)
    assert top_3[1] == ("cm_revenue_per_customer", 8)
    assert top_3[2] == ("cm_total_customers", 5)


def test_metrics_avg_confidence_with_zero_segments():
    """Test average confidence calculation with zero segments."""
    from src.extraction.metric_classifier import ClassificationMetrics

    metrics = ClassificationMetrics()
    assert metrics.avg_confidence() == 0.0


# ===== T5: Revenue Predictability Metrics Tests =====


class TestBookingsMetricPatterns:
    """Test identification of bookings-related metrics (T5)."""

    @pytest.fixture
    def classifier(self):
        return MetricClassifier()

    @pytest.fixture
    def sample_segment(self):
        return SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Sample text for testing",
        )

    def test_bookings_basic(self, classifier, sample_segment):
        """Test identification of basic bookings mention."""
        sample_segment.raw_text = "Our bookings grew 25% year-over-year to $100 million."
        result = classifier.classify_segment(sample_segment)
        assert "cm_bookings" in result.candidate_metric_ids

    def test_bookings_total(self, classifier, sample_segment):
        """Test identification of total bookings."""
        sample_segment.raw_text = "Total bookings for fiscal 2024 were $500 million."
        result = classifier.classify_segment(sample_segment)
        assert "cm_bookings" in result.candidate_metric_ids

    def test_bookings_new(self, classifier, sample_segment):
        """Test identification of new bookings."""
        sample_segment.raw_text = "New bookings increased by $50 million in Q4."
        result = classifier.classify_segment(sample_segment)
        assert "cm_bookings" in result.candidate_metric_ids

    def test_billings_basic(self, classifier, sample_segment):
        """Test identification of billings metric."""
        sample_segment.raw_text = "Billings were $120 million, up from $100 million."
        result = classifier.classify_segment(sample_segment)
        assert "cm_billings" in result.candidate_metric_ids

    def test_billings_total(self, classifier, sample_segment):
        """Test identification of total billings."""
        sample_segment.raw_text = "Total billings reached $400 million in 2024."
        result = classifier.classify_segment(sample_segment)
        assert "cm_billings" in result.candidate_metric_ids

    def test_deferred_revenue_basic(self, classifier, sample_segment):
        """Test identification of deferred revenue."""
        sample_segment.raw_text = "Deferred revenue increased to $200 million at year end."
        result = classifier.classify_segment(sample_segment)
        assert "cm_deferred_revenue" in result.candidate_metric_ids

    def test_deferred_revenue_unearned(self, classifier, sample_segment):
        """Test identification via 'unearned revenue' variant."""
        sample_segment.raw_text = "Unearned revenue was $150 million."
        result = classifier.classify_segment(sample_segment)
        assert "cm_deferred_revenue" in result.candidate_metric_ids

    def test_deferred_revenue_rpo(self, classifier, sample_segment):
        """Test identification via RPO acronym."""
        sample_segment.raw_text = "Our remaining performance obligations (RPO) were $300 million."
        result = classifier.classify_segment(sample_segment)
        assert "cm_deferred_revenue" in result.candidate_metric_ids

    def test_deferred_revenue_backlog(self, classifier, sample_segment):
        """Test identification via backlog variant."""
        sample_segment.raw_text = "Revenue backlog totaled $250 million."
        result = classifier.classify_segment(sample_segment)
        assert "cm_deferred_revenue" in result.candidate_metric_ids

    def test_deferred_revenue_contract_liabilities(self, classifier, sample_segment):
        """Test identification via contract liabilities variant."""
        sample_segment.raw_text = "Contract liabilities were $180 million at December 31."
        result = classifier.classify_segment(sample_segment)
        assert "cm_deferred_revenue" in result.candidate_metric_ids

    def test_bookings_not_booking_singular(self, classifier, sample_segment):
        """Test that singular 'booking' (reservations) doesn't match."""
        sample_segment.raw_text = "The booking process for hotel reservations is simple."
        result = classifier.classify_segment(sample_segment)
        # Should NOT match cm_bookings (pattern requires plural or compound)
        assert "cm_bookings" not in result.candidate_metric_ids

    def test_billings_not_billing_singular(self, classifier, sample_segment):
        """Test that singular 'billing' (invoicing) doesn't match."""
        sample_segment.raw_text = "Our billing department handles invoices."
        result = classifier.classify_segment(sample_segment)
        # Should NOT match cm_billings (pattern requires plural)
        assert "cm_billings" not in result.candidate_metric_ids

    def test_multiple_revenue_predictability_metrics(self, classifier, sample_segment):
        """Test segment with multiple revenue predictability metrics."""
        sample_segment.raw_text = (
            "Bookings were $100 million, billings were $90 million, "
            "and deferred revenue increased to $50 million."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_bookings" in result.candidate_metric_ids
        assert "cm_billings" in result.candidate_metric_ids
        assert "cm_deferred_revenue" in result.candidate_metric_ids
