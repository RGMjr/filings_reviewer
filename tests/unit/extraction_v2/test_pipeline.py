"""Tests for V2 extraction pipeline orchestrator."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.extraction_v2.models import MetricFact, ReviewStatus
from src.extraction_v2.pipeline import (
    PipelineConfig,
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    V2Pipeline,
    process_filing,
)


class TestPipelineConfig:
    """Tests for PipelineConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = PipelineConfig()
        assert config.enable_section_classification is True
        assert config.enable_image_extraction is True
        assert config.enable_chart_extraction is True
        assert config.min_confidence_auto_accept == 0.90
        assert config.min_confidence_no_review == 0.85
        assert config.max_confidence_auto_reject == 0.15
        assert config.value_tolerance == 0.02

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = PipelineConfig(
            enable_chart_extraction=False,
            min_confidence_auto_accept=0.95,
            max_images_per_document=100,
        )
        assert config.enable_chart_extraction is False
        assert config.min_confidence_auto_accept == 0.95
        assert config.max_images_per_document == 100


class TestStageResult:
    """Tests for StageResult dataclass."""

    def test_successful_result(self) -> None:
        """Test successful stage result."""
        result = StageResult(
            stage=PipelineStage.INGESTION,
            success=True,
            duration_ms=150,
            items_processed=1,
            items_output=50,
            metadata={"segment_count": 50},
        )
        assert result.success is True
        assert result.duration_ms == 150
        assert result.items_output == 50
        assert len(result.errors) == 0

    def test_failed_result(self) -> None:
        """Test failed stage result."""
        result = StageResult(
            stage=PipelineStage.TABLE_RECONSTRUCTION,
            success=False,
            duration_ms=100,
            items_processed=10,
            items_output=0,
            errors=["Table structure invalid"],
        )
        assert result.success is False
        assert len(result.errors) == 1


class TestPipelineContext:
    """Tests for PipelineContext dataclass."""

    def test_context_creation(self) -> None:
        """Test context initialization."""
        config = PipelineConfig()
        context = PipelineContext(
            html_path=Path("/test/filing.html"),
            filing_id=123,
            config=config,
        )
        assert context.html_path == Path("/test/filing.html")
        assert context.filing_id == 123
        assert context.document is None
        assert len(context.segments) == 0
        assert len(context.facts) == 0
        assert context.llm_calls == 0


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_result_properties(self) -> None:
        """Test computed properties."""
        from src.extraction_v2.models import Document

        facts = [
            MetricFact(requires_review=True),
            MetricFact(requires_review=False),
            MetricFact(requires_review=True),
        ]
        result = PipelineResult(
            document=Document(),
            facts=facts,
            tables=[],
            images=[],
            segments=[],
            stage_results=[],
            total_duration_ms=1000,
            success=True,
        )
        assert result.fact_count == 3
        assert result.pending_review_count == 2
        assert result.auto_accepted_count == 1

    def test_has_stub_warnings_false_when_no_stubs(self) -> None:
        """Test has_stub_warnings is False when no stub warnings."""
        from src.extraction_v2.models import Document

        result = PipelineResult(
            document=Document(),
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=[
                StageResult(
                    stage=PipelineStage.INGESTION,
                    success=True,
                    duration_ms=100,
                    items_processed=1,
                    items_output=10,
                    warnings=[],  # No warnings
                ),
            ],
            total_duration_ms=100,
            success=True,
        )
        assert result.has_stub_warnings is False
        assert result.stub_stage_warnings == []

    def test_has_stub_warnings_true_when_stub_present(self) -> None:
        """Test has_stub_warnings is True when stub warnings present."""
        from src.extraction_v2.models import Document

        result = PipelineResult(
            document=Document(),
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=[
                StageResult(
                    stage=PipelineStage.INGESTION,
                    success=True,
                    duration_ms=100,
                    items_processed=1,
                    items_output=10,
                ),
                StageResult(
                    stage=PipelineStage.CANDIDATE_GENERATION,
                    success=True,
                    duration_ms=50,
                    items_processed=10,
                    items_output=0,
                    warnings=["Candidate generation not yet implemented - no metric candidates generated"],
                ),
            ],
            total_duration_ms=150,
            success=True,
        )
        assert result.has_stub_warnings is True
        assert len(result.stub_stage_warnings) == 1
        assert "candidate_generation" in result.stub_stage_warnings[0]

    def test_stub_stage_warnings_collects_all(self) -> None:
        """Test stub_stage_warnings collects warnings from all stages."""
        from src.extraction_v2.models import Document

        result = PipelineResult(
            document=Document(),
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=[
                StageResult(
                    stage=PipelineStage.SECTION_CLASSIFICATION,
                    success=True,
                    duration_ms=10,
                    items_processed=10,
                    items_output=10,
                    warnings=["Section classification not yet implemented - all segments marked UNKNOWN"],
                ),
                StageResult(
                    stage=PipelineStage.VALUE_BINDING,
                    success=True,
                    duration_ms=10,
                    items_processed=0,
                    items_output=0,
                    warnings=["Value binding not yet implemented - no values bound to metrics"],
                ),
            ],
            total_duration_ms=20,
            success=True,
        )
        assert result.has_stub_warnings is True
        assert len(result.stub_stage_warnings) == 2


class TestV2Pipeline:
    """Tests for V2Pipeline orchestrator."""

    def test_pipeline_initialization(self) -> None:
        """Test pipeline initializes with all stages."""
        pipeline = V2Pipeline()
        # Should have 11 stages by default
        assert len(pipeline._stages) == 11

    def test_pipeline_with_disabled_features(self) -> None:
        """Test pipeline with disabled optional features."""
        config = PipelineConfig(
            enable_section_classification=False,
            enable_image_extraction=False,
            enable_chart_extraction=False,
        )
        pipeline = V2Pipeline(config=config)
        # Should have fewer stages
        stage_ids = [s[0] for s in pipeline._stages]
        assert PipelineStage.SECTION_CLASSIFICATION not in stage_ids
        assert PipelineStage.IMAGE_TRIAGE not in stage_ids
        assert PipelineStage.OCR_CHART_EXTRACTION not in stage_ids

    def test_pipeline_process_basic(self, tmp_path: Path) -> None:
        """Test basic pipeline execution."""
        # Create a minimal test HTML file
        html_file = tmp_path / "test_filing.html"
        html_file.write_text("<html><body><p>Test content</p></body></html>")

        pipeline = V2Pipeline()
        result = pipeline.process(html_file, filing_id=1)

        # Should complete without error (even if no facts extracted)
        assert result.success is True
        assert result.document is not None
        assert len(result.stage_results) == 11  # All stages executed

    def test_pipeline_tracks_stage_durations(self, tmp_path: Path) -> None:
        """Test that stage durations are tracked."""
        html_file = tmp_path / "test_filing.html"
        html_file.write_text("<html><body></body></html>")

        pipeline = V2Pipeline()
        result = pipeline.process(html_file, filing_id=1)

        for stage_result in result.stage_results:
            assert stage_result.duration_ms >= 0

    def test_pipeline_stub_stages_produce_warnings(self, tmp_path: Path) -> None:
        """Test that stub stages produce 'not yet implemented' warnings."""
        html_file = tmp_path / "test_filing.html"
        html_file.write_text("<html><body><p>Test content for extraction.</p></body></html>")

        pipeline = V2Pipeline()
        result = pipeline.process(html_file, filing_id=1)

        # Pipeline should succeed but have stub warnings
        assert result.success is True
        assert result.has_stub_warnings is True

        # Should have multiple stub stage warnings
        stub_warnings = result.stub_stage_warnings
        assert len(stub_warnings) > 0

        # Check specific stub stages produce warnings
        warning_stages = [w.split(":")[0] for w in stub_warnings]
        assert "section_classification" in warning_stages
        assert "table_reconstruction" in warning_stages
        assert "candidate_generation" in warning_stages
        assert "value_binding" in warning_stages
        assert "period_inference" in warning_stages
        assert "fact_construction" in warning_stages
        assert "deduplication" in warning_stages

    def test_pipeline_stub_warnings_detectable_before_production(self, tmp_path: Path) -> None:
        """Test that has_stub_warnings can be used to detect unimplemented stages.

        This is critical for ensuring the pipeline isn't accidentally
        used in production when stages are still stubs.
        """
        html_file = tmp_path / "test_filing.html"
        html_file.write_text("<html><body></body></html>")

        pipeline = V2Pipeline()
        result = pipeline.process(html_file, filing_id=1)

        # A production check would look like this:
        if result.has_stub_warnings:
            # In production, you'd raise an error or log a warning
            # For now, just verify this check works
            assert True, "Stub warnings detected - pipeline not production-ready"
        else:
            # This should NOT happen until all stages are implemented
            pytest.fail("Expected stub warnings but none found")


class TestValidationStage:
    """Tests for validation and review routing."""

    def test_high_confidence_auto_accept(self) -> None:
        """Test that high-confidence facts are auto-accepted."""
        config = PipelineConfig(min_confidence_auto_accept=0.90)
        context = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=config,
        )

        # Add a high-confidence fact
        fact = MetricFact(confidence=0.95, requires_review=True)
        context.facts = [fact]

        # Run validation stage
        from src.extraction_v2.pipeline import ValidationStage

        stage = ValidationStage()
        result = stage.process(context)

        assert result.success is True
        assert context.facts[0].requires_review is False

    def test_low_confidence_requires_review(self) -> None:
        """Test that low-confidence facts require review."""
        config = PipelineConfig(
            min_confidence_auto_accept=0.90,
            max_confidence_auto_reject=0.15,
        )
        context = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=config,
        )

        # Add a medium-confidence fact
        fact = MetricFact(confidence=0.50, requires_review=False)
        context.facts = [fact]

        # Run validation stage
        from src.extraction_v2.pipeline import ValidationStage

        stage = ValidationStage()
        result = stage.process(context)

        assert result.success is True
        assert context.facts[0].requires_review is True

    def test_very_low_confidence_flagged(self) -> None:
        """Test that very low confidence facts are flagged for rejection."""
        config = PipelineConfig(max_confidence_auto_reject=0.15)
        context = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=config,
        )

        # Add a very low-confidence fact
        fact = MetricFact(confidence=0.10, requires_review=False)
        context.facts = [fact]

        # Run validation stage
        from src.extraction_v2.pipeline import ValidationStage

        stage = ValidationStage()
        result = stage.process(context)

        assert context.facts[0].requires_review is True
        assert "auto-reject" in context.facts[0].review_reason.lower()


class TestProcessFiling:
    """Tests for the convenience function."""

    def test_process_filing_function(self, tmp_path: Path) -> None:
        """Test the main entry point function."""
        html_file = tmp_path / "filing.html"
        html_file.write_text("<html><body>Content</body></html>")

        result = process_filing(html_file, filing_id=42)

        assert isinstance(result, PipelineResult)
        assert result.success is True

    def test_process_filing_with_config(self, tmp_path: Path) -> None:
        """Test with custom configuration."""
        html_file = tmp_path / "filing.html"
        html_file.write_text("<html><body>Content</body></html>")

        config = PipelineConfig(enable_chart_extraction=False)
        result = process_filing(html_file, filing_id=42, config=config)

        # Should not have OCR/chart stage in results
        stage_names = [r.stage for r in result.stage_results]
        assert PipelineStage.OCR_CHART_EXTRACTION not in stage_names


class TestPipelineStages:
    """Tests for individual pipeline stages."""

    def test_ingestion_stage(self, tmp_path: Path) -> None:
        """Test ingestion stage creates document."""
        from src.extraction_v2.pipeline import IngestionStage

        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body>Test</body></html>")

        context = PipelineContext(
            html_path=html_file,
            filing_id=1,
            config=PipelineConfig(),
        )

        stage = IngestionStage()
        result = stage.process(context)

        assert result.success is True
        assert context.document is not None
        assert str(context.document.html_path) == str(html_file)

    def test_table_reconstruction_stage(self) -> None:
        """Test table reconstruction stage."""
        from src.extraction_v2.pipeline import TableReconstructionStage

        context = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=PipelineConfig(),
        )

        stage = TableReconstructionStage()
        result = stage.process(context)

        assert result.success is True
        assert result.stage == PipelineStage.TABLE_RECONSTRUCTION

    def test_deduplication_stage(self) -> None:
        """Test deduplication stage."""
        from src.extraction_v2.pipeline import DeduplicationStage

        context = PipelineContext(
            html_path=Path("/test.html"),
            filing_id=1,
            config=PipelineConfig(),
        )
        # Add some facts
        context.facts = [MetricFact(), MetricFact()]

        stage = DeduplicationStage()
        result = stage.process(context)

        assert result.success is True
        assert "duplicates_removed" in result.metadata
