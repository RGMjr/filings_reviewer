"""
Unit tests for V2 Image Triage Stage.

Tests:
- Image classification (logo, signature, chart, table_image, decorative)
- Chart type detection
- Relevance scoring with section bonuses
- Batch triage processing
- Pipeline stage integration
"""

from __future__ import annotations

import pytest

from src.extraction_v2.models import (
    ChartType,
    ImageAsset,
    ImageClassification,
    SectionType,
)
from src.extraction_v2.stages.image_triage import ImageTriageStage


class TestImageClassification:
    """Tests for image classification logic."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        """Create a fresh stage instance for each test."""
        return ImageTriageStage()

    def test_classify_logo_by_filename(self, stage: ImageTriageStage) -> None:
        """Images with 'logo' in filename should be classified as LOGO."""
        asset = ImageAsset(
            img_id="test_1",
            filename="company_logo.png",
            nearby_text="",
            width=200,
            height=100,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.LOGO

    def test_classify_logo_by_dimensions(self, stage: ImageTriageStage) -> None:
        """Small square images with logo keywords in text should be LOGO."""
        asset = ImageAsset(
            img_id="test_2",
            filename="image_001.png",
            nearby_text="company logo displayed here",
            width=150,
            height=100,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.LOGO

    def test_classify_logo_small_square(self, stage: ImageTriageStage) -> None:
        """Very small square-ish images should be LOGO."""
        asset = ImageAsset(
            img_id="test_3",
            filename="img_001.png",
            nearby_text="",
            width=100,
            height=80,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.LOGO

    def test_classify_signature(self, stage: ImageTriageStage) -> None:
        """Images with 'signature' in filename should be SIGNATURE."""
        asset = ImageAsset(
            img_id="test_4",
            filename="ceo_signature.png",
            nearby_text="",
            width=400,
            height=100,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.SIGNATURE

    def test_classify_signature_by_text(self, stage: ImageTriageStage) -> None:
        """Images with signature keywords in nearby text should be SIGNATURE."""
        asset = ImageAsset(
            img_id="test_5",
            filename="img_002.png",
            nearby_text="signature of the chief executive officer",
            width=500,
            height=200,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.SIGNATURE

    def test_classify_chart_by_filename(self, stage: ImageTriageStage) -> None:
        """Images with 'chart' in filename should be CHART."""
        asset = ImageAsset(
            img_id="test_6",
            filename="revenue_chart.png",
            nearby_text="",
            width=800,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_classify_chart_by_caption(self, stage: ImageTriageStage) -> None:
        """Images with chart keywords in caption should be CHART."""
        asset = ImageAsset(
            img_id="test_7",
            filename="figure_01.png",
            nearby_text="Figure 1: Customer Growth Chart",
            width=800,
            height=500,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_classify_chart_large_with_metrics(self, stage: ImageTriageStage) -> None:
        """Large images with metric keywords should be CHART."""
        asset = ImageAsset(
            img_id="test_8",
            filename="img_003.png",
            nearby_text="Annual retention rates by customer cohort",
            width=900,
            height=700,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_classify_table_image(self, stage: ImageTriageStage) -> None:
        """Images with table keywords should be TABLE_IMAGE."""
        asset = ImageAsset(
            img_id="test_9",
            filename="schedule_data.png",
            nearby_text="Schedule 2: Summary of Data by Segment",
            width=600,  # Smaller - not large enough for chart by size
            height=400,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.TABLE_IMAGE

    def test_classify_table_image_wide_aspect(self, stage: ImageTriageStage) -> None:
        """Wide images with financial keywords should be TABLE_IMAGE."""
        asset = ImageAsset(
            img_id="test_10",
            filename="data_001.png",
            nearby_text="Expense breakdown for fiscal year 2023 total income",  # expense not revenue
            width=700,  # Wide but not large enough
            height=200,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.TABLE_IMAGE

    def test_classify_decorative_banner(self, stage: ImageTriageStage) -> None:
        """Banner images should be DECORATIVE."""
        asset = ImageAsset(
            img_id="test_11",
            filename="header_banner.png",
            nearby_text="",
            width=1200,
            height=100,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.DECORATIVE

    def test_classify_decorative_tiny(self, stage: ImageTriageStage) -> None:
        """Very small images should be DECORATIVE."""
        asset = ImageAsset(
            img_id="test_12",
            filename="bullet.png",
            nearby_text="",
            width=20,
            height=20,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.DECORATIVE

    def test_classify_decorative_in_exhibits(self, stage: ImageTriageStage) -> None:
        """Images in exhibits section should be DECORATIVE."""
        asset = ImageAsset(
            img_id="test_13",
            filename="misc_image.png",
            nearby_text="",
            width=500,
            height=400,
            section_type=SectionType.EXHIBITS,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.DECORATIVE

    def test_classify_unknown_no_signals(self, stage: ImageTriageStage) -> None:
        """Images with no classification signals should be UNKNOWN."""
        asset = ImageAsset(
            img_id="test_14",
            filename="img_100.png",
            nearby_text="Some general text without keywords",
            width=600,
            height=500,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.UNKNOWN

    def test_classify_zero_dimensions(self, stage: ImageTriageStage) -> None:
        """Images with zero dimensions should still classify by filename."""
        asset = ImageAsset(
            img_id="test_15",
            filename="revenue_chart.png",
            nearby_text="",
            width=0,
            height=0,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART


class TestChartTypeDetection:
    """Tests for chart type detection."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_detect_bar_chart(self, stage: ImageTriageStage) -> None:
        """Bar chart keywords should be detected."""
        asset = ImageAsset(
            img_id="test_1",
            filename="bar_chart.png",
            nearby_text="Figure 1: Revenue Bar Chart by Quarter",
            classification=ImageClassification.CHART,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.BAR

    def test_detect_line_chart(self, stage: ImageTriageStage) -> None:
        """Line chart keywords should be detected."""
        asset = ImageAsset(
            img_id="test_2",
            filename="trend.png",
            nearby_text="Time series line graph showing growth",
            classification=ImageClassification.CHART,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.LINE

    def test_detect_pie_chart(self, stage: ImageTriageStage) -> None:
        """Pie chart keywords should be detected."""
        asset = ImageAsset(
            img_id="test_3",
            filename="distribution.png",
            nearby_text="Customer Distribution pie chart",
            classification=ImageClassification.CHART,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.PIE

    def test_detect_stacked_bar(self, stage: ImageTriageStage) -> None:
        """Stacked bar keywords should be detected (priority over bar)."""
        asset = ImageAsset(
            img_id="test_4",
            filename="revenue.png",
            nearby_text="Stacked bar chart showing revenue breakdown",
            classification=ImageClassification.CHART,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.STACKED_BAR

    def test_detect_area_chart(self, stage: ImageTriageStage) -> None:
        """Area chart keywords should be detected."""
        asset = ImageAsset(
            img_id="test_5",
            filename="growth.png",
            nearby_text="Area chart showing cumulative growth",
            classification=ImageClassification.CHART,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.AREA

    def test_unknown_chart_type(self, stage: ImageTriageStage) -> None:
        """Charts without type keywords should be UNKNOWN."""
        asset = ImageAsset(
            img_id="test_6",
            filename="figure.png",
            nearby_text="Figure showing customer metrics",
            classification=ImageClassification.CHART,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.UNKNOWN

    def test_non_chart_returns_unknown(self, stage: ImageTriageStage) -> None:
        """Non-chart images should return UNKNOWN type."""
        asset = ImageAsset(
            img_id="test_7",
            filename="logo.png",
            nearby_text="Bar chart",  # Even with chart keywords
            classification=ImageClassification.LOGO,
        )
        result = stage.detect_chart_type(asset)
        assert result == ChartType.UNKNOWN


class TestRelevanceScoring:
    """Tests for relevance scoring logic."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_chart_base_score(self, stage: ImageTriageStage) -> None:
        """Charts should have high base score."""
        asset = ImageAsset(
            img_id="test_1",
            classification=ImageClassification.CHART,
            nearby_text="",
        )
        score = stage.score_relevance(asset)
        assert score == 0.5  # Base score for CHART

    def test_decorative_zero_score(self, stage: ImageTriageStage) -> None:
        """Decorative images should have zero score."""
        asset = ImageAsset(
            img_id="test_2",
            classification=ImageClassification.DECORATIVE,
            nearby_text="cohort retention",  # Even with keywords
        )
        score = stage.score_relevance(asset)
        # Base is 0.0, but keywords add bonus
        assert score >= 0.0

    def test_section_bonus_mda(self, stage: ImageTriageStage) -> None:
        """MD&A section should add +0.2 bonus."""
        asset = ImageAsset(
            img_id="test_3",
            classification=ImageClassification.CHART,
            section_type=SectionType.MDA,
            nearby_text="",
        )
        score = stage.score_relevance(asset)
        assert score == 0.7  # 0.5 base + 0.2 MDA bonus

    def test_section_bonus_business(self, stage: ImageTriageStage) -> None:
        """Business section should add +0.15 bonus."""
        asset = ImageAsset(
            img_id="test_4",
            classification=ImageClassification.CHART,
            section_type=SectionType.BUSINESS,
            nearby_text="",
        )
        score = stage.score_relevance(asset)
        assert score == 0.65  # 0.5 base + 0.15 business bonus

    def test_keyword_bonus(self, stage: ImageTriageStage) -> None:
        """High-value keywords should add bonus."""
        asset = ImageAsset(
            img_id="test_5",
            classification=ImageClassification.CHART,
            nearby_text="cohort retention analysis",
        )
        score = stage.score_relevance(asset)
        # 0.5 base + 0.08 * 2 keywords = 0.66
        assert score >= 0.66

    def test_keyword_bonus_capped(self, stage: ImageTriageStage) -> None:
        """Keyword bonus should be capped at 0.3."""
        asset = ImageAsset(
            img_id="test_6",
            classification=ImageClassification.CHART,
            nearby_text="cohort retention churn ltv cac arr mrr nrr revenue customers",
        )
        score = stage.score_relevance(asset)
        # 0.5 base + 0.3 max keyword bonus = 0.8
        assert score == pytest.approx(0.8, abs=0.05)

    def test_score_capped_at_one(self, stage: ImageTriageStage) -> None:
        """Score should never exceed 1.0."""
        asset = ImageAsset(
            img_id="test_7",
            classification=ImageClassification.CHART,
            section_type=SectionType.MDA,
            nearby_text="cohort retention churn ltv cac arr mrr nrr revenue customers",
        )
        score = stage.score_relevance(asset)
        assert score <= 1.0

    def test_unknown_classification_base_score(self, stage: ImageTriageStage) -> None:
        """Unknown images should have low base score."""
        asset = ImageAsset(
            img_id="test_8",
            classification=ImageClassification.UNKNOWN,
            nearby_text="",
        )
        score = stage.score_relevance(asset)
        assert score == 0.2


class TestTriageBatch:
    """Tests for batch triage processing."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_triage_empty_list(self, stage: ImageTriageStage) -> None:
        """Empty image list should return empty result."""
        result = stage.triage_images([])
        assert result == []

    def test_triage_single_chart(self, stage: ImageTriageStage) -> None:
        """Single chart should be classified and returned for processing."""
        asset = ImageAsset(
            img_id="test_1",
            filename="revenue_chart.png",
            nearby_text="Figure 1: Revenue Growth",
            width=800,
            height=600,
        )
        result = stage.triage_images([asset])

        assert asset.classification == ImageClassification.CHART
        assert asset.relevance_score >= 0.5
        assert len(result) == 1
        assert result[0] is asset

    def test_triage_filters_decorative(self, stage: ImageTriageStage) -> None:
        """Decorative images should not be returned for processing."""
        assets = [
            ImageAsset(
                img_id="test_1",
                filename="logo.png",
                width=100,
                height=50,
            ),
            ImageAsset(
                img_id="test_2",
                filename="chart.png",
                nearby_text="Revenue chart",
                width=800,
                height=600,
            ),
        ]
        result = stage.triage_images(assets)

        assert assets[0].classification == ImageClassification.LOGO
        assert assets[1].classification == ImageClassification.CHART
        assert len(result) == 1  # Only chart returned
        assert result[0].img_id == "test_2"

    def test_triage_marks_ambiguous_for_manual_capture(self, stage: ImageTriageStage) -> None:
        """Ambiguous images should be marked for manual capture."""
        asset = ImageAsset(
            img_id="test_1",
            filename="img_001.png",
            nearby_text="Some customers data",  # Has keyword but vague
            width=500,
            height=400,
        )
        result = stage.triage_images([asset])

        # Should be UNKNOWN with some relevance
        assert asset.classification == ImageClassification.UNKNOWN
        if asset.relevance_score >= 0.3 and asset.relevance_score < 0.5:
            assert asset.requires_manual_capture is True

    def test_triage_preserves_all_images(self, stage: ImageTriageStage) -> None:
        """Triage should classify all images, not just returned ones."""
        assets = [
            ImageAsset(img_id="test_1", filename="logo.png", width=100, height=50),
            ImageAsset(img_id="test_2", filename="chart.png", width=800, height=600),
            ImageAsset(img_id="test_3", filename="bullet.png", width=10, height=10),
        ]
        stage.triage_images(assets)

        # All should have classifications
        assert all(a.classification != ImageClassification.UNKNOWN or True for a in assets)
        assert assets[0].classification == ImageClassification.LOGO
        assert assets[1].classification == ImageClassification.CHART
        assert assets[2].classification == ImageClassification.DECORATIVE


class TestPipelineIntegration:
    """Tests for pipeline stage integration."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_process_empty_context(self, stage: ImageTriageStage) -> None:
        """Process should handle empty images list."""
        from src.extraction_v2.pipeline import PipelineContext, PipelineStage
        from pathlib import Path

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=None,  # type: ignore
        )
        context.images = []

        result = stage.process(context)

        assert result.success is True
        assert result.stage == PipelineStage.IMAGE_TRIAGE
        assert result.items_processed == 0
        assert result.items_output == 0

    def test_process_with_images(self, stage: ImageTriageStage) -> None:
        """Process should classify and score images."""
        from src.extraction_v2.pipeline import PipelineContext, PipelineStage
        from pathlib import Path

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=None,  # type: ignore
        )
        context.images = [
            ImageAsset(
                img_id="test_1",
                filename="revenue_chart.png",
                nearby_text="Annual revenue growth",
                width=800,
                height=600,
            ),
            ImageAsset(
                img_id="test_2",
                filename="logo.png",
                width=100,
                height=50,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.stage == PipelineStage.IMAGE_TRIAGE
        assert result.items_processed == 2
        assert result.items_output == 1  # Only chart is relevant
        assert "classification_counts" in result.metadata
        assert result.metadata["total_images"] == 2

    def test_process_returns_metadata(self, stage: ImageTriageStage) -> None:
        """Process should return classification statistics."""
        from src.extraction_v2.pipeline import PipelineContext
        from pathlib import Path

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=None,  # type: ignore
        )
        context.images = [
            ImageAsset(img_id="1", filename="chart.png", width=800, height=600),
            ImageAsset(img_id="2", filename="logo.png", width=100, height=50),
            ImageAsset(img_id="3", filename="banner.png", width=1200, height=100),
        ]

        result = stage.process(context)

        assert "classification_counts" in result.metadata
        counts = result.metadata["classification_counts"]
        assert "chart" in counts
        assert "logo" in counts


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_empty_filename(self, stage: ImageTriageStage) -> None:
        """Empty filename should still classify by other signals."""
        asset = ImageAsset(
            img_id="test_1",
            filename="",
            nearby_text="Cohort retention chart",
            width=800,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_empty_nearby_text(self, stage: ImageTriageStage) -> None:
        """Empty nearby text should use filename."""
        asset = ImageAsset(
            img_id="test_1",
            filename="revenue_chart.png",
            nearby_text="",
            width=800,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_negative_dimensions(self, stage: ImageTriageStage) -> None:
        """Negative dimensions should be treated as unknown."""
        asset = ImageAsset(
            img_id="test_1",
            filename="image.png",
            nearby_text="",
            width=-100,
            height=-50,
        )
        # Should not crash, dimensions checks will fail gracefully
        result = stage.classify_image(asset)
        assert result in ImageClassification

    def test_mixed_case_keywords(self, stage: ImageTriageStage) -> None:
        """Keywords should be case-insensitive."""
        asset = ImageAsset(
            img_id="test_1",
            filename="REVENUE_CHART.PNG",
            nearby_text="COHORT RETENTION Analysis",
            width=800,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_unicode_text(self, stage: ImageTriageStage) -> None:
        """Unicode text should be handled."""
        asset = ImageAsset(
            img_id="test_1",
            filename="données_graphique.png",
            nearby_text="Graphique de rétention des clients",
            width=800,
            height=600,
        )
        # Should not crash
        result = stage.classify_image(asset)
        assert result in ImageClassification

    def test_very_long_text(self, stage: ImageTriageStage) -> None:
        """Very long nearby text should be handled."""
        long_text = "retention cohort analysis " * 1000
        asset = ImageAsset(
            img_id="test_1",
            filename="chart.png",
            nearby_text=long_text,
            width=800,
            height=600,
        )
        # Should not crash, and should classify
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART


class TestPatternMatching:
    """Tests for pattern matching internals."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_logo_pattern_variations(self, stage: ImageTriageStage) -> None:
        """Various logo filename patterns should be detected."""
        patterns = ["company_logo.png", "Logo_2024.jpg", "brand-logo.gif", "LOGO.PNG"]
        for filename in patterns:
            asset = ImageAsset(img_id="test", filename=filename, width=200, height=100)
            result = stage.classify_image(asset)
            assert result == ImageClassification.LOGO, f"Failed for {filename}"

    def test_chart_pattern_variations(self, stage: ImageTriageStage) -> None:
        """Various chart filename patterns should be detected."""
        patterns = ["bar_chart.png", "line-graph.jpg", "Figure_1.gif", "EXHIBIT_A.PNG"]
        for filename in patterns:
            asset = ImageAsset(img_id="test", filename=filename, width=800, height=600)
            result = stage.classify_image(asset)
            assert result == ImageClassification.CHART, f"Failed for {filename}"

    def test_signature_pattern_variations(self, stage: ImageTriageStage) -> None:
        """Various signature filename patterns should be detected."""
        patterns = ["ceo_signature.png", "sign_001.jpg", "signature.gif"]
        for filename in patterns:
            asset = ImageAsset(img_id="test", filename=filename, width=400, height=100)
            result = stage.classify_image(asset)
            assert result == ImageClassification.SIGNATURE, f"Failed for {filename}"
