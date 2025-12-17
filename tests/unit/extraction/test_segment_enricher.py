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
