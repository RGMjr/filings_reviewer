"""
Golden-file tests for MetricClassifier.

These tests use "golden files" - expected classification outputs for known inputs.
They catch regressions when classification logic changes.
"""

import pytest

from src.extraction.metric_classifier import MetricClassifier
from src.extraction.models import SourceSegment
from tests.unit.extraction.test_utils import assert_classification_match, load_golden_file


@pytest.mark.skip(reason="Golden file not created yet - see tests/unit/extraction/golden/README.md")
def test_synthetic_segments_classification():
    """Test classification matches golden file for synthetic test segments."""
    # Load golden expectations
    golden = load_golden_file("synthetic_segments_expected", "metric_classifier")

    # Create classifier
    classifier = MetricClassifier()

    # Classify each test segment
    for i, test_case in enumerate(golden["test_segments"]):
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=i,
            raw_text=test_case["raw_text"]
        )

        # Classify
        result = classifier.classify_segment(segment)

        # Assert match
        assert_classification_match(result, test_case["expected_classification"])


@pytest.mark.skip(reason="Requires Shopify S-1 segmentation first - see golden/README.md")
def test_shopify_segments_classification():
    """Test that Shopify segment classification is deterministic.

    To enable this test:
    1. Run HTMLSegmenter on Shopify S-1 filing
    2. Extract representative segments (definitions, methodologies, numeric disclosures)
    3. Classify them and record expected results
    4. Create golden file with expected classifications
    5. Remove @pytest.mark.skip decorator
    """
    golden = load_golden_file("shopify_segments_expected", "metric_classifier")

    classifier = MetricClassifier()

    for test_case in golden["test_segments"]:
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=test_case["sequence_index"],
            raw_text=test_case["raw_text"]
        )

        result = classifier.classify_segment(segment)
        assert_classification_match(result, test_case["expected_classification"])


@pytest.mark.skip(reason="Requires Datadog F-1 segmentation first - see golden/README.md")
def test_datadog_segments_classification():
    """Test that Datadog segment classification is deterministic.

    To enable this test:
    1. Run HTMLSegmenter on Datadog F-1 filing
    2. Extract representative segments
    3. Classify them and record expected results
    4. Create golden file
    5. Remove @pytest.mark.skip decorator
    """
    golden = load_golden_file("datadog_segments_expected", "metric_classifier")

    classifier = MetricClassifier()

    for test_case in golden["test_segments"]:
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=test_case["sequence_index"],
            raw_text=test_case["raw_text"]
        )

        result = classifier.classify_segment(segment)
        assert_classification_match(result, test_case["expected_classification"])
