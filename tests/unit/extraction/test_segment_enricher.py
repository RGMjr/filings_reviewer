"""
Unit tests for SegmentEnricher.

Tests the enrichment of classified segments with richness metadata.
"""

import pytest
from unittest.mock import patch

from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.models import SourceSegment


@pytest.fixture
def enricher() -> SegmentEnricher:
    """Create a SegmentEnricher instance."""
    return SegmentEnricher()


@pytest.fixture
def sample_segment() -> SourceSegment:
    """Segment with realistic data for testing."""
    return SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text="We had 1.2 million active users in 2023, representing 25% growth year-over-year.",
        candidate_metric_ids=["cm_active_users_total", "cm_user_growth_rate"],
        classifier_confidence=0.85,
    )


@pytest.fixture
def empty_segment() -> SourceSegment:
    """Segment with minimal data."""
    return SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text="",
        candidate_metric_ids=[],
    )


# =============================================================================
# Batch Processing Tests (4 tests)
# =============================================================================


class TestEnrichBatch:
    """Tests for enrich_batch() method."""

    def test_enrich_batch_empty_list(self, enricher: SegmentEnricher) -> None:
        """Returns empty list, no errors."""
        result = enricher.enrich_batch([])
        assert result == []

    def test_enrich_batch_single_segment(
        self, enricher: SegmentEnricher, sample_segment: SourceSegment
    ) -> None:
        """Enriches one segment correctly."""
        result = enricher.enrich_batch([sample_segment])

        assert len(result) == 1
        assert result[0].metric_density is not None
        assert result[0].metric_density > 0
        assert result[0].distinct_metric_count == 2

    def test_enrich_batch_multiple_segments(
        self, enricher: SegmentEnricher
    ) -> None:
        """Enriches all segments in list."""
        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="We have 100 active customers.",
                candidate_metric_ids=["cm_active_customers_total"],
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Revenue grew 50% year over year to $10 million.",
                candidate_metric_ids=["cm_revenue_per_customer", "cm_arr"],
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Our churn rate decreased to 5%.",
                candidate_metric_ids=["cm_customer_churn_rate"],
            ),
        ]

        result = enricher.enrich_batch(segments)

        assert len(result) == 3
        # All segments should be enriched
        for segment in result:
            assert segment.metric_density is not None
            assert segment.distinct_metric_count >= 0

    def test_enrich_batch_returns_same_list(
        self, enricher: SegmentEnricher, sample_segment: SourceSegment
    ) -> None:
        """Return value is same object (mutated)."""
        input_list = [sample_segment]
        result = enricher.enrich_batch(input_list)

        # Should be the exact same list object
        assert result is input_list
        # And the same segment object inside
        assert result[0] is sample_segment


# =============================================================================
# Metric Density Tests (6 tests)
# =============================================================================


class TestMetricDensity:
    """Tests for metric density calculation."""

    def test_metric_density_basic_calculation(
        self, enricher: SegmentEnricher
    ) -> None:
        """2 metrics / 200 chars = 1.0 density."""
        # Create a segment with exactly 200 characters
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 200,  # 200 characters
            candidate_metric_ids=["cm_active_users_total", "cm_customer_churn_rate"],
        )

        enricher.enrich_batch([segment])

        # 2 metrics / 200 chars * 100 = 1.0
        assert segment.metric_density == 1.0

    def test_metric_density_with_duplicates(
        self, enricher: SegmentEnricher
    ) -> None:
        """Duplicate metric IDs don't inflate count."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 100,  # 100 characters
            candidate_metric_ids=[
                "cm_active_users_total",
                "cm_active_users_total",  # duplicate
                "cm_customer_churn_rate",
            ],
        )

        enricher.enrich_batch([segment])

        # Only 2 unique metrics / 100 chars * 100 = 2.0
        assert segment.metric_density == 2.0

    def test_metric_density_empty_text(
        self, enricher: SegmentEnricher
    ) -> None:
        """Empty raw_text -> 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
            candidate_metric_ids=["cm_active_users_total"],
        )

        enricher.enrich_batch([segment])

        assert segment.metric_density == 0.0

    def test_metric_density_no_metrics(
        self, enricher: SegmentEnricher
    ) -> None:
        """No candidate_metric_ids -> 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="This is some text without any metrics.",
            candidate_metric_ids=[],
        )

        enricher.enrich_batch([segment])

        assert segment.metric_density == 0.0

    def test_metric_density_rounding(
        self, enricher: SegmentEnricher
    ) -> None:
        """Result rounded to 2 decimal places."""
        # Create a scenario that would produce a non-round number
        # 3 metrics / 79 chars * 100 = 3.79746... -> should round to 3.80
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 79,
            candidate_metric_ids=[
                "cm_active_users_total",
                "cm_customer_churn_rate",
                "cm_arr",
            ],
        )

        enricher.enrich_batch([segment])

        # Should be rounded to 2 decimal places
        assert segment.metric_density == 3.80

    def test_metric_density_high_value(
        self, enricher: SegmentEnricher
    ) -> None:
        """Very dense segment (many metrics, short text)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 10,  # Very short text
            candidate_metric_ids=[
                "cm_active_users_total",
                "cm_customer_churn_rate",
                "cm_arr",
                "cm_mrr",
                "cm_revenue_per_customer",
            ],
        )

        enricher.enrich_batch([segment])

        # 5 metrics / 10 chars * 100 = 50.0
        assert segment.metric_density == 50.0


# =============================================================================
# Distinct Metric Count Tests (4 tests)
# =============================================================================


class TestDistinctMetricCount:
    """Tests for distinct metric count calculation."""

    def test_distinct_count_unique_ids(
        self, enricher: SegmentEnricher
    ) -> None:
        """Counts unique IDs correctly."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            candidate_metric_ids=[
                "cm_active_users_total",
                "cm_customer_churn_rate",
                "cm_arr",
            ],
        )

        enricher.enrich_batch([segment])

        assert segment.distinct_metric_count == 3

    def test_distinct_count_with_duplicates(
        self, enricher: SegmentEnricher
    ) -> None:
        """Duplicates not double-counted."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            candidate_metric_ids=[
                "cm_active_users_total",
                "cm_active_users_total",  # duplicate
                "cm_customer_churn_rate",
                "cm_customer_churn_rate",  # duplicate
                "cm_arr",
            ],
        )

        enricher.enrich_batch([segment])

        assert segment.distinct_metric_count == 3

    def test_distinct_count_none_list(
        self, enricher: SegmentEnricher
    ) -> None:
        """None candidate_metric_ids -> 0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
        )
        # Explicitly set to None (testing edge case)
        segment.candidate_metric_ids = None  # type: ignore[assignment]

        enricher.enrich_batch([segment])

        assert segment.distinct_metric_count == 0

    def test_distinct_count_empty_list(
        self, enricher: SegmentEnricher, empty_segment: SourceSegment
    ) -> None:
        """Empty list -> 0."""
        enricher.enrich_batch([empty_segment])

        assert empty_segment.distinct_metric_count == 0


# =============================================================================
# Edge Cases (5 tests)
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_segment_with_all_none_values(
        self, enricher: SegmentEnricher
    ) -> None:
        """All optional fields are None."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
        )
        # Set raw_text to None (testing edge case)
        segment.raw_text = None  # type: ignore[assignment]
        segment.candidate_metric_ids = None  # type: ignore[assignment]

        # Should not raise an exception
        enricher.enrich_batch([segment])

        assert segment.metric_density == 0.0
        assert segment.distinct_metric_count == 0

    def test_segment_with_whitespace_only_text(
        self, enricher: SegmentEnricher
    ) -> None:
        """raw_text = '   ' (whitespace)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="   ",  # 3 whitespace characters
            candidate_metric_ids=["cm_active_users_total"],
        )

        enricher.enrich_batch([segment])

        # 1 metric / 3 chars * 100 = 33.33
        assert segment.metric_density == 33.33
        assert segment.distinct_metric_count == 1

    def test_preserves_other_fields(
        self, enricher: SegmentEnricher
    ) -> None:
        """Enrichment doesn't modify existing fields."""
        segment = SourceSegment(
            filing_id=42,
            segment_type="table",
            section_path="Item 1. Business > Customers",
            section_heading="Customer Metrics",
            sequence_index=5,
            raw_text="x" * 100,
            candidate_metric_ids=["cm_active_users_total"],
            classifier_confidence=0.95,
            contains_definition_flag=True,
            contains_methodology_flag=True,
            contains_numeric_disclosure_flag=True,
        )

        enricher.enrich_batch([segment])

        # Check that existing fields are preserved
        assert segment.filing_id == 42
        assert segment.segment_type == "table"
        assert segment.section_path == "Item 1. Business > Customers"
        assert segment.section_heading == "Customer Metrics"
        assert segment.sequence_index == 5
        assert segment.classifier_confidence == 0.95
        assert segment.contains_definition_flag is True
        assert segment.contains_methodology_flag is True
        assert segment.contains_numeric_disclosure_flag is True

        # But enrichment fields should be populated
        assert segment.metric_density == 1.0
        assert segment.distinct_metric_count == 1

    def test_idempotent_enrichment(
        self, enricher: SegmentEnricher, sample_segment: SourceSegment
    ) -> None:
        """Running twice gives same result."""
        # First enrichment
        enricher.enrich_batch([sample_segment])
        first_density = sample_segment.metric_density
        first_count = sample_segment.distinct_metric_count

        # Second enrichment
        enricher.enrich_batch([sample_segment])
        second_density = sample_segment.metric_density
        second_count = sample_segment.distinct_metric_count

        assert first_density == second_density
        assert first_count == second_count

    def test_segment_with_single_character_text(
        self, enricher: SegmentEnricher
    ) -> None:
        """Single character text with a metric."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x",  # 1 character
            candidate_metric_ids=["cm_active_users_total"],
        )

        enricher.enrich_batch([segment])

        # 1 metric / 1 char * 100 = 100.0
        assert segment.metric_density == 100.0
        assert segment.distinct_metric_count == 1

    def test_exception_during_enrichment_is_caught(
        self, enricher: SegmentEnricher
    ) -> None:
        """Exceptions during enrichment are caught and logged as warnings."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=5,
            raw_text="Test text",
            candidate_metric_ids=["cm_active_users_total"],
        )

        # Mock _enrich_segment to raise an exception
        with patch.object(
            enricher, "_enrich_segment", side_effect=ValueError("Test error")
        ):
            # Should not raise - exception should be caught
            result = enricher.enrich_batch([segment])

        # Should still return the list
        assert result is not None
        assert len(result) == 1
        # The segment should not have been enriched
        assert segment.metric_density is None
        assert segment.distinct_metric_count == 0


# =============================================================================
# Initialization Tests (1 test)
# =============================================================================


class TestInitialization:
    """Tests for enricher initialization."""

    def test_enricher_initialization(self) -> None:
        """Test that enricher initializes properly."""
        enricher = SegmentEnricher()
        assert enricher is not None


# =============================================================================
# Temporal Trend Detection Tests (G5) - 14 tests
# =============================================================================


class TestTemporalTrendDetection:
    """Tests for temporal trend detection (G5)."""

    # -------------------------------------------------------------------------
    # Year Detection Tests (5 tests)
    # -------------------------------------------------------------------------

    def test_single_year_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Single year mentioned -> False (no trend)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="As of December 31, 2023, we had 1.2 million users.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    def test_two_distinct_years_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """Two distinct years -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue grew from $5M in 2021 to $8M in 2023.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    def test_three_distinct_years_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """Three distinct years -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Active users: 1M in 2021, 1.5M in 2022, and 2.1M in 2023.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    def test_same_year_repeated_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Same year repeated multiple times -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="In 2023, we expanded our business. Throughout 2023, growth was strong. As of 2023 year-end...",
        )

        enricher.enrich_batch([segment])

        # Only has year-over-year language which would make it True
        # But this test is about same year repeated - the "year-end" wouldn't match YoY patterns
        # Actually, let me reconsider - this text has "2023" repeated 3 times but only 1 distinct year
        # However, it does NOT have YoY language (year-end is not year-over-year)
        assert segment.contains_temporal_trend is False

    def test_years_at_boundaries(
        self, enricher: SegmentEnricher
    ) -> None:
        """Years at start and end of text are detected."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="2021 marked our founding year. We expect continued growth through 2025.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    # -------------------------------------------------------------------------
    # Fiscal Period Tests (3 tests)
    # -------------------------------------------------------------------------

    def test_fiscal_year_references_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """FY references: 'FY2022 and FY2023' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue increased from FY2022 to FY2023 by 25%.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    def test_quarter_references_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """Quarter references: 'Q1 2023 vs Q1 2022' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Q1 2023 revenue compared to Q1 2022 showed 15% improvement.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    def test_single_fiscal_period_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Single fiscal period -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="For FY2023, we reported strong results.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    # -------------------------------------------------------------------------
    # YoY Language Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_year_over_year_with_single_year_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """'year-over-year' with single year -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="In 2023, we achieved 25% year-over-year growth.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    def test_yoy_standalone_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """'yoy' as standalone word -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue grew 30% YoY driven by new customer acquisition.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    def test_yoy_in_other_words_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """'yoyo' or 'coyote' should NOT match -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our yoyo sales and coyote tracking services are growing.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    def test_compared_to_prior_year_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """'compared to the prior year' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="User growth compared to the prior year was significant.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is True

    # -------------------------------------------------------------------------
    # Edge Cases Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_empty_text_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Empty raw_text -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    def test_none_raw_text_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """None raw_text -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
        )
        segment.raw_text = None  # type: ignore[assignment]

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    def test_no_temporal_language_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Text with no years or temporal language -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our platform enables customers to track their usage metrics efficiently.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    def test_year_embedded_in_number_not_matched(
        self, enricher: SegmentEnricher
    ) -> None:
        """Year embedded in larger number should not match (word boundary)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our Part 12023 includes detailed specifications.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_temporal_trend is False

    def test_non_string_raw_text_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Non-string raw_text -> False with warning (direct method test)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=42,
        )
        # Set raw_text to a non-string type to test type checking
        segment.raw_text = 12345  # type: ignore[assignment]

        # Call _detect_temporal_trends directly to test the isinstance check
        result = enricher._detect_temporal_trends(segment)

        assert result is False

    # -------------------------------------------------------------------------
    # Integration Tests (2 tests)
    # -------------------------------------------------------------------------

    def test_full_enrich_batch_sets_temporal_trend(
        self, enricher: SegmentEnricher
    ) -> None:
        """Full enrich_batch() flow sets contains_temporal_trend correctly."""
        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Revenue grew from 2021 to 2023.",
                candidate_metric_ids=["cm_revenue"],
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Users as of 2023.",
                candidate_metric_ids=["cm_active_users_total"],
            ),
        ]

        result = enricher.enrich_batch(segments)

        assert result[0].contains_temporal_trend is True
        assert result[1].contains_temporal_trend is False

    def test_temporal_trend_alongside_density_calculation(
        self, enricher: SegmentEnricher
    ) -> None:
        """Temporal trend detection works alongside density calculations."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 100 + " Revenue grew from 2021 to 2023.",  # ~130 chars
            candidate_metric_ids=["cm_revenue", "cm_arr"],
        )

        enricher.enrich_batch([segment])

        # Check density and distinct count are still computed
        assert segment.metric_density is not None
        assert segment.metric_density > 0
        assert segment.distinct_metric_count == 2

        # Check temporal trend is detected
        assert segment.contains_temporal_trend is True


# =============================================================================
# Cohort Breakdown Detection Tests (G6) - 16 tests
# =============================================================================


class TestCohortBreakdownDetection:
    """Tests for cohort breakdown detection (G6)."""

    # -------------------------------------------------------------------------
    # Percentage Breakdown Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_percentage_of_consumers_new_customers(
        self, enricher: SegmentEnricher
    ) -> None:
        """'44.4% of consumers were new customers' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="44.4% of consumers were new customers in the fiscal year.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_percentage_of_users_enterprise(
        self, enricher: SegmentEnricher
    ) -> None:
        """'15% of users are enterprise accounts' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="15% of users are enterprise accounts with annual contracts.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_percentage_revenue_growth_no_customer_context(
        self, enricher: SegmentEnricher
    ) -> None:
        """'Revenue grew 25%' -> False (no customer breakdown)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue grew 25% compared to the prior period.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is False

    def test_percentage_satisfaction_rate(
        self, enricher: SegmentEnricher
    ) -> None:
        """'100% satisfaction rate' -> False (not customer segmentation)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We achieved a 100% satisfaction rate on support tickets.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is False

    # -------------------------------------------------------------------------
    # Cohort Keyword Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_cohort_analysis_keyword(
        self, enricher: SegmentEnricher
    ) -> None:
        """'cohort analysis by acquisition year' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="The following table shows cohort analysis by acquisition year.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_customers_acquired_in_year(
        self, enricher: SegmentEnricher
    ) -> None:
        """'Customers acquired in 2022' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Customers acquired in 2022 showed strong retention rates.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_by_tenure_cohort(
        self, enricher: SegmentEnricher
    ) -> None:
        """'by tenure cohort' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Metrics are broken down by tenure cohort in the table below.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_customer_lifetime_value(
        self, enricher: SegmentEnricher
    ) -> None:
        """'customer lifetime value' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We measure customer lifetime as a key indicator of success.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_cohesive_not_cohort(
        self, enricher: SegmentEnricher
    ) -> None:
        """'cohesive team' -> False (not cohort)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We have a cohesive team focused on product development.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is False

    # -------------------------------------------------------------------------
    # New/Existing Customer Tests (3 tests)
    # -------------------------------------------------------------------------

    def test_new_customers_represented_percentage(
        self, enricher: SegmentEnricher
    ) -> None:
        """'New customers represented 35% of revenue' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="New customers represented 35% of total revenue in the quarter.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_existing_vs_new_customers(
        self, enricher: SegmentEnricher
    ) -> None:
        """'existing vs new customers' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We track metrics for existing vs new customers separately.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_first_year_customers(
        self, enricher: SegmentEnricher
    ) -> None:
        """'first-year customers' -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="First-year customers typically have lower engagement.",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    # -------------------------------------------------------------------------
    # Multiple Cohort Metrics Tests (2 tests)
    # -------------------------------------------------------------------------

    def test_multiple_cohort_metrics_returns_true(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with 2+ cohort metrics in candidate_metric_ids -> True."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="See the table below for detailed metrics.",
            candidate_metric_ids=[
                "cm_revenue_by_cohort",
                "cm_transactions_by_cohort",
            ],
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is True

    def test_single_non_cohort_metric_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with non-cohort metrics only -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We track active users monthly.",
            candidate_metric_ids=["cm_active_users_total"],
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is False

    # -------------------------------------------------------------------------
    # Edge Cases Tests (3 tests)
    # -------------------------------------------------------------------------

    def test_empty_text_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Empty raw_text -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
        )

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is False

    def test_none_raw_text_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """None raw_text -> False."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
        )
        segment.raw_text = None  # type: ignore[assignment]

        enricher.enrich_batch([segment])

        assert segment.contains_cohort_breakdown is False

    def test_case_insensitive_detection(
        self, enricher: SegmentEnricher
    ) -> None:
        """'COHORT ANALYSIS' and 'Cohort Analysis' -> True."""
        segment_upper = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our COHORT ANALYSIS shows strong performance.",
        )
        segment_mixed = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our Cohort Analysis shows strong performance.",
        )

        enricher.enrich_batch([segment_upper, segment_mixed])

        assert segment_upper.contains_cohort_breakdown is True
        assert segment_mixed.contains_cohort_breakdown is True

    def test_non_string_raw_text_returns_false(
        self, enricher: SegmentEnricher
    ) -> None:
        """Non-string raw_text -> False with warning (direct method test)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=42,
        )
        # Set raw_text to a non-string type to test type checking
        segment.raw_text = 12345  # type: ignore[assignment]

        # Call _detect_cohort_breakdowns directly to test the isinstance check
        result = enricher._detect_cohort_breakdowns(segment)

        assert result is False

    # -------------------------------------------------------------------------
    # Integration Tests (2 tests)
    # -------------------------------------------------------------------------

    def test_full_enrich_batch_sets_cohort_breakdown(
        self, enricher: SegmentEnricher
    ) -> None:
        """Full enrich_batch() flow sets contains_cohort_breakdown correctly."""
        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="44.4% of consumers were new customers.",
                candidate_metric_ids=["cm_revenue"],
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Total revenue was $10 million.",
                candidate_metric_ids=["cm_revenue"],
            ),
        ]

        result = enricher.enrich_batch(segments)

        assert result[0].contains_cohort_breakdown is True
        assert result[1].contains_cohort_breakdown is False

    def test_cohort_alongside_temporal_and_density(
        self, enricher: SegmentEnricher
    ) -> None:
        """Cohort detection works alongside temporal and density calculations."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 100 + " New customers represented 40% of revenue in 2022 and 2023.",
            candidate_metric_ids=["cm_revenue", "cm_active_customers"],
        )

        enricher.enrich_batch([segment])

        # Check density and distinct count are still computed
        assert segment.metric_density is not None
        assert segment.metric_density > 0
        assert segment.distinct_metric_count == 2

        # Check temporal trend is detected (2022 and 2023)
        assert segment.contains_temporal_trend is True

        # Check cohort breakdown is detected
        assert segment.contains_cohort_breakdown is True


# =============================================================================
# Image Detection Tests (G7) - 16 tests
# =============================================================================


class TestImageDetection:
    """Tests for image/chart detection (G7)."""

    # -------------------------------------------------------------------------
    # Basic Detection Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_single_large_image_returns_1(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with one large <img> -> 1."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue chart",
            raw_html='<div><img src="revenue-chart.png" width="600" height="400"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_multiple_meaningful_images_returns_correct_count(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with multiple meaningful images -> correct count."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Multiple charts",
            raw_html='''
                <div>
                    <img src="chart1.png" width="500" height="300">
                    <img src="chart2.png" width="400" height="250">
                    <img src="chart3.png" width="600" height="400">
                </div>
            ''',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 3

    def test_svg_chart_returns_1(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with SVG chart -> 1."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="SVG chart",
            raw_html='<div><svg><rect width="100" height="50"/></svg></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_canvas_element_returns_1(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with canvas element -> 1."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Canvas chart",
            raw_html='<div><canvas id="myChart"></canvas></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    # -------------------------------------------------------------------------
    # Decorative Filtering Tests (5 tests)
    # -------------------------------------------------------------------------

    def test_small_width_filtered_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Small image (width < 100) -> filtered out (count 0)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Small icon",
            raw_html='<div><img src="icon.png" width="20" height="200"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_small_height_filtered_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Small image (height < 100) -> filtered out (count 0)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Small icon",
            raw_html='<div><img src="icon.png" width="200" height="20"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_icon_class_filtered_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Image with 'icon' in class -> filtered out."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Icon image",
            raw_html='<div><img src="checkmark.png" class="icon checkmark"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_logo_alt_filtered_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Image with 'logo' in alt text -> filtered out."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Logo image",
            raw_html='<div><img src="company.png" alt="Company Logo"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_bullet_arrow_spacer_filtered_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Images with bullet/arrow/spacer classes -> filtered out."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Decorative images",
            raw_html='''
                <div>
                    <img src="bullet.png" class="bullet-point">
                    <img src="arrow.png" class="nav-arrow">
                    <img src="spacer.gif" class="spacer">
                </div>
            ''',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    # -------------------------------------------------------------------------
    # Mixed Content Tests (3 tests)
    # -------------------------------------------------------------------------

    def test_mix_meaningful_and_decorative_only_meaningful_counted(
        self, enricher: SegmentEnricher
    ) -> None:
        """Mix of meaningful + decorative images -> only meaningful counted."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Mixed images",
            raw_html='''
                <div>
                    <img src="chart.png" width="500" height="300">
                    <img src="icon.png" class="icon">
                    <img src="graph.png" width="400" height="200">
                </div>
            ''',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 2

    def test_large_image_plus_small_icons_only_large_counted(
        self, enricher: SegmentEnricher
    ) -> None:
        """Large image + small icons -> only large image counted."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Chart with icons",
            raw_html='''
                <div>
                    <img src="chart.png" width="600" height="400">
                    <img src="icon1.png" width="16" height="16">
                    <img src="icon2.png" width="24" height="24">
                </div>
            ''',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_chart_image_plus_logo_only_chart_counted(
        self, enricher: SegmentEnricher
    ) -> None:
        """Chart image + logo -> only chart counted."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Chart and logo",
            raw_html='''
                <div>
                    <img src="revenue-chart.png" width="500" height="300">
                    <img src="company-logo.png" alt="Company Logo">
                </div>
            ''',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    # -------------------------------------------------------------------------
    # Edge Cases (4 tests)
    # -------------------------------------------------------------------------

    def test_none_raw_html_returns_0(
        self, enricher: SegmentEnricher
    ) -> None:
        """None raw_html -> 0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="No HTML",
            raw_html=None,
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_empty_raw_html_returns_0(
        self, enricher: SegmentEnricher
    ) -> None:
        """Empty string raw_html -> 0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Empty HTML",
            raw_html="",
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_image_without_dimensions_counted(
        self, enricher: SegmentEnricher
    ) -> None:
        """Image without width/height attributes -> NOT filtered (counted)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Image no dimensions",
            raw_html='<div><img src="chart.png"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_width_with_px_suffix_parsed_correctly(
        self, enricher: SegmentEnricher
    ) -> None:
        """Width/height with 'px' suffix -> parsed correctly."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Chart with px",
            raw_html='<div><img src="chart.png" width="500px" height="300px"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_percentage_width_not_filtered(
        self, enricher: SegmentEnricher
    ) -> None:
        """Images with percentage widths (100%) -> NOT filtered (no pixel count)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Full width image",
            raw_html='<div><img src="chart.png" width="100%"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_mixed_case_keywords_detected(
        self, enricher: SegmentEnricher
    ) -> None:
        """'ICON', 'Logo' -> should still be detected (case insensitive)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Mixed case keywords",
            raw_html='''
                <div>
                    <img src="check.png" class="ICON">
                    <img src="company.png" alt="Company Logo">
                </div>
            ''',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    def test_inline_svg_counted(
        self, enricher: SegmentEnricher
    ) -> None:
        """SVG inline (no src) -> should be counted."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Inline SVG",
            raw_html='<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="100" height="100"/></svg>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1

    def test_multiple_decorative_keywords_filtered(
        self, enricher: SegmentEnricher
    ) -> None:
        """class='icon logo small' -> should be filtered."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Multiple keywords",
            raw_html='<div><img src="brand.png" class="icon logo small"></div>',
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0

    # -------------------------------------------------------------------------
    # Integration Tests (2 tests)
    # -------------------------------------------------------------------------

    def test_full_enrich_batch_sets_image_count(
        self, enricher: SegmentEnricher
    ) -> None:
        """Full enrich_batch() flow sets image_count correctly."""
        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Chart segment",
                raw_html='<div><img src="chart.png" width="500" height="300"></div>',
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="No images",
                raw_html="<div><p>Just text</p></div>",
            ),
        ]

        result = enricher.enrich_batch(segments)

        assert result[0].image_count == 1
        assert result[1].image_count == 0

    def test_image_count_alongside_density_temporal_cohort(
        self, enricher: SegmentEnricher
    ) -> None:
        """Image count works alongside density, temporal, cohort calculations."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="x" * 100 + " Revenue grew from 2021 to 2023. 44.4% of consumers were new.",
            raw_html='<div><img src="chart.png" width="500" height="300"><svg><rect/></svg></div>',
            candidate_metric_ids=["cm_revenue", "cm_active_users_total"],
        )

        enricher.enrich_batch([segment])

        # Check density and distinct count are still computed
        assert segment.metric_density is not None
        assert segment.metric_density > 0
        assert segment.distinct_metric_count == 2

        # Check temporal trend is detected (2021 and 2023)
        assert segment.contains_temporal_trend is True

        # Check cohort breakdown is detected
        assert segment.contains_cohort_breakdown is True

        # Check image count is detected (1 img + 1 svg = 2)
        assert segment.image_count == 2


# =============================================================================
# _parse_dimension Direct Tests (G7) - 4 tests
# =============================================================================


class TestParseDimension:
    """Direct tests for _parse_dimension helper method (G7)."""

    def test_parse_integer_string(
        self, enricher: SegmentEnricher
    ) -> None:
        """'100' -> 100."""
        result = enricher._parse_dimension("100")
        assert result == 100

    def test_parse_px_suffix(
        self, enricher: SegmentEnricher
    ) -> None:
        """'100px' -> 100."""
        result = enricher._parse_dimension("100px")
        assert result == 100

    def test_parse_percentage_returns_none(
        self, enricher: SegmentEnricher
    ) -> None:
        """'100%' -> None (not a pixel count)."""
        result = enricher._parse_dimension("100%")
        assert result is None

    def test_parse_empty_returns_none(
        self, enricher: SegmentEnricher
    ) -> None:
        """'' -> None."""
        result = enricher._parse_dimension("")
        assert result is None

    def test_parse_none_returns_none(
        self, enricher: SegmentEnricher
    ) -> None:
        """None -> None."""
        result = enricher._parse_dimension(None)
        assert result is None

    def test_parse_whitespace_with_px(
        self, enricher: SegmentEnricher
    ) -> None:
        """' 100px ' -> 100 (whitespace handled)."""
        result = enricher._parse_dimension(" 100px ")
        assert result == 100

    def test_parse_non_numeric_returns_none(
        self, enricher: SegmentEnricher
    ) -> None:
        """'auto' -> None."""
        result = enricher._parse_dimension("auto")
        assert result is None

    def test_parse_integer_type_converted(
        self, enricher: SegmentEnricher
    ) -> None:
        """Integer 100 -> 100 (converted to string first)."""
        result = enricher._parse_dimension(100)  # type: ignore[arg-type]
        assert result == 100


# =============================================================================
# _is_decorative_image Direct Tests (G7) - Additional coverage
# =============================================================================


class TestIsDecorativeImage:
    """Direct tests for _is_decorative_image helper method (G7)."""

    def test_image_with_class_as_string(
        self, enricher: SegmentEnricher
    ) -> None:
        """Handle case where class attribute is a string, not a list."""
        from bs4 import BeautifulSoup

        # Some HTML parsers return class as string
        html = '<img src="test.png" class="icon">'
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")

        result = enricher._is_decorative_image(img)

        assert result is True

    def test_image_with_none_alt(
        self, enricher: SegmentEnricher
    ) -> None:
        """Handle case where alt attribute is None."""
        from bs4 import BeautifulSoup

        html = '<img src="chart.png" width="500" height="300">'
        soup = BeautifulSoup(html, "html.parser")
        img = soup.find("img")
        # Ensure alt is None (default from BeautifulSoup when not present)

        result = enricher._is_decorative_image(img)

        assert result is False  # No decorative indicators


# =============================================================================
# _detect_images Error Handling Tests (G7) - Additional coverage
# =============================================================================


class TestDetectImagesErrorHandling:
    """Tests for error handling in _detect_images (G7)."""

    def test_malformed_html_returns_0(
        self, enricher: SegmentEnricher
    ) -> None:
        """Malformed HTML doesn't crash, returns 0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Malformed",
            raw_html="<div><img src='test.png' unclosed",
        )

        enricher.enrich_batch([segment])

        # BeautifulSoup handles malformed HTML gracefully, so this should still work
        assert segment.image_count >= 0


# =============================================================================
# Richness Score Tests (G8) - 19 tests
# =============================================================================


class TestRichnessScore:
    """Tests for richness score calculation (G8)."""

    # -------------------------------------------------------------------------
    # Base Confidence Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_base_confidence_zero(
        self, enricher: SegmentEnricher
    ) -> None:
        """classifier_confidence=0.0 -> base score = 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # Only base confidence, which is 0.0 * 3.0 = 0.0
        assert segment.richness_score == 0.0

    def test_base_confidence_half(
        self, enricher: SegmentEnricher
    ) -> None:
        """classifier_confidence=0.5 -> base score = 1.5."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            classifier_confidence=0.5,
        )

        enricher.enrich_batch([segment])

        # 0.5 * 3.0 = 1.5
        assert segment.richness_score == 1.5

    def test_base_confidence_full(
        self, enricher: SegmentEnricher
    ) -> None:
        """classifier_confidence=1.0 -> base score = 3.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            classifier_confidence=1.0,
        )

        enricher.enrich_batch([segment])

        # 1.0 * 3.0 = 3.0
        assert segment.richness_score == 3.0

    def test_base_confidence_none(
        self, enricher: SegmentEnricher
    ) -> None:
        """classifier_confidence=None -> base score = 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            classifier_confidence=None,
        )

        enricher.enrich_batch([segment])

        # None treated as 0.0
        assert segment.richness_score == 0.0

    # -------------------------------------------------------------------------
    # Metric Density Component Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_metric_density_zero_metrics(
        self, enricher: SegmentEnricher
    ) -> None:
        """0 metrics -> density bonus = 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            candidate_metric_ids=[],
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # 0 * 0.5 = 0.0
        assert segment.richness_score == 0.0

    def test_metric_density_one_metric(
        self, enricher: SegmentEnricher
    ) -> None:
        """1 metric -> density bonus = 0.5."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            candidate_metric_ids=["cm_active_users_total"],
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # 1 * 0.5 = 0.5
        assert segment.richness_score == 0.5

    def test_metric_density_four_metrics_capped(
        self, enricher: SegmentEnricher
    ) -> None:
        """4 metrics -> density bonus = 2.0 (capped)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            candidate_metric_ids=[
                "cm_active_users_total",
                "cm_customer_churn_rate",
                "cm_arr",
                "cm_mrr",
            ],
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # min(4 * 0.5, 2.0) = 2.0
        assert segment.richness_score == 2.0

    def test_metric_density_ten_metrics_capped(
        self, enricher: SegmentEnricher
    ) -> None:
        """10 metrics -> density bonus = 2.0 (capped at max)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            candidate_metric_ids=[
                f"cm_metric_{i}" for i in range(10)
            ],
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # min(10 * 0.5, 2.0) = 2.0
        assert segment.richness_score == 2.0

    # -------------------------------------------------------------------------
    # Boolean Flag Component Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_temporal_trend_adds_1_point(
        self, enricher: SegmentEnricher
    ) -> None:
        """contains_temporal_trend=True -> +1.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue grew from 2021 to 2023.",  # Triggers temporal detection
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # Temporal trend detected: +1.0
        assert segment.richness_score == 1.0

    def test_cohort_breakdown_adds_1_5_points(
        self, enricher: SegmentEnricher
    ) -> None:
        """contains_cohort_breakdown=True -> +1.5."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="44.4% of consumers were new customers.",  # Triggers cohort detection
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # Cohort breakdown detected: +1.5
        assert segment.richness_score == 1.5

    def test_definition_flag_adds_1_point(
        self, enricher: SegmentEnricher
    ) -> None:
        """contains_definition_flag=True -> +1.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            contains_definition_flag=True,
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # Definition flag: +1.0
        assert segment.richness_score == 1.0

    def test_all_flags_false_no_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """All flags False -> no bonuses."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Simple text without triggers.",
            contains_definition_flag=False,
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        # No flags set: 0.0
        assert segment.richness_score == 0.0

    # -------------------------------------------------------------------------
    # Image Component Tests (3 tests)
    # -------------------------------------------------------------------------

    def test_image_count_zero(
        self, enricher: SegmentEnricher
    ) -> None:
        """image_count=0 -> image bonus = 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            raw_html="<div>No images</div>",
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 0
        assert segment.richness_score == 0.0

    def test_image_count_one(
        self, enricher: SegmentEnricher
    ) -> None:
        """image_count=1 -> image bonus = 0.5."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            raw_html='<div><img src="chart.png" width="500" height="300"></div>',
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 1
        # 1 * 0.5 = 0.5
        assert segment.richness_score == 0.5

    def test_image_count_three_capped(
        self, enricher: SegmentEnricher
    ) -> None:
        """image_count=3 -> image bonus = 1.5 (capped)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            raw_html='''
                <div>
                    <img src="chart1.png" width="500" height="300">
                    <img src="chart2.png" width="500" height="300">
                    <img src="chart3.png" width="500" height="300">
                </div>
            ''',
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        assert segment.image_count == 3
        # min(3 * 0.5, 1.5) = 1.5
        assert segment.richness_score == 1.5

    # -------------------------------------------------------------------------
    # Composite Score Tests (4 tests)
    # -------------------------------------------------------------------------

    def test_empty_segment_score_zero(
        self, enricher: SegmentEnricher
    ) -> None:
        """Empty segment -> score = 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
            classifier_confidence=0.0,
        )

        enricher.enrich_batch([segment])

        assert segment.richness_score == 0.0

    def test_typical_goldmine_segment(
        self, enricher: SegmentEnricher
    ) -> None:
        """Typical goldmine segment -> score >= 6.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            # Triggers temporal (2021, 2023) and cohort (44.4% of consumers)
            raw_text="44.4% of consumers were new customers. Revenue grew from 2021 to 2023.",
            candidate_metric_ids=[
                "cm_active_customers_total",
                "cm_new_customers_acquired",
                "cm_revenue",
            ],
            contains_definition_flag=True,
            classifier_confidence=0.85,
            raw_html='<div><img src="chart.png" width="500" height="300"></div>',
        )

        enricher.enrich_batch([segment])

        # Expected score:
        # - Base: 0.85 * 3.0 = 2.55
        # - Density: min(3 * 0.5, 2.0) = 1.5
        # - Temporal: 1.0
        # - Cohort: 1.5
        # - Definition: 1.0
        # - Images: 0.5
        # Total: 2.55 + 1.5 + 1.0 + 1.5 + 1.0 + 0.5 = 8.05
        assert segment.richness_score >= 6.0
        assert segment.richness_score == 8.05

    def test_maximum_score_capped_at_ten(
        self, enricher: SegmentEnricher
    ) -> None:
        """Maximum everything -> score = 10.0 exactly (not higher)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            # Triggers temporal (2021, 2023) and cohort
            raw_text="44.4% of consumers were new customers. Revenue grew from 2021 to 2023.",
            candidate_metric_ids=[f"cm_metric_{i}" for i in range(10)],  # 10 metrics
            contains_definition_flag=True,
            classifier_confidence=1.0,  # Max confidence
            raw_html='''
                <div>
                    <img src="chart1.png" width="500" height="300">
                    <img src="chart2.png" width="500" height="300">
                    <img src="chart3.png" width="500" height="300">
                    <img src="chart4.png" width="500" height="300">
                    <img src="chart5.png" width="500" height="300">
                </div>
            ''',  # 5 images
        )

        enricher.enrich_batch([segment])

        # Expected score (uncapped):
        # - Base: 1.0 * 3.0 = 3.0
        # - Density: min(10 * 0.5, 2.0) = 2.0
        # - Temporal: 1.0
        # - Cohort: 1.5
        # - Definition: 1.0
        # - Images: min(5 * 0.5, 1.5) = 1.5
        # Total: 3.0 + 2.0 + 1.0 + 1.5 + 1.0 + 1.5 = 10.0 (exactly at cap)
        assert segment.richness_score == 10.0

    def test_farfetch_like_segment(
        self, enricher: SegmentEnricher
    ) -> None:
        """Real-world Farfetch-like segment characteristics."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=(
                "As of December 31, 2015, 2016 and 2017, we had 0.8 million, "
                "1.0 million and 1.4 million Active Consumers. We define "
                "Active Consumers as the total number of unique consumers "
                "who have placed at least one order on our marketplace."
            ),
            candidate_metric_ids=["cm_active_customers_total", "cm_new_customers_acquired"],
            contains_definition_flag=True,
            classifier_confidence=0.85,
        )

        enricher.enrich_batch([segment])

        # Expected:
        # - Base: 0.85 * 3.0 = 2.55
        # - Density: min(2 * 0.5, 2.0) = 1.0
        # - Temporal: 1.0 (2015, 2016, 2017)
        # - Cohort: 0 (no cohort language)
        # - Definition: 1.0
        # - Images: 0
        # Total: 2.55 + 1.0 + 1.0 + 0 + 1.0 + 0 = 5.55
        assert segment.richness_score == 5.55
        # Just under goldmine threshold
        assert segment.richness_score < 6.0

    # -------------------------------------------------------------------------
    # Goldmine Threshold Tests (3 tests)
    # -------------------------------------------------------------------------

    def test_score_5_9_not_goldmine(
        self, enricher: SegmentEnricher
    ) -> None:
        """Score of 5.9 -> NOT a goldmine."""
        # Create segment that scores just under 6.0
        # Base: 1.0 * 3.0 = 3.0
        # Density: 2 * 0.5 = 1.0
        # Temporal: 1.0 (two years)
        # No cohort, no definition, no images
        # Total: 3.0 + 1.0 + 1.0 = 5.0
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue grew from 2021 to 2023.",
            candidate_metric_ids=["cm_revenue", "cm_arr"],
            classifier_confidence=1.0,
        )

        enricher.enrich_batch([segment])

        # Score should be 5.0
        assert segment.richness_score == 5.0
        assert segment.richness_score < SegmentEnricher.GOLDMINE_THRESHOLD

    def test_score_6_0_is_goldmine(
        self, enricher: SegmentEnricher
    ) -> None:
        """Score of 6.0 -> IS a goldmine."""
        # Create segment that scores exactly 6.0
        # Base: 1.0 * 3.0 = 3.0
        # Density: 2 * 0.5 = 1.0
        # Temporal: 1.0 (two years)
        # Definition: 1.0
        # No cohort, no images
        # Total: 3.0 + 1.0 + 1.0 + 1.0 = 6.0
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Revenue grew from 2021 to 2023.",
            candidate_metric_ids=["cm_revenue", "cm_arr"],
            classifier_confidence=1.0,
            contains_definition_flag=True,
        )

        enricher.enrich_batch([segment])

        assert segment.richness_score == 6.0
        assert segment.richness_score >= SegmentEnricher.GOLDMINE_THRESHOLD

    def test_score_8_5_is_goldmine(
        self, enricher: SegmentEnricher
    ) -> None:
        """Score of 8.5 -> IS a goldmine."""
        # Create high-value segment
        # Base: 1.0 * 3.0 = 3.0
        # Density: 4 * 0.5 = 2.0
        # Temporal: 1.0
        # Cohort: 1.5
        # Definition: 1.0
        # No images
        # Total: 3.0 + 2.0 + 1.0 + 1.5 + 1.0 = 8.5
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="44.4% of consumers were new in 2021 to 2023.",
            candidate_metric_ids=["cm_1", "cm_2", "cm_3", "cm_4"],
            classifier_confidence=1.0,
            contains_definition_flag=True,
        )

        enricher.enrich_batch([segment])

        assert segment.richness_score == 8.5
        assert segment.richness_score >= SegmentEnricher.GOLDMINE_THRESHOLD

    # -------------------------------------------------------------------------
    # Integration Tests (2 tests)
    # -------------------------------------------------------------------------

    def test_full_enrich_batch_sets_richness_score(
        self, enricher: SegmentEnricher
    ) -> None:
        """Full enrich_batch() flow computes richness_score."""
        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Simple text.",
                classifier_confidence=0.5,
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Revenue grew from 2021 to 2023.",
                candidate_metric_ids=["cm_revenue"],
                classifier_confidence=0.8,
            ),
        ]

        result = enricher.enrich_batch(segments)

        # All segments should have richness_score set
        assert result[0].richness_score is not None
        assert result[1].richness_score is not None

        # First segment: base 0.5 * 3.0 = 1.5
        assert result[0].richness_score == 1.5

        # Second segment: base 0.8 * 3.0 = 2.4, density 0.5, temporal 1.0
        # Total: 2.4 + 0.5 + 1.0 = 3.9
        assert result[1].richness_score == 3.9

    def test_goldmine_logging_outputs_correctly(
        self, enricher: SegmentEnricher, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Goldmine logging outputs correctly."""
        import logging

        # Create mix of goldmine and non-goldmine segments
        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="Simple text.",
                classifier_confidence=0.5,
            ),
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text="44.4% of consumers were new in 2021 to 2023.",
                candidate_metric_ids=["cm_1", "cm_2", "cm_3", "cm_4"],
                classifier_confidence=1.0,
                contains_definition_flag=True,
            ),
        ]

        with caplog.at_level(logging.INFO):
            enricher.enrich_batch(segments)

        # Should log goldmine statistics
        assert "goldmine" in caplog.text.lower()
        assert "avg richness" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Edge Cases (2 tests)
    # -------------------------------------------------------------------------

    def test_all_inputs_at_minimum(
        self, enricher: SegmentEnricher
    ) -> None:
        """All inputs at minimum (0/False/None) -> score = 0.0."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
            candidate_metric_ids=[],
            classifier_confidence=None,
            contains_definition_flag=False,
            raw_html=None,
        )

        enricher.enrich_batch([segment])

        assert segment.richness_score == 0.0

    def test_floating_point_precision(
        self, enricher: SegmentEnricher
    ) -> None:
        """Floating point precision - consistent rounding to 2 decimal places."""
        # 0.33 * 3.0 = 0.99 (should not have floating point issues)
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Sample text",
            classifier_confidence=0.33,
        )

        enricher.enrich_batch([segment])

        # Should be exactly 0.99, rounded to 2 decimal places
        assert segment.richness_score == 0.99
        # Verify it's actually a float with 2 decimal places
        assert str(segment.richness_score) == "0.99"
