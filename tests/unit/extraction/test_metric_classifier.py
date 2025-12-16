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


# ===== T6: E-Commerce Metrics Tests =====


class TestECommerceMetricPatterns:
    """Test identification of e-commerce metrics (T6)."""

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

    # --- Average Order Value Tests ---

    def test_aov_acronym(self, classifier, sample_segment):
        """Test identification via AOV acronym."""
        sample_segment.raw_text = "Our AOV increased to $75 in Q4 2024."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids

    def test_aov_full_phrase(self, classifier, sample_segment):
        """Test identification via 'average order value' phrase."""
        sample_segment.raw_text = "Average order value grew 15% year-over-year to $80."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids

    def test_aov_order_size(self, classifier, sample_segment):
        """Test identification via 'average order size' variant."""
        sample_segment.raw_text = "The average order size was $65 in the fiscal year."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids

    def test_aov_average_ticket(self, classifier, sample_segment):
        """Test identification via 'average ticket' retail variant."""
        sample_segment.raw_text = "Average ticket size increased to $45."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids

    def test_aov_average_basket(self, classifier, sample_segment):
        """Test identification via 'average basket' e-commerce variant."""
        sample_segment.raw_text = "Average basket value was $55 per order."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids

    def test_aov_transaction_value(self, classifier, sample_segment):
        """Test identification via 'average transaction value' variant."""
        sample_segment.raw_text = "Average transaction value reached $90."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids

    # --- Repeat Purchase Rate Tests ---

    def test_repeat_purchase_rate_explicit(self, classifier, sample_segment):
        """Test identification of explicit repeat purchase rate mention."""
        sample_segment.raw_text = "Our repeat purchase rate improved to 45%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    def test_repeat_customers(self, classifier, sample_segment):
        """Test identification via 'repeat customers' variant."""
        sample_segment.raw_text = "Repeat customers represented 60% of revenue."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    def test_repeat_buyers(self, classifier, sample_segment):
        """Test identification via 'repeat buyers' variant."""
        sample_segment.raw_text = "Repeat buyers grew to 40% of our customer base."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    def test_purchase_frequency(self, classifier, sample_segment):
        """Test identification via 'purchase frequency' variant."""
        sample_segment.raw_text = "Purchase frequency increased from 2.1 to 2.5 orders per year."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    def test_reorder_rate(self, classifier, sample_segment):
        """Test identification via 'reorder rate' variant."""
        sample_segment.raw_text = "Customer reorder rate was 35% in 2024."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    def test_repurchase_rate(self, classifier, sample_segment):
        """Test identification via 'repurchase rate' variant."""
        sample_segment.raw_text = "The repurchase rate for existing customers was 50%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    # --- Combined / Edge Case Tests ---

    def test_multiple_ecommerce_metrics(self, classifier, sample_segment):
        """Test segment with both AOV and repeat purchase metrics."""
        sample_segment.raw_text = (
            "Average order value increased to $70 while repeat customers "
            "accounted for 55% of all orders."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids
        assert "cm_repeat_purchase_rate" in result.candidate_metric_ids

    def test_aov_not_avg_generic(self, classifier, sample_segment):
        """Test that generic 'average' doesn't match AOV."""
        sample_segment.raw_text = "The average customer age is 35 years."
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" not in result.candidate_metric_ids

    def test_repeat_not_repeat_generic(self, classifier, sample_segment):
        """Test that generic 'repeat' doesn't match repeat purchase rate."""
        sample_segment.raw_text = "We do not repeat our mistakes in operations."
        result = classifier.classify_segment(sample_segment)
        assert "cm_repeat_purchase_rate" not in result.candidate_metric_ids

    def test_aov_cmasb_extended_boost(self, classifier, sample_segment):
        """Test that AOV receives CMASB extended boost."""
        sample_segment.raw_text = (
            "Our average order value increased to $85 in the fourth quarter, "
            "up from $75 in the prior year, representing a 13% improvement in "
            "customer spending per transaction."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_average_order_value" in result.candidate_metric_ids
        # Should have extended boost (0.1) applied
        # Base: 0.3 (numeric) + 0.3 (single candidate) + 0.1 (CMASB) = 0.7
        assert result.classifier_confidence >= 0.6


# ===== T7: Marketplace Metrics Tests =====


class TestMarketplaceMetricPatterns:
    """Test identification of marketplace/platform metrics (T7)."""

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

    # --- Gross Merchandise Value Tests ---

    def test_gmv_acronym(self, classifier, sample_segment):
        """Test identification via GMV acronym."""
        sample_segment.raw_text = "GMV increased to $10 billion in fiscal 2024."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_full_phrase(self, classifier, sample_segment):
        """Test identification via 'gross merchandise value' phrase."""
        sample_segment.raw_text = "Gross merchandise value grew 25% year-over-year."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_volume_variant(self, classifier, sample_segment):
        """Test identification via 'gross merchandise volume' variant."""
        sample_segment.raw_text = "Gross merchandise volume reached $5 billion."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_booking_value(self, classifier, sample_segment):
        """Test identification via 'gross booking value' (ride-sharing)."""
        sample_segment.raw_text = "Gross booking value for rides was $15 billion."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_transaction_value(self, classifier, sample_segment):
        """Test identification via 'gross transaction value' variant."""
        sample_segment.raw_text = "Gross transaction value on our platform was $2 billion."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_total_transaction_value(self, classifier, sample_segment):
        """Test identification via 'total transaction value' variant."""
        sample_segment.raw_text = "Total transaction value processed was $8 billion."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_order_value(self, classifier, sample_segment):
        """Test identification via 'gross order value' e-commerce variant."""
        sample_segment.raw_text = "Gross order value for Q4 was $1.5 billion."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    def test_gmv_platform_volume(self, classifier, sample_segment):
        """Test identification via 'platform volume' variant."""
        sample_segment.raw_text = "Platform transaction volume exceeded $20 billion."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids

    # --- Take Rate Tests ---

    def test_take_rate_basic(self, classifier, sample_segment):
        """Test identification of basic take rate mention."""
        sample_segment.raw_text = "Our take rate improved to 15% in 2024."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_platform(self, classifier, sample_segment):
        """Test identification via 'platform take rate' variant."""
        sample_segment.raw_text = "The platform take rate averaged 12% for the year."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_commission(self, classifier, sample_segment):
        """Test identification via 'commission rate' marketplace variant."""
        sample_segment.raw_text = "Our commission rate on seller transactions is 8%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_net(self, classifier, sample_segment):
        """Test identification via 'net take rate' variant."""
        sample_segment.raw_text = "Net take rate after promotions was 10%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_monetization(self, classifier, sample_segment):
        """Test identification via 'monetization rate' variant."""
        sample_segment.raw_text = "Our monetization rate increased from 5% to 7%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_service_fee(self, classifier, sample_segment):
        """Test identification via 'service fee rate' ride-sharing variant."""
        sample_segment.raw_text = "The service fee rate for rides averaged 25%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_platform_fee(self, classifier, sample_segment):
        """Test identification via 'platform fee rate' variant."""
        sample_segment.raw_text = "Platform fee rate was 18% across all categories."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_take_rate_revenue_percentage_gmv(self, classifier, sample_segment):
        """Test identification via 'revenue as percentage of GMV' variant."""
        sample_segment.raw_text = "Revenue as a percentage of GMV was 12%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids

    # --- Combined / Edge Case Tests ---

    def test_gmv_and_take_rate_together(self, classifier, sample_segment):
        """Test segment with both GMV and take rate metrics."""
        sample_segment.raw_text = (
            "Gross merchandise value reached $5 billion while our take rate "
            "improved to 15%, resulting in $750 million of revenue."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids
        assert "cm_take_rate" in result.candidate_metric_ids

    def test_gmv_not_gross_margin(self, classifier, sample_segment):
        """Test that 'gross margin' doesn't match GMV."""
        sample_segment.raw_text = "Gross margin improved to 45% in the quarter."
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" not in result.candidate_metric_ids

    def test_take_rate_not_interest_rate(self, classifier, sample_segment):
        """Test that 'interest rate' doesn't match take rate."""
        sample_segment.raw_text = "Interest rate on our credit facility is 5%."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" not in result.candidate_metric_ids

    def test_take_rate_not_churn_rate(self, classifier, sample_segment):
        """Test that 'churn rate' doesn't match take rate."""
        sample_segment.raw_text = "Our churn rate decreased to 3% annually."
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" not in result.candidate_metric_ids

    def test_gmv_cmasb_extended_boost(self, classifier, sample_segment):
        """Test that GMV receives CMASB extended boost."""
        sample_segment.raw_text = (
            "Gross merchandise value on our platform increased to $10 billion in "
            "fiscal 2024, representing 30% growth over the prior year. This GMV growth "
            "was driven by increased transactions and customer engagement."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids
        # Should have extended boost (0.1) applied
        # Base: 0.3 (numeric) + 0.3 (single candidate) + 0.1 (CMASB) = 0.7
        assert result.classifier_confidence >= 0.6

    def test_take_rate_cmasb_extended_boost(self, classifier, sample_segment):
        """Test that take rate receives CMASB extended boost."""
        sample_segment.raw_text = (
            "Our take rate improved to 15% in 2024, up from 12% in the prior year, "
            "as we expanded premium services and increased revenue monetization of our "
            "marketplace platform across all seller categories and transactions."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_take_rate" in result.candidate_metric_ids
        # Should have extended boost (0.1) applied
        assert result.classifier_confidence >= 0.6

    def test_multiple_marketplace_metrics_real_example(self, classifier, sample_segment):
        """Test realistic marketplace S-1 disclosure language."""
        sample_segment.raw_text = (
            "For the fiscal year ended December 31, 2024, our GMV was $25.3 billion, "
            "representing a 28% increase compared to the prior year. Our take rate "
            "was 14.2%, up from 13.5% in 2023, driven by improvements in our "
            "revenue monetization strategy and transaction optimization."
        )
        result = classifier.classify_segment(sample_segment)
        assert "cm_gmv" in result.candidate_metric_ids
        assert "cm_take_rate" in result.candidate_metric_ids
        assert result.contains_numeric_disclosure_flag is True
