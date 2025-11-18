"""
Definition Extractor - Extract metric definitions and methodologies.

This module extracts textual definitions and calculation methodologies
for metrics from classified segments.
"""

import logging
import re
from typing import List, Optional, Set

from .models import SourceSegment, MetricDefinition

logger = logging.getLogger(__name__)


class DefinitionExtractor:
    """
    Extract metric definitions and methodologies from source segments.

    Extracts:
    1. Definition text (what the metric means)
    2. Methodology text (how it's calculated)
    3. Assesses alignment with CMASB canonical definitions
    """

    # Canonical definitions for alignment assessment
    CANONICAL_DEFINITIONS = {
        'cm_new_customers_acquired': {
            'keywords': ['first', 'qualifying', 'economic', 'activity', 'purchase', 'transaction', 'period'],
            'definition': 'Count of unique customers whose first qualifying economic activity with the company occurs in the reporting period.',
        },
        'cm_customers_period_end_by_tenure': {
            'keywords': ['active', 'period', 'end', 'tenure', 'cohort', 'time', 'since'],
            'definition': 'Number of customers active at period end, broken down by tenure cohorts.',
        },
        'cm_revenue_by_cohort': {
            'keywords': ['revenue', 'gaap', 'cohort', 'acquisition', 'tenure', 'period'],
            'definition': 'Recognized GAAP revenue in the period, attributed to customer cohorts.',
        },
        'cm_transactions_by_cohort': {
            'keywords': ['transactions', 'purchase', 'cohort', 'completed'],
            'definition': 'Number of completed purchase transactions in the period, grouped by customer cohort.',
        },
    }

    def __init__(self):
        """Initialize the definition extractor."""
        pass

    def extract_definitions(
        self,
        segments: List[SourceSegment],
        company_id: int
    ) -> List[MetricDefinition]:
        """
        Extract definitions for all metrics found in segments.

        Args:
            segments: List of classified source segments
            company_id: Company ID

        Returns:
            List of MetricDefinition objects
        """
        definitions = []

        # Group segments by metric
        metric_segments = self._group_segments_by_metric(segments)

        # Extract definition for each metric
        for metric_id, metric_segs in metric_segments.items():
            definition = self._extract_metric_definition(metric_id, metric_segs, company_id)
            if definition:
                definitions.append(definition)

        logger.info(f"Extracted {len(definitions)} metric definitions")
        return definitions

    def _group_segments_by_metric(
        self,
        segments: List[SourceSegment]
    ) -> dict:
        """
        Group segments by the metrics they mention.

        Returns:
            Dictionary mapping metric_id -> list of segments
        """
        metric_segments = {}

        for seg in segments:
            for metric_id in (seg.candidate_metric_ids or []):
                if metric_id not in metric_segments:
                    metric_segments[metric_id] = []
                metric_segments[metric_id].append(seg)

        return metric_segments

    def _extract_metric_definition(
        self,
        metric_id: str,
        segments: List[SourceSegment],
        company_id: int
    ) -> Optional[MetricDefinition]:
        """
        Extract definition for a specific metric from its segments.

        Args:
            metric_id: Metric ID
            segments: Segments mentioning this metric
            company_id: Company ID

        Returns:
            MetricDefinition or None
        """
        # Find segments with definitions
        definition_segments = [s for s in segments if s.contains_definition_flag]
        methodology_segments = [s for s in segments if s.contains_methodology_flag]

        if not definition_segments and not methodology_segments:
            return None  # No definition or methodology found

        # Extract and normalize text
        definition_text = None
        definition_segment_id = None
        if definition_segments:
            # Use the first definition segment
            seg = definition_segments[0]
            definition_text = self._normalize_definition_text(seg.raw_text)
            definition_segment_id = seg.sequence_index  # Store sequence_index temporarily

        methodology_text = None
        methodology_segment_id = None
        if methodology_segments:
            # Use the first methodology segment
            seg = methodology_segments[0]
            methodology_text = self._normalize_definition_text(seg.raw_text)
            methodology_segment_id = seg.sequence_index  # Store sequence_index temporarily

        # Assess alignment with canonical definition
        alignment_flag = self.assess_alignment(metric_id, definition_text)

        # Get filing_id from first segment
        filing_id = segments[0].filing_id

        definition = MetricDefinition(
            filing_id=filing_id,
            company_id=company_id,
            metric_id=metric_id,
            definition_text_normalized=definition_text,
            methodology_text_normalized=methodology_text,
            definition_raw_text=definition_segments[0].raw_text if definition_segments else None,
            methodology_raw_text=methodology_segments[0].raw_text if methodology_segments else None,
            definition_segment_id=definition_segment_id,
            methodology_segment_id=methodology_segment_id,
            alignment_flag=alignment_flag,
        )

        return definition

    def _normalize_definition_text(self, text: str) -> str:
        """
        Clean and normalize definition text.

        - Remove excess whitespace
        - Normalize punctuation
        - Truncate to reasonable length
        """
        # Remove excess whitespace
        normalized = re.sub(r'\s+', ' ', text).strip()

        # Truncate if too long (keep first 500 chars)
        if len(normalized) > 500:
            normalized = normalized[:500] + '...'

        return normalized

    def assess_alignment(
        self,
        metric_id: str,
        issuer_definition: Optional[str]
    ) -> str:
        """
        Assess alignment between issuer and CMASB canonical definitions.

        Args:
            metric_id: Metric ID
            issuer_definition: Issuer's definition text

        Returns:
            'aligned', 'partial', 'not_aligned', or 'unknown'
        """
        if not issuer_definition:
            return 'unknown'

        canonical = self.CANONICAL_DEFINITIONS.get(metric_id)
        if not canonical:
            return 'unknown'  # No canonical definition available

        # Simple keyword overlap approach
        issuer_lower = issuer_definition.lower()
        keywords = canonical['keywords']

        # Count how many canonical keywords appear in issuer definition
        matches = sum(1 for kw in keywords if kw in issuer_lower)
        overlap_ratio = matches / len(keywords) if keywords else 0

        # Classify alignment
        if overlap_ratio >= 0.7:
            return 'aligned'
        elif overlap_ratio >= 0.3:
            return 'partial'
        elif overlap_ratio > 0:
            return 'not_aligned'
        else:
            return 'unknown'


# Convenience function
def extract_definitions(segments: List[SourceSegment], company_id: int) -> List[MetricDefinition]:
    """
    Convenience function to extract definitions from segments.

    Args:
        segments: List of classified source segments
        company_id: Company ID

    Returns:
        List of MetricDefinition objects
    """
    extractor = DefinitionExtractor()
    return extractor.extract_definitions(segments, company_id)
