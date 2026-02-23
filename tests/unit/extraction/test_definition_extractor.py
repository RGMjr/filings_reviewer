"""
Unit tests for DefinitionExtractor.

Tests the extraction of metric definitions and methodologies from segments.
"""

from unittest.mock import Mock

import pytest

from src.extraction.definition_extractor import DefinitionExtractor, extract_definitions
from src.extraction.models import SourceSegment


@pytest.fixture
def extractor():
    """Create a DefinitionExtractor instance."""
    return DefinitionExtractor()


@pytest.fixture
def sample_segments_with_definition():
    """Create sample segments with definition and methodology."""
    return [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="We define daily active users as unique users who log in at least once per day.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
            contains_methodology_flag=False,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="DAU is calculated by counting distinct user IDs with login events in a 24-hour period.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=False,
            contains_methodology_flag=True,
        ),
    ]


@pytest.fixture
def sample_segments_new_customers():
    """Create segments for new customers metric with canonical keywords."""
    return [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="New customers acquired represents the count of unique customers whose first qualifying economic activity occurs in the reporting period.",
            candidate_metric_ids=["cm_new_customers_acquired"],
            contains_definition_flag=True,
            contains_methodology_flag=False,
        ),
    ]


def test_extractor_initialization(extractor):
    """Test that extractor initializes properly."""
    assert extractor is not None
    assert hasattr(extractor, "CANONICAL_DEFINITIONS")
    assert len(extractor.CANONICAL_DEFINITIONS) > 0


def test_extract_definitions_empty_list(extractor):
    """Test extraction with empty segment list."""
    definitions = extractor.extract_definitions(segments=[], company_id=1)
    assert definitions == []


def test_extract_definitions_no_metrics(extractor):
    """Test extraction with segments that have no candidate metrics."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="General text without metrics.",
            candidate_metric_ids=None,
        ),
    ]
    definitions = extractor.extract_definitions(segments, company_id=1)
    assert definitions == []


def test_extract_single_definition(extractor, sample_segments_with_definition):
    """Test extraction of a single definition."""
    definitions = extractor.extract_definitions(sample_segments_with_definition, company_id=1)

    assert len(definitions) == 1
    definition = definitions[0]

    assert definition.metric_id == "cm_daily_active_users"
    assert definition.company_id == 1
    assert definition.filing_id == 1
    assert definition.definition_text_normalized is not None
    assert "daily active users" in definition.definition_text_normalized.lower()


def test_extract_definition_and_methodology(extractor, sample_segments_with_definition):
    """Test extraction of both definition and methodology."""
    definitions = extractor.extract_definitions(sample_segments_with_definition, company_id=1)

    definition = definitions[0]
    assert definition.definition_text_normalized is not None
    assert definition.methodology_text_normalized is not None
    assert "unique users" in definition.definition_text_normalized.lower()
    assert "calculated" in definition.methodology_text_normalized.lower()


def test_group_segments_by_metric(extractor):
    """Test grouping segments by metric."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="DAU text",
            candidate_metric_ids=["cm_daily_active_users"],
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="MAU text",
            candidate_metric_ids=["cm_monthly_active_users"],
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=2,
            raw_text="Both DAU and MAU",
            candidate_metric_ids=["cm_daily_active_users", "cm_monthly_active_users"],
        ),
    ]

    grouped = extractor._group_segments_by_metric(segments)

    assert "cm_daily_active_users" in grouped
    assert "cm_monthly_active_users" in grouped
    assert len(grouped["cm_daily_active_users"]) == 2  # Segments 0 and 2
    assert len(grouped["cm_monthly_active_users"]) == 2  # Segments 1 and 2


def test_group_segments_handles_none_candidate_ids(extractor):
    """Test grouping handles segments with None candidate_metric_ids."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Text without metrics",
            candidate_metric_ids=None,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="DAU text",
            candidate_metric_ids=["cm_daily_active_users"],
        ),
    ]

    grouped = extractor._group_segments_by_metric(segments)

    # Should only have the metric from segment 1
    assert len(grouped) == 1
    assert "cm_daily_active_users" in grouped


def test_normalize_definition_text(extractor):
    """Test text normalization."""
    text = "This   has    multiple   spaces   and\n\nnewlines\nthat   should   be   normalized."
    normalized = extractor._normalize_definition_text(text)

    # Should have single spaces
    assert "  " not in normalized
    # Should not have multiple newlines
    assert "\n\n" not in normalized
    # Should be stripped
    assert normalized == normalized.strip()


def test_normalize_long_text_truncates(extractor):
    """Test that very long text is truncated."""
    long_text = "A" * 1000  # 1000 characters
    normalized = extractor._normalize_definition_text(long_text)

    # Should be truncated to 500 chars + "..."
    assert len(normalized) <= 503
    assert normalized.endswith("...")


def test_assess_alignment_aligned(extractor, sample_segments_new_customers):
    """Test alignment assessment for well-aligned definition."""
    definition_text = sample_segments_new_customers[0].raw_text
    alignment = extractor.assess_alignment("cm_new_customers_acquired", definition_text)

    # Should be aligned - has many canonical keywords
    assert alignment == "aligned"


def test_assess_alignment_partial(extractor):
    """Test alignment assessment for partially aligned definition."""
    # Has some keywords but not all
    definition_text = "New customers are those making their first purchase in the period."
    alignment = extractor.assess_alignment("cm_new_customers_acquired", definition_text)

    # Should be partial alignment
    assert alignment in ["partial", "aligned"]


def test_assess_alignment_not_aligned(extractor):
    """Test alignment assessment for poorly aligned definition."""
    # Has very few canonical keywords
    definition_text = "People who bought stuff."
    alignment = extractor.assess_alignment("cm_new_customers_acquired", definition_text)

    # Should not be aligned
    assert alignment in ["not_aligned", "unknown"]


def test_assess_alignment_no_definition(extractor):
    """Test alignment assessment with no definition."""
    alignment = extractor.assess_alignment("cm_daily_active_users", None)
    assert alignment == "unknown"


def test_assess_alignment_no_canonical(extractor):
    """Test alignment assessment for metric without canonical definition."""
    alignment = extractor.assess_alignment("unknown_metric_id", "Some definition text")
    assert alignment == "unknown"


def test_extract_multiple_metrics(extractor):
    """Test extraction of multiple different metrics."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="We define DAU as daily active users.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="MAU is defined as monthly active users.",
            candidate_metric_ids=["cm_monthly_active_users"],
            contains_definition_flag=True,
        ),
    ]

    definitions = extractor.extract_definitions(segments, company_id=1)

    assert len(definitions) == 2
    metric_ids = {d.metric_id for d in definitions}
    assert "cm_daily_active_users" in metric_ids
    assert "cm_monthly_active_users" in metric_ids


def test_no_definition_or_methodology_returns_none(extractor):
    """Test that segments without definition/methodology flags return None."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Just mentions DAU without defining it.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=False,
            contains_methodology_flag=False,
        ),
    ]

    definitions = extractor.extract_definitions(segments, company_id=1)
    assert definitions == []


def test_definition_stores_segment_ids(extractor, sample_segments_with_definition):
    """Test that definition stores segment IDs properly."""
    definitions = extractor.extract_definitions(sample_segments_with_definition, company_id=1)

    definition = definitions[0]
    assert definition.definition_segment_id == 0  # First segment
    assert definition.methodology_segment_id == 1  # Second segment


def test_definition_stores_raw_text(extractor, sample_segments_with_definition):
    """Test that raw text is stored."""
    definitions = extractor.extract_definitions(sample_segments_with_definition, company_id=1)

    definition = definitions[0]
    assert definition.definition_raw_text == sample_segments_with_definition[0].raw_text
    assert definition.methodology_raw_text == sample_segments_with_definition[1].raw_text


def test_only_definition_no_methodology(extractor):
    """Test extraction when only definition is present."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="We define DAU as daily active users.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
            contains_methodology_flag=False,
        ),
    ]

    definitions = extractor.extract_definitions(segments, company_id=1)

    definition = definitions[0]
    assert definition.definition_text_normalized is not None
    assert definition.methodology_text_normalized is None


def test_only_methodology_no_definition(extractor):
    """Test extraction when only methodology is present."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="DAU is calculated by counting unique daily logins.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=False,
            contains_methodology_flag=True,
        ),
    ]

    definitions = extractor.extract_definitions(segments, company_id=1)

    definition = definitions[0]
    assert definition.definition_text_normalized is None
    assert definition.methodology_text_normalized is not None


def test_convenience_function():
    """Test the convenience extract_definitions function."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="We define DAU as daily active users.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        ),
    ]

    # Use the convenience function
    definitions = extract_definitions(segments, company_id=1)

    assert len(definitions) == 1
    assert definitions[0].metric_id == "cm_daily_active_users"


def test_canonical_definitions_coverage(extractor):
    """Test that canonical definitions exist for core metrics."""
    expected_metrics = [
        "cm_new_customers_acquired",
        "cm_customers_period_end_by_tenure",
        "cm_revenue_by_cohort",
        "cm_transactions_by_cohort",
    ]

    for metric_id in expected_metrics:
        assert metric_id in extractor.CANONICAL_DEFINITIONS
        canonical = extractor.CANONICAL_DEFINITIONS[metric_id]
        assert "keywords" in canonical
        assert "definition" in canonical
        assert len(canonical["keywords"]) > 0


def test_alignment_keyword_overlap_ratio(extractor):
    """Test keyword overlap ratio calculation."""
    # All keywords present
    all_keywords = "first qualifying economic activity purchase transaction period unique customers"
    alignment = extractor.assess_alignment("cm_new_customers_acquired", all_keywords)
    assert alignment == "aligned"

    # About half keywords
    half_keywords = "first purchase transaction customers"
    alignment = extractor.assess_alignment("cm_new_customers_acquired", half_keywords)
    assert alignment in ["partial", "aligned"]

    # Very few keywords (but at least one canonical keyword)
    few_keywords = "New customers in the period"
    alignment = extractor.assess_alignment("cm_new_customers_acquired", few_keywords)
    assert alignment in ["not_aligned", "partial"]

    # No canonical keywords at all
    no_keywords = "People who bought stuff"
    alignment = extractor.assess_alignment("cm_new_customers_acquired", no_keywords)
    assert alignment == "unknown"


def test_uses_first_definition_segment(extractor):
    """Test that when multiple definition segments exist, uses the first one."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="First definition of DAU.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=1,
            raw_text="Second definition of DAU.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        ),
    ]

    definitions = extractor.extract_definitions(segments, company_id=1)

    definition = definitions[0]
    # Should use first segment
    assert definition.definition_segment_id == 0
    assert "First definition" in definition.definition_raw_text


def build_segment(**overrides) -> SourceSegment:
    """Helper to construct a SourceSegment with sensible defaults."""
    defaults = {
        "filing_id": 1,
        "segment_type": "paragraph",
        "raw_text": "Placeholder",
        "sequence_index": 0,
        "candidate_metric_ids": [],
        "contains_definition_flag": True,
    }
    defaults.update(overrides)
    return SourceSegment(**defaults)


class TestDefinitionQuoteVerification:
    """Tests for quote verification in definition extraction."""

    def test_verified_quote_is_extracted(self):
        """Definition with verified quote should be extracted."""
        # Create mock LLM client
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = """[{
            "metric_name": "daily_active_users",
            "definition_text": "Users who logged in within the last 24 hours",
            "includes_calculation": false,
            "quote": "We define daily active users as users who logged in"
        }]"""
        mock_llm.complete.return_value = mock_response

        extractor = DefinitionExtractor(llm_client=mock_llm)

        # Create segment with text that CONTAINS the quote
        segment = build_segment(
            raw_text="We define daily active users as users who logged in within the last 24 hours.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        )

        definitions = extractor.extract_definitions([segment], company_id=1)

        # Quote is verified, so definition should be extracted with LLM result
        assert len(definitions) == 1
        assert (
            definitions[0].definition_raw_text
            == "We define daily active users as users who logged in"
        )

    def test_unverified_quote_falls_back_to_rule_based(self):
        """Unverified quote should trigger fallback to rule-based extraction."""
        # Create mock LLM client that returns a hallucinated quote
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = """[{
            "metric_name": "daily_active_users",
            "definition_text": "Users who logged in within the last 24 hours",
            "includes_calculation": false,
            "quote": "This quote does not exist in the source at all"
        }]"""
        mock_llm.complete.return_value = mock_response

        extractor = DefinitionExtractor(llm_client=mock_llm)

        # Create segment with text that does NOT contain the quote
        segment = build_segment(
            raw_text="We define daily active users as users who logged in within the last 24 hours.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        )

        definitions = extractor.extract_definitions([segment], company_id=1)

        # Quote verification fails, should fall back to rule-based
        # Rule-based will extract the definition from the segment text
        # The key assertion: the LLM's hallucinated quote should NOT be in the result
        for defn in definitions:
            assert defn.definition_raw_text != "This quote does not exist in the source at all"

    def test_empty_quote_uses_llm_result(self):
        """When LLM returns empty quote, should still use the definition."""
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = """[{
            "metric_name": "daily_active_users",
            "definition_text": "Users who logged in within the last 24 hours",
            "includes_calculation": false,
            "quote": ""
        }]"""
        mock_llm.complete.return_value = mock_response

        extractor = DefinitionExtractor(llm_client=mock_llm)

        segment = build_segment(
            raw_text="We define daily active users as users who logged in within the last 24 hours.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_definition_flag=True,
        )

        definitions = extractor.extract_definitions([segment], company_id=1)

        # Empty quote should not trigger verification, so LLM result is used
        assert len(definitions) == 1
        assert definitions[0].definition_raw_text == ""  # Empty quote stored as-is
