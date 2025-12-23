"""
Quality Scorer - Compute filing-metric incidence and quality scores.

This module aggregates extraction results at the filing × metric level
and computes quality scores across multiple dimensions.
"""

import logging

from .models import (
    FilingMetricIncidence,
    MetricDefinition,
    MetricValue,
    SourceSegment,
)

logger = logging.getLogger(__name__)


class QualityScorer:
    """
    Compute incidence and quality scores for filing × metric pairs.

    Quality scoring dimensions (0-3 scale):
    - Overall: comprehensive disclosure quality
    - Definition: clarity of metric definition
    - Methodology: clarity of calculation method
    - Completeness: level of detail and breakdowns
    - Comparability: alignment with CMASB standards
    """

    def __init__(self):
        """Initialize the quality scorer."""
        pass

    def score_filing(
        self,
        filing_id: int,
        company_id: int,
        segments: list[SourceSegment],
        values: list[MetricValue],
        definitions: list[MetricDefinition],
    ) -> list[FilingMetricIncidence]:
        """
        Compute incidence and quality scores for all metrics in a filing.

        Args:
            filing_id: Filing ID
            company_id: Company ID
            segments: All source segments from filing
            values: All extracted metric values
            definitions: All extracted metric definitions

        Returns:
            List of FilingMetricIncidence objects (one per metric disclosed)
        """
        # Get all metrics mentioned in filing
        all_metrics = self._get_all_metrics(segments, values, definitions)

        incidences = []
        for metric_id in all_metrics:
            incidence = self._score_filing_metric(
                filing_id, company_id, metric_id, segments, values, definitions
            )
            incidences.append(incidence)

        logger.info(f"Scored {len(incidences)} filing-metric pairs")
        return incidences

    def _get_all_metrics(
        self,
        segments: list[SourceSegment],
        values: list[MetricValue],
        definitions: list[MetricDefinition],
    ) -> set:
        """Get set of all metrics mentioned in filing."""
        metrics = set()

        # From segments
        for seg in segments:
            metrics.update(seg.candidate_metric_ids or [])

        # From values
        for val in values:
            metrics.add(val.metric_id)

        # From definitions
        for defn in definitions:
            metrics.add(defn.metric_id)

        return metrics

    def _score_filing_metric(
        self,
        filing_id: int,
        company_id: int,
        metric_id: str,
        segments: list[SourceSegment],
        values: list[MetricValue],
        definitions: list[MetricDefinition],
    ) -> FilingMetricIncidence:
        """
        Compute incidence and quality for a specific filing × metric pair.

        Args:
            filing_id: Filing ID
            company_id: Company ID
            metric_id: Metric ID
            segments: All segments
            values: All values
            definitions: All definitions

        Returns:
            FilingMetricIncidence object
        """
        # Filter to this metric
        metric_segments = [
            s for s in segments if metric_id in (s.candidate_metric_ids or [])
        ]
        metric_values = [v for v in values if v.metric_id == metric_id]
        metric_definitions = [d for d in definitions if d.metric_id == metric_id]

        # Count segments by type
        num_numeric_segments = sum(
            1 for s in metric_segments if s.contains_numeric_disclosure_flag
        )
        num_definition_segments = sum(
            1 for s in metric_segments if s.contains_definition_flag
        )
        num_methodology_segments = sum(
            1 for s in metric_segments if s.contains_methodology_flag
        )

        # Identify primary segments
        primary_definition_segment_id = None
        primary_methodology_segment_id = None

        if metric_definitions:
            defn = metric_definitions[0]
            primary_definition_segment_id = defn.definition_segment_id
            primary_methodology_segment_id = defn.methodology_segment_id

        # Check for cohort breakdowns
        has_cohort_breakdown_flag = any(
            v.cohort_type is not None for v in metric_values
        )
        has_tenure_breakdown_flag = any(
            v.cohort_type == "tenure" for v in metric_values
        )
        has_acquisition_cohort_flag = any(
            v.cohort_type == "acquisition" for v in metric_values
        )

        # Compute quality scores
        quality_overall_score = self._compute_overall_quality(
            metric_values, metric_definitions, has_cohort_breakdown_flag
        )

        quality_definition_score = self._compute_definition_quality(metric_definitions)
        quality_methodology_score = self._compute_methodology_quality(
            metric_definitions
        )
        quality_completeness_score = self._compute_completeness_quality(
            metric_values, has_cohort_breakdown_flag
        )
        quality_comparability_score = self._compute_comparability_quality(
            metric_definitions
        )

        # Alignment flag (from definition)
        alignment_flag = (
            metric_definitions[0].alignment_flag if metric_definitions else None
        )

        # Disclosed if we have any values or definitions
        metric_disclosed_flag = len(metric_values) > 0 or len(metric_definitions) > 0

        incidence = FilingMetricIncidence(
            filing_id=filing_id,
            company_id=company_id,
            metric_id=metric_id,
            metric_disclosed_flag=metric_disclosed_flag,
            num_numeric_segments=num_numeric_segments,
            num_definition_segments=num_definition_segments,
            num_methodology_segments=num_methodology_segments,
            primary_definition_segment_id=primary_definition_segment_id,
            primary_methodology_segment_id=primary_methodology_segment_id,
            quality_overall_score=quality_overall_score,
            quality_definition_score=quality_definition_score,
            quality_methodology_score=quality_methodology_score,
            quality_completeness_score=quality_completeness_score,
            quality_comparability_score=quality_comparability_score,
            alignment_flag=alignment_flag,
            has_cohort_breakdown_flag=has_cohort_breakdown_flag,
            has_tenure_breakdown_flag=has_tenure_breakdown_flag,
            has_acquisition_cohort_flag=has_acquisition_cohort_flag,
        )

        return incidence

    def _compute_overall_quality(
        self,
        values: list[MetricValue],
        definitions: list[MetricDefinition],
        has_cohort_breakdown: bool,
    ) -> int:
        """
        Compute overall quality score (0-3).

        Scoring rubric:
        - 0: Not disclosed
        - 1: Minimal (value only, no definition)
        - 2: Moderate (value + definition OR methodology)
        - 3: Excellent (value + definition + methodology + cohort breakdown)
        """
        if not values and not definitions:
            return 0

        if not values:
            return 1  # Definition only, no values

        has_definition = any(d.definition_text_normalized for d in definitions)
        has_methodology = any(d.methodology_text_normalized for d in definitions)

        if has_definition and has_methodology and has_cohort_breakdown:
            return 3  # Excellent
        elif has_definition or has_methodology:
            return 2  # Moderate
        else:
            return 1  # Minimal

    def _compute_definition_quality(self, definitions: list[MetricDefinition]) -> int:
        """
        Compute definition quality score (0-3).

        Scoring rubric:
        - 0: No definition
        - 1: Vague or incomplete
        - 2: Clear, mostly aligned
        - 3: Comprehensive, fully aligned
        """
        if not definitions:
            return 0

        defn = definitions[0]
        if not defn.definition_text_normalized:
            return 0

        # Check alignment
        if defn.alignment_flag == "aligned":
            # Check length/completeness
            if len(defn.definition_text_normalized) > 100:
                return 3  # Comprehensive and aligned
            else:
                return 2  # Aligned but brief
        elif defn.alignment_flag == "partial":
            return 2  # Clear but not fully aligned
        else:
            return 1  # Vague or not aligned

    def _compute_methodology_quality(self, definitions: list[MetricDefinition]) -> int:
        """
        Compute methodology quality score (0-3).

        Scoring rubric:
        - 0: No methodology
        - 1: Vague calculation description
        - 2: Clear calculation method
        - 3: Detailed formula with examples
        """
        if not definitions:
            return 0

        defn = definitions[0]
        if not defn.methodology_text_normalized:
            return 0

        # Simple heuristic based on length and keywords
        methodology = defn.methodology_text_normalized.lower()

        # Look for calculation keywords
        has_formula_keywords = any(
            kw in methodology for kw in ["formula", "divided by", "equals", "="]
        )
        has_example = any(
            kw in methodology for kw in ["example", "for instance", "such as"]
        )

        if has_formula_keywords and has_example:
            return 3
        elif has_formula_keywords or len(methodology) > 150:
            return 2
        else:
            return 1

    def _compute_completeness_quality(
        self, values: list[MetricValue], has_cohort_breakdown: bool
    ) -> int:
        """
        Compute completeness quality score (0-3).

        Scoring rubric:
        - 0: Not disclosed
        - 1: Single aggregate number
        - 2: Breakdowns by period OR cohort
        - 3: Breakdowns by both period AND cohort
        """
        if not values:
            return 0

        # Check for period variations
        periods = set(v.period_end for v in values if v.period_end)
        has_period_breakdown = len(periods) > 1

        if has_period_breakdown and has_cohort_breakdown:
            return 3
        elif has_period_breakdown or has_cohort_breakdown:
            return 2
        else:
            return 1

    def _compute_comparability_quality(
        self, definitions: list[MetricDefinition]
    ) -> int:
        """
        Compute comparability quality score (0-3).

        Based on alignment with CMASB canonical definitions:
        - 0: Not disclosed
        - 1: Definition differs significantly
        - 2: Definition partially aligned
        - 3: Definition fully aligned
        """
        if not definitions:
            return 0

        defn = definitions[0]

        alignment_scores = {
            "aligned": 3,
            "partial": 2,
            "not_aligned": 1,
            "unknown": 0,
        }

        return alignment_scores.get(defn.alignment_flag or "unknown", 0)


# Convenience function
def score_filing(
    filing_id: int,
    company_id: int,
    segments: list[SourceSegment],
    values: list[MetricValue],
    definitions: list[MetricDefinition],
) -> list[FilingMetricIncidence]:
    """
    Convenience function to score a filing.

    Args:
        filing_id: Filing ID
        company_id: Company ID
        segments: Source segments
        values: Metric values
        definitions: Metric definitions

    Returns:
        List of FilingMetricIncidence objects
    """
    scorer = QualityScorer()
    return scorer.score_filing(filing_id, company_id, segments, values, definitions)
