"""
Tests for cohort chart image detection in SegmentEnricher.

Tests the _detect_cohort_chart_images() method which identifies
images likely to contain cohort-related charts based on proximity
to cohort keywords.
"""

import pytest

from src.extraction.models import SourceSegment
from src.extraction.segment_enricher import SegmentEnricher


def make_segment(
    raw_text: str = "",
    raw_html: str | None = None,
    sequence_index: int = 0,
    filing_id: int = 1,
) -> SourceSegment:
    """Helper to create a SourceSegment for testing."""
    return SourceSegment(
        filing_id=filing_id,
        segment_type="paragraph",
        sequence_index=sequence_index,
        raw_text=raw_text,
        raw_html=raw_html,
    )


class TestCohortChartImageDetection:
    """Tests for _detect_cohort_chart_images method."""

    @pytest.fixture
    def enricher(self) -> SegmentEnricher:
        return SegmentEnricher()

    def test_detects_cohort_keyword_near_image(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should detect image when 'cohort' appears nearby."""
        html = '''
        <p>The chart below illustrates the annual recurring revenue, or ARR, of each cohort over the periods presented.</p>
        <img src="mdaa2.jpg" alt="ARR by cohort" width="569" height="357"/>
        '''
        text = "The chart below illustrates the annual recurring revenue, or ARR, of each cohort over the periods presented."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 1
        assert result[0]["image_src"] == "mdaa2.jpg"
        assert "cohort" in [kw.lower() for kw in result[0]["detected_keywords"]]
        assert result[0]["confidence"] >= 0.6

    def test_detects_retention_cohort_pattern(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should detect retention by cohort pattern."""
        html = '''
        <p>The following graph shows our net dollar retention by cohort.</p>
        <img src="retention_chart.png" width="500" height="300"/>
        '''
        text = "The following graph shows our net dollar retention by cohort."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 1
        assert result[0]["confidence"] >= 0.7  # Higher confidence due to chart keyword

    def test_detects_ltv_cac_pattern(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should detect LTV/CAC chart pattern."""
        html = '''
        <p>The chart below shows our LTV/CAC ratios over time.</p>
        <img src="ltv_cac.jpg" width="600" height="400"/>
        '''
        text = "The chart below shows our LTV/CAC ratios over time."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 1
        assert "LTV/CAC" in result[0]["detected_keywords"]

    def test_ignores_decorative_images(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should ignore small decorative images."""
        html = '''
        <p>The chart below illustrates cohort revenue.</p>
        <img src="icon.png" width="20" height="20"/>
        '''
        text = "The chart below illustrates cohort revenue."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 0

    def test_ignores_image_without_cohort_keyword(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should not detect images when no cohort keywords are present."""
        # Text without any cohort keywords
        text = "Our company has grown significantly with strong revenue."
        html = f'''
        <p>{text}</p>
        <img src="chart.jpg" width="500" height="300"/>
        '''
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        # Image should not be detected because no cohort keywords
        assert len(result) == 0

    def test_no_cohort_keywords_returns_empty(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should return empty when no cohort keywords present."""
        html = '''
        <p>Our revenue grew significantly last year.</p>
        <img src="revenue.jpg" width="500" height="300"/>
        '''
        text = "Our revenue grew significantly last year."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 0

    def test_no_images_returns_empty(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should return empty when no images present."""
        html = '<p>Our cohort analysis shows strong retention.</p>'
        text = "Our cohort analysis shows strong retention."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 0

    def test_empty_html_returns_empty(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should return empty for missing HTML."""
        segment = make_segment(raw_text="cohort analysis", raw_html=None)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 0

    def test_multiple_images_detected(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should detect multiple cohort chart images."""
        html = '''
        <p>The following charts illustrate cohort performance.</p>
        <img src="chart1.jpg" width="500" height="300"/>
        <p>ARR by cohort year is shown below.</p>
        <img src="chart2.jpg" width="500" height="300"/>
        '''
        text = "The following charts illustrate cohort performance. ARR by cohort year is shown below."
        segment = make_segment(raw_text=text, raw_html=html)

        result = enricher._detect_cohort_chart_images(segment)

        assert len(result) == 2

    def test_chart_keyword_increases_confidence(
        self, enricher: SegmentEnricher
    ) -> None:
        """Presence of 'chart' should increase confidence."""
        # With chart keyword
        html_with = '''
        <p>The chart below illustrates cohort revenue.</p>
        <img src="chart.jpg" width="500" height="300"/>
        '''
        text_with = "The chart below illustrates cohort revenue."
        segment_with = make_segment(raw_text=text_with, raw_html=html_with)

        # Without chart keyword
        html_without = '''
        <p>cohort revenue is shown.</p>
        <img src="img.jpg" width="500" height="300"/>
        '''
        text_without = "cohort revenue is shown."
        segment_without = make_segment(raw_text=text_without, raw_html=html_without)

        result_with = enricher._detect_cohort_chart_images(segment_with)
        result_without = enricher._detect_cohort_chart_images(segment_without)

        assert len(result_with) == 1
        assert len(result_without) == 1
        assert result_with[0]["confidence"] > result_without[0]["confidence"]


class TestCohortChartEnrichmentIntegration:
    """Tests that cohort chart detection integrates with enrich_batch."""

    @pytest.fixture
    def enricher(self) -> SegmentEnricher:
        return SegmentEnricher()

    def test_enrichment_populates_extra_metadata(
        self, enricher: SegmentEnricher
    ) -> None:
        """Enrichment should populate cohort_chart_candidates in extra_metadata."""
        html = '''
        <p>The chart below illustrates the ARR of each cohort.</p>
        <img src="cohort_arr.jpg" width="500" height="300"/>
        '''
        text = "The chart below illustrates the ARR of each cohort."
        segment = make_segment(raw_text=text, raw_html=html)

        enricher.enrich_batch([segment])

        assert segment.extra_metadata is not None
        assert "cohort_chart_candidates" in segment.extra_metadata
        candidates = segment.extra_metadata["cohort_chart_candidates"]
        assert len(candidates) == 1
        assert candidates[0]["image_src"] == "cohort_arr.jpg"

    def test_no_cohort_charts_no_key(
        self, enricher: SegmentEnricher
    ) -> None:
        """When no cohort charts detected, key should not be present."""
        html = '<p>Our revenue grew strongly.</p>'
        text = "Our revenue grew strongly."
        segment = make_segment(raw_text=text, raw_html=html)

        enricher.enrich_batch([segment])

        assert segment.extra_metadata is not None
        assert "cohort_chart_candidates" not in segment.extra_metadata


class TestConfidenceScoring:
    """Tests for _calculate_cohort_chart_confidence."""

    @pytest.fixture
    def enricher(self) -> SegmentEnricher:
        return SegmentEnricher()

    def test_base_confidence(self, enricher: SegmentEnricher) -> None:
        """Base confidence should be 0.6 for any match."""
        result = enricher._calculate_cohort_chart_confidence(
            text="cohort data",
            matched_keywords=["cohort"],
            distance=100,
        )
        assert result == pytest.approx(0.6, abs=0.01)

    def test_chart_keyword_bonus(self, enricher: SegmentEnricher) -> None:
        """Chart keywords should add +0.15 bonus."""
        result = enricher._calculate_cohort_chart_confidence(
            text="The chart below illustrates cohort data",
            matched_keywords=["cohort"],
            distance=100,
        )
        assert result >= 0.75  # 0.6 + 0.15

    def test_retention_bonus(self, enricher: SegmentEnricher) -> None:
        """Retention/revenue keywords should add +0.10 bonus."""
        result = enricher._calculate_cohort_chart_confidence(
            text="cohort retention rates",
            matched_keywords=["cohort"],
            distance=100,
        )
        assert result >= 0.7  # 0.6 + 0.10

    def test_multiple_keywords_bonus(self, enricher: SegmentEnricher) -> None:
        """Multiple cohort keywords should add +0.10 bonus."""
        result = enricher._calculate_cohort_chart_confidence(
            text="cohort by vintage",
            matched_keywords=["cohort", "by vintage"],
            distance=100,
        )
        assert result >= 0.7  # 0.6 + 0.10

    def test_distance_penalty(self, enricher: SegmentEnricher) -> None:
        """Large distance should reduce confidence."""
        close_result = enricher._calculate_cohort_chart_confidence(
            text="cohort data",
            matched_keywords=["cohort"],
            distance=100,
        )
        far_result = enricher._calculate_cohort_chart_confidence(
            text="cohort data",
            matched_keywords=["cohort"],
            distance=1200,
        )
        assert close_result > far_result

    def test_confidence_capped_at_one(self, enricher: SegmentEnricher) -> None:
        """Confidence should never exceed 1.0."""
        result = enricher._calculate_cohort_chart_confidence(
            text="The chart below illustrates cohort retention by vintage ARR",
            matched_keywords=["cohort", "by vintage", "ARR"],
            distance=50,
        )
        assert result <= 1.0


class TestElementPositionEstimation:
    """Tests for _estimate_element_position helper."""

    @pytest.fixture
    def enricher(self) -> SegmentEnricher:
        return SegmentEnricher()

    def test_estimates_position(self, enricher: SegmentEnricher) -> None:
        """Should estimate element position based on preceding text."""
        html = '<p>Hello world</p><img src="test.jpg"/>'
        element = '<img src="test.jpg"/>'

        pos = enricher._estimate_element_position(html, element)

        # Position should be around the length of "Hello world"
        assert pos >= 10

    def test_element_not_found_returns_zero(
        self, enricher: SegmentEnricher
    ) -> None:
        """Should return 0 if element not found."""
        html = '<p>Hello world</p>'
        element = '<img src="missing.jpg"/>'

        pos = enricher._estimate_element_position(html, element)

        assert pos == 0

    def test_empty_html_returns_zero(self, enricher: SegmentEnricher) -> None:
        """Should return 0 for empty HTML."""
        pos = enricher._estimate_element_position("", '<img src="test.jpg"/>')
        assert pos == 0
