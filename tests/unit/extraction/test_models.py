"""
Unit tests for extraction data models.

Tests focus on SourceSegment richness metadata fields (Task G1).
"""

from src.extraction.models import SourceSegment


class TestSourceSegmentRichnessFields:
    """Tests for richness metadata fields added in Task G1."""

    def test_default_values_for_new_fields(self):
        """Test that new richness fields have correct default values."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="Test text")

        # Optional[float] fields should be None
        assert segment.metric_density is None
        assert segment.richness_score is None

        # int fields should be 0
        assert segment.distinct_metric_count == 0
        assert segment.image_count == 0

        # bool fields should be False
        assert segment.contains_temporal_trend is False
        assert segment.contains_cohort_breakdown is False

    def test_explicit_field_values(self):
        """Test that SourceSegment can be instantiated with richness fields explicitly set."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Test text",
            metric_density=2.5,
            distinct_metric_count=3,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            image_count=2,
            richness_score=8.5,
        )

        assert segment.metric_density == 2.5
        assert segment.distinct_metric_count == 3
        assert segment.contains_temporal_trend is True
        assert segment.contains_cohort_breakdown is True
        assert segment.image_count == 2
        assert segment.richness_score == 8.5

    def test_mixing_old_and_new_fields(self):
        """Test that mixing old classifier fields with new richness fields works correctly."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Test text",
            candidate_metric_ids=["cm_active_customers_total"],
            classifier_confidence=0.85,
            # New richness fields
            metric_density=1.8,
            distinct_metric_count=1,
            richness_score=6.0,
        )

        # Old fields work
        assert segment.candidate_metric_ids == ["cm_active_customers_total"]
        assert segment.classifier_confidence == 0.85

        # New fields work
        assert segment.metric_density == 1.8
        assert segment.distinct_metric_count == 1
        assert segment.richness_score == 6.0

    def test_partial_richness_fields(self):
        """Test that only some richness fields can be set while others use defaults."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="table",
            raw_text="Test table",
            distinct_metric_count=5,
            contains_temporal_trend=True,
            # Other richness fields use defaults
        )

        assert segment.distinct_metric_count == 5
        assert segment.contains_temporal_trend is True
        assert segment.metric_density is None  # default
        assert segment.contains_cohort_breakdown is False  # default
        assert segment.image_count == 0  # default
        assert segment.richness_score is None  # default


class TestSourceSegmentToDictWithRichnessFields:
    """Tests for to_dict() method including richness fields."""

    def test_to_dict_includes_all_richness_fields(self):
        """Test that to_dict() includes all 6 new richness fields."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="Test text")

        result = segment.to_dict()

        # All 6 richness fields should be present
        assert "metric_density" in result
        assert "distinct_metric_count" in result
        assert "contains_temporal_trend" in result
        assert "contains_cohort_breakdown" in result
        assert "image_count" in result
        assert "richness_score" in result

    def test_to_dict_default_values(self):
        """Test that to_dict() correctly represents default values."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="Test text")

        result = segment.to_dict()

        # Verify default values in dict
        assert result["metric_density"] is None
        assert result["distinct_metric_count"] == 0
        assert result["contains_temporal_trend"] is False
        assert result["contains_cohort_breakdown"] is False
        assert result["image_count"] == 0
        assert result["richness_score"] is None

    def test_to_dict_explicit_values(self):
        """Test that to_dict() correctly represents explicitly set values."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Test text",
            metric_density=3.2,
            distinct_metric_count=4,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            image_count=1,
            richness_score=7.5,
        )

        result = segment.to_dict()

        assert result["metric_density"] == 3.2
        assert result["distinct_metric_count"] == 4
        assert result["contains_temporal_trend"] is True
        assert result["contains_cohort_breakdown"] is True
        assert result["image_count"] == 1
        assert result["richness_score"] == 7.5

    def test_to_dict_max_richness_score(self):
        """Test to_dict() output with richness_score at max value (10.0)."""
        segment = SourceSegment(
            filing_id=1, segment_type="paragraph", raw_text="Goldmine section", richness_score=10.0
        )

        result = segment.to_dict()

        assert result["richness_score"] == 10.0

    def test_to_dict_zero_metric_density(self):
        """Test to_dict() output with metric_density = 0.0 (empty segment scenario)."""
        segment = SourceSegment(
            filing_id=1, segment_type="paragraph", raw_text="No metrics here", metric_density=0.0
        )

        result = segment.to_dict()

        assert result["metric_density"] == 0.0


class TestSourceSegmentTypeValidation:
    """Tests for type validation of richness fields."""

    def test_metric_density_accepts_none(self):
        """Verify Optional[float] fields accept None."""
        segment = SourceSegment(
            filing_id=1, segment_type="paragraph", raw_text="Test", metric_density=None
        )

        assert segment.metric_density is None

    def test_richness_score_accepts_none(self):
        """Verify richness_score accepts None."""
        segment = SourceSegment(
            filing_id=1, segment_type="paragraph", raw_text="Test", richness_score=None
        )

        assert segment.richness_score is None

    def test_int_fields_default_to_zero(self):
        """Verify int fields default to 0, not None."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="Test")

        # These should be 0, not None
        assert segment.distinct_metric_count == 0
        assert segment.image_count == 0
        assert type(segment.distinct_metric_count) is int
        assert type(segment.image_count) is int

    def test_bool_fields_default_to_false(self):
        """Verify bool fields default to False, not None."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="Test")

        # These should be False, not None
        assert segment.contains_temporal_trend is False
        assert segment.contains_cohort_breakdown is False
        assert type(segment.contains_temporal_trend) is bool
        assert type(segment.contains_cohort_breakdown) is bool


class TestSourceSegmentBackwardCompatibility:
    """Tests to ensure backward compatibility with existing code."""

    def test_minimal_segment_creation(self):
        """Test that segments can still be created with only required fields."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph")

        # Should succeed without specifying any richness fields
        assert segment.filing_id == 1
        assert segment.segment_type == "paragraph"

        # New fields should have defaults
        assert segment.metric_density is None
        assert segment.distinct_metric_count == 0

    def test_existing_fields_unaffected(self):
        """Test that existing fields still work as before."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            section_path="Item 1. Business",
            section_heading="Customers",
            sequence_index=5,
            raw_text="Our customer base grew significantly.",
            candidate_metric_ids=["cm_active_customers_total"],
            contains_definition_flag=False,
            classifier_confidence=0.92,
        )

        # All existing fields work
        assert segment.filing_id == 1
        assert segment.segment_type == "paragraph"
        assert segment.section_path == "Item 1. Business"
        assert segment.section_heading == "Customers"
        assert segment.sequence_index == 5
        assert segment.raw_text == "Our customer base grew significantly."
        assert segment.candidate_metric_ids == ["cm_active_customers_total"]
        assert segment.contains_definition_flag is False
        assert segment.classifier_confidence == 0.92

    def test_to_dict_contains_all_expected_keys(self):
        """Test that to_dict() contains both old and new fields."""
        segment = SourceSegment(filing_id=1, segment_type="paragraph", raw_text="Test")

        result = segment.to_dict()

        # Old fields present
        assert "filing_id" in result
        assert "segment_type" in result
        assert "raw_text" in result
        assert "candidate_metric_ids" in result
        assert "classifier_confidence" in result

        # New richness fields present
        assert "metric_density" in result
        assert "distinct_metric_count" in result
        assert "contains_temporal_trend" in result
        assert "contains_cohort_breakdown" in result
        assert "image_count" in result
        assert "richness_score" in result
