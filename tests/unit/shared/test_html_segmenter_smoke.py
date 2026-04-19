"""
Smoke tests for src/shared/html_segmenter.py.

Intentionally narrow: covers the constructor, input validation, and a minimal
happy-path parse against inline HTML. Full coverage of this 761-LOC module is
tracked under docs/KNOWN_ISSUES.md Issue #32 — these tests exist only to keep
the CI coverage gate green until that work is done.
"""

from __future__ import annotations

import pytest

from src.shared.extraction_exceptions import HTMLParsingError, ValidationError
from src.shared.html_segmenter import HTMLSegmenter, SegmentationMetrics

# ---------------------------------------------------------------------------
# SegmentationMetrics
# ---------------------------------------------------------------------------


def test_segmentation_metrics_defaults():
    m = SegmentationMetrics(filing_id=42)
    assert m.filing_id == 42
    assert m.total_segments == 0
    assert m.segment_counts_by_type == {}
    assert m.total_text_length == 0
    assert m.parse_time_seconds == 0.0
    assert m.encoding_used == "utf-8"
    assert m.warnings == []


def test_segmentation_metrics_avg_length_empty_is_zero():
    m = SegmentationMetrics(filing_id=1)
    assert m.avg_segment_length() == 0.0


def test_segmentation_metrics_avg_length_computed():
    m = SegmentationMetrics(filing_id=1, total_segments=4, total_text_length=800)
    assert m.avg_segment_length() == 200.0


def test_segmentation_metrics_summary_includes_counts_and_timing():
    m = SegmentationMetrics(
        filing_id=1,
        total_segments=3,
        segment_counts_by_type={"paragraph": 2, "table": 1},
        total_text_length=600,
        parse_time_seconds=0.123,
    )
    summary = m.summary()
    assert "3 segments" in summary
    assert "0.123" in summary
    assert "2 paragraphs" in summary
    assert "1 tables" in summary


# ---------------------------------------------------------------------------
# HTMLSegmenter constructor
# ---------------------------------------------------------------------------


def test_html_segmenter_default_construction():
    seg = HTMLSegmenter()
    assert seg.min_length == HTMLSegmenter.MIN_SEGMENT_LENGTH
    assert seg.max_length == HTMLSegmenter.MAX_SEGMENT_LENGTH


def test_html_segmenter_custom_lengths():
    seg = HTMLSegmenter(min_length=10, max_length=500)
    assert seg.min_length == 10
    assert seg.max_length == 500


def test_html_segmenter_rejects_invalid_lengths():
    with pytest.raises(ValidationError):
        HTMLSegmenter(min_length=-1, max_length=500)
    with pytest.raises(ValidationError):
        HTMLSegmenter(min_length=100, max_length=10)


# ---------------------------------------------------------------------------
# segment_filing input validation
# ---------------------------------------------------------------------------


def test_segment_filing_invalid_filing_id_returns_empty_when_silent():
    seg = HTMLSegmenter()
    # Silent path: validation failure → empty list, metrics not populated.
    result = seg.segment_filing(filing_id=0, html_content="<html><body><p>x</p></body></html>")
    assert result == []


def test_segment_filing_invalid_filing_id_raises_when_requested():
    seg = HTMLSegmenter()
    with pytest.raises(ValidationError):
        seg.segment_filing(
            filing_id=-1,
            html_content="<html><body><p>x</p></body></html>",
            raise_on_error=True,
        )


def test_segment_filing_empty_html_content_returns_empty_when_silent():
    seg = HTMLSegmenter()
    result = seg.segment_filing(filing_id=1, html_content="")
    assert result == []


def test_segment_filing_empty_html_content_raises_when_requested():
    seg = HTMLSegmenter()
    with pytest.raises(HTMLParsingError):
        seg.segment_filing(filing_id=1, html_content="", raise_on_error=True)


def test_segment_filing_missing_html_path_returns_empty_when_silent():
    seg = HTMLSegmenter()
    # No html_content, no valid path → ValidationError swallowed.
    result = seg.segment_filing(filing_id=1, html_path="")
    assert result == []


def test_segment_filing_nonexistent_html_path_raises_when_requested():
    seg = HTMLSegmenter()
    with pytest.raises(FileNotFoundError):
        seg.segment_filing(
            filing_id=1,
            html_path="/does/not/exist.htm",
            raise_on_error=True,
        )


# ---------------------------------------------------------------------------
# segment_filing happy path on inline HTML
# ---------------------------------------------------------------------------


_MINIMAL_SEC_HTML = """
<html>
  <body>
    <p>The following discussion analyzes our customer metrics for the period.
    Our total customer count reached one hundred thousand at period end,
    representing year-over-year growth of twenty percent. We define a
    customer as any entity with an active subscription during the period.</p>
    <table>
      <tr><th>Metric</th><th>2024</th><th>2023</th></tr>
      <tr><td>Customers</td><td>100,000</td><td>80,000</td></tr>
      <tr><td>Revenue</td><td>$50M</td><td>$40M</td></tr>
    </table>
    <p>Net revenue retention was calculated as the trailing-twelve-month
    revenue from our existing customer cohort divided by the prior period's
    revenue from the same cohort, expressed as a percentage.</p>
  </body>
</html>
""".strip()


def test_segment_filing_parses_inline_html_and_returns_segments():
    seg = HTMLSegmenter(min_length=20)
    result = seg.segment_filing(filing_id=1, html_content=_MINIMAL_SEC_HTML)
    # Happy path produces at least one segment. We do not pin exact counts —
    # the segmenter's internal heuristics can evolve — but it must not be empty
    # and every segment must be a SourceSegment keyed to filing_id=1.
    assert len(result) >= 1
    for s in result:
        assert s.filing_id == 1
        assert s.segment_type in {
            "paragraph",
            "table",
            "footnote",
            "definition_block",
            "methodology_block",
            "other",
        }


def test_segment_filing_populates_metrics_after_parse():
    seg = HTMLSegmenter(min_length=20)
    seg.segment_filing(filing_id=7, html_content=_MINIMAL_SEC_HTML)
    # Internal metrics object is populated as a side effect of parsing.
    assert seg._metrics is not None
    assert seg._metrics.filing_id == 7
    assert seg._metrics.encoding_used == "provided"
