"""
Data models for metric extraction pipeline.

These models represent extracted data before it's written to the database.

Note: FilingMetricIncidence has been moved to src.shared.models.
It is re-exported here for backward compatibility.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.shared.models import FilingMetricIncidence as FilingMetricIncidence  # noqa: F401


@dataclass
class SourceSegment:
    """
    Represents a segment of a filing (paragraph, table, footnote, etc.).

    Corresponds to the source_segments database table.
    """

    # Foreign key
    filing_id: int

    # Segment metadata
    segment_type: (
        str  # 'paragraph', 'table', 'footnote', 'definition_block', 'methodology_block', 'other'
    )
    section_path: str | None = None  # e.g., "Item 1. Business > Customers"
    section_heading: str | None = None
    sequence_index: int = 0  # Order within filing (0-based)

    # Location / provenance
    html_selector: str | None = None  # XPath or CSS selector
    char_start_offset: int | None = None
    char_end_offset: int | None = None
    page_number: int | None = None

    # Content
    raw_text: str = ""  # Normalized visible text
    raw_html: str | None = None  # Original HTML snippet

    # LLM / classification metadata (populated by classifier)
    candidate_metric_ids: list[str] = field(default_factory=list)
    contains_definition_flag: bool = False
    contains_methodology_flag: bool = False
    contains_numeric_disclosure_flag: bool = False
    classifier_confidence: float | None = None

    # Context preservation (populated by enhanced segmenter)
    context_prefix: str | None = None  # Last sentence from previous segment
    document_position: float | None = None  # 0.0-1.0 position in document
    sentence_boundaries: list[tuple[int, int]] | None = None  # (start, end) pairs
    table_truncated_flag: bool = False  # True if table was too large and summarized
    definition_merged_count: int = 0  # Number of segments merged for definition

    # Richness metadata (computed post-classification by SegmentEnricher)
    metric_density: float | None = None  # Metrics per 100 characters
    distinct_metric_count: int = 0  # Count of unique metric IDs in segment
    contains_temporal_trend: bool = False  # True if segment discusses multiple time periods
    contains_cohort_breakdown: bool = False  # True if segment contains cohort analysis patterns
    image_count: int = 0  # Count of meaningful images/charts in segment
    richness_score: float | None = None  # Composite score 0-10 (computed by enricher)
    extra_metadata: dict[str, Any] | None = (
        None  # Additional enrichment metadata (e.g., SaaS indicators)
    )

    # Database fields (populated after insert)
    source_segment_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "filing_id": self.filing_id,
            "segment_type": self.segment_type,
            "section_path": self.section_path,
            "section_heading": self.section_heading,
            "sequence_index": self.sequence_index,
            "html_selector": self.html_selector,
            "char_start_offset": self.char_start_offset,
            "char_end_offset": self.char_end_offset,
            "page_number": self.page_number,
            "raw_text": self.raw_text,
            "raw_html": self.raw_html,
            "candidate_metric_ids": self.candidate_metric_ids,
            "contains_definition_flag": self.contains_definition_flag,
            "contains_methodology_flag": self.contains_methodology_flag,
            "contains_numeric_disclosure_flag": self.contains_numeric_disclosure_flag,
            "classifier_confidence": self.classifier_confidence,
            # Context preservation fields (not yet in DB schema)
            "context_prefix": self.context_prefix,
            "document_position": self.document_position,
            "sentence_boundaries": self.sentence_boundaries,
            "table_truncated_flag": self.table_truncated_flag,
            "definition_merged_count": self.definition_merged_count,
            # Richness metadata fields
            "metric_density": self.metric_density,
            "distinct_metric_count": self.distinct_metric_count,
            "contains_temporal_trend": self.contains_temporal_trend,
            "contains_cohort_breakdown": self.contains_cohort_breakdown,
            "image_count": self.image_count,
            "richness_score": self.richness_score,
            "extra_metadata": self.extra_metadata,
        }


@dataclass
class MetricValue:
    """
    Represents an extracted metric value.

    Corresponds to the metric_values database table.
    """

    # Foreign keys
    filing_id: int
    company_id: int
    metric_id: str
    source_segment_id: int

    # Provenance
    source_type: str  # 'table', 'text', 'footnote', 'other'
    extraction_method: str  # 'rule_table', 'llm_table', 'llm_text', 'manual_review'

    # Value
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None  # Canonical: '%', 'usd', 'count'; Also: 'basis_points', 'per_customer'
    currency: str | None = None  # ISO code when monetary

    # Time dimensions
    period_start: date | None = None
    period_end: date | None = None
    period_type: str | None = None  # 'fy', 'quarter', 'month', 'ttm', 'since_inception'

    # Cohort dimensions
    cohort_type: str | None = None  # 'acquisition', 'tenure', 'other'
    cohort_bucket_raw: str | None = None  # Issuer's label
    cohort_bucket_normalized: str | None = None  # Standardized bucket

    # Customer segmentation dimensions
    segment_dimension: str | None = None  # e.g., 'customer_type', 'product', 'geography'
    segment_value: str | None = None  # e.g., 'enterprise', 'SMB', 'US'

    # Quality / alignment
    qa_status: str = "unreviewed"  # 'unreviewed', 'pass', 'warning', 'fail'
    qa_notes: str | None = None
    alignment_flag: str | None = None  # 'aligned', 'partial', 'not_aligned', 'unknown'

    # Database fields
    metric_value_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "filing_id": self.filing_id,
            "company_id": self.company_id,
            "metric_id": self.metric_id,
            "source_segment_id": self.source_segment_id,
            "source_type": self.source_type,
            "extraction_method": self.extraction_method,
            "value_numeric": self.value_numeric,
            "value_text": self.value_text,
            "unit": self.unit,
            "currency": self.currency,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_type": self.period_type,
            "cohort_type": self.cohort_type,
            "cohort_bucket_raw": self.cohort_bucket_raw,
            "cohort_bucket_normalized": self.cohort_bucket_normalized,
            "segment_dimension": self.segment_dimension,
            "segment_value": self.segment_value,
            "qa_status": self.qa_status,
            "qa_notes": self.qa_notes,
            "alignment_flag": self.alignment_flag,
        }


@dataclass
class MetricDefinition:
    """
    Represents an issuer-specific metric definition.

    Corresponds to the metric_definitions database table.
    """

    # Foreign keys
    filing_id: int
    company_id: int
    metric_id: str

    # Version
    definition_version_in_filing: int = 1

    # Content
    definition_text_normalized: str | None = None
    methodology_text_normalized: str | None = None
    definition_raw_text: str | None = None
    methodology_raw_text: str | None = None

    # Provenance
    definition_segment_id: int | None = None
    methodology_segment_id: int | None = None

    # Alignment
    alignment_flag: str | None = None  # 'aligned', 'partial', 'not_aligned', 'unknown'
    alignment_notes: str | None = None

    # Database fields
    metric_definition_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "filing_id": self.filing_id,
            "company_id": self.company_id,
            "metric_id": self.metric_id,
            "definition_version_in_filing": self.definition_version_in_filing,
            "definition_text_normalized": self.definition_text_normalized,
            "methodology_text_normalized": self.methodology_text_normalized,
            "definition_raw_text": self.definition_raw_text,
            "methodology_raw_text": self.methodology_raw_text,
            "definition_segment_id": self.definition_segment_id,
            "methodology_segment_id": self.methodology_segment_id,
            "alignment_flag": self.alignment_flag,
            "alignment_notes": self.alignment_notes,
        }


@dataclass
class FilingMetricIncidence:
    """
    Represents filing x metric incidence and quality scores.

    Corresponds to the filing_metric_incidence database table.
    """

    # Foreign keys
    filing_id: int
    company_id: int
    metric_id: str

    # Incidence
    metric_disclosed_flag: bool
    num_numeric_segments: int = 0
    num_definition_segments: int = 0
    num_methodology_segments: int = 0

    # Primary segments
    primary_definition_segment_id: int | None = None
    primary_methodology_segment_id: int | None = None

    # Quality scores (0-3)
    quality_overall_score: int | None = None
    quality_definition_score: int | None = None
    quality_methodology_score: int | None = None
    quality_completeness_score: int | None = None
    quality_comparability_score: int | None = None

    # Notes and flags
    alignment_flag: str | None = None
    quality_notes: str | None = None
    has_cohort_breakdown_flag: bool = False
    has_tenure_breakdown_flag: bool = False
    has_acquisition_cohort_flag: bool = False

    # Database fields
    filing_metric_incidence_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "filing_id": self.filing_id,
            "company_id": self.company_id,
            "metric_id": self.metric_id,
            "metric_disclosed_flag": self.metric_disclosed_flag,
            "num_numeric_segments": self.num_numeric_segments,
            "num_definition_segments": self.num_definition_segments,
            "num_methodology_segments": self.num_methodology_segments,
            "primary_definition_segment_id": self.primary_definition_segment_id,
            "primary_methodology_segment_id": self.primary_methodology_segment_id,
            "quality_overall_score": self.quality_overall_score,
            "quality_definition_score": self.quality_definition_score,
            "quality_methodology_score": self.quality_methodology_score,
            "quality_completeness_score": self.quality_completeness_score,
            "quality_comparability_score": self.quality_comparability_score,
            "alignment_flag": self.alignment_flag,
            "quality_notes": self.quality_notes,
            "has_cohort_breakdown_flag": self.has_cohort_breakdown_flag,
            "has_tenure_breakdown_flag": self.has_tenure_breakdown_flag,
            "has_acquisition_cohort_flag": self.has_acquisition_cohort_flag,
        }
