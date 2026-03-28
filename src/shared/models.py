"""
Shared data models used across V2 extraction pipeline and scripts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


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
