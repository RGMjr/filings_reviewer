"""
Unit tests for QualityScorer.

Ensures basic scoring works and segments without candidate metrics are ignored.
"""

from datetime import date
from decimal import Decimal

from src.extraction.models import MetricDefinition, MetricValue, SourceSegment
from src.extraction.quality_scorer import QualityScorer, score_filing


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


# ===== Tests for _get_all_metrics =====


def test_get_all_metrics_from_segments():
    """Should extract metrics from segment candidate_metric_ids."""
    scorer = QualityScorer()
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="MAU text",
            candidate_metric_ids=["cm_monthly_active_users"],
            sequence_index=0,
        )
    ]

    metrics = scorer._get_all_metrics(segments, [], [])
    assert metrics == {"cm_monthly_active_users"}


def test_get_all_metrics_from_values():
    """Should extract metrics from values."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_churn_rate",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
        )
    ]

    metrics = scorer._get_all_metrics([], values, [])
    assert metrics == {"cm_churn_rate"}


def test_get_all_metrics_from_definitions():
    """Should extract metrics from definitions."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_net_retention",
        )
    ]

    metrics = scorer._get_all_metrics([], [], definitions)
    assert metrics == {"cm_net_retention"}


def test_get_all_metrics_combines_all_sources():
    """Should combine metrics from all sources."""
    scorer = QualityScorer()
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            candidate_metric_ids=["cm_mau", "cm_dau"],
            sequence_index=0,
        )
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_dau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
        )
    ]
    definitions = [MetricDefinition(filing_id=1, company_id=1, metric_id="cm_arpu")]

    metrics = scorer._get_all_metrics(segments, values, definitions)
    assert metrics == {"cm_mau", "cm_dau", "cm_arpu"}


# ===== Tests for _compute_overall_quality =====


def test_compute_overall_quality_score_0_not_disclosed():
    """Score 0 when no values or definitions."""
    scorer = QualityScorer()
    score = scorer._compute_overall_quality([], [], False)
    assert score == 0


def test_compute_overall_quality_score_1_definition_only():
    """Score 1 when definition exists but no values."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Users who logged in during the month",
        )
    ]
    score = scorer._compute_overall_quality([], definitions, False)
    assert score == 1


def test_compute_overall_quality_score_1_minimal():
    """Score 1 when values exist but no definition or methodology."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("1000"),
        )
    ]
    score = scorer._compute_overall_quality(values, [], False)
    assert score == 1


def test_compute_overall_quality_score_2_with_definition():
    """Score 2 when values exist with definition."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("1000"),
        )
    ]
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Users who logged in during the month",
        )
    ]
    score = scorer._compute_overall_quality(values, definitions, False)
    assert score == 2


def test_compute_overall_quality_score_2_with_methodology():
    """Score 2 when values exist with methodology."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("1000"),
        )
    ]
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            methodology_text_normalized="Calculated by counting unique user IDs",
        )
    ]
    score = scorer._compute_overall_quality(values, definitions, False)
    assert score == 2


def test_compute_overall_quality_score_3_excellent():
    """Score 3 when values, definition, methodology, and cohort breakdown all exist."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_retention",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("95"),
        )
    ]
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_retention",
            definition_text_normalized="Percentage of customers who remain active",
            methodology_text_normalized="Calculated as (active end / active start) * 100",
        )
    ]
    score = scorer._compute_overall_quality(values, definitions, has_cohort_breakdown=True)
    assert score == 3


# ===== Tests for _compute_definition_quality =====


def test_compute_definition_quality_score_0_no_definitions():
    """Score 0 when no definitions provided."""
    scorer = QualityScorer()
    score = scorer._compute_definition_quality([])
    assert score == 0


def test_compute_definition_quality_score_0_empty_definition_text():
    """Score 0 when definition exists but text is empty."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized=None,
        )
    ]
    score = scorer._compute_definition_quality(definitions)
    assert score == 0


def test_compute_definition_quality_score_1_not_aligned():
    """Score 1 when definition is not aligned."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Our users",
            alignment_flag="not_aligned",
        )
    ]
    score = scorer._compute_definition_quality(definitions)
    assert score == 1


def test_compute_definition_quality_score_2_aligned_but_brief():
    """Score 2 when definition is aligned but brief (<100 chars)."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Active users in the month",
            alignment_flag="aligned",
        )
    ]
    score = scorer._compute_definition_quality(definitions)
    assert score == 2


def test_compute_definition_quality_score_2_partial_alignment():
    """Score 2 when definition is partially aligned."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Users who accessed our platform in the month, with some custom criteria that differ from standard definitions",
            alignment_flag="partial",
        )
    ]
    score = scorer._compute_definition_quality(definitions)
    assert score == 2


def test_compute_definition_quality_score_3_comprehensive_and_aligned():
    """Score 3 when definition is aligned and comprehensive (>100 chars)."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="We define monthly active users as the number of unique customer accounts that have logged in to our platform at least once during the calendar month, excluding test accounts and internal users.",
            alignment_flag="aligned",
        )
    ]
    score = scorer._compute_definition_quality(definitions)
    assert score == 3


# ===== Tests for _compute_methodology_quality =====


def test_compute_methodology_quality_score_0_no_definitions():
    """Score 0 when no definitions provided."""
    scorer = QualityScorer()
    score = scorer._compute_methodology_quality([])
    assert score == 0


def test_compute_methodology_quality_score_0_no_methodology_text():
    """Score 0 when definition exists but methodology text is empty."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            methodology_text_normalized=None,
        )
    ]
    score = scorer._compute_methodology_quality(definitions)
    assert score == 0


def test_compute_methodology_quality_score_1_vague():
    """Score 1 when methodology is vague (short, no formula keywords)."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_churn",
            methodology_text_normalized="We count churned customers",
        )
    ]
    score = scorer._compute_methodology_quality(definitions)
    assert score == 1


def test_compute_methodology_quality_score_2_has_formula():
    """Score 2 when methodology has formula keywords."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_churn",
            methodology_text_normalized="Churn rate equals churned customers divided by total customers",
        )
    ]
    score = scorer._compute_methodology_quality(definitions)
    assert score == 2


def test_compute_methodology_quality_score_2_detailed():
    """Score 2 when methodology is detailed (>150 chars) even without formula keywords."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_ltv",
            methodology_text_normalized="Customer lifetime value represents the total revenue we expect to generate from a customer over their entire relationship with our company, taking into account historical behavior patterns and trends",
        )
    ]
    score = scorer._compute_methodology_quality(definitions)
    assert score == 2


def test_compute_methodology_quality_score_3_formula_with_example():
    """Score 3 when methodology has both formula and examples."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_nrr",
            methodology_text_normalized="Net revenue retention equals (starting ARR + expansion - contraction - churn) divided by starting ARR. For example, if we start with $100M, add $20M expansion, lose $5M to contraction and $10M to churn, NRR = ($100M + $20M - $5M - $10M) / $100M = 105%",
        )
    ]
    score = scorer._compute_methodology_quality(definitions)
    assert score == 3


# ===== Tests for _compute_completeness_quality =====


def test_compute_completeness_quality_score_0_no_values():
    """Score 0 when no values provided."""
    scorer = QualityScorer()
    score = scorer._compute_completeness_quality([], False)
    assert score == 0


def test_compute_completeness_quality_score_1_single_aggregate():
    """Score 1 when only single aggregate value (no breakdowns)."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("5000"),
        )
    ]
    score = scorer._compute_completeness_quality(values, has_cohort_breakdown=False)
    assert score == 1


def test_compute_completeness_quality_score_2_period_breakdown():
    """Score 2 when multiple periods provided."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("5000"),
            period_end=date(2023, 12, 31),
        ),
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("5500"),
            period_end=date(2024, 3, 31),
        ),
    ]
    score = scorer._compute_completeness_quality(values, has_cohort_breakdown=False)
    assert score == 2


def test_compute_completeness_quality_score_2_cohort_breakdown():
    """Score 2 when cohort breakdown provided."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_retention",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("95"),
        )
    ]
    score = scorer._compute_completeness_quality(values, has_cohort_breakdown=True)
    assert score == 2


def test_compute_completeness_quality_score_3_period_and_cohort():
    """Score 3 when both period and cohort breakdowns provided."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_retention",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("95"),
            period_end=date(2023, 12, 31),
        ),
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_retention",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("97"),
            period_end=date(2024, 3, 31),
        ),
    ]
    score = scorer._compute_completeness_quality(values, has_cohort_breakdown=True)
    assert score == 3


# ===== Tests for _compute_comparability_quality =====


def test_compute_comparability_quality_score_0_no_definitions():
    """Score 0 when no definitions provided."""
    scorer = QualityScorer()
    score = scorer._compute_comparability_quality([])
    assert score == 0


def test_compute_comparability_quality_score_0_unknown_alignment():
    """Score 0 when alignment flag is unknown or None."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Users in month",
            alignment_flag="unknown",
        )
    ]
    score = scorer._compute_comparability_quality(definitions)
    assert score == 0


def test_compute_comparability_quality_score_0_null_alignment():
    """Score 0 when alignment flag is None."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Users in month",
            alignment_flag=None,
        )
    ]
    score = scorer._compute_comparability_quality(definitions)
    assert score == 0


def test_compute_comparability_quality_score_1_not_aligned():
    """Score 1 when definition differs significantly."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Our custom metric",
            alignment_flag="not_aligned",
        )
    ]
    score = scorer._compute_comparability_quality(definitions)
    assert score == 1


def test_compute_comparability_quality_score_2_partial_alignment():
    """Score 2 when definition partially aligned."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Active users with some custom criteria",
            alignment_flag="partial",
        )
    ]
    score = scorer._compute_comparability_quality(definitions)
    assert score == 2


def test_compute_comparability_quality_score_3_fully_aligned():
    """Score 3 when definition fully aligned with CMASB standards."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Monthly active users per CMASB standard",
            alignment_flag="aligned",
        )
    ]
    score = scorer._compute_comparability_quality(definitions)
    assert score == 3


# ===== Tests for _score_filing_metric (integration) =====


def test_score_filing_metric_with_all_data():
    """Test scoring a filing-metric pair with complete data."""
    scorer = QualityScorer()
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="MAU definition and values",
            candidate_metric_ids=["cm_mau"],
            contains_numeric_disclosure_flag=True,
            contains_definition_flag=True,
            sequence_index=0,
        )
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("10000"),
            period_end=date(2023, 12, 31),
            cohort_type="acquisition",
        )
    ]
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            definition_text_normalized="Monthly active users are unique accounts that logged in during the calendar month",
            methodology_text_normalized="Calculated by counting distinct user IDs with login events",
            definition_segment_id=0,
            methodology_segment_id=0,
            alignment_flag="aligned",
        )
    ]

    incidence = scorer._score_filing_metric(
        filing_id=1,
        company_id=1,
        metric_id="cm_mau",
        segments=segments,
        values=values,
        definitions=definitions,
    )

    assert incidence.metric_id == "cm_mau"
    assert incidence.metric_disclosed_flag is True
    assert incidence.num_numeric_segments == 1
    assert incidence.num_definition_segments == 1
    assert incidence.primary_definition_segment_id == 0
    assert incidence.primary_methodology_segment_id == 0
    assert incidence.has_cohort_breakdown_flag is True
    assert incidence.has_acquisition_cohort_flag is True
    assert incidence.alignment_flag == "aligned"


def test_score_filing_metric_with_tenure_cohort():
    """Test tenure cohort flag detection."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_retention",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            cohort_type="tenure",
        )
    ]

    incidence = scorer._score_filing_metric(
        filing_id=1,
        company_id=1,
        metric_id="cm_retention",
        segments=[],
        values=values,
        definitions=[],
    )

    assert incidence.has_tenure_breakdown_flag is True
    assert incidence.has_acquisition_cohort_flag is False


def test_score_filing_metric_minimal():
    """Test scoring with minimal data (values only, no definition)."""
    scorer = QualityScorer()
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_arpu",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("25.50"),
        )
    ]

    incidence = scorer._score_filing_metric(
        filing_id=1,
        company_id=1,
        metric_id="cm_arpu",
        segments=[],
        values=values,
        definitions=[],
    )

    assert incidence.metric_disclosed_flag is True
    assert incidence.quality_overall_score == 1  # Minimal
    assert incidence.quality_definition_score == 0
    assert incidence.quality_methodology_score == 0
    assert incidence.alignment_flag is None


def test_score_filing_metric_definition_only():
    """Test scoring when only definition exists (no values)."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_ltv",
            definition_text_normalized="Customer lifetime value represents total expected revenue from a customer",
        )
    ]

    incidence = scorer._score_filing_metric(
        filing_id=1,
        company_id=1,
        metric_id="cm_ltv",
        segments=[],
        values=[],
        definitions=definitions,
    )

    assert incidence.metric_disclosed_flag is True
    assert incidence.quality_overall_score == 1


# ===== Tests for score_filing (convenience function) =====


def test_score_filing_convenience_function():
    """Test the module-level convenience function."""
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We had 2,000 DAUs.",
            candidate_metric_ids=["cm_dau"],
            contains_numeric_disclosure_flag=True,
            sequence_index=0,
        )
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_dau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("2000"),
        )
    ]

    incidences = score_filing(1, 1, segments, values, definitions=[])

    assert len(incidences) == 1
    assert incidences[0].metric_id == "cm_dau"


# ===== Edge case tests =====


def test_score_filing_multiple_metrics():
    """Test scoring when filing contains multiple different metrics."""
    scorer = QualityScorer()
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            candidate_metric_ids=["cm_mau", "cm_dau"],
            sequence_index=0,
        )
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_mau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("10000"),
        ),
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_dau",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("3000"),
        ),
    ]

    incidences = scorer.score_filing(1, 1, segments, values, definitions=[])

    assert len(incidences) == 2
    metric_ids = {inc.metric_id for inc in incidences}
    assert metric_ids == {"cm_mau", "cm_dau"}


def test_score_filing_empty_inputs():
    """Test scoring with completely empty inputs."""
    scorer = QualityScorer()
    incidences = scorer.score_filing(1, 1, segments=[], values=[], definitions=[])
    assert len(incidences) == 0


def test_score_filing_metric_with_methodology_segment():
    """Test that methodology segment ID is captured correctly."""
    scorer = QualityScorer()
    definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=1,
            metric_id="cm_nrr",
            definition_text_normalized="Net revenue retention",
            methodology_text_normalized="Calculated as renewal revenue divided by starting revenue",
            definition_segment_id=5,
            methodology_segment_id=7,
        )
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_nrr",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("120"),
        )
    ]

    incidence = scorer._score_filing_metric(
        filing_id=1,
        company_id=1,
        metric_id="cm_nrr",
        segments=[],
        values=values,
        definitions=definitions,
    )

    assert incidence.primary_definition_segment_id == 5
    assert incidence.primary_methodology_segment_id == 7


def test_score_filing_counts_segment_types():
    """Test that different segment types are counted correctly."""
    scorer = QualityScorer()
    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            candidate_metric_ids=["cm_churn"],
            contains_numeric_disclosure_flag=True,
            sequence_index=0,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            candidate_metric_ids=["cm_churn"],
            contains_definition_flag=True,
            sequence_index=1,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            candidate_metric_ids=["cm_churn"],
            contains_methodology_flag=True,
            sequence_index=2,
        ),
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            candidate_metric_ids=["cm_churn"],
            contains_numeric_disclosure_flag=True,
            contains_definition_flag=True,
            sequence_index=3,
        ),
    ]
    values = [
        MetricValue(
            filing_id=1,
            company_id=1,
            metric_id="cm_churn",
            source_segment_id=0,
            source_type="text",
            extraction_method="llm_text",
            value_numeric=Decimal("5.2"),
        )
    ]

    incidence = scorer._score_filing_metric(
        filing_id=1,
        company_id=1,
        metric_id="cm_churn",
        segments=segments,
        values=values,
        definitions=[],
    )

    assert incidence.num_numeric_segments == 2
    assert incidence.num_definition_segments == 2
    assert incidence.num_methodology_segments == 1
