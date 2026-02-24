"""
V2 Extraction Pipeline Orchestrator.

This module orchestrates the 12-stage extraction pipeline:

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

Design principles:
- Structure-first, LLM-second
- No value without provenance
- Fail closed (ambiguous → review, don't guess)
- Charts only when labeled (never interpolate from axis)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from src.extraction_v2.models import (
    BoundValue,
    Document,
    ImageAsset,
    MetricCandidate,
    MetricFact,
    Segment,
    Table,
)
from src.extraction_v2.stages.candidate_generation import CandidateGenerationStage
from src.extraction_v2.stages.deduplication import DeduplicationStage
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


class PipelineStage(str, Enum):
    """Pipeline stage identifiers for tracking and logging."""

    INGESTION = "ingestion"
    SECTION_CLASSIFICATION = "section_classification"
    TABLE_RECONSTRUCTION = "table_reconstruction"
    IMAGE_TRIAGE = "image_triage"
    OCR_CHART_EXTRACTION = "ocr_chart_extraction"
    CANDIDATE_GENERATION = "candidate_generation"
    VALUE_BINDING = "value_binding"
    FALSE_POSITIVE_FILTER = "false_positive_filter"
    PERIOD_INFERENCE = "period_inference"
    FACT_CONSTRUCTION = "fact_construction"
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

    # Diagnostics
    retain_context: bool = False  # If True, attach PipelineContext to PipelineResult

    # Fiscal year configuration (for non-calendar fiscal years)
    fiscal_year_end_month: int | None = None  # e.g., 1 for January FYE
    fiscal_year_end_day: int | None = None  # e.g., 31 for Jan 31 FYE


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
    deduplicated_facts: list[MetricFact] = field(default_factory=list)  # After dedup

    # Diagnostics (only populated when config.retain_context=True)
    _pre_filter_bound_values: list[BoundValue] = field(default_factory=list)  # Before FP filter

    # SEC filing info (for image downloading)
    cik: str = ""
    accession_number: str = ""

    # Tracking
    stage_results: list[StageResult] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)

    # Counters
    llm_calls: int = 0
    ocr_calls: int = 0
    vision_calls: int = 0


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
        self.config = config or PipelineConfig()
        self._sec_client = sec_client
        self._stages: list[tuple[PipelineStage, StageProcessor]] = []
        self._setup_stages()

    def _setup_stages(self) -> None:
        """Initialize pipeline stages."""
        # Stage 1: Ingestion & Parsing
        self._stages.append((PipelineStage.INGESTION, IngestionStage()))

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
    ) -> PipelineResult:
        """
        Execute the full extraction pipeline on a filing.

        Args:
            html_path: Path to the HTML filing
            filing_id: Database ID of the filing
            cik: SEC Central Index Key (for image downloading)
            accession_number: SEC accession number (for image downloading)

        Returns:
            PipelineResult with extracted facts and metadata
        """
        html_path = Path(html_path)
        start_time = datetime.utcnow()

        # Initialize context
        context = PipelineContext(
            html_path=html_path,
            filing_id=filing_id,
            config=self.config,
            cik=cik,
            accession_number=accession_number,
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
                    }:
                        return self._build_failure_result(
                            context,
                            start_time,
                            f"Critical stage failed: {stage_id.value}",
                        )

            except Exception as e:
                logger.exception(f"Exception in stage {stage_id.value}: {e}")
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
        end_time = datetime.utcnow()
        total_ms = int((end_time - start_time).total_seconds() * 1000)

        # Use deduplicated facts if available (Stage 10 output), else raw facts
        output_facts = context.deduplicated_facts if context.deduplicated_facts else context.facts

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
            context=context if self.config.retain_context else None,
        )

    def _build_failure_result(
        self,
        context: PipelineContext,
        start_time: datetime,
        error_message: str,
    ) -> PipelineResult:
        """Build a failure result."""
        end_time = datetime.utcnow()
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

    Returns:
        PipelineResult with extracted facts and metadata
    """
    pipeline = V2Pipeline(config=config)
    return pipeline.process(html_path, filing_id, cik=cik, accession_number=accession_number)
