"""
Unit tests for QualityScorer.

Ensures basic scoring works and segments without candidate metrics are ignored.
"""

from decimal import Decimal

from src.extraction.models import MetricValue, SourceSegment
from src.extraction.quality_scorer import QualityScorer


def test_quality_scorer_counts_metric_with_values():
    """A metric with numeric disclosures should be marked as disclosed."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We had 1,500 DAUs.",
            candidate_metric_ids=["cm_daily_active_users"],
            contains_numeric_disclosure_flag=True,
            sequence_index=0,
        ),
        # Segment without candidate ids should be ignored safely
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="General discussion.",
            candidate_metric_ids=None,
            sequence_index=1,
        ),
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_daily_active_users",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("1500"),
        )
    ]

    scorer = QualityScorer()
    incidences = scorer.score_filing(1, 1, segments, values, definitions=[])

    assert len(incidences) == 1
    incidence = incidences[0]
    assert incidence.metric_id == "cm_daily_active_users"
    assert incidence.metric_disclosed_flag is True
    assert incidence.num_numeric_segments == 1
