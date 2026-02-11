"""
Unit tests for V2 Image Extraction Pipeline integration.

Tests the 4 breaks fixed in the image extraction chain:
- C4: Image downloading via SECClient (OCRExtractionStage._download_missing_images)
- C2: OCR tables fed into context.tables (OCRExtractionStage.process)
- C1: Chart scanning in candidate generation (_scan_chart)
- C3: Chart value binding (_bind_chart_candidate + _infer_unit_from_axis)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.extraction_v2.models import (
    BoundValue,
    Cell,
    ChartData,
    ChartSeries,
    ChartType,
    DataPoint,
    ImageAsset,
    ImageClassification,
    MetricCandidate,
    SectionType,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
    Table,
    Unit,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.candidate_generation import CandidateGenerationStage
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.extraction_v2.stages.value_binding import ValueBindingStage
from src.llm.vision_client import VisionResponse


# =============================================================================
# Shared Fixtures
# =============================================================================


@dataclass
class MockPipelineConfig:
    """Mock pipeline config for testing."""

    min_confidence_auto_accept: float = 0.90
    min_confidence_no_review: float = 0.85
    max_confidence_auto_reject: float = 0.15
    enable_image_extraction: bool = True
    enable_chart_extraction: bool = True


@dataclass
class MockPipelineContext:
    """Mock pipeline context for testing."""

    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: Any = field(default_factory=MockPipelineConfig)

    document: Any = None
    segments: list[Segment] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    candidates: list[MetricCandidate] = field(default_factory=list)
    bound_values: list[Any] = field(default_factory=list)
    facts: list[Any] = field(default_factory=list)
    deduplicated_facts: list[Any] = field(default_factory=list)
    stage_results: list[Any] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    llm_calls: int = 0
    ocr_calls: int = 0
    vision_calls: int = 0

    # SEC filing info
    cik: str = ""
    accession_number: str = ""


class MockVisionClient:
    """Mock vision client for testing."""

    def __init__(self, responses: list[VisionResponse]) -> None:
        self.responses = responses
        self.call_count = 0
        self.model = "gpt-4o-mock"

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        detail: str = "high",
        max_tokens: int = 2000,
    ) -> VisionResponse:
        if self.call_count >= len(self.responses):
            raise IndexError(f"No more mock responses (call_count={self.call_count})")
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


class MockSECClient:
    """Mock SEC client for testing image downloading."""

    def __init__(self, image_data: dict[str, bytes] | None = None) -> None:
        self.image_data = image_data or {}
        self.fetch_calls: list[tuple[str, str, str]] = []

    def fetch_image(
        self,
        cik: str,
        accession_number: str,
        filename: str,
        *,
        max_size_bytes: int = 10 * 1024 * 1024,
    ) -> bytes | None:
        self.fetch_calls.append((cik, accession_number, filename))
        return self.image_data.get(filename)


def _make_chart_asset(
    img_id: str = "img-chart-1",
    title: str = "GMV by Consumer Cohort (USDm)",
    y_axis_label: str = "GMV (USDm)",
    x_axis_label: str = "Year",
    series_data: list[tuple[str, list[tuple[str, float, str | None]]]] | None = None,
    section_type: SectionType = SectionType.MDA,
    confidence: float = 0.85,
) -> ImageAsset:
    """Create a chart ImageAsset with ChartData for testing."""
    if series_data is None:
        series_data = [
            (
                "Total GMV",
                [
                    ("2016", 800.0, "$800M"),
                    ("2017", 1400.0, "$1,400M"),
                    ("2018", 2100.0, "$2,100M"),
                ],
            ),
        ]

    series = []
    for name, points in series_data:
        data_points = [DataPoint(x=x, y=y, label=label) for x, y, label in points]
        series.append(ChartSeries(name=name, points=data_points))

    chart_data = ChartData(
        chart_type=ChartType.BAR,
        title=title,
        x_axis_label=x_axis_label,
        y_axis_label=y_axis_label,
        series=series,
    )

    asset = ImageAsset(
        img_id=img_id,
        classification=ImageClassification.CHART,
        chart_data=chart_data,
        section_type=section_type,
        processed=True,
        confidence=confidence,
        relevance_score=0.9,
        dom_locator="/html/body/div[5]/img[1]",
    )
    return asset


# =============================================================================
# C4: Image Downloading Tests
# =============================================================================


class TestImageDownloading:
    """Tests for OCRExtractionStage._download_missing_images."""

    def test_downloads_images_without_file_path(self, tmp_path: Path) -> None:
        """Images that passed triage but lack file_path get downloaded."""
        mock_sec = MockSECClient(
            image_data={"chart1.jpg": b"\xff\xd8\xff\xe0fake_jpeg_data"}
        )
        stage = OCRExtractionStage(sec_client=mock_sec)

        context = MockPipelineContext(
            cik="1234567",
            accession_number="0001234567-24-000001",
        )
        asset = ImageAsset(
            img_id="img-1",
            filename="chart1.jpg",
            file_path=None,
            classification=ImageClassification.CHART,
            relevance_score=0.8,
            processed=False,
        )
        context.images = [asset]

        downloaded = stage._download_missing_images(context)

        assert downloaded == 1
        assert asset.file_path is not None
        assert Path(asset.file_path).exists()
        assert mock_sec.fetch_calls == [("1234567", "0001234567-24-000001", "chart1.jpg")]

    def test_skips_images_with_existing_file_path(self) -> None:
        """Images that already have file_path are not re-downloaded."""
        mock_sec = MockSECClient()
        stage = OCRExtractionStage(sec_client=mock_sec)

        context = MockPipelineContext(
            cik="1234567",
            accession_number="0001234567-24-000001",
        )
        asset = ImageAsset(
            img_id="img-1",
            filename="chart1.jpg",
            file_path="/existing/path.jpg",
            classification=ImageClassification.CHART,
            relevance_score=0.8,
            processed=False,
        )
        context.images = [asset]

        downloaded = stage._download_missing_images(context)

        assert downloaded == 0
        assert mock_sec.fetch_calls == []

    def test_skips_decorative_images(self) -> None:
        """Decorative images are not downloaded."""
        mock_sec = MockSECClient(image_data={"logo.png": b"fake"})
        stage = OCRExtractionStage(sec_client=mock_sec)

        context = MockPipelineContext(
            cik="1234567",
            accession_number="0001234567-24-000001",
        )
        asset = ImageAsset(
            img_id="img-1",
            filename="logo.png",
            classification=ImageClassification.DECORATIVE,
            relevance_score=0.1,
            processed=False,
        )
        context.images = [asset]

        downloaded = stage._download_missing_images(context)

        assert downloaded == 0

    def test_skips_low_relevance_images(self) -> None:
        """Images below relevance threshold are not downloaded."""
        mock_sec = MockSECClient(image_data={"img.jpg": b"fake"})
        stage = OCRExtractionStage(sec_client=mock_sec)

        context = MockPipelineContext(
            cik="1234567",
            accession_number="0001234567-24-000001",
        )
        asset = ImageAsset(
            img_id="img-1",
            filename="img.jpg",
            classification=ImageClassification.CHART,
            relevance_score=0.1,  # Below MIN_RELEVANCE_FOR_PROCESSING
            processed=False,
        )
        context.images = [asset]

        downloaded = stage._download_missing_images(context)

        assert downloaded == 0

    def test_no_download_without_cik(self) -> None:
        """No downloads when CIK is missing."""
        mock_sec = MockSECClient()
        stage = OCRExtractionStage(sec_client=mock_sec)

        context = MockPipelineContext(cik="", accession_number="0001234567-24-000001")
        context.images = [
            ImageAsset(
                filename="chart.jpg",
                classification=ImageClassification.CHART,
                relevance_score=0.8,
            )
        ]

        downloaded = stage._download_missing_images(context)

        assert downloaded == 0

    def test_handles_failed_download(self) -> None:
        """Failed downloads are handled gracefully."""
        mock_sec = MockSECClient(image_data={})  # Returns None for all
        stage = OCRExtractionStage(sec_client=mock_sec)

        context = MockPipelineContext(
            cik="1234567",
            accession_number="0001234567-24-000001",
        )
        asset = ImageAsset(
            img_id="img-1",
            filename="missing.jpg",
            classification=ImageClassification.CHART,
            relevance_score=0.8,
            processed=False,
        )
        context.images = [asset]

        downloaded = stage._download_missing_images(context)

        assert downloaded == 0
        assert asset.file_path is None


# =============================================================================
# C2: OCR Tables → context.tables Tests
# =============================================================================


class TestOCRTableFeeding:
    """Tests for OCR tables being added to context.tables."""

    def test_ocr_table_added_to_context(self, tmp_path: Path) -> None:
        """Successfully OCR'd table images feed their Table into context.tables."""
        ocr_response = VisionResponse(
            content=json.dumps(
                {
                    "raw_text": "Metric 2023\nARR $100M",
                    "confidence": 0.9,
                    "cells": [
                        {"row": 0, "col": 0, "text": "Metric", "is_header": True},
                        {"row": 0, "col": 1, "text": "2023", "is_header": True},
                        {"row": 1, "col": 0, "text": "ARR", "is_header": False},
                        {"row": 1, "col": 1, "text": "$100M", "is_header": False},
                    ],
                }
            ),
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=500,
        )
        mock_vision = MockVisionClient([ocr_response])
        stage = OCRExtractionStage(vision_client=mock_vision)

        # Create temp image file
        image_path = tmp_path / "table.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_image")

        context = MockPipelineContext()
        asset = ImageAsset(
            img_id="img-table-1",
            filename="table.png",
            file_path=str(image_path),
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
        )
        context.images = [asset]

        result = stage.process(context)

        assert result.success
        assert len(context.tables) == 1
        table = context.tables[0]
        assert table.row_count == 2
        assert table.col_count == 2

    def test_failed_ocr_does_not_add_table(self, tmp_path: Path) -> None:
        """Failed OCR (non-JSON response) doesn't add table to context."""
        bad_response = VisionResponse(
            content="I cannot read this image",
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=20,
            cost_usd=0.005,
            latency_ms=300,
        )
        mock_vision = MockVisionClient([bad_response])
        stage = OCRExtractionStage(vision_client=mock_vision)

        image_path = tmp_path / "bad_table.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_image")

        context = MockPipelineContext()
        asset = ImageAsset(
            img_id="img-table-2",
            filename="bad_table.png",
            file_path=str(image_path),
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
        )
        context.images = [asset]

        result = stage.process(context)

        # Tables list should remain empty
        assert len(context.tables) == 0


# =============================================================================
# C1: Chart Scanning in Candidate Generation Tests
# =============================================================================


class TestChartScanning:
    """Tests for CandidateGenerationStage._scan_chart."""

    @pytest.fixture
    def stage(self) -> CandidateGenerationStage:
        """Create an initialized candidate generation stage."""
        s = CandidateGenerationStage()
        s._ensure_initialized()
        return s

    def test_scan_chart_finds_metric_in_title(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Chart title containing metric keyword produces candidates."""
        asset = _make_chart_asset(
            title="Annual Recurring Revenue Growth",
            y_axis_label="ARR ($M)",
        )

        candidates = stage._scan_chart(asset)

        # Should find at least one candidate for ARR
        assert len(candidates) >= 1
        # All should be CHART source type
        assert all(c.source_type == SourceType.CHART for c in candidates)
        # All should reference the correct img_id
        assert all(c.source_locator.img_id == asset.img_id for c in candidates)

    def test_scan_chart_finds_metric_in_axis_label(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Metric keyword in y-axis label produces candidates."""
        asset = _make_chart_asset(
            title="Growth Over Time",
            y_axis_label="Annual Recurring Revenue ($M)",
        )

        candidates = stage._scan_chart(asset)

        # Should find ARR-related candidate
        metric_ids = {c.metric_id for c in candidates}
        assert any("arr" in mid.lower() for mid in metric_ids), (
            f"Expected ARR metric, got: {metric_ids}"
        )

    def test_scan_chart_finds_metric_in_series_name(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Metric keyword in series name produces candidates."""
        asset = _make_chart_asset(
            title="Key Metrics",
            y_axis_label="Value",
            series_data=[
                ("Net Revenue Retention", [("2023", 120.0, "120%")]),
            ],
        )

        candidates = stage._scan_chart(asset)

        metric_ids = {c.metric_id for c in candidates}
        assert any("retention" in mid.lower() or "nrr" in mid.lower() for mid in metric_ids), (
            f"Expected retention metric, got: {metric_ids}"
        )

    def test_scan_chart_empty_metadata(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Chart with no title/labels/series produces no candidates."""
        asset = _make_chart_asset(
            title="",
            y_axis_label="",
            x_axis_label="",
            series_data=[("", [("2023", 100.0, "100")])],
        )

        candidates = stage._scan_chart(asset)

        assert len(candidates) == 0

    def test_scan_chart_no_chart_data(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Asset without chart_data produces no candidates."""
        asset = ImageAsset(
            img_id="img-no-chart",
            chart_data=None,
        )

        candidates = stage._scan_chart(asset)

        assert len(candidates) == 0

    def test_scan_chart_confidence_includes_structured_bonus(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Chart candidates get the structured source bonus (same as tables)."""
        asset = _make_chart_asset(
            title="Annual Recurring Revenue Over Time",
            y_axis_label="Revenue ($M)",
        )

        candidates = stage._scan_chart(asset)

        if candidates:
            # Chart candidates should have at least base + structured bonus
            assert all(
                c.confidence >= stage.BASE_CONFIDENCE + stage.TABLE_SOURCE_BONUS
                for c in candidates
            ), f"Confidence too low: {[c.confidence for c in candidates]}"

    def test_chart_candidates_in_pipeline_context(
        self, stage: CandidateGenerationStage
    ) -> None:
        """Chart candidates are added to context.candidates during process()."""
        asset = _make_chart_asset(
            title="Annual Recurring Revenue by Cohort",
            y_axis_label="ARR ($M)",
        )

        context = MockPipelineContext()
        context.images = [asset]

        result = stage.process(context)

        assert result.success
        chart_candidates = [
            c for c in context.candidates if c.source_type == SourceType.CHART
        ]
        assert len(chart_candidates) >= 1


# =============================================================================
# C3: Chart Value Binding Tests
# =============================================================================


class TestChartValueBinding:
    """Tests for ValueBindingStage._bind_chart_candidate."""

    @pytest.fixture
    def stage(self) -> ValueBindingStage:
        return ValueBindingStage()

    def test_bind_chart_candidate_produces_bound_values(
        self, stage: ValueBindingStage
    ) -> None:
        """Chart candidate with data points produces BoundValue per point."""
        asset = _make_chart_asset(
            series_data=[
                (
                    "Total GMV",
                    [
                        ("2016", 800.0, "$800M"),
                        ("2017", 1400.0, "$1,400M"),
                        ("2018", 2100.0, "$2,100M"),
                    ],
                ),
            ],
        )

        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id=asset.img_id),
            source_type=SourceType.CHART,
            confidence=0.7,
        )

        bound_values = stage._bind_chart_candidate(candidate, [asset])

        assert len(bound_values) == 3
        assert bound_values[0].value == 800.0
        assert bound_values[0].value_raw == "$800M"
        assert bound_values[1].value == 1400.0
        assert bound_values[2].value == 2100.0

    def test_bind_chart_candidate_sets_unit_from_axis(
        self, stage: ValueBindingStage
    ) -> None:
        """Unit is inferred from y-axis label."""
        asset = _make_chart_asset(y_axis_label="Revenue ($M)")

        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id=asset.img_id),
            source_type=SourceType.CHART,
        )

        bound_values = stage._bind_chart_candidate(candidate, [asset])

        assert all(bv.unit == Unit.CURRENCY for bv in bound_values)

    def test_bind_chart_candidate_binding_type(
        self, stage: ValueBindingStage
    ) -> None:
        """Bound values have binding_type='chart_label'."""
        asset = _make_chart_asset()

        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id=asset.img_id),
            source_type=SourceType.CHART,
        )

        bound_values = stage._bind_chart_candidate(candidate, [asset])

        assert all(bv.binding_type == "chart_label" for bv in bound_values)

    def test_bind_chart_candidate_confidence_discount(
        self, stage: ValueBindingStage
    ) -> None:
        """Chart binding confidence is discounted by 0.9x from asset confidence."""
        asset = _make_chart_asset(confidence=0.85)

        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id=asset.img_id),
            source_type=SourceType.CHART,
        )

        bound_values = stage._bind_chart_candidate(candidate, [asset])

        expected_confidence = 0.85 * 0.9
        assert all(
            abs(bv.binding_confidence - expected_confidence) < 0.001
            for bv in bound_values
        )

    def test_bind_chart_candidate_missing_asset(
        self, stage: ValueBindingStage
    ) -> None:
        """Returns empty when asset is not found."""
        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id="nonexistent"),
            source_type=SourceType.CHART,
        )

        bound_values = stage._bind_chart_candidate(candidate, [])

        assert len(bound_values) == 0

    def test_bind_chart_candidate_multiple_series(
        self, stage: ValueBindingStage
    ) -> None:
        """Multiple series produce bound values from all series."""
        asset = _make_chart_asset(
            series_data=[
                ("Series A", [("2023", 100.0, "100")]),
                ("Series B", [("2023", 200.0, "200")]),
            ],
        )

        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id=asset.img_id),
            source_type=SourceType.CHART,
        )

        bound_values = stage._bind_chart_candidate(candidate, [asset])

        assert len(bound_values) == 2
        values = sorted(bv.value for bv in bound_values)
        assert values == [100.0, 200.0]

    def test_bind_chart_in_process(self, stage: ValueBindingStage) -> None:
        """Chart candidates are bound during process() (not stubbed)."""
        asset = _make_chart_asset()

        candidate = MetricCandidate(
            metric_id="cm_gmv",
            match_text="GMV",
            source_locator=SourceLocator(img_id=asset.img_id),
            source_type=SourceType.CHART,
        )

        context = MockPipelineContext()
        context.images = [asset]
        context.candidates = [candidate]

        result = stage.process(context)

        assert result.success
        assert len(context.bound_values) > 0
        assert all(bv.binding_type == "chart_label" for bv in context.bound_values)


# =============================================================================
# Unit Inference Tests
# =============================================================================


class TestInferUnitFromAxis:
    """Tests for ValueBindingStage._infer_unit_from_axis."""

    @pytest.fixture
    def stage(self) -> ValueBindingStage:
        return ValueBindingStage()

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Revenue ($M)", Unit.CURRENCY),
            ("GMV (USDm)", Unit.CURRENCY),
            ("$millions", Unit.CURRENCY),
            ("Retention Rate (%)", Unit.PERCENT),
            ("Churn Rate", Unit.PERCENT),
            ("Growth percent", Unit.PERCENT),
            ("Number of Users", Unit.COUNT),
            ("Customer Count", Unit.COUNT),
            ("Active Subscribers", Unit.COUNT),
            ("Value", Unit.OTHER),
            ("", Unit.OTHER),
            (None, Unit.OTHER),
        ],
    )
    def test_infer_unit(
        self, stage: ValueBindingStage, label: str | None, expected: Unit
    ) -> None:
        result = stage._infer_unit_from_axis(label)  # type: ignore[arg-type]
        assert result == expected, f"For label {label!r}: expected {expected}, got {result}"


# =============================================================================
# Pipeline-level Integration Tests
# =============================================================================


class TestPipelineContextFields:
    """Tests for new PipelineContext fields."""

    def test_context_has_cik_and_accession(self) -> None:
        """PipelineContext has cik and accession_number fields."""
        ctx = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=PipelineConfig(),
            cik="1234567",
            accession_number="0001234567-24-000001",
        )
        assert ctx.cik == "1234567"
        assert ctx.accession_number == "0001234567-24-000001"

    def test_context_defaults_empty_strings(self) -> None:
        """CIK and accession_number default to empty strings."""
        ctx = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=PipelineConfig(),
        )
        assert ctx.cik == ""
        assert ctx.accession_number == ""


class TestV2PipelineSecClient:
    """Tests for V2Pipeline accepting sec_client parameter."""

    def test_pipeline_accepts_sec_client(self) -> None:
        """V2Pipeline can be initialized with a sec_client."""
        from src.extraction_v2.pipeline import V2Pipeline

        mock_client = MagicMock()
        pipeline = V2Pipeline(sec_client=mock_client)
        assert pipeline._sec_client is mock_client

    def test_pipeline_passes_sec_client_to_ocr_stage(self) -> None:
        """V2Pipeline passes sec_client through to OCRExtractionStage."""
        from src.extraction_v2.pipeline import V2Pipeline

        mock_client = MagicMock()
        pipeline = V2Pipeline(sec_client=mock_client)

        # Find the OCR stage
        ocr_stages = [
            (stage_id, proc)
            for stage_id, proc in pipeline._stages
            if isinstance(proc, OCRExtractionStage)
        ]
        assert len(ocr_stages) == 1
        _, ocr_stage = ocr_stages[0]
        assert ocr_stage._sec_client is mock_client
