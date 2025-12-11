"""
Test utilities for extraction module tests.

Provides helper functions for golden-file testing, temp file creation,
and assertion utilities for comparing extraction results.
"""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from src.extraction.models import SourceSegment


# Directory for golden files
GOLDEN_DIR = Path(__file__).parent / "golden"


def load_golden_file(name: str, subdir: str = "") -> dict:
    """Load golden JSON file from tests/unit/extraction/golden/.

    Args:
        name: Name of golden file (without .json extension)
        subdir: Optional subdirectory (e.g., 'html_segmenter', 'metric_classifier')

    Returns:
        Parsed JSON as dict

    Raises:
        FileNotFoundError: If golden file doesn't exist
        json.JSONDecodeError: If file is not valid JSON

    Example:
        >>> data = load_golden_file("shopify_s1_2015_expected", "html_segmenter")
        >>> assert data["filing_metadata"]["cik"] == "0001419612"
    """
    if subdir:
        golden_path = GOLDEN_DIR / subdir / f"{name}.json"
    else:
        golden_path = GOLDEN_DIR / f"{name}.json"

    if not golden_path.exists():
        raise FileNotFoundError(f"Golden file not found: {golden_path}")

    with open(golden_path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_temp_html_file(content: str, suffix: str = ".html") -> str:
    """Create temporary HTML file for testing.

    Args:
        content: HTML content to write
        suffix: File suffix (default: .html)

    Returns:
        Path to temporary file (caller should clean up)

    Example:
        >>> path = create_temp_html_file("<html><body>Test</body></html>")
        >>> # Use path in tests...
        >>> Path(path).unlink()  # Clean up
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(content)
        return f.name


def assert_segments_match(actual: List[SourceSegment], expected: dict, tolerance: float = 0.05) -> None:
    """Assert segments match golden file expectations.

    Compares actual segmentation results against expected values from golden file.
    Uses tolerance-based comparison for counts to handle minor variations.

    Args:
        actual: List of actual SourceSegment objects
        expected: Expected results from golden file with keys:
            - expected_segment_count: Total segments (±tolerance)
            - expected_segment_types: Dict of type counts
            - sample_segments: List of segments to verify
        tolerance: Acceptable deviation for counts (default: 5%)

    Raises:
        AssertionError: If actual doesn't match expected

    Example:
        >>> expected = {
        ...     "expected_segment_count": 450,
        ...     "expected_segment_types": {"paragraph": 380, "table": 45},
        ...     "sample_segments": [
        ...         {"sequence_index": 0, "segment_type": "paragraph", "raw_text_prefix": "Shopify"}
        ...     ]
        ... }
        >>> assert_segments_match(segments, expected)
    """
    # Check total count with tolerance
    expected_count = expected["expected_segment_count"]
    min_count = int(expected_count * (1 - tolerance))
    max_count = int(expected_count * (1 + tolerance))

    assert (
        min_count <= len(actual) <= max_count
    ), f"Segment count {len(actual)} not in expected range [{min_count}, {max_count}] (target: {expected_count})"

    # Check segment type distribution
    actual_types: Dict[str, int] = {}
    for segment in actual:
        actual_types[segment.segment_type] = actual_types.get(segment.segment_type, 0) + 1

    for seg_type, expected_type_count in expected["expected_segment_types"].items():
        actual_type_count = actual_types.get(seg_type, 0)
        min_type_count = int(expected_type_count * (1 - tolerance))
        max_type_count = int(expected_type_count * (1 + tolerance))

        assert (
            min_type_count <= actual_type_count <= max_type_count
        ), f"Type '{seg_type}' count {actual_type_count} not in range [{min_type_count}, {max_type_count}] (target: {expected_type_count})"

    # Check sample segments
    if "sample_segments" in expected:
        for expected_sample in expected["sample_segments"]:
            seq_index = expected_sample["sequence_index"]

            # Find segment by index
            matching_segments = [s for s in actual if s.sequence_index == seq_index]
            assert len(matching_segments) == 1, f"Expected exactly 1 segment with sequence_index={seq_index}, found {len(matching_segments)}"

            segment = matching_segments[0]

            # Check segment type
            if "segment_type" in expected_sample:
                assert (
                    segment.segment_type == expected_sample["segment_type"]
                ), f"Segment {seq_index}: expected type '{expected_sample['segment_type']}', got '{segment.segment_type}'"

            # Check text prefix
            if "raw_text_prefix" in expected_sample:
                prefix = expected_sample["raw_text_prefix"]
                assert segment.raw_text.startswith(
                    prefix
                ), f"Segment {seq_index}: text doesn't start with '{prefix}', got: {segment.raw_text[:50]}"

            # Check section heading
            if "section_heading" in expected_sample:
                assert (
                    segment.section_heading == expected_sample["section_heading"]
                ), f"Segment {seq_index}: expected heading '{expected_sample['section_heading']}', got '{segment.section_heading}'"

    # Check sequence indices are sequential
    indices = [s.sequence_index for s in actual]
    assert indices == list(range(len(indices))), f"Sequence indices not sequential: {indices[:10]}..."


def assert_classification_match(segment: SourceSegment, expected: dict) -> None:
    """Assert classification matches expected values.

    Compares segment classification results against expected values.

    Args:
        segment: SourceSegment with classification results
        expected: Expected results with keys:
            - contains_definition_flag: bool
            - contains_methodology_flag: bool (optional)
            - contains_numeric_disclosure_flag: bool (optional)
            - candidate_metric_ids: List[str]
            - min_confidence: float (optional)
            - max_confidence: float (optional)

    Raises:
        AssertionError: If classification doesn't match

    Example:
        >>> expected = {
        ...     "contains_definition_flag": True,
        ...     "candidate_metric_ids": ["cm_revenue_per_customer"],
        ...     "min_confidence": 0.5,
        ...     "max_confidence": 0.8
        ... }
        >>> assert_classification_match(segment, expected)
    """
    # Check flags
    assert (
        segment.contains_definition_flag == expected["contains_definition_flag"]
    ), f"Definition flag: expected {expected['contains_definition_flag']}, got {segment.contains_definition_flag}"

    if "contains_methodology_flag" in expected:
        assert (
            segment.contains_methodology_flag == expected["contains_methodology_flag"]
        ), f"Methodology flag: expected {expected['contains_methodology_flag']}, got {segment.contains_methodology_flag}"

    if "contains_numeric_disclosure_flag" in expected:
        assert (
            segment.contains_numeric_disclosure_flag == expected["contains_numeric_disclosure_flag"]
        ), f"Numeric flag: expected {expected['contains_numeric_disclosure_flag']}, got {segment.contains_numeric_disclosure_flag}"

    # Check candidate metrics (order independent)
    expected_metrics = set(expected["candidate_metric_ids"])
    actual_metrics = set(segment.candidate_metric_ids or [])

    assert (
        actual_metrics == expected_metrics
    ), f"Candidate metrics: expected {expected_metrics}, got {actual_metrics}. Missing: {expected_metrics - actual_metrics}, Extra: {actual_metrics - expected_metrics}"

    # Check confidence range
    if "min_confidence" in expected:
        assert (
            segment.classifier_confidence >= expected["min_confidence"]
        ), f"Confidence {segment.classifier_confidence} below minimum {expected['min_confidence']}"

    if "max_confidence" in expected:
        assert (
            segment.classifier_confidence <= expected["max_confidence"]
        ), f"Confidence {segment.classifier_confidence} above maximum {expected['max_confidence']}"
