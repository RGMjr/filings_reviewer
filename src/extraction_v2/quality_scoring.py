"""
V2 Quality Scoring Adapter.

Ports V1 quality scoring rubrics to work with V2 pipeline outputs.
Writes results to V1's filing_metric_incidence table for analytics compatibility.

Design principles:
- Direct port of 5 scoring dimensions from V1 quality_scorer.py
- Maps V2 MetricFact → V1 scoring inputs
- Idempotent: DELETE + INSERT pattern (matches V1)
- Script-layer only (not a pipeline stage) — needs company_id not in PipelineContext
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from src.extraction_v2.models import MetricDefinition, MetricFact, Segment
from src.shared.models import FilingMetricIncidence

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class V2QualityScorer:
    """
    Adapter that computes V1-compatible quality scores from V2 pipeline outputs.

    Maps V2 types to V1 scoring inputs:
    - MetricFact.cohort_def (non-null) → has_cohort_breakdown
    - MetricFact.period_end → period set for completeness scoring
    - MetricDefinition.alignment_flag → comparability score
    """

    def score_filing(
        self,
        filing_id: int,
        company_id: int,
        facts: list[MetricFact],
        definitions: list[MetricDefinition],
        segments: list[Segment],
    ) -> list[FilingMetricIncidence]:
        """
        Compute quality scores for all metrics in a filing.

        Args:
            filing_id: Database filing ID
            company_id: Database company ID
            facts: Extracted MetricFact objects from pipeline
            definitions: MetricDefinition objects from Stage 9.5
            segments: Segment objects (for counting definition/methodology segments)

        Returns:
            List of FilingMetricIncidence with quality scores
        """
        # Collect all metric IDs from facts
        metric_ids = {f.canonical_metric_id for f in facts}

        # Also include metric IDs from definitions (metric defined but no facts is possible)
        for defn in definitions:
            metric_ids.add(defn.canonical_metric_id)

        if not metric_ids:
            return []

        # Build lookups
        facts_by_metric: dict[str, list[MetricFact]] = {}
        for fact in facts:
            facts_by_metric.setdefault(fact.canonical_metric_id, []).append(fact)

        definitions_by_metric: dict[str, list[MetricDefinition]] = {}
        for defn in definitions:
            definitions_by_metric.setdefault(defn.canonical_metric_id, []).append(defn)

        results = []

        for metric_id in sorted(metric_ids):
            metric_facts = facts_by_metric.get(metric_id, [])
            metric_defs = definitions_by_metric.get(metric_id, [])

            # Cohort breakdown: any fact has non-null cohort_def
            has_cohort_breakdown = any(f.cohort_def is not None for f in metric_facts)
            has_tenure_breakdown = False  # V2 doesn't distinguish cohort subtypes yet
            has_acquisition_cohort = False

            # Period set for completeness scoring
            periods: set[date | None] = {f.period_end for f in metric_facts}

            # Compute quality scores
            overall = self._compute_overall_quality(metric_facts, metric_defs, has_cohort_breakdown)
            definition_score = self._compute_definition_quality(metric_defs)
            methodology_score = self._compute_methodology_quality(metric_defs)
            completeness_score = self._compute_completeness_quality(
                metric_facts, periods, has_cohort_breakdown
            )
            comparability_score = self._compute_comparability_quality(metric_defs)

            # Alignment flag from first definition
            alignment_flag = metric_defs[0].alignment_flag if metric_defs else None

            # Disclosed if we have facts or definitions
            metric_disclosed = len(metric_facts) > 0 or len(metric_defs) > 0

            incidence = FilingMetricIncidence(
                filing_id=filing_id,
                company_id=company_id,
                metric_id=metric_id,
                metric_disclosed_flag=metric_disclosed,
                num_numeric_segments=len(metric_facts),  # Approximate: one segment per fact
                num_definition_segments=1 if any(d.definition_text for d in metric_defs) else 0,
                num_methodology_segments=1 if any(d.methodology_text for d in metric_defs) else 0,
                primary_definition_segment_id=None,  # V1 uses integer FKs; not applicable in V2
                primary_methodology_segment_id=None,
                quality_overall_score=overall,
                quality_definition_score=definition_score,
                quality_methodology_score=methodology_score,
                quality_completeness_score=completeness_score,
                quality_comparability_score=comparability_score,
                alignment_flag=alignment_flag,
                quality_notes=None,
                has_cohort_breakdown_flag=has_cohort_breakdown,
                has_tenure_breakdown_flag=has_tenure_breakdown,
                has_acquisition_cohort_flag=has_acquisition_cohort,
            )
            results.append(incidence)

        logger.info(
            f"Quality scoring: {len(results)} metrics scored for filing_id={filing_id}"
        )
        return results

    def _compute_overall_quality(
        self,
        facts: list[MetricFact],
        definitions: list[MetricDefinition],
        has_cohort_breakdown: bool,
    ) -> int:
        """
        Compute overall quality score (0-3).

        Ported from V1 quality_scorer.py _compute_overall_quality().

        Scoring rubric:
        - 0: Not disclosed
        - 1: Minimal (value only, no definition)
        - 2: Moderate (value + definition OR methodology)
        - 3: Excellent (value + definition + methodology + cohort breakdown)
        """
        if not facts and not definitions:
            return 0

        if not facts:
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

        Ported from V1 quality_scorer.py _compute_definition_quality().

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

        if defn.alignment_flag == "aligned":
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

        Ported from V1 quality_scorer.py _compute_methodology_quality().

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

        methodology = defn.methodology_text_normalized.lower()

        has_formula_keywords = any(
            kw in methodology for kw in ["formula", "divided by", "equals", "="]
        )
        has_example = any(kw in methodology for kw in ["example", "for instance", "such as"])

        if has_formula_keywords and has_example:
            return 3
        elif has_formula_keywords or len(methodology) > 150:
            return 2
        else:
            return 1

    def _compute_completeness_quality(
        self,
        facts: list[MetricFact],
        periods: set[date | None],
        has_cohort_breakdown: bool,
    ) -> int:
        """
        Compute completeness quality score (0-3).

        Ported from V1 quality_scorer.py _compute_completeness_quality().

        Scoring rubric:
        - 0: Not disclosed
        - 1: Single aggregate number
        - 2: Breakdowns by period OR cohort
        - 3: Breakdowns by both period AND cohort
        """
        if not facts:
            return 0

        # More than one distinct period_end → period breakdown
        non_null_periods = {p for p in periods if p is not None}
        has_period_breakdown = len(non_null_periods) > 1

        if has_period_breakdown and has_cohort_breakdown:
            return 3
        elif has_period_breakdown or has_cohort_breakdown:
            return 2
        else:
            return 1

    def _compute_comparability_quality(self, definitions: list[MetricDefinition]) -> int:
        """
        Compute comparability quality score (0-3).

        Ported from V1 quality_scorer.py _compute_comparability_quality().

        Based on alignment with CMASB canonical definitions:
        - 0: Not disclosed or unknown alignment
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
