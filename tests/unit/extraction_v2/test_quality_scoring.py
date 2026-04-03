"""
Unit tests for V2 Quality Scoring Adapter.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.extraction_v2.models import MetricDefinition, MetricFact
from src.extraction_v2.quality_scoring import V2QualityScorer


def make_fact(
    metric_id: str = "cm_arr",
    period_end: date | None = None,
    cohort_def: str | None = None,
    value: float = 1.0,
) -> MetricFact:
    f = MetricFact()
    f.canonical_metric_id = metric_id
    f.period_end = period_end
    f.cohort_def = cohort_def
    f.value = value
    return f


def make_definition(
    metric_id: str = "cm_arr",
    definition_text: str = "",
    methodology_text: str = "",
    alignment_flag: str = "unknown",
) -> MetricDefinition:
    d = MetricDefinition()
    d.canonical_metric_id = metric_id
    d.definition_text = definition_text
    d.definition_text_normalized = definition_text
    d.methodology_text = methodology_text
    d.methodology_text_normalized = methodology_text
    d.alignment_flag = alignment_flag
    return d


@pytest.fixture
def scorer() -> V2QualityScorer:
    return V2QualityScorer()


class TestOverallQuality:
    def test_no_facts_no_defs_returns_zero(self, scorer):
        assert scorer._compute_overall_quality([], [], False) == 0

    def test_defs_only_no_facts_returns_one(self, scorer):
        defn = make_definition(definition_text="something")
        assert scorer._compute_overall_quality([], [defn], False) == 1

    def test_facts_only_returns_one(self, scorer):
        fact = make_fact()
        assert scorer._compute_overall_quality([fact], [], False) == 1

    def test_facts_with_definition_returns_two(self, scorer):
        fact = make_fact()
        defn = make_definition(definition_text="long definition text here")
        assert scorer._compute_overall_quality([fact], [defn], False) == 2

    def test_facts_definition_methodology_cohort_returns_three(self, scorer):
        fact = make_fact(cohort_def="2021")
        defn = make_definition(
            definition_text="definition text",
            methodology_text="formula: a divided by b",
        )
        assert scorer._compute_overall_quality([fact], [defn], True) == 3


class TestDefinitionQuality:
    def test_no_definitions_returns_zero(self, scorer):
        assert scorer._compute_definition_quality([]) == 0

    def test_empty_definition_text_returns_zero(self, scorer):
        defn = make_definition()
        assert scorer._compute_definition_quality([defn]) == 0

    def test_not_aligned_returns_one(self, scorer):
        defn = make_definition(definition_text="some text", alignment_flag="not_aligned")
        assert scorer._compute_definition_quality([defn]) == 1

    def test_partial_alignment_returns_two(self, scorer):
        defn = make_definition(definition_text="some text", alignment_flag="partial")
        assert scorer._compute_definition_quality([defn]) == 2

    def test_aligned_brief_returns_two(self, scorer):
        defn = make_definition(definition_text="brief", alignment_flag="aligned")
        assert scorer._compute_definition_quality([defn]) == 2

    def test_aligned_long_returns_three(self, scorer):
        long_text = "x" * 150
        defn = make_definition(definition_text=long_text, alignment_flag="aligned")
        assert scorer._compute_definition_quality([defn]) == 3


class TestMethodologyQuality:
    def test_no_definitions_returns_zero(self, scorer):
        assert scorer._compute_methodology_quality([]) == 0

    def test_empty_methodology_returns_zero(self, scorer):
        defn = make_definition()
        assert scorer._compute_methodology_quality([defn]) == 0

    def test_vague_returns_one(self, scorer):
        defn = make_definition(methodology_text="calculated internally")
        assert scorer._compute_methodology_quality([defn]) == 1

    def test_formula_keyword_returns_two(self, scorer):
        defn = make_definition(methodology_text="calculated by divided by total customers")
        assert scorer._compute_methodology_quality([defn]) == 2

    def test_formula_and_example_returns_three(self, scorer):
        defn = make_definition(
            methodology_text="formula: revenue divided by customers, for instance in 2023"
        )
        assert scorer._compute_methodology_quality([defn]) == 3


class TestCompletenessQuality:
    def test_no_facts_returns_zero(self, scorer):
        assert scorer._compute_completeness_quality([], set(), False) == 0

    def test_single_fact_no_breakdown_returns_one(self, scorer):
        fact = make_fact(period_end=date(2023, 12, 31))
        assert scorer._compute_completeness_quality([fact], {date(2023, 12, 31)}, False) == 1

    def test_multiple_periods_returns_two(self, scorer):
        facts = [make_fact(period_end=date(2022, 12, 31)), make_fact(period_end=date(2023, 12, 31))]
        periods = {date(2022, 12, 31), date(2023, 12, 31)}
        assert scorer._compute_completeness_quality(facts, periods, False) == 2

    def test_cohort_breakdown_only_returns_two(self, scorer):
        fact = make_fact(period_end=date(2023, 12, 31), cohort_def="2021")
        assert scorer._compute_completeness_quality([fact], {date(2023, 12, 31)}, True) == 2

    def test_both_period_and_cohort_returns_three(self, scorer):
        facts = [make_fact(period_end=date(2022, 12, 31)), make_fact(period_end=date(2023, 12, 31))]
        periods = {date(2022, 12, 31), date(2023, 12, 31)}
        assert scorer._compute_completeness_quality(facts, periods, True) == 3


class TestComparabilityQuality:
    def test_no_definitions_returns_zero(self, scorer):
        assert scorer._compute_comparability_quality([]) == 0

    def test_unknown_alignment_returns_zero(self, scorer):
        defn = make_definition(alignment_flag="unknown")
        assert scorer._compute_comparability_quality([defn]) == 0

    def test_not_aligned_returns_one(self, scorer):
        defn = make_definition(alignment_flag="not_aligned")
        assert scorer._compute_comparability_quality([defn]) == 1

    def test_partial_returns_two(self, scorer):
        defn = make_definition(alignment_flag="partial")
        assert scorer._compute_comparability_quality([defn]) == 2

    def test_aligned_returns_three(self, scorer):
        defn = make_definition(alignment_flag="aligned")
        assert scorer._compute_comparability_quality([defn]) == 3


class TestScoreFiling:
    def test_empty_filing_returns_empty(self, scorer):
        result = scorer.score_filing(1, 1, [], [], [])
        assert result == []

    def test_single_metric_with_fact(self, scorer):
        fact = make_fact("cm_arr", period_end=date(2023, 12, 31))
        result = scorer.score_filing(1, 42, [fact], [], [])
        assert len(result) == 1
        incidence = result[0]
        assert incidence.filing_id == 1
        assert incidence.company_id == 42
        assert incidence.metric_id == "cm_arr"
        assert incidence.metric_disclosed_flag is True
        assert incidence.quality_overall_score == 1  # fact only, no definition

    def test_definition_only_metric_included(self, scorer):
        defn = make_definition("cm_arr", definition_text="Annual Recurring Revenue")
        result = scorer.score_filing(1, 1, [], [defn], [])
        assert len(result) == 1
        assert result[0].metric_id == "cm_arr"
        assert result[0].metric_disclosed_flag is True

    def test_cohort_breakdown_detected(self, scorer):
        fact = make_fact("cm_arr", cohort_def="2021 cohort")
        result = scorer.score_filing(1, 1, [fact], [], [])
        assert result[0].has_cohort_breakdown_flag is True

    def test_alignment_flag_propagated(self, scorer):
        fact = make_fact("cm_arr")
        defn = make_definition("cm_arr", definition_text="some text", alignment_flag="aligned")
        result = scorer.score_filing(1, 1, [fact], [defn], [])
        assert result[0].alignment_flag == "aligned"

    def test_multiple_metrics_scored_separately(self, scorer):
        facts = [
            make_fact("cm_arr", period_end=date(2023, 12, 31)),
            make_fact("cm_nrr", period_end=date(2023, 12, 31)),
        ]
        result = scorer.score_filing(1, 1, facts, [], [])
        metric_ids = {r.metric_id for r in result}
        assert "cm_arr" in metric_ids
        assert "cm_nrr" in metric_ids
        assert len(result) == 2

    def test_quality_scores_non_negative(self, scorer):
        fact = make_fact("cm_arr")
        result = scorer.score_filing(1, 1, [fact], [], [])
        inc = result[0]
        assert inc.quality_overall_score >= 0
        assert inc.quality_definition_score >= 0
        assert inc.quality_methodology_score >= 0
        assert inc.quality_completeness_score >= 0
        assert inc.quality_comparability_score >= 0

    def test_primary_segment_ids_are_none(self, scorer):
        """V2 doesn't set integer FK segment IDs for V1 table."""
        fact = make_fact("cm_arr")
        defn = make_definition("cm_arr", definition_text="text")
        result = scorer.score_filing(1, 1, [fact], [defn], [])
        assert result[0].primary_definition_segment_id is None
        assert result[0].primary_methodology_segment_id is None


class TestCohortTypeFlags:
    """Tests for has_tenure_breakdown_flag and has_acquisition_cohort_flag."""

    def test_tenure_breakdown_flag_true_when_cohort_type_tenure(self, scorer):
        """has_tenure_breakdown_flag should be True when any fact has cohort_type='tenure'."""
        fact = make_fact("cm_arr")
        fact.cohort_type = "tenure"
        result = scorer.score_filing(1, 1, [fact], [], [])
        assert result[0].has_tenure_breakdown_flag is True

    def test_acquisition_cohort_flag_true_when_cohort_type_acquisition(self, scorer):
        """has_acquisition_cohort_flag should be True when any fact has cohort_type='acquisition'."""
        fact = make_fact("cm_arr")
        fact.cohort_type = "acquisition"
        result = scorer.score_filing(1, 1, [fact], [], [])
        assert result[0].has_acquisition_cohort_flag is True

    def test_cohort_flags_false_when_cohort_type_none(self, scorer):
        """Both cohort flags should be False when cohort_type is None."""
        fact = make_fact("cm_arr")
        # cohort_type defaults to None — do not set it
        result = scorer.score_filing(1, 1, [fact], [], [])
        assert result[0].has_tenure_breakdown_flag is False
        assert result[0].has_acquisition_cohort_flag is False

    def test_cohort_flags_false_when_cohort_type_other(self, scorer):
        """Neither specific flag should fire when cohort_type='other'."""
        fact = make_fact("cm_arr")
        fact.cohort_type = "other"
        result = scorer.score_filing(1, 1, [fact], [], [])
        assert result[0].has_tenure_breakdown_flag is False
        assert result[0].has_acquisition_cohort_flag is False

    def test_tenure_and_acquisition_flags_independent(self, scorer):
        """Tenure and acquisition flags come from separate facts for the same metric."""
        fact_tenure = make_fact("cm_arr")
        fact_tenure.cohort_type = "tenure"
        fact_acquisition = make_fact("cm_arr")
        fact_acquisition.cohort_type = "acquisition"
        result = scorer.score_filing(1, 1, [fact_tenure, fact_acquisition], [], [])
        assert result[0].has_tenure_breakdown_flag is True
        assert result[0].has_acquisition_cohort_flag is True
