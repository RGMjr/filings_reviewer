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
