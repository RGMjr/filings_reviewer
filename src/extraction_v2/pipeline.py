"""
V2 Extraction Pipeline Orchestrator.

This module orchestrates the 12-stage extraction pipeline, plus an optional
Chart Fact Bridge that runs after validation when enable_chart_fact_bridge=True:

1. Ingestion & Parsing         → Segments with XPath locators
2. Section Classification      → MD&A, Risk Factors, etc.
3. Table Reconstruction        → header_path, stub_path per cell
4. Image Triage                → chart, table_image, decorative
5. OCR & Chart Extraction      → labeled values only
6. Metric Candidate Generation → YAML taxonomy matching
7. Value Binding               → structural link required
7.5. False Positive Filter     → V1 FP filter on bound values
8. Period Inference            → from header_path or context
9. MetricFact Construction     → with evidence_pack
10. Deduplication              → by identity tuple
11. Validation & Review Routing → confidence-based
12. Chart Fact Bridge (optional) → cohort facts from chart images

Design principles:
- Structure-first, LLM-second
- No value without provenance
- Fail closed (ambiguous → review, don't guess)
- Charts only when labeled (never interpolate from axis)
"""

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

from src.extraction_v2.exceptions import V2FatalError, V2TransientError
from src.extraction_v2.models import (
    BoundValue,
    Document,
    ImageAsset,
    MetricCandidate,
    MetricDefinition,
    MetricFact,
    Segment,
    Table,
)
from src.extraction_v2.stages.candidate_generation import CandidateGenerationStage
from src.extraction_v2.stages.chart_fact_bridge import ChartFactBridgeStage
from src.extraction_v2.stages.deduplication import DeduplicationStage
from src.extraction_v2.stages.definition_extraction import DefinitionExtractionStage
from src.extraction_v2.stages.fact_construction import FactConstructionStage
from src.extraction_v2.stages.false_positive_filter import FalsePositiveFilterStage
from src.extraction_v2.stages.image_triage import ImageTriageStage
from src.extraction_v2.stages.ingestion import IngestionStage
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.extraction_v2.stages.period_inference import PeriodInferenceStage
from src.extraction_v2.stages.section_classification import SectionClassificationStage
from src.extraction_v2.stages.table_reconstruction import TableReconstructionStage
from src.extraction_v2.stages.validation import ValidationStage
from src.extraction_v2.stages.value_binding import ValueBindingStage

logger = logging.getLogger(__name__)

# Document type constants
DOC_TYPE_SEC_FILING = "sec_filing"
DOC_TYPE_TRANSCRIPT = "transcript"
DOC_TYPE_PRESENTATION = "investor_presentation"


class PipelineStage(str, Enum):
    """Pipeline stage identifiers for tracking and logging."""

    INGESTION = "ingestion"
    SECTION_CLASSIFICATION = "section_classification"
    TABLE_RECONSTRUCTION = "table_reconstruction"
    IMAGE_TRIAGE = "image_triage"
    OCR_CHART_EXTRACTION = "ocr_chart_extraction"
    CHART_FACT_BRIDGE = "chart_fact_bridge"
    CANDIDATE_GENERATION = "candidate_generation"
    VALUE_BINDING = "value_binding"
    FALSE_POSITIVE_FILTER = "false_positive_filter"
    PERIOD_INFERENCE = "period_inference"
    FACT_CONSTRUCTION = "fact_construction"
    DEFINITION_EXTRACTION = "definition_extraction"
    DEDUPLICATION = "deduplication"
    VALIDATION = "validation"


@dataclass
class PipelineConfig:
    """Configuration for V2 extraction pipeline."""

    # Stage toggles
    enable_section_classification: bool = True
    enable_image_extraction: bool = True
    enable_chart_extraction: bool = True

    # Quality thresholds
    min_confidence_auto_accept: float = 0.90  # Auto-accept above this
    min_confidence_no_review: float = 0.85  # Flag for review below this
    max_confidence_auto_reject: float = 0.15  # Auto-reject below this

    # Table reconstruction
    max_table_rows: int = 1000  # Skip very large tables
    max_table_cols: int = 100

    # Image processing
    min_image_relevance: float = 0.30  # Process images above this relevance
    max_images_per_document: int = 50  # Limit OCR/vision calls

    # Performance
    batch_size: int = 10  # Segments per batch for LLM calls
    max_llm_calls_per_document: int = 100  # Cost control

    # Deduplication
    value_tolerance: float = 0.02  # 2% tolerance for duplicate detection

    # Output
    save_evidence_screenshots: bool = True
    evidence_screenshot_dir: str = "evidence_v2/"

    # Document type
    document_type: str = DOC_TYPE_SEC_FILING
    text_proximity_chars: int = 100
    relaxed_fp_filter: bool = False
    min_paragraph_chars: int = 50

    # Diagnostics
    retain_context: bool = False  # If True, attach PipelineContext to PipelineResult

    # Fiscal year configuration (for non-calendar fiscal years)
    fiscal_year_end_month: int | None = None  # e.g., 1 for January FYE
    fiscal_year_end_day: int | None = None  # e.g., 31 for Jan 31 FYE

    # Chart fact bridge
    enable_chart_fact_bridge: bool = True
    chart_metric_classification_min_score: float = 0.6
    chart_image_min_confidence: float = 0.6
    chart_fact_review_threshold: float = 0.80
    chart_axis_range_multiplier: float = 10.0

    @classmethod
    def for_transcript(cls, **overrides) -> PipelineConfig:
        """Create a config tuned for earnings call transcripts."""
        defaults = {
            "document_type": DOC_TYPE_TRANSCRIPT,
            "enable_image_extraction": False,
            "enable_chart_extraction": False,
            "enable_chart_fact_bridge": False,  # no chart data to bridge without chart extraction
            "text_proximity_chars": 400,
            "relaxed_fp_filter": True,
            "min_paragraph_chars": 30,
        }
        defaults.update(overrides)
        return cls(**defaults)

    @classmethod
    def for_presentation(cls, **overrides) -> PipelineConfig:
        """Create a config tuned for investor presentation PDFs."""
        defaults = {
            "document_type": DOC_TYPE_PRESENTATION,
            "relaxed_fp_filter": True,
            "min_paragraph_chars": 20,
            "enable_image_extraction": True,
            "enable_chart_extraction": True,
            "text_proximity_chars": 150,
        }
        defaults.update(overrides)
        return cls(**defaults)


@dataclass
class StageResult:
    """Result from a pipeline stage."""

    stage: PipelineStage
    success: bool
    duration_ms: int
    items_processed: int
    items_output: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Result from full pipeline execution."""

    document: Document
    facts: list[MetricFact]
    tables: list[Table]
    images: list[ImageAsset]
    segments: list[Segment]
    stage_results: list[StageResult]
    total_duration_ms: int
    success: bool
    definitions: list[MetricDefinition] = field(default_factory=list)
    error_message: str | None = None
    context: Any | None = None  # PipelineContext — only set when retain_context=True

    @property
    def fact_count(self) -> int:
        """Number of extracted facts."""
        return len(self.facts)

    @property
    def pending_review_count(self) -> int:
        """Number of facts requiring review."""
        return sum(1 for f in self.facts if f.requires_review)

    @property
    def auto_accepted_count(self) -> int:
        """Number of facts auto-accepted."""
        return sum(1 for f in self.facts if not f.requires_review)

    @property
    def has_stub_warnings(self) -> bool:
        """
        Check if any stages produced stub/not-implemented warnings.

        Returns True if the pipeline ran through stub stages that
        don't actually do any processing.
        """
        return any(
            any("not yet implemented" in w.lower() for w in result.warnings)
            for result in self.stage_results
        )

    @property
    def stub_stage_warnings(self) -> list[str]:
        """
        Get list of stub/not-implemented warnings from all stages.

        Useful for logging and debugging when the pipeline reports
        success but stages were actually stubs.
        """
        warnings = []
        for result in self.stage_results:
            for w in result.warnings:
                if "not yet implemented" in w.lower():
                    warnings.append(f"{result.stage.value}: {w}")
        return warnings


class StageProcessor(Protocol):
    """Protocol for pipeline stage processors."""

    def process(self, context: PipelineContext) -> StageResult:
        """Process the stage and return result."""
        ...


@dataclass
class PipelineContext:
    """
    Mutable context passed between pipeline stages.

    Each stage reads from and writes to this context.
    """

    # Input
    html_path: Path
    filing_id: int
    config: PipelineConfig

    # Document metadata
    document_type: str = DOC_TYPE_SEC_FILING
    document_date: date | None = None

    # Document (populated by Stage 1)
    document: Document | None = None

    # Content (populated by various stages)
    segments: list[Segment] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)

    # Extraction results
    candidates: list[MetricCandidate] = field(default_factory=list)
    bound_values: list[BoundValue] = field(default_factory=list)
    facts: list[MetricFact] = field(default_factory=list)
    deduplicated_facts: list[MetricFact] | None = None  # Populated by Stage 10; None = not yet run
    definitions: list[MetricDefinition] = field(default_factory=list)

    # Diagnostics (only populated when config.retain_context=True)
    _pre_filter_bound_values: list[BoundValue] = field(default_factory=list)  # Before FP filter

    # SEC filing info (for image downloading)
    cik: str = ""
    accession_number: str = ""

    # Tracking
    stage_results: list[StageResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Counters
    llm_calls: int = 0
    ocr_calls: int = 0
    vision_calls: int = 0

    @cached_property
    def segment_by_id(self) -> dict[str, Segment]:
        return {s.segment_id: s for s in self.segments}

    @cached_property
    def table_by_id(self) -> dict[str, Table]:
        return {t.table_id: t for t in self.tables}

    @cached_property
    def image_by_id(self) -> dict[str, ImageAsset]:
        return {img.img_id: img for img in self.images}


class V2Pipeline:
    """
    V2 Extraction Pipeline Orchestrator.

    Coordinates the 12-stage extraction process for a single filing.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        sec_client: Any | None = None,
    ) -> None:
        """Initialize pipeline with configuration.

        Args:
            config: Pipeline configuration
            sec_client: Optional SECClient instance for image downloading
        """
        self.config = dataclasses.replace(config) if config is not None else PipelineConfig()
        self._sec_client = sec_client
        self._stages: list[tuple[PipelineStage, StageProcessor]] = []
        self._setup_stages()

    def _check_vision_api_availability(self) -> None:
        """Check if OPENAI_API_KEY is set; disable image/chart extraction if not."""
        if self.config.enable_chart_extraction and not os.environ.get("OPENAI_API_KEY", "").strip():
            logger.warning(
                "OPENAI_API_KEY is not set. Disabling image and chart extraction "
                "(Stages 4 and 5). Text extraction will proceed normally."
            )
            self.config.enable_image_extraction = False
            self.config.enable_chart_extraction = False

    def _setup_stages(self) -> None:
        """Initialize pipeline stages."""
        self._check_vision_api_availability()
        # Stage 1: Ingestion & Parsing
        self._stages.append((PipelineStage.INGESTION, IngestionStage(
            min_paragraph_chars=self.config.min_paragraph_chars,
        )))

        # Stage 2: Section Classification
        if self.config.enable_section_classification:
            self._stages.append(
                (PipelineStage.SECTION_CLASSIFICATION, SectionClassificationStage())
            )

        # Stage 3: Table Reconstruction
        self._stages.append((PipelineStage.TABLE_RECONSTRUCTION, TableReconstructionStage()))

        # Stage 4: Image Triage
        if self.config.enable_image_extraction:
            self._stages.append((PipelineStage.IMAGE_TRIAGE, ImageTriageStage()))

        # Stage 5: OCR & Chart Extraction
        if self.config.enable_chart_extraction:
            self._stages.append(
                (
                    PipelineStage.OCR_CHART_EXTRACTION,
                    OCRExtractionStage(sec_client=self._sec_client),
                )
            )

        # Stage 5.5: Chart Fact Bridge
        if self.config.enable_chart_fact_bridge:
            self._stages.append(
                (PipelineStage.CHART_FACT_BRIDGE, ChartFactBridgeStage())
            )

        # Stage 6: Metric Candidate Generation
        self._stages.append((PipelineStage.CANDIDATE_GENERATION, CandidateGenerationStage()))

        # Stage 7: Value Binding
        self._stages.append((PipelineStage.VALUE_BINDING, ValueBindingStage()))

        # Stage 7.5: False Positive Filter
        self._stages.append((PipelineStage.FALSE_POSITIVE_FILTER, FalsePositiveFilterStage()))

        # Stage 8: Period Inference
        self._stages.append((PipelineStage.PERIOD_INFERENCE, PeriodInferenceStage()))

        # Stage 9: MetricFact Construction
        self._stages.append((PipelineStage.FACT_CONSTRUCTION, FactConstructionStage()))

        # Stage 9.5: Definition Extraction
        self._stages.append((PipelineStage.DEFINITION_EXTRACTION, DefinitionExtractionStage()))

        # Stage 10: Deduplication
        self._stages.append((PipelineStage.DEDUPLICATION, DeduplicationStage()))

        # Stage 11: Validation & Review Routing
        self._stages.append((PipelineStage.VALIDATION, ValidationStage()))

    def process(
        self,
        html_path: Path | str,
        filing_id: int,
        cik: str = "",
        accession_number: str = "",
        document_type: str | None = None,
        document_date: date | None = None,
    ) -> PipelineResult:
        """
        Execute the full extraction pipeline on a filing.

        Args:
            html_path: Path to the HTML filing
            filing_id: Database ID of the filing
            cik: SEC Central Index Key (for image downloading)
            accession_number: SEC accession number (for image downloading)
            document_type: Override document type (defaults to config value)
            document_date: Per-document date for period inference fallback

        Returns:
            PipelineResult with extracted facts and metadata
        """
        html_path = Path(html_path)
        start_time = datetime.now(UTC)

        # Initialize context
        context = PipelineContext(
            html_path=html_path,
            filing_id=filing_id,
            config=self.config,
            cik=cik,
            accession_number=accession_number,
            document_type=document_type or self.config.document_type,
            document_date=document_date,
        )

        logger.info(f"Starting V2 pipeline for filing {filing_id}: {html_path.name}")

        # Execute stages
        for stage_id, processor in self._stages:
            try:
                logger.debug(f"Executing stage: {stage_id.value}")
                result = processor.process(context)
                context.stage_results.append(result)

                if not result.success:
                    logger.error(f"Stage {stage_id.value} failed: {result.errors}")
                    # Continue with remaining stages unless critical failure
                    if stage_id in {
                        PipelineStage.INGESTION,
                        PipelineStage.TABLE_RECONSTRUCTION,
                        PipelineStage.CANDIDATE_GENERATION,
                        PipelineStage.VALUE_BINDING,
                    }:
                        return self._build_failure_result(
                            context,
                            start_time,
                            f"Critical stage failed: {stage_id.value}",
                        )

            except V2TransientError:
                # Propagate transient errors (network/API timeouts) for caller retry
                raise
            except V2FatalError as e:
                logger.error(f"Fatal error in stage {stage_id.value}: {e}")
                context.stage_results.append(
                    StageResult(
                        stage=stage_id,
                        success=False,
                        duration_ms=0,
                        items_processed=0,
                        items_output=0,
                        errors=[str(e)],
                    )
                )
                if stage_id in {
                    PipelineStage.INGESTION,
                    PipelineStage.TABLE_RECONSTRUCTION,
                    PipelineStage.CANDIDATE_GENERATION,
                    PipelineStage.VALUE_BINDING,
                }:
                    return self._build_failure_result(
                        context,
                        start_time,
                        f"Critical stage fatal error: {stage_id.value}: {e}",
                    )
            except Exception as e:
                logger.exception(f"Unhandled exception in stage {stage_id.value}: {e}")
                context.stage_results.append(
                    StageResult(
                        stage=stage_id,
                        success=False,
                        duration_ms=0,
                        items_processed=0,
                        items_output=0,
                        errors=[str(e)],
                    )
                )

        # Build result
        end_time = datetime.now(UTC)
        total_ms = int((end_time - start_time).total_seconds() * 1000)

        # Use deduplicated facts if available (Stage 10 output), else raw facts
        output_facts = (
            context.deduplicated_facts if context.deduplicated_facts is not None else context.facts
        )

        logger.info(
            f"V2 pipeline complete for filing {filing_id}: "
            f"{len(output_facts)} facts ({len(context.facts)} pre-dedup) "
            f"extracted in {total_ms}ms"
        )

        return PipelineResult(
            document=context.document or Document(),
            facts=output_facts,
            tables=context.tables,
            images=context.images,
            segments=context.segments,
            stage_results=context.stage_results,
            total_duration_ms=total_ms,
            success=True,
            definitions=context.definitions,
            context=context if self.config.retain_context else None,
        )

    def _build_failure_result(
        self,
        context: PipelineContext,
        start_time: datetime,
        error_message: str,
    ) -> PipelineResult:
        """Build a failure result."""
        end_time = datetime.now(UTC)
        total_ms = int((end_time - start_time).total_seconds() * 1000)

        return PipelineResult(
            document=context.document or Document(),
            facts=[],
            tables=context.tables,
            images=context.images,
            segments=context.segments,
            stage_results=context.stage_results,
            total_duration_ms=total_ms,
            success=False,
            definitions=[],
            error_message=error_message,
        )


# ============================================================================
# Convenience functions
# ============================================================================


def process_filing(
    html_path: Path | str,
    filing_id: int,
    config: PipelineConfig | None = None,
    cik: str = "",
    accession_number: str = "",
    document_type: str | None = None,
    document_date: date | None = None,
) -> PipelineResult:
    """
    Process a single filing through the V2 pipeline.

    This is the main entry point for extraction.

    Args:
        html_path: Path to the HTML filing
        filing_id: Database ID of the filing
        config: Optional pipeline configuration
        cik: SEC Central Index Key (for image downloading)
        accession_number: SEC accession number (for image downloading)
        document_type: Override document type (defaults to config value)
        document_date: Per-document date for period inference fallback

    Returns:
        PipelineResult with extracted facts and metadata
    """
    pipeline = V2Pipeline(config=config)
    return pipeline.process(
        html_path,
        filing_id,
        cik=cik,
        accession_number=accession_number,
        document_type=document_type,
        document_date=document_date,
    )
