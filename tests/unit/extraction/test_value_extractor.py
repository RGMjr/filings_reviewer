"""
Unit tests for ValueExtractor.

These cover basic text extraction behavior and guard against regressions in the
extraction_method flag expected by the analysis schema.
"""

from decimal import Decimal

from src.extraction.models import SourceSegment
from src.extraction.value_extractor import ValueExtractor


def build_segment(**overrides) -> SourceSegment:
    """Helper to construct a SourceSegment with sensible defaults."""
    defaults = {
        "filing_id": 1,
        "segment_type": "paragraph",
        "raw_text": "Placeholder",
        "sequence_index": 0,
        "candidate_metric_ids": [],
        "contains_numeric_disclosure_flag": True,
    }
    defaults.update(overrides)
    return SourceSegment(**defaults)


def test_extract_from_text_returns_llm_text_method():
    """Text extraction should populate values with the allowed extraction method."""
    segment = build_segment(
        raw_text="We had approximately 1,500 daily active users (DAUs).",
        candidate_metric_ids=["cm_daily_active_users"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=42)

    assert len(values) == 1
    value = values[0]
    assert value.metric_id == "cm_daily_active_users"
    assert value.extraction_method == "llm_text"
    assert value.value_numeric == Decimal("1500")


def test_extract_from_text_handles_missing_candidate_metrics():
    """Segments without candidate metric ids should not raise errors."""
    # Explicitly set candidate_metric_ids to None to simulate legacy data.
    segment = build_segment(
        raw_text="Customers spent $10 million during FY 2024.",
        candidate_metric_ids=None,
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=99)

    assert values == []
