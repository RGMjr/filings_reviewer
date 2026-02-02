"""
V2 Extraction Pipeline Orchestrator.

This module orchestrates the 11-stage extraction pipeline:

1. Ingestion & Parsing       → Segments with XPath locators
2. Section Classification    → MD&A, Risk Factors, etc.
3. Table Reconstruction      → header_path, stub_path per cell
4. Image Triage              → chart, table_image, decorative
5. OCR & Chart Extraction    → labeled values only
6. Metric Candidate Generation → YAML taxonomy matching
7. Value Binding             → structural link required
8. Period Inference          → from header_path or context
9. MetricFact Construction   → with evidence_pack
10. Deduplication            → by identity tuple
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
    Document,
    ImageAsset,
    MetricFact,
    Segment,
    Table,
)
from src.extraction_v2.stages.ingestion import IngestionStage
from src.extraction_v2.stages.section_classification import SectionClassificationStage

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
    candidates: list[Any] = field(default_factory=list)  # MetricCandidate
    bound_values: list[Any] = field(default_factory=list)  # BoundValue
    facts: list[MetricFact] = field(default_factory=list)

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

    Coordinates the 11-stage extraction process for a single filing.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        """Initialize pipeline with configuration."""
        self.config = config or PipelineConfig()
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
        self._stages.append(
            (PipelineStage.TABLE_RECONSTRUCTION, TableReconstructionStage())
        )

        # Stage 4: Image Triage
        if self.config.enable_image_extraction:
            self._stages.append((PipelineStage.IMAGE_TRIAGE, ImageTriageStage()))

        # Stage 5: OCR & Chart Extraction
        if self.config.enable_chart_extraction:
            self._stages.append(
                (PipelineStage.OCR_CHART_EXTRACTION, OCRChartExtractionStage())
            )

        # Stage 6: Metric Candidate Generation
        self._stages.append(
            (PipelineStage.CANDIDATE_GENERATION, CandidateGenerationStage())
        )

        # Stage 7: Value Binding
        self._stages.append((PipelineStage.VALUE_BINDING, ValueBindingStage()))

        # Stage 8: Period Inference
        self._stages.append((PipelineStage.PERIOD_INFERENCE, PeriodInferenceStage()))

        # Stage 9: MetricFact Construction
        self._stages.append(
            (PipelineStage.FACT_CONSTRUCTION, FactConstructionStage())
        )

        # Stage 10: Deduplication
        self._stages.append((PipelineStage.DEDUPLICATION, DeduplicationStage()))

        # Stage 11: Validation & Review Routing
        self._stages.append((PipelineStage.VALIDATION, ValidationStage()))

    def process(self, html_path: Path | str, filing_id: int) -> PipelineResult:
        """
        Execute the full extraction pipeline on a filing.

        Args:
            html_path: Path to the HTML filing
            filing_id: Database ID of the filing

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
        )

        logger.info(
            f"Starting V2 pipeline for filing {filing_id}: {html_path.name}"
        )

        # Execute stages
        for stage_id, processor in self._stages:
            try:
                logger.debug(f"Executing stage: {stage_id.value}")
                result = processor.process(context)
                context.stage_results.append(result)

                if not result.success:
                    logger.error(
                        f"Stage {stage_id.value} failed: {result.errors}"
                    )
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

        logger.info(
            f"V2 pipeline complete for filing {filing_id}: "
            f"{len(context.facts)} facts extracted in {total_ms}ms"
        )

        return PipelineResult(
            document=context.document or Document(),
            facts=context.facts,
            tables=context.tables,
            images=context.images,
            segments=context.segments,
            stage_results=context.stage_results,
            total_duration_ms=total_ms,
            success=True,
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
# Stage Implementations (Stubs - to be implemented in separate modules)
# ============================================================================
# Note: IngestionStage and SectionClassificationStage are now imported from src.extraction_v2.stages


class TableReconstructionStage:
    """
    Stage 3: Table Reconstruction.

    - Resolve rowspan/colspan into full grid
    - Identify header rows and stub columns
    - Compute header_path and stub_path for each cell

    Key invariant: After span resolution, every logical cell has
    exactly one (row, col) coordinate. No gaps. No overlaps.
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Reconstruct tables with full structure."""
        start_time = datetime.utcnow()

        # TODO: Implement colspan/rowspan resolution algorithm
        # TODO: Compute header_path for each cell
        # TODO: Compute stub_path for each cell

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.TABLE_RECONSTRUCTION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.segments),
            items_output=len(context.tables),
            metadata={"table_count": len(context.tables)},
        )


class ImageTriageStage:
    """
    Stage 4: Image Triage.

    - Classify: chart, table_image, decorative
    - Score relevance by proximity to metric keywords
    - Queue high-relevance images for OCR/vision
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Classify and score images."""
        start_time = datetime.utcnow()

        # TODO: Implement image classification
        # TODO: Score by keyword proximity
        # TODO: Filter decorative images

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.IMAGE_TRIAGE,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.images),
            items_output=len([i for i in context.images if i.is_relevant()]),
        )


class OCRChartExtractionStage:
    """
    Stage 5: OCR & Chart Extraction.

    - Table images → OCR → Table reconstruction
    - Charts → Title/axis OCR → Extract labeled values only
    - Low-confidence → flag for manual capture

    Constraint: NEVER fabricate chart values by reading axis pixels.
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Extract values from images."""
        start_time = datetime.utcnow()

        # TODO: Implement PaddleOCR integration for table images
        # TODO: Implement Claude Vision for chart extraction
        # TODO: Apply constrained extraction (labeled values only)

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.OCR_CHART_EXTRACTION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len([i for i in context.images if i.is_relevant()]),
            items_output=0,  # Number of values extracted
            metadata={
                "ocr_calls": context.ocr_calls,
                "vision_calls": context.vision_calls,
            },
        )


class CandidateGenerationStage:
    """
    Stage 6: Metric Candidate Generation.

    - Scan all content for metric aliases (from YAML taxonomy)
    - Apply required_signals and negative_signals filters
    - Output: Candidate list with source pointers
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Generate metric candidates."""
        start_time = datetime.utcnow()

        # TODO: Load YAML taxonomy
        # TODO: Scan segments for metric aliases
        # TODO: Apply signal filters

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.CANDIDATE_GENERATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.segments) + len(context.tables),
            items_output=len(context.candidates),
        )


class ValueBindingStage:
    """
    Stage 7: Value Binding.

    - Tables: bind value via header_path + stub_path
    - Text: bind via sentence proximity
    - Charts: bind via axis labels
    - RULE: No binding without structural link
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Bind values to metrics."""
        start_time = datetime.utcnow()

        # TODO: Implement table binding via header_path/stub_path
        # TODO: Implement text binding via proximity
        # TODO: Implement chart binding via axis labels

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.VALUE_BINDING,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.candidates),
            items_output=len(context.bound_values),
        )


class PeriodInferenceStage:
    """
    Stage 8: Period Inference.

    - Extract period from: header_path, stub_path, context
    - Validate against filing fiscal period
    - Flag ambiguous periods for review
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Infer time periods for bound values."""
        start_time = datetime.utcnow()

        # TODO: Implement period extraction from header_path
        # TODO: Implement period extraction from context
        # TODO: Validate against filing fiscal period

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.PERIOD_INFERENCE,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.bound_values),
            items_output=len(context.bound_values),
        )


class FactConstructionStage:
    """
    Stage 9: MetricFact Construction.

    - Assemble full MetricFact record
    - Compute confidence score
    - Generate evidence_pack
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Construct MetricFact objects."""
        start_time = datetime.utcnow()

        # TODO: Create MetricFact from bound values
        # TODO: Compute confidence scores
        # TODO: Generate evidence packs

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.FACT_CONSTRUCTION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.bound_values),
            items_output=len(context.facts),
        )


class DeduplicationStage:
    """
    Stage 10: Deduplication.

    - Group by identity tuple (metric_id, period, value±2%, scope)
    - Select primary by source quality ranking: HTML > OCR > chart
    - Link alternates via alternate_evidence
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Deduplicate extracted facts."""
        start_time = datetime.utcnow()
        initial_count = len(context.facts)

        # TODO: Group facts by identity tuple
        # TODO: Select primary by source quality
        # TODO: Link alternates

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.DEDUPLICATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=initial_count,
            items_output=len(context.facts),
            metadata={"duplicates_removed": initial_count - len(context.facts)},
        )


class ValidationStage:
    """
    Stage 11: Validation & Review Routing.

    - Schema validation
    - Route low-confidence to human review
    - Export accepted facts to production dataset
    """

    def process(self, context: PipelineContext) -> StageResult:
        """Validate and route facts."""
        start_time = datetime.utcnow()

        # Apply review routing based on confidence
        for fact in context.facts:
            if fact.confidence >= context.config.min_confidence_auto_accept:
                fact.requires_review = False
                fact.review_reason = None
            elif fact.confidence < context.config.max_confidence_auto_reject:
                fact.requires_review = True
                fact.review_reason = "Low confidence (auto-reject candidate)"
            else:
                fact.requires_review = True
                if not fact.review_reason:
                    fact.review_reason = "Confidence below auto-accept threshold"

        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        pending_review = sum(1 for f in context.facts if f.requires_review)
        auto_accepted = len(context.facts) - pending_review

        return StageResult(
            stage=PipelineStage.VALIDATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.facts),
            items_output=len(context.facts),
            metadata={
                "pending_review": pending_review,
                "auto_accepted": auto_accepted,
            },
        )


# ============================================================================
# Convenience functions
# ============================================================================


def process_filing(
    html_path: Path | str,
    filing_id: int,
    config: PipelineConfig | None = None,
) -> PipelineResult:
    """
    Process a single filing through the V2 pipeline.

    This is the main entry point for extraction.

    Args:
        html_path: Path to the HTML filing
        filing_id: Database ID of the filing
        config: Optional pipeline configuration

    Returns:
        PipelineResult with extracted facts and metadata
    """
    pipeline = V2Pipeline(config=config)
    return pipeline.process(html_path, filing_id)
