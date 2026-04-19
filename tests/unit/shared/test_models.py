"""Unit tests for src/shared/models.py."""

from datetime import datetime

from src.shared.models import SourceSegment


def test_source_segment_defaults_match_schema():
    seg = SourceSegment(filing_id=1, segment_type="paragraph")
    assert seg.filing_id == 1
    assert seg.segment_type == "paragraph"
    assert seg.sequence_index == 0
    assert seg.raw_text == ""
    assert seg.raw_html is None
    assert seg.candidate_metric_ids == []
    assert seg.contains_definition_flag is False
    assert seg.contains_methodology_flag is False
    assert seg.contains_numeric_disclosure_flag is False
    assert seg.classifier_confidence is None
    assert seg.metric_density is None
    assert seg.distinct_metric_count == 0
    assert seg.contains_temporal_trend is False
    assert seg.contains_cohort_breakdown is False
    assert seg.image_count == 0
    assert seg.richness_score is None
    assert seg.extra_metadata is None
    assert seg.source_segment_id is None


def test_source_segment_candidate_metric_ids_are_independent_per_instance():
    # Guard against accidental shared mutable default.
    a = SourceSegment(filing_id=1, segment_type="paragraph")
    b = SourceSegment(filing_id=2, segment_type="table")
    a.candidate_metric_ids.append("cm_revenue_concentration")
    assert b.candidate_metric_ids == []


def test_source_segment_to_dict_returns_all_schema_keys():
    now = datetime(2026, 4, 19, 12, 0, 0)
    seg = SourceSegment(
        filing_id=7,
        segment_type="table",
        section_path="Item 1 > Customers",
        section_heading="Customers",
        sequence_index=3,
        html_selector="//table[1]",
        char_start_offset=100,
        char_end_offset=500,
        page_number=2,
        raw_text="A customer table.",
        raw_html="<table></table>",
        candidate_metric_ids=["cm_active_customers_total"],
        contains_definition_flag=True,
        contains_methodology_flag=False,
        contains_numeric_disclosure_flag=True,
        classifier_confidence=0.85,
        context_prefix="Prior sentence.",
        document_position=0.42,
        sentence_boundaries=[(0, 17)],
        table_truncated_flag=False,
        definition_merged_count=1,
        metric_density=1.5,
        distinct_metric_count=2,
        contains_temporal_trend=True,
        contains_cohort_breakdown=False,
        image_count=0,
        richness_score=7.2,
        extra_metadata={"saas_indicator": True},
        source_segment_id=123,
        created_at=now,
        updated_at=now,
    )
    d = seg.to_dict()
    # Core persistence fields land in the dict.
    assert d["filing_id"] == 7
    assert d["segment_type"] == "table"
    assert d["section_path"] == "Item 1 > Customers"
    assert d["raw_text"] == "A customer table."
    assert d["candidate_metric_ids"] == ["cm_active_customers_total"]
    assert d["classifier_confidence"] == 0.85
    # Context fields (not in DB schema but preserved by to_dict).
    assert d["context_prefix"] == "Prior sentence."
    assert d["document_position"] == 0.42
    # Richness fields survive round-trip.
    assert d["richness_score"] == 7.2
    assert d["extra_metadata"] == {"saas_indicator": True}
    # DB-only fields (source_segment_id, created_at/updated_at) are intentionally
    # excluded from to_dict — guard against accidental inclusion.
    assert "source_segment_id" not in d
    assert "created_at" not in d
    assert "updated_at" not in d


def test_source_segment_to_dict_handles_none_optional_fields():
    seg = SourceSegment(filing_id=1, segment_type="paragraph")
    d = seg.to_dict()
    assert d["section_path"] is None
    assert d["html_selector"] is None
    assert d["classifier_confidence"] is None
    assert d["raw_html"] is None
    assert d["extra_metadata"] is None
