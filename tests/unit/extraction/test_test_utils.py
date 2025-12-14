"""
Tests for extraction test utilities.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.extraction.models import SourceSegment
from tests.unit.extraction.test_utils import (
    assert_classification_match,
    assert_segments_match,
    create_temp_html_file,
    load_golden_file,
)


class TestLoadGoldenFile:
    """Tests for load_golden_file utility."""

    def test_load_golden_file_creates_directory_structure(self):
        """Test loading golden file uses correct directory structure."""
        # Create a test golden file
        golden_dir = Path(__file__).parent / "golden"
        test_subdir = golden_dir / "test_subdir"
        test_subdir.mkdir(parents=True, exist_ok=True)

        test_file = test_subdir / "test_data.json"
        test_data = {"key": "value", "number": 123}

        try:
            with open(test_file, "w") as f:
                json.dump(test_data, f)

            # Load the file
            result = load_golden_file("test_data", "test_subdir")

            assert result == test_data
            assert result["key"] == "value"
            assert result["number"] == 123

        finally:
            # Cleanup
            if test_file.exists():
                test_file.unlink()
            if test_subdir.exists():
                test_subdir.rmdir()

    def test_load_golden_file_not_found(self):
        """Test loading non-existent golden file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_golden_file("nonexistent_file", "nonexistent_subdir")


class TestCreateTempHtmlFile:
    """Tests for create_temp_html_file utility."""

    def test_create_temp_html_file_creates_file(self):
        """Test temp file is created with correct content."""
        content = "<html><body>Test content</body></html>"

        path = create_temp_html_file(content)

        try:
            # Verify file exists
            assert Path(path).exists()

            # Verify content
            with open(path, "r") as f:
                actual_content = f.read()
            assert actual_content == content

        finally:
            Path(path).unlink()

    def test_create_temp_html_file_custom_suffix(self):
        """Test temp file uses custom suffix."""
        content = "<xml>test</xml>"

        path = create_temp_html_file(content, suffix=".xml")

        try:
            assert path.endswith(".xml")
            assert Path(path).exists()

        finally:
            Path(path).unlink()


class TestAssertSegmentsMatch:
    """Tests for assert_segments_match utility."""

    def test_assert_segments_match_success(self):
        """Test matching segments pass assertion."""
        segments = [
            SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="Shopify is a leading platform"),
            SourceSegment(filing_id=1, sequence_index=1, segment_type="paragraph", raw_text="We define revenue"),
            SourceSegment(filing_id=1, sequence_index=2, segment_type="table", raw_text="Revenue by region"),
        ]

        expected = {
            "expected_segment_count": 3,
            "expected_segment_types": {"paragraph": 2, "table": 1},
            "sample_segments": [{"sequence_index": 0, "segment_type": "paragraph", "raw_text_prefix": "Shopify is"}],
        }

        # Should not raise
        assert_segments_match(segments, expected, tolerance=0.05)

    def test_assert_segments_match_count_mismatch(self):
        """Test segment count outside tolerance raises AssertionError."""
        segments = [SourceSegment(filing_id=1, sequence_index=i, segment_type="paragraph", raw_text="test") for i in range(10)]

        expected = {"expected_segment_count": 20, "expected_segment_types": {"paragraph": 20}}

        with pytest.raises(AssertionError, match="Segment count .* not in expected range"):
            assert_segments_match(segments, expected, tolerance=0.05)

    def test_assert_segments_match_type_distribution_mismatch(self):
        """Test type distribution mismatch raises AssertionError."""
        segments = [
            SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="test"),
            SourceSegment(filing_id=1, sequence_index=1, segment_type="paragraph", raw_text="test"),
        ]

        expected = {"expected_segment_count": 2, "expected_segment_types": {"paragraph": 1, "table": 1}}

        # The first type mismatch will be caught (paragraph has 2 instead of 1)
        with pytest.raises(AssertionError, match="Type .* count"):
            assert_segments_match(segments, expected, tolerance=0.05)

    def test_assert_segments_match_sample_mismatch(self):
        """Test sample segment mismatch raises AssertionError."""
        segments = [SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="Wrong text content")]

        expected = {
            "expected_segment_count": 1,
            "expected_segment_types": {"paragraph": 1},
            "sample_segments": [{"sequence_index": 0, "raw_text_prefix": "Expected text"}],
        }

        with pytest.raises(AssertionError, match="text doesn't start with"):
            assert_segments_match(segments, expected, tolerance=0.05)


class TestAssertClassificationMatch:
    """Tests for assert_classification_match utility."""

    def test_assert_classification_match_success(self):
        """Test matching classification passes assertion."""
        segment = SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="We define DAU as...")

        segment.contains_definition_flag = True
        segment.contains_methodology_flag = False
        segment.contains_numeric_disclosure_flag = True
        segment.candidate_metric_ids = ["cm_daily_active_users"]
        segment.confidence = 0.75

        expected = {
            "contains_definition_flag": True,
            "contains_methodology_flag": False,
            "contains_numeric_disclosure_flag": True,
            "candidate_metric_ids": ["cm_daily_active_users"],
            "min_confidence": 0.7,
            "max_confidence": 0.8,
        }

        # Should not raise
        assert_classification_match(segment, expected)

    def test_assert_classification_match_flag_mismatch(self):
        """Test flag mismatch raises AssertionError."""
        segment = SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="Test")
        segment.contains_definition_flag = False

        expected = {"contains_definition_flag": True, "candidate_metric_ids": []}

        with pytest.raises(AssertionError, match="Definition flag"):
            assert_classification_match(segment, expected)

    def test_assert_classification_match_metrics_mismatch(self):
        """Test candidate metrics mismatch raises AssertionError."""
        segment = SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="Test")
        segment.contains_definition_flag = True
        segment.candidate_metric_ids = ["cm_daily_active_users"]

        expected = {"contains_definition_flag": True, "candidate_metric_ids": ["cm_monthly_active_users"]}

        with pytest.raises(AssertionError, match="Candidate metrics"):
            assert_classification_match(segment, expected)

    def test_assert_classification_match_confidence_out_of_range(self):
        """Test confidence outside range raises AssertionError."""
        segment = SourceSegment(filing_id=1, sequence_index=0, segment_type="paragraph", raw_text="Test")
        segment.contains_definition_flag = True
        segment.candidate_metric_ids = []
        segment.confidence = 0.9

        expected = {"contains_definition_flag": True, "candidate_metric_ids": [], "min_confidence": 0.5, "max_confidence": 0.7}

        with pytest.raises(AssertionError, match="Confidence .* above maximum"):
            assert_classification_match(segment, expected)
