"""
Tests for extraction validators.
"""

import tempfile
from pathlib import Path

import pytest

from src.extraction.exceptions import ValidationError
from src.extraction.models import SourceSegment
from src.extraction.validators import ClassificationValidator, SegmentValidator


class TestSegmentValidator:
    """Tests for SegmentValidator."""

    def test_validate_filing_id_valid(self):
        """Test valid filing IDs pass validation."""
        SegmentValidator.validate_filing_id(1)
        SegmentValidator.validate_filing_id(12345)
        SegmentValidator.validate_filing_id(999999)
        # Should not raise

    def test_validate_filing_id_invalid_type(self):
        """Test non-integer filing_id raises ValidationError."""
        with pytest.raises(ValidationError, match="must be an integer"):
            SegmentValidator.validate_filing_id("123")

        with pytest.raises(ValidationError, match="must be an integer"):
            SegmentValidator.validate_filing_id(12.5)

    def test_validate_filing_id_not_positive(self):
        """Test non-positive filing_id raises ValidationError."""
        with pytest.raises(ValidationError, match="must be positive"):
            SegmentValidator.validate_filing_id(0)

        with pytest.raises(ValidationError, match="must be positive"):
            SegmentValidator.validate_filing_id(-1)

    def test_validate_html_path_valid(self):
        """Test valid HTML path passes validation."""
        # Create temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html><body>Test</body></html>")
            temp_path = f.name

        try:
            result = SegmentValidator.validate_html_path(temp_path)
            assert isinstance(result, Path)
            assert result.exists()
            assert result.is_absolute()
        finally:
            Path(temp_path).unlink()

    def test_validate_html_path_not_exists(self):
        """Test non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            SegmentValidator.validate_html_path("/nonexistent/path/file.html")

    def test_validate_html_path_not_file(self):
        """Test directory path raises ValidationError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValidationError, match="not a file"):
                SegmentValidator.validate_html_path(tmpdir)

    def test_validate_html_path_empty(self):
        """Test empty path raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            SegmentValidator.validate_html_path("")

        with pytest.raises(ValidationError, match="cannot be empty"):
            SegmentValidator.validate_html_path("   ")

    def test_validate_segment_valid(self):
        """Test valid segment passes validation."""
        segment = SourceSegment(
            filing_id=123, sequence_index=0, segment_type="paragraph", raw_text="Test content"
        )

        SegmentValidator.validate_segment(segment)
        # Should not raise

    def test_validate_segment_invalid_type(self):
        """Test non-SourceSegment raises ValidationError."""
        with pytest.raises(ValidationError, match="must be SourceSegment"):
            SegmentValidator.validate_segment({"filing_id": 123})

    def test_validate_segment_invalid_filing_id(self):
        """Test segment with invalid filing_id raises ValidationError."""
        segment = SourceSegment(
            filing_id=0, sequence_index=0, segment_type="paragraph", raw_text="Test"
        )

        with pytest.raises(ValidationError, match="filing_id must be positive"):
            SegmentValidator.validate_segment(segment)

    def test_validate_segment_missing_segment_type(self):
        """Test segment without segment_type raises ValidationError."""
        segment = SourceSegment(filing_id=123, sequence_index=0, segment_type="", raw_text="Test")

        with pytest.raises(ValidationError, match="must have segment_type"):
            SegmentValidator.validate_segment(segment)

    def test_validate_segment_negative_sequence_index(self):
        """Test segment with negative sequence_index raises ValidationError."""
        segment = SourceSegment(
            filing_id=123, sequence_index=-1, segment_type="paragraph", raw_text="Test content"
        )

        with pytest.raises(ValidationError, match="sequence_index must be >= 0"):
            SegmentValidator.validate_segment(segment)

    def test_validate_min_max_length_valid(self):
        """Test valid min/max length passes validation."""
        SegmentValidator.validate_min_max_length(50, 10000)
        SegmentValidator.validate_min_max_length(0, 1000)
        SegmentValidator.validate_min_max_length(100, 100)
        # Should not raise

    def test_validate_min_max_length_invalid_types(self):
        """Test non-integer lengths raise ValidationError."""
        with pytest.raises(ValidationError, match="must be integers"):
            SegmentValidator.validate_min_max_length("50", 100)

        with pytest.raises(ValidationError, match="must be integers"):
            SegmentValidator.validate_min_max_length(50, 100.5)

    def test_validate_min_max_length_negative_min(self):
        """Test negative min_length raises ValidationError."""
        with pytest.raises(ValidationError, match="min_length must be non-negative"):
            SegmentValidator.validate_min_max_length(-10, 100)

    def test_validate_min_max_length_non_positive_max(self):
        """Test non-positive max_length raises ValidationError."""
        with pytest.raises(ValidationError, match="max_length must be positive"):
            SegmentValidator.validate_min_max_length(50, 0)

        with pytest.raises(ValidationError, match="max_length must be positive"):
            SegmentValidator.validate_min_max_length(50, -100)

    def test_validate_min_max_length_min_greater_than_max(self):
        """Test min > max raises ValidationError."""
        with pytest.raises(ValidationError, match="min_length .* must be <= max_length"):
            SegmentValidator.validate_min_max_length(200, 100)


class TestClassificationValidator:
    """Tests for ClassificationValidator."""

    def test_validate_confidence_valid(self):
        """Test valid confidence scores pass validation."""
        ClassificationValidator.validate_confidence(0.0)
        ClassificationValidator.validate_confidence(0.5)
        ClassificationValidator.validate_confidence(1.0)
        ClassificationValidator.validate_confidence(0.123456)
        # Should not raise

    def test_validate_confidence_out_of_range(self):
        """Test confidence score outside [0, 1] raises ValidationError."""
        with pytest.raises(ValidationError, match="must be in \\[0, 1\\] range"):
            ClassificationValidator.validate_confidence(-0.1)

        with pytest.raises(ValidationError, match="must be in \\[0, 1\\] range"):
            ClassificationValidator.validate_confidence(1.1)

    def test_validate_confidence_invalid_type(self):
        """Test non-numeric confidence raises ValidationError."""
        with pytest.raises(ValidationError, match="must be a number"):
            ClassificationValidator.validate_confidence("0.5")

        with pytest.raises(ValidationError, match="must be a number"):
            ClassificationValidator.validate_confidence(None)

    def test_validate_metric_ids_valid(self):
        """Test valid metric ID lists pass validation."""
        ClassificationValidator.validate_metric_ids([])
        ClassificationValidator.validate_metric_ids(["cm_daily_active_users"])
        ClassificationValidator.validate_metric_ids(["cm_dau", "cm_mau", "cm_revenue_per_customer"])
        # Should not raise

    def test_validate_metric_ids_invalid_type(self):
        """Test non-list metric_ids raises ValidationError."""
        with pytest.raises(ValidationError, match="must be a list"):
            ClassificationValidator.validate_metric_ids("cm_dau")

        with pytest.raises(ValidationError, match="must be a list"):
            ClassificationValidator.validate_metric_ids({"cm_dau"})

    def test_validate_metric_ids_non_string_element(self):
        """Test non-string elements raise ValidationError."""
        with pytest.raises(ValidationError, match="metric_ids\\[1\\] must be a string"):
            ClassificationValidator.validate_metric_ids(["cm_dau", 123, "cm_mau"])

    def test_validate_metric_ids_empty_string(self):
        """Test empty string elements raise ValidationError."""
        with pytest.raises(ValidationError, match="metric_ids\\[0\\] cannot be empty"):
            ClassificationValidator.validate_metric_ids([""])

        with pytest.raises(ValidationError, match="metric_ids\\[1\\] cannot be empty"):
            ClassificationValidator.validate_metric_ids(["cm_dau", "   ", "cm_mau"])

    def test_validate_segment_for_classification_valid(self):
        """Test valid segment passes classification validation."""
        segment = SourceSegment(
            filing_id=123,
            sequence_index=0,
            segment_type="paragraph",
            raw_text="We define DAU as...",
        )

        ClassificationValidator.validate_segment_for_classification(segment)
        # Should not raise

    def test_validate_segment_for_classification_missing_raw_text(self):
        """Test segment without raw_text raises ValidationError."""
        segment = SourceSegment(
            filing_id=123, sequence_index=0, segment_type="paragraph", raw_text=None
        )

        with pytest.raises(ValidationError, match="must have raw_text for classification"):
            ClassificationValidator.validate_segment_for_classification(segment)

    def test_validate_segment_for_classification_invalid_raw_text_type(self):
        """Test segment with non-string raw_text raises ValidationError."""
        segment = SourceSegment(filing_id=123, sequence_index=0, segment_type="paragraph")
        segment.raw_text = 12345  # Invalid type

        with pytest.raises(ValidationError, match="raw_text must be a string"):
            ClassificationValidator.validate_segment_for_classification(segment)
