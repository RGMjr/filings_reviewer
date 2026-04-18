"""
Shared data models used across V2 extraction pipeline and scripts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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
    extra_metadata: dict[str, Any] | None = None  # Additional enrichment metadata (e.g., SaaS indicators)

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
