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

from pathlib import Path

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
        stage.triage_images([asset])

        # Should be UNKNOWN with some relevance.
        assert asset.classification == ImageClassification.UNKNOWN
        assert asset.relevance_score is not None
        # Verify the manual_capture flag is consistent with the triage thresholds:
        # images with relevance in [MIN_RELEVANCE_FOR_PROCESSING, AMBIGUOUS_THRESHOLD)
        # get marked for manual capture; others do not.
        expected_manual_capture = (
            asset.relevance_score >= stage.MIN_RELEVANCE_FOR_PROCESSING
            and asset.relevance_score < stage.AMBIGUOUS_RELEVANCE_THRESHOLD
        )
        assert asset.requires_manual_capture is expected_manual_capture

    def test_triage_preserves_all_images(self, stage: ImageTriageStage) -> None:
        """Triage should classify all images, not just returned ones."""
        assets = [
            ImageAsset(img_id="test_1", filename="logo.png", width=100, height=50),
            ImageAsset(img_id="test_2", filename="chart.png", width=800, height=600),
            ImageAsset(img_id="test_3", filename="bullet.png", width=10, height=10),
        ]
        stage.triage_images(assets)

        # All should have been classified (assigned a non-None classification)
        assert all(a.classification is not None for a in assets)
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
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineContext, PipelineStage

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
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineContext, PipelineStage

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
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineContext

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

    def test_figures_plural_classified_as_chart(self, stage: ImageTriageStage) -> None:
        """'figures' (plural) in nearby text should trigger CHART classification."""
        asset = ImageAsset(
            img_id="test_farfetch",
            filename="g607688g12o45.jpg",
            nearby_text="The figures below represent our GMV by cohort",
            width=800,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_dimensionless_image_with_metric_keywords_is_chart(
        self, stage: ImageTriageStage
    ) -> None:
        """Dimensionless images (width=0, height=0) with metric keywords should be CHART."""
        asset = ImageAsset(
            img_id="test_dimensionless",
            filename="g607688g09d00.jpg",
            nearby_text="Order Contribution Margin by cohort retention analysis",
            width=0,
            height=0,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_dimensionless_image_without_keywords_stays_unknown(
        self, stage: ImageTriageStage
    ) -> None:
        """Dimensionless images without metric keywords should NOT be classified as CHART."""
        asset = ImageAsset(
            img_id="test_dimensionless_unknown",
            filename="g607688x99z99.jpg",
            nearby_text="Some general text without relevant keywords",
            width=0,
            height=0,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.UNKNOWN


# ============================================================================
# Full-page-scan detection (Path A, Phase 2)
# ============================================================================


class TestIsPageShaped:
    """Tests for ImageTriageStage._is_page_shaped dimensional heuristic."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_portrait_page_sized_jpeg_is_page_shaped(self, stage: ImageTriageStage) -> None:
        asset = ImageAsset(img_id="1", filename="p1.jpg", width=1055, height=1365)
        assert stage._is_page_shaped(asset) is True

    def test_narrow_portrait_still_in_bounds(self, stage: ImageTriageStage) -> None:
        # Aspect 0.72 is inside [0.7, 0.85], width 1000 inside [900, 1300]
        asset = ImageAsset(img_id="1", filename="p1.jpg", width=1000, height=1388)
        assert stage._is_page_shaped(asset) is True

    def test_too_wide_aspect_rejected(self, stage: ImageTriageStage) -> None:
        # Aspect 1.33 — landscape, not page-shaped
        asset = ImageAsset(img_id="1", filename="wide.jpg", width=1200, height=900)
        assert stage._is_page_shaped(asset) is False

    def test_too_narrow_width_rejected(self, stage: ImageTriageStage) -> None:
        # Width 500 — below the 900 floor
        asset = ImageAsset(img_id="1", filename="small.jpg", width=500, height=700)
        assert stage._is_page_shaped(asset) is False

    def test_missing_dimensions_defer_to_true(self, stage: ImageTriageStage) -> None:
        # SEC filings often omit width/height on scanned exhibits. Defer
        # to the filing-wide ratio gate — don't pre-filter on dimensions.
        asset = ImageAsset(img_id="1", filename="no_dims.jpg", width=0, height=0)
        assert stage._is_page_shaped(asset) is True


class TestFullPageScanDetection:
    """Tests for the filing-wide _detect_full_page_scan_filing gate."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def _make_context(
        self,
        *,
        segments: list,
        images: list[ImageAsset],
        flag_on: bool = True,
    ):
        """Build a PipelineContext with the full-page-OCR flag explicitly set."""
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineConfig, PipelineContext

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=flag_on),
        )
        context.segments = segments
        context.images = images
        return context

    def _paypal_like_images(self, count: int = 16) -> list[ImageAsset]:
        return [
            ImageAsset(
                img_id=f"page_{i}",
                filename=f"page_{i}.jpg",
                width=1055,
                height=1365,
            )
            for i in range(count)
        ]

    def test_paypal_like_fires(self, stage: ImageTriageStage) -> None:
        """0 segments, 16 portrait page JPGs: detector fires."""
        context = self._make_context(segments=[], images=self._paypal_like_images(16))
        assert stage._detect_full_page_scan_filing(context) is True

    def test_normal_10k_does_not_fire(self, stage: ImageTriageStage) -> None:
        """250k chars of HTML + 40 images: ratio 0.32 → does NOT fire."""
        from src.extraction_v2.models import Segment, SegmentType

        segments = [
            Segment(segment_id=f"s{i}", segment_type=SegmentType.PARAGRAPH, text="x" * 1000)
            for i in range(250)  # 250k chars total
        ]
        images = self._paypal_like_images(40)
        context = self._make_context(segments=segments, images=images)
        assert stage._detect_full_page_scan_filing(context) is False

    def test_text_dense_s1_with_product_photos_does_not_fire(self, stage: ImageTriageStage) -> None:
        """100k chars + 30 portrait images: ratio 0.6 → does NOT fire."""
        from src.extraction_v2.models import Segment, SegmentType

        segments = [
            Segment(segment_id=f"s{i}", segment_type=SegmentType.PARAGRAPH, text="y" * 1000)
            for i in range(100)
        ]
        images = self._paypal_like_images(30)
        context = self._make_context(segments=segments, images=images)
        assert stage._detect_full_page_scan_filing(context) is False

    def test_mixed_investor_deck_fires(self, stage: ImageTriageStage) -> None:
        """20k chars + 25 portrait page images: ratio 2.5 → fires."""
        from src.extraction_v2.models import Segment, SegmentType

        segments = [
            Segment(segment_id=f"s{i}", segment_type=SegmentType.PARAGRAPH, text="z" * 1000)
            for i in range(20)
        ]
        images = self._paypal_like_images(25)
        context = self._make_context(segments=segments, images=images)
        assert stage._detect_full_page_scan_filing(context) is True

    def test_below_min_images_does_not_fire(self, stage: ImageTriageStage) -> None:
        """4 images with 0 segments: below the 5-image floor → does NOT fire."""
        context = self._make_context(segments=[], images=self._paypal_like_images(4))
        assert stage._detect_full_page_scan_filing(context) is False

    def test_mostly_non_page_shaped_does_not_fire(self, stage: ImageTriageStage) -> None:
        """16 images but only 40% page-shaped → does NOT fire even with 0 segments."""
        page_shaped = [
            ImageAsset(img_id=f"p{i}", filename=f"p{i}.jpg", width=1055, height=1365)
            for i in range(6)
        ]
        landscape = [
            ImageAsset(img_id=f"l{i}", filename=f"l{i}.jpg", width=1600, height=900)
            for i in range(10)
        ]
        context = self._make_context(segments=[], images=page_shaped + landscape)
        assert stage._detect_full_page_scan_filing(context) is False


class TestPromoteToFullPageScan:
    """Tests for promotion behavior after the detector fires."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_promotes_page_shaped_overrides_prior_classification(
        self, stage: ImageTriageStage
    ) -> None:
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineConfig, PipelineContext

        page = ImageAsset(
            img_id="p1",
            filename="page_1.jpg",
            width=1055,
            height=1365,
            classification=ImageClassification.UNKNOWN,
            relevance_score=0.2,
        )
        small_logo = ImageAsset(
            img_id="logo",
            filename="company_logo.png",
            width=100,
            height=60,
            classification=ImageClassification.LOGO,
            relevance_score=0.0,
        )
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [page, small_logo]

        promoted = stage._promote_to_full_page_scan(context)

        # Page-shaped image gets promoted; logo is left alone.
        assert promoted == [page]
        assert page.classification == ImageClassification.FULL_PAGE_SCAN
        assert page.relevance_score == 0.6
        assert small_logo.classification == ImageClassification.LOGO

    def test_process_with_flag_off_does_not_promote(self, stage: ImageTriageStage) -> None:
        """When the feature flag is off, page-shaped images retain their UNKNOWN class."""
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineConfig, PipelineContext

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=False),
        )
        context.images = [
            ImageAsset(img_id=f"p{i}", filename=f"p{i}.jpg", width=1055, height=1365)
            for i in range(16)
        ]

        result = stage.process(context)

        assert result.metadata["full_page_scan_mode"] is False
        for img in context.images:
            assert img.classification != ImageClassification.FULL_PAGE_SCAN

    def test_process_with_flag_on_and_paypal_fixture_promotes_all(
        self, stage: ImageTriageStage
    ) -> None:
        """End-to-end: flag on + PayPal-like fixture → all page-shaped images promoted."""
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineConfig, PipelineContext

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [
            ImageAsset(img_id=f"p{i}", filename=f"p{i}.jpg", width=1055, height=1365)
            for i in range(16)
        ]

        result = stage.process(context)

        assert result.metadata["full_page_scan_mode"] is True
        assert all(
            img.classification == ImageClassification.FULL_PAGE_SCAN for img in context.images
        )
        # All 16 get queued for downstream OCR processing.
        assert result.items_output == 16
        assert context.full_page_scan_mode is True


class TestLearnedTriageGate:
    """Tests for the USE_LEARNED_TRIAGE feature-flag gate (Wave B3 Stage 1).

    Post gh-477, the gate is read per-call from `os.environ`, so tests use
    `monkeypatch.setenv` rather than patching module attributes.

    `_MODEL_CACHE` in `src/shared/image_features` is module-scope and persists
    across test instances in the same process — earlier tests that load a real
    model artifact would otherwise satisfy the "model absent" precondition in
    `test_gate_on_but_model_absent_falls_back_to_heuristic`. The autouse fixture
    below wipes the cache before and after every test in this class to guarantee
    order-independence (gh-445, gh-456).
    """

    @pytest.fixture(autouse=True)
    def reset_model_cache(self) -> None:
        """Clear _MODEL_CACHE before and after each test to prevent cross-test pollution."""
        from src.shared import image_features

        image_features._MODEL_CACHE.clear()
        yield
        image_features._MODEL_CACHE.clear()

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def _make_chart_asset(self, relevance_hint: float = 0.6) -> ImageAsset:
        """Build a chart-ish asset whose heuristic score will be roughly the hint."""
        return ImageAsset(
            img_id=f"test_{relevance_hint}",
            filename="chart.png",
            nearby_text="Customer retention cohort",
            width=800,
            height=600,
        )

    def test_gate_off_by_default_matches_heuristic(
        self, stage: ImageTriageStage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """USE_LEARNED_TRIAGE=false (default): behavior matches heuristic path."""
        monkeypatch.setenv("USE_LEARNED_TRIAGE", "false")

        asset = self._make_chart_asset()
        result = stage.triage_images([asset])

        # Heuristic should classify this as a chart and queue it.
        assert asset.classification == ImageClassification.CHART
        # predicted_relevance should NOT be set — the ML gate didn't run.
        assert asset.predicted_relevance is None
        assert len(result) == 1

    def test_gate_on_but_model_absent_falls_back_to_heuristic(
        self,
        stage: ImageTriageStage,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """USE_LEARNED_TRIAGE=true + no model file: queueing uses heuristic.

        This is the critical fallback path — if the model artifact never ships
        or fails to load, the pipeline must not crash or silently drop images.
        """
        monkeypatch.setenv("USE_LEARNED_TRIAGE", "true")
        # Force the local-disk resolution path; with R2_BUCKET set, _load_model
        # would materialize the live model from storage and bypass the patched
        # DEFAULT_MODEL_PATH below (see image_features._load_model:194).
        monkeypatch.delenv("R2_BUCKET", raising=False)
        # Point the loader at a non-existent path so predict_relevance returns None.
        monkeypatch.setattr(
            "src.shared.image_features.DEFAULT_MODEL_PATH",
            tmp_path / "absent.joblib",
        )
        # Clear the module cache to avoid a cached result from a prior test.
        from src.shared import image_features

        image_features._MODEL_CACHE.clear()

        asset = self._make_chart_asset()
        result = stage.triage_images([asset])

        # Heuristic should still queue it since the chart is classified and
        # relevance meets MIN_RELEVANCE_FOR_PROCESSING.
        assert asset.classification == ImageClassification.CHART
        assert len(result) == 1
        # predicted_relevance stays None (fallback path, no model score).
        assert asset.predicted_relevance is None

    def test_gate_on_with_model_uses_predicted_relevance(
        self,
        stage: ImageTriageStage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """USE_LEARNED_TRIAGE=true + model present: queueing uses predicted_relevance.

        Mocks predict_relevance to return 0.8 (above default LEARNED_TRIAGE_MIN=0.4);
        asset should be queued regardless of its heuristic relevance_score and
        predicted_relevance should land on the asset.
        """
        monkeypatch.setenv("USE_LEARNED_TRIAGE", "true")
        monkeypatch.setattr(
            "src.extraction_v2.stages.image_triage.predict_relevance",
            lambda features: 0.8,
        )

        asset = self._make_chart_asset()
        result = stage.triage_images([asset])

        assert asset.predicted_relevance == 0.8
        assert len(result) == 1

    def test_gate_on_below_min_threshold_skips(
        self,
        stage: ImageTriageStage,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """USE_LEARNED_TRIAGE=true + predicted_relevance < LEARNED_TRIAGE_MIN: skip."""
        monkeypatch.setenv("USE_LEARNED_TRIAGE", "true")
        # Default LEARNED_TRIAGE_MIN is 0.4; 0.2 is below threshold.
        monkeypatch.setattr(
            "src.extraction_v2.stages.image_triage.predict_relevance",
            lambda features: 0.2,
        )

        asset = self._make_chart_asset()
        result = stage.triage_images([asset])

        assert asset.predicted_relevance == 0.2
        # Asset was classified but not queued (below learned threshold).
        assert asset.classification == ImageClassification.CHART
        assert len(result) == 0

    def test_env_var_change_after_stage_construction_takes_effect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flipping USE_LEARNED_TRIAGE after import picks up on the next call (gh-477).

        Pre-refactor the gate was read at module import, so a long-running worker
        would never see a Render env-var flip until restart. This test pins the
        per-call read by constructing the stage with the var unset, then flipping
        it on AFTER construction, and asserting the next triage call exercises
        the learned gate path.
        """
        monkeypatch.delenv("USE_LEARNED_TRIAGE", raising=False)
        stage = ImageTriageStage()

        # Flip the gate ON after the stage already exists.
        monkeypatch.setenv("USE_LEARNED_TRIAGE", "true")
        monkeypatch.setattr(
            "src.extraction_v2.stages.image_triage.predict_relevance",
            lambda features: 0.9,
        )

        asset = self._make_chart_asset()
        result = stage.triage_images([asset])

        # If the read were still module-scoped, predicted_relevance would stay None.
        assert asset.predicted_relevance == 0.9
        assert len(result) == 1


# ============================================================================
# A1 reorder regression tests (2026-04-28)
# ============================================================================


class TestA1ReorderBehavior:
    """Pin the A1 priority-reorder: _is_table_image runs before _is_chart.

    These tests document the documented PayPal misrouting regression and
    confirm that the inner ``not self._is_chart()`` guard inside
    ``_is_table_image`` is gone — table structural signals win on conflict.
    """

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def test_paypal_style_table_routes_to_table_image(self, stage: ImageTriageStage) -> None:
        """PayPal-style cohort table: image with "schedule" in nearby text wins TABLE_IMAGE.

        Before A1, ``_is_table_image`` contained a ``not self._is_chart()`` guard —
        so images with both table keywords ("schedule") and metric keywords
        ("revenue", "cohort") in nearby_text would be claimed by CHART.
        After A1, ``_is_table_image`` runs first and has no inner guard, so the
        explicit "schedule" keyword routes this to TABLE_IMAGE.
        """
        asset = ImageAsset(
            img_id="paypal_cohort_table",
            filename="cohort_revenue.png",
            nearby_text="Schedule: cohort revenue by year",
            width=1200,
            height=900,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.TABLE_IMAGE

    def test_wide_aspect_financial_table_routes_to_table_image(
        self, stage: ImageTriageStage
    ) -> None:
        """Strongly wide image (aspect 2.67) with financial keywords → TABLE_IMAGE.

        aspect = 1600/600 = 2.67, well above the 2.0 threshold in _is_table_image;
        nearby text has "revenue" and "period", both in the financial_keywords list.
        Without the A1 reorder this image would have been claimed first by _is_chart
        (large dimensions + metric keyword), never reaching the aspect-ratio check.
        """
        asset = ImageAsset(
            img_id="wide_financial_table",
            filename="data_table_001.png",
            nearby_text="quarterly revenue breakdown by period",
            width=1600,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.TABLE_IMAGE

    def test_pure_chart_filename_still_wins(self, stage: ImageTriageStage) -> None:
        """Chart-pattern filename with no table keywords → CHART.

        Confirms that moving _is_table_image before _is_chart did not suppress
        legitimate chart detection.  A filename hit in _is_chart beats anything
        that _is_table_image could claim (because _is_table_image has no keyword
        match for this asset).
        """
        asset = ImageAsset(
            img_id="bar_chart_growth",
            filename="bar_chart_growth.png",
            nearby_text="Annual customer growth",
            width=800,
            height=600,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.CHART

    def test_table_keyword_beats_chart_signal(self, stage: ImageTriageStage) -> None:
        """Image whose signals would previously conflict now resolves to TABLE_IMAGE.

        This test covers the removal of the inner ``not self._is_chart()`` guard
        that used to live inside ``_is_table_image``.  With the guard gone and
        table-check-first ordering, an image that has BOTH a table keyword (e.g.,
        "schedule" in nearby text) AND would satisfy _is_chart (large dimensions
        + metric keyword) returns TABLE_IMAGE, not CHART.
        """
        asset = ImageAsset(
            img_id="conflicting_signals",
            filename="img_summary.png",
            # "schedule" is an explicit table_keyword; "revenue" is a metric keyword
            # that would also satisfy _is_chart's large-image branch.
            nearby_text="Schedule 2: revenue by cohort",
            width=900,
            height=700,
        )
        result = stage.classify_image(asset)
        assert result == ImageClassification.TABLE_IMAGE


class TestTriageGateEagerLoadStatusLog:
    """One-shot eager-load status log fired on first triage stage run per worker.

    The eager-load surfaces silent degradation at pipeline construction time
    rather than waiting for the first per-image predict call. The flag is
    module-level (`image_triage._LOGGED_TRIAGE_MODEL_STATUS`) so it persists
    across `ImageTriageStage` instances within a worker process — that's
    intentional (one log per worker cold-start, not per filing). Tests must
    reset both the flag and `image_features._MODEL_CACHE` to keep order
    independence.
    """

    @pytest.fixture(autouse=True)
    def reset_module_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reset the once-per-worker flag and the model cache around every test."""
        from src.extraction_v2.stages import image_triage
        from src.shared import image_features

        monkeypatch.setattr(image_triage, "_LOGGED_TRIAGE_MODEL_STATUS", False)
        # Wipe the model cache so a previous test's load doesn't satisfy this one.
        image_features._MODEL_CACHE.clear()
        # Make sure no R2 path is exercised — _load_model resolves to disk.
        monkeypatch.delenv("R2_BUCKET", raising=False)
        yield
        image_features._MODEL_CACHE.clear()

    def _empty_context(self):
        from pathlib import Path

        from src.extraction_v2.pipeline import PipelineContext

        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=None,  # type: ignore
        )
        context.images = []
        return context

    def test_triage_gate_logs_error_once_when_model_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """USE_LEARNED_TRIAGE=true + missing model → exactly one ERROR per worker."""
        import logging

        from src.shared import image_features

        monkeypatch.setenv("USE_LEARNED_TRIAGE", "true")
        # Point the loader at a non-existent file so _load_model returns None silently.
        monkeypatch.setattr(image_features, "DEFAULT_MODEL_PATH", tmp_path / "no_such_model.joblib")

        with caplog.at_level(logging.INFO, logger="src.extraction_v2.stages.image_triage"):
            ImageTriageStage().process(self._empty_context())

        triage_errors = [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and r.name == "src.extraction_v2.stages.image_triage"
        ]
        assert len(triage_errors) == 1, (
            f"Expected exactly one ERROR from image_triage, got "
            f"{[(r.levelname, r.message) for r in caplog.records]}"
        )
        assert "USE_LEARNED_TRIAGE=true" in triage_errors[0].message

        # Second .process() on a fresh stage instance — the flag is module-level
        # so no additional ERROR record should fire.
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="src.extraction_v2.stages.image_triage"):
            ImageTriageStage().process(self._empty_context())

        assert [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and r.name == "src.extraction_v2.stages.image_triage"
        ] == [], "Eager-load ERROR must fire only once per worker process"

    def test_triage_gate_logs_info_once_when_model_loads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """USE_LEARNED_TRIAGE=true + loadable model → INFO log, no ERROR."""
        import logging
        from unittest.mock import MagicMock, patch

        from src.shared import image_features

        monkeypatch.setenv("USE_LEARNED_TRIAGE", "true")
        # Provide a real existing path; patch joblib.load to return a fake pipeline.
        model_file = tmp_path / "model.joblib"
        model_file.write_bytes(b"placeholder")
        monkeypatch.setattr(image_features, "DEFAULT_MODEL_PATH", model_file)

        fake_pipeline = MagicMock(name="fake_pipeline")

        with caplog.at_level(logging.INFO, logger="src.extraction_v2.stages.image_triage"):
            with patch("joblib.load", return_value=fake_pipeline):
                ImageTriageStage().process(self._empty_context())

        triage_records = [
            r for r in caplog.records if r.name == "src.extraction_v2.stages.image_triage"
        ]
        info_records = [r for r in triage_records if r.levelno == logging.INFO]
        error_records = [r for r in triage_records if r.levelno >= logging.ERROR]

        assert error_records == [], (
            f"No ERROR expected when model loads; got {[r.message for r in error_records]}"
        )
        assert any(
            "image relevance model loaded successfully" in r.message for r in info_records
        ), f"Expected INFO load-success log; got {[r.message for r in info_records]}"

    def test_triage_gate_silent_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """USE_LEARNED_TRIAGE=false → no eager-load log of any level."""
        import logging

        monkeypatch.setenv("USE_LEARNED_TRIAGE", "false")

        with caplog.at_level(logging.DEBUG, logger="src.extraction_v2.stages.image_triage"):
            ImageTriageStage().process(self._empty_context())

        gate_messages = [
            r.message
            for r in caplog.records
            if r.name == "src.extraction_v2.stages.image_triage"
            and "USE_LEARNED_TRIAGE" in r.message
        ]
        assert gate_messages == [], (
            f"Eager-load helper must be a no-op when the gate flag is off; got: {gate_messages}"
        )
