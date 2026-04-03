"""
V2 Fact Construction Stage

Stage 9 of the V2 extraction pipeline. Transforms BoundValue objects (with period
information from Stage 8) into complete MetricFact objects with confidence scores
and evidence packs.

Design principles:
- Rule-based only (no LLM calls)
- Every fact must have complete provenance (source_locator)
- Every fact must have audit-grade evidence (evidence_pack)
- Confidence scoring combines binding quality, section context, and source type
- Conservative approach: flag all for review initially (Stage 11 will adjust)
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import (
    BoundValue,
    EvidencePack,
    ExtractionMethod,
    ImageAsset,
    MetricFact,
    ReviewStatus,
    SectionType,
    SourceType,
)

if TYPE_CHECKING:
    from src.extraction_v2.models import MetricCandidate, Segment, Table
    from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, StageResult

logger = logging.getLogger(__name__)


# Cohort classification patterns (ported from V1 value_extractor.py)
_ACQUISITION_COHORT_PATTERN = r"(\d{4})\s+[Cc]ohort"
_TENURE_COHORT_PATTERNS = [
    (r"(\d+)\s*-\s*(\d+)\s+(?:months?|mos?)", "months"),
    (r"(\d+)\s*-\s*(\d+)\s+years?", "years"),
    (r"(\d+)\+\s+years?", "years_plus"),
    (r"<\s*(\d+)\s+(?:months?|years?)", "less_than"),
]
_ACQUISITION_COHORT_RE = re.compile(_ACQUISITION_COHORT_PATTERN)


# Confidence adjustment constants
MDA_SECTION_BONUS: float = 0.10
BUSINESS_SECTION_BONUS: float = 0.05
OCR_TABLE_PENALTY: float = 0.10
CHART_PENALTY: float = 0.05
PERIOD_AMBIGUITY_PENALTY: float = 0.15
PERIOD_CONFIDENCE_WEIGHT: float = 0.2
BINDING_CONFIDENCE_WEIGHT: float = 0.8


def parse_cohort_label(raw_label: str) -> tuple[str | None, str | None]:
    """Parse cohort label into (cohort_type, cohort_bucket_normalized).

    Returns:
        (cohort_type, cohort_bucket_normalized) where cohort_type is
        'acquisition', 'tenure', 'other', or None.

    Examples:
        "2021 Cohort" -> ("acquisition", "2021")
        "0-12 months" -> ("tenure", "0-1y")
        "2+ years"    -> ("tenure", "2y+")
    """
    if not raw_label:
        return None, None

    match = _ACQUISITION_COHORT_RE.search(raw_label)
    if match:
        year = match.group(1)
        return "acquisition", year

    for pattern, cohort_subtype in _TENURE_COHORT_PATTERNS:
        match = re.search(pattern, raw_label, re.IGNORECASE)
        if match:
            if cohort_subtype == "months":
                start, end = match.groups()
                start_years = int(start) // 12
                end_years = int(end) // 12
                return "tenure", f"{start_years}-{end_years}y"
            elif cohort_subtype == "years":
                start, end = match.groups()
                return "tenure", f"{start}-{end}y"
            elif cohort_subtype == "years_plus":
                years = match.group(1)
                return "tenure", f"{years}y+"
            elif cohort_subtype == "less_than":
                value = match.group(1)
                if "month" in raw_label.lower():
                    years = int(value) // 12
                    return "tenure", f"<{years}y"
                else:
                    return "tenure", f"<{value}y"

    return "other", raw_label


class FactConstructionStage:
    """
    Stage 9: Fact Construction.

    Transforms BoundValue objects into complete MetricFact objects with:
    - Confidence scoring based on binding quality, section type, and source type
    - EvidencePack generation for audit/review
    - Source type determination from SourceLocator
    - Complete provenance chain from candidate through value to fact
    """

    def __init__(self) -> None:
        """Initialize the fact construction stage."""
        pass

    def process(self, context: PipelineContext) -> StageResult:
        """
        Process all bound values and transform them into facts.

        Args:
            context: Pipeline context with bound_values populated

        Returns:
            StageResult with success status and metrics
        """
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        try:
            start_time = datetime.now(UTC)
            errors: list[str] = []
            warnings: list[str] = []

            # Build lookup dicts for O(1) access
            candidate_lookup: dict[str, MetricCandidate] = {
                c.candidate_id: c for c in context.candidates
            }
            segment_lookup: dict[str, Segment] = {s.segment_id: s for s in context.segments}
            table_lookup: dict[str, Table] = {t.table_id: t for t in context.tables}
            image_lookup: dict[str, ImageAsset] = {img.img_id: img for img in context.images}

            # Process each bound value
            for bv in context.bound_values:
                try:
                    fact = self._construct_fact(
                        bv, candidate_lookup, segment_lookup, table_lookup, image_lookup, context
                    )
                    context.facts.append(fact)
                except Exception as e:
                    error_msg = f"Error constructing fact for {bv.bound_value_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Build stage result
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            return StageResult(
                stage=PipelineStage.FACT_CONSTRUCTION,
                success=len(errors) == 0,
                duration_ms=duration_ms,
                items_processed=len(context.bound_values),
                items_output=len(context.facts),
                errors=errors,
                warnings=warnings,
                metadata={
                    "avg_confidence": self._compute_avg_confidence(context.facts),
                    "facts_by_source_type": self._count_by_source_type(context.facts),
                },
            )
        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="fact_construction") from e

    def _construct_fact(
        self,
        bv: BoundValue,
        candidate_lookup: dict[str, MetricCandidate],
        segment_lookup: dict[str, Segment],
        table_lookup: dict[str, Table],
        image_lookup: dict[str, ImageAsset],
        context: PipelineContext,
    ) -> MetricFact:
        """
        Construct a complete MetricFact from a BoundValue.

        Args:
            bv: BoundValue to transform
            candidate_lookup: Dict of candidate_id -> MetricCandidate
            segment_lookup: Dict of segment_id -> Segment
            table_lookup: Dict of table_id -> Table
            context: Pipeline context

        Returns:
            Complete MetricFact object
        """
        # Look up candidate for metric_id and section_type
        candidate = candidate_lookup.get(bv.candidate_id)
        metric_id = candidate.metric_id if candidate else ""

        if not candidate:
            logger.warning(f"No candidate found for bound_value_id {bv.bound_value_id}")

        # Determine source type from source locator
        source_type = self._determine_source_type(bv)

        # Compute confidence score
        confidence = self._compute_confidence(bv, candidate, source_type)

        # Generate evidence pack
        evidence = self._generate_evidence(
            bv, segment_lookup, table_lookup, image_lookup, context.config
        )

        # Build the fact
        fact = MetricFact(
            doc_id=context.document.doc_id if context.document else "",
            canonical_metric_id=metric_id,
            value=bv.value,
            value_raw=bv.value_raw,
            unit=bv.unit,
            period_type=bv.period_type,
            period_start=bv.period_start,
            period_end=bv.period_end,
            source_type=source_type,
            source_locator=bv.source_locator,
            evidence_pack=evidence,
            confidence=confidence,
            extraction_method=ExtractionMethod.EXACT_MATCH,
            requires_review=True,
            review_status=ReviewStatus.PENDING_REVIEW,
        )
        if fact.cohort_def is not None:
            fact.cohort_type, _ = parse_cohort_label(fact.cohort_def)
        return fact

    def _determine_source_type(self, bv: BoundValue) -> SourceType:
        """
        Determine source type from SourceLocator.

        Logic:
        - Has table_id and no img_id → HTML_TABLE
        - Has table_id and img_id → OCR_TABLE
        - Has img_id and no table_id → CHART
        - Otherwise → TEXT

        Args:
            bv: BoundValue with source_locator

        Returns:
            SourceType enum value
        """
        loc = bv.source_locator

        if loc.table_id and not loc.img_id:
            return SourceType.HTML_TABLE
        elif loc.table_id and loc.img_id:
            return SourceType.OCR_TABLE
        elif loc.img_id and not loc.table_id:
            return SourceType.CHART
        else:
            return SourceType.TEXT

    def _compute_confidence(
        self,
        bv: BoundValue,
        candidate: MetricCandidate | None,
        source_type: SourceType,
    ) -> float:
        """
        Compute confidence score for the fact.

        Formula:
        1. Start with binding_confidence from BoundValue
        2. Add section bonuses (MDA +0.1, BUSINESS +0.05)
        3. Subtract source penalties (OCR_TABLE -0.1, CHART -0.05)
        4. Blend with period confidence (80% binding, 20% period)
        5. Subtract period ambiguity penalty (-0.15)
        6. Clamp to [0, 1]

        Args:
            bv: BoundValue with confidence and period info
            candidate: MetricCandidate with section_type (may be None)
            source_type: Type of source (table, text, chart)

        Returns:
            Confidence score in [0.0, 1.0]
        """
        confidence = bv.binding_confidence

        # Section bonuses (requires candidate)
        if candidate:
            if candidate.section_type == SectionType.MDA:
                confidence += MDA_SECTION_BONUS
            elif candidate.section_type == SectionType.BUSINESS:
                confidence += BUSINESS_SECTION_BONUS

        # Source type penalties
        if source_type == SourceType.OCR_TABLE:
            confidence -= OCR_TABLE_PENALTY
        elif source_type == SourceType.CHART:
            confidence -= CHART_PENALTY

        # Blend with period confidence (weighted average)
        confidence = (
            confidence * BINDING_CONFIDENCE_WEIGHT + bv.period_confidence * PERIOD_CONFIDENCE_WEIGHT
        )

        # Period ambiguity penalty
        if bv.period_ambiguous:
            confidence -= PERIOD_AMBIGUITY_PENALTY

        # Clamp to valid range
        return max(0.0, min(1.0, confidence))

    def _generate_evidence(
        self,
        bv: BoundValue,
        segment_lookup: dict[str, Segment],
        table_lookup: dict[str, Table],
        image_lookup: dict[str, ImageAsset],
        config: PipelineConfig,
    ) -> EvidencePack:
        """
        Generate evidence pack for audit/review.

        For table sources:
        - snippet_html: Highlighted table excerpt
        - header_path: Column headers
        - stub_path: Row stubs
        - raw_value_text: Original value

        For text sources:
        - snippet_html: Highlighted text excerpt
        - context_before: 200 chars before value
        - context_after: 200 chars after value
        - raw_value_text: Original value

        For chart sources (future):
        - screenshot_path: Path to chart image (stub)
        - raw_value_text: Original value

        Args:
            bv: BoundValue with source_locator
            segment_lookup: Dict of segment_id -> Segment
            table_lookup: Dict of table_id -> Table

        Returns:
            Complete EvidencePack object
        """
        loc = bv.source_locator

        # Initialize all fields
        header_path: list[str] = []
        stub_path: list[str] = []
        context_before = ""
        context_after = ""
        snippet_html = f"<mark>{bv.value_raw}</mark>"  # Default snippet

        # Table sources: populate header_path and stub_path
        if loc.table_id:
            table = table_lookup.get(loc.table_id)
            if table:
                # Get header path for the column
                if loc.cell_col is not None:
                    header_path = table.get_header_path(loc.cell_col)

                # Get stub path for the row
                if loc.cell_row is not None:
                    stub_path = table.get_stub_path(loc.cell_row)

        # Text sources: populate context_before and context_after
        elif loc.segment_id and not loc.table_id:
            segment = segment_lookup.get(loc.segment_id)
            if segment and loc.text_span:
                start, end = loc.text_span
                text = segment.text

                # Extract 200 chars before and after
                context_before = text[max(0, start - 200) : start].strip()
                context_after = text[end : end + 200].strip()

        # Chart sources: wire screenshot and snippet
        screenshot_path: str | None = None
        if loc.img_id:
            asset = image_lookup.get(loc.img_id)
            if asset is not None:
                # Build snippet from chart title
                chart_title = ""
                if asset.chart_data and asset.chart_data.title:
                    chart_title = asset.chart_data.title
                snippet_html = (
                    f"<figure><figcaption>{chart_title}</figcaption>"
                    f"<mark>{bv.value_raw}</mark></figure>"
                    if chart_title
                    else f"<mark>{bv.value_raw}</mark>"
                )
                # Populate context_before from nearby text
                if asset.nearby_text:
                    context_before = asset.nearby_text[:200].strip()
                # Copy screenshot if configured
                if config.save_evidence_screenshots and asset.file_path:
                    src_path = Path(asset.file_path)
                    if src_path.exists():
                        try:
                            dest_dir = Path(config.evidence_screenshot_dir)
                            dest_dir.mkdir(parents=True, exist_ok=True)
                            ext = src_path.suffix or ".png"
                            dest_name = f"{loc.img_id}_{bv.bound_value_id[:8]}{ext}"
                            dest_path = dest_dir / dest_name
                            shutil.copy2(src_path, dest_path)
                            screenshot_path = str(dest_path)
                        except Exception as copy_err:
                            logger.warning(
                                f"Failed to copy chart screenshot for {loc.img_id}: {copy_err}"
                            )

        return EvidencePack(
            snippet_html=snippet_html,
            header_path=header_path,
            stub_path=stub_path,
            context_before=context_before,
            context_after=context_after,
            raw_value_text=bv.value_raw,
            screenshot_path=screenshot_path,
        )

    def _compute_avg_confidence(self, facts: list[MetricFact]) -> float:
        """Compute average confidence across all facts."""
        if not facts:
            return 0.0
        return sum(f.confidence for f in facts) / len(facts)

    def _count_by_source_type(self, facts: list[MetricFact]) -> dict[str, int]:
        """Count facts by source type."""
        counts: dict[str, int] = {}
        for fact in facts:
            source = fact.source_type.value
            counts[source] = counts.get(source, 0) + 1
        return counts
