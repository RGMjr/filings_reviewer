"""
Golden-file tests for HTMLSegmenter.

These tests use "golden files" - expected outputs for known inputs.
They catch regressions when extraction logic changes.
"""

import pytest

from src.extraction.html_segmenter import HTMLSegmenter
from tests.unit.extraction.test_utils import assert_segments_match, load_golden_file


def test_small_filing_segmentation():
    """Test segmentation matches golden file for small synthetic filing."""
    # Load golden expectations
    expected = load_golden_file("small_filing_expected", "html_segmenter")

    # Run segmentation
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(
        filing_id=1,
        html_path="data/fixtures/small_synthetic_filing.html"
    )

    # Assert match with ±5% tolerance
    assert_segments_match(segments, expected, tolerance=0.05)

    # Verify sample segments
    assert len(segments) >= 8
    assert segments[0].segment_type == "paragraph"
    assert segments[0].section_heading == "Prospectus Summary"
    assert segments[0].raw_text.startswith("We are a leading provider of cloud-based software solutions")


@pytest.mark.skip(reason="Requires Shopify S-1 filing download - see golden/README.md")
def test_shopify_s1_segmentation_deterministic():
    """Test that Shopify S-1 segmentation is deterministic and matches golden file.

    To enable this test:
    1. Download Shopify S-1 filing (see data/fixtures/shopify_s1_2015.json for URL)
    2. Run segmentation to generate baseline counts
    3. Create golden file with expected values
    4. Remove @pytest.mark.skip decorator
    """
    expected = load_golden_file("shopify_s1_2015_expected", "html_segmenter")

    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(
        filing_id=1,
        html_path="cache/1419612/000119312515140667/d893971ds1.htm"
    )

    assert_segments_match(segments, expected, tolerance=0.05)


@pytest.mark.skip(reason="Requires Datadog F-1 filing download - see golden/README.md")
def test_datadog_f1_segmentation_deterministic():
    """Test that Datadog F-1 segmentation is deterministic and matches golden file.

    To enable this test:
    1. Download Datadog F-1 filing (see data/fixtures/datadog_f1_2019.json for URL)
    2. Run segmentation to generate baseline counts
    3. Create golden file with expected values
    4. Remove @pytest.mark.skip decorator
    """
    expected = load_golden_file("datadog_f1_2019_expected", "html_segmenter")

    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(
        filing_id=1,
        html_path="cache/1561550/000119312519222862/d735281df1.htm"
    )

    assert_segments_match(segments, expected, tolerance=0.05)
