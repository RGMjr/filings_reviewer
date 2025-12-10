"""
Data models for metric extraction pipeline.

These models represent extracted data before it's written to the database.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional
from decimal import Decimal


@dataclass
class SourceSegment:
    """
    Represents a segment of a filing (paragraph, table, footnote, etc.).

    Corresponds to the source_segments database table.
    """

    # Foreign key
    filing_id: int

    # Segment metadata
    segment_type: str  # 'paragraph', 'table', 'footnote', 'definition_block', 'methodology_block', 'other'
    section_path: Optional[str] = None  # e.g., "Item 1. Business > Customers"
    section_heading: Optional[str] = None
    sequence_index: int = 0  # Order within filing (0-based)

    # Location / provenance
    html_selector: Optional[str] = None  # XPath or CSS selector
    char_start_offset: Optional[int] = None
    char_end_offset: Optional[int] = None
    page_number: Optional[int] = None

    # Content
    raw_text: str = ""  # Normalized visible text
    raw_html: Optional[str] = None  # Original HTML snippet

    # LLM / classification metadata (populated by classifier)
    candidate_metric_ids: List[str] = field(default_factory=list)
    contains_definition_flag: bool = False
    contains_methodology_flag: bool = False
    contains_numeric_disclosure_flag: bool = False
    classifier_confidence: Optional[float] = None

    # Database fields (populated after insert)
    source_segment_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
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
    value_numeric: Optional[Decimal] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None  # Canonical: '%', 'usd', 'count'; Also: 'basis_points', 'per_customer'
    currency: Optional[str] = None  # ISO code when monetary

    # Time dimensions
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    period_type: Optional[str] = (
        None  # 'fy', 'quarter', 'month', 'ttm', 'since_inception'
    )

    # Cohort dimensions
    cohort_type: Optional[str] = None  # 'acquisition', 'tenure', 'other'
    cohort_bucket_raw: Optional[str] = None  # Issuer's label
    cohort_bucket_normalized: Optional[str] = None  # Standardized bucket

    # Customer segmentation dimensions
    segment_dimension: Optional[str] = (
        None  # e.g., 'customer_type', 'product', 'geography'
    )
    segment_value: Optional[str] = None  # e.g., 'enterprise', 'SMB', 'US'

    # Quality / alignment
    qa_status: str = "unreviewed"  # 'unreviewed', 'pass', 'warning', 'fail'
    qa_notes: Optional[str] = None
    alignment_flag: Optional[str] = (
        None  # 'aligned', 'partial', 'not_aligned', 'unknown'
    )

    # Database fields
    metric_value_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
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
    definition_text_normalized: Optional[str] = None
    methodology_text_normalized: Optional[str] = None
    definition_raw_text: Optional[str] = None
    methodology_raw_text: Optional[str] = None

    # Provenance
    definition_segment_id: Optional[int] = None
    methodology_segment_id: Optional[int] = None

    # Alignment
    alignment_flag: Optional[str] = (
        None  # 'aligned', 'partial', 'not_aligned', 'unknown'
    )
    alignment_notes: Optional[str] = None

    # Database fields
    metric_definition_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
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
    primary_definition_segment_id: Optional[int] = None
    primary_methodology_segment_id: Optional[int] = None

    # Quality scores (0-3)
    quality_overall_score: Optional[int] = None
    quality_definition_score: Optional[int] = None
    quality_methodology_score: Optional[int] = None
    quality_completeness_score: Optional[int] = None
    quality_comparability_score: Optional[int] = None

    # Notes and flags
    alignment_flag: Optional[str] = None
    quality_notes: Optional[str] = None
    has_cohort_breakdown_flag: bool = False
    has_tenure_breakdown_flag: bool = False
    has_acquisition_cohort_flag: bool = False

    # Database fields
    filing_metric_incidence_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
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
