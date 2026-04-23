"""Unit tests for src/gold_standard/image_eval.py.

All tests use fixtured inputs — no DB, no OpenAI calls.
"""

from __future__ import annotations

import pytest

from src.gold_standard.image_eval import (
    CHART_TYPES,
    REJECTION_REASONS,
    REVIEWER_ACTIONS,
    ImageEvalResult,
    ImageRunRecord,
    _list_cell_accuracy,
    _str_similarity,
    aggregate_results,
    chart_detection_metrics,
    data_value_match,
    data_value_scores,
    expected_calibration_error,
    is_hard_ocr_image,
    is_tier1_image,
    legend_match_score,
    metric_tag_match,
    metric_tag_scores,
    ocr_axis_label_accuracy_score,
    ocr_cell_accuracy_score,
    parse_failure_rate,
    reviewer_action,
    reviewer_action_counts,
    stratum_label,
    tier1_fact_recall_score,
    title_match_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    img_id: str = "img-001",
    reviewer_decision: str = "relevant",
    reviewer_chart_type: str | None = "cohort_table",
    reviewer_notes: str = "",
    tier1_facts_in_db: int = 0,
    predicted_chart_type: str | None = "cohort_table",
    predicted_relevant: bool = True,
    ocr_cells_extracted: list[str] | None = None,
    ocr_cells_reference: list[str] | None = None,
    axis_labels_extracted: list[str] | None = None,
    axis_labels_reference: list[str] | None = None,
    title_extracted: str = "",
    legend_extracted: str = "",
    tier1_facts_extracted: int = 0,
    parse_failed: bool = False,
    cost_usd: float = 0.005,
    latency_ms: int = 1200,
    raw_output: str = "",
    provider: str = "openai/gpt-4o",
) -> ImageRunRecord:
    return ImageRunRecord(
        img_id=img_id,
        reviewer_decision=reviewer_decision,
        reviewer_chart_type=reviewer_chart_type,
        reviewer_notes=reviewer_notes,
        tier1_facts_in_db=tier1_facts_in_db,
        predicted_chart_type=predicted_chart_type,
        predicted_relevant=predicted_relevant,
        ocr_cells_extracted=ocr_cells_extracted or [],
        ocr_cells_reference=ocr_cells_reference or [],
        axis_labels_extracted=axis_labels_extracted or [],
        axis_labels_reference=axis_labels_reference or [],
        title_extracted=title_extracted,
        legend_extracted=legend_extracted,
        tier1_facts_extracted=tier1_facts_extracted,
        parse_failed=parse_failed,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        raw_output=raw_output,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# _str_similarity
# ---------------------------------------------------------------------------


class TestStrSimilarity:
    def test_identical_strings(self) -> None:
        assert _str_similarity("hello", "hello") == pytest.approx(1.0)

    def test_empty_strings_equal_one(self) -> None:
        assert _str_similarity("", "") == pytest.approx(1.0)

    def test_one_empty_returns_zero(self) -> None:
        assert _str_similarity("hello", "") == pytest.approx(0.0)
        assert _str_similarity("", "hello") == pytest.approx(0.0)

    def test_case_insensitive(self) -> None:
        assert _str_similarity("Hello", "hello") == pytest.approx(1.0)

    def test_partial_overlap(self) -> None:
        score = _str_similarity("abcdef", "abcxyz")
        assert 0.0 < score < 1.0

    def test_completely_different(self) -> None:
        score = _str_similarity("abc", "xyz")
        assert score < 0.5


# ---------------------------------------------------------------------------
# _list_cell_accuracy
# ---------------------------------------------------------------------------


class TestListCellAccuracy:
    def test_empty_reference_empty_extracted(self) -> None:
        assert _list_cell_accuracy([], []) == pytest.approx(1.0)

    def test_empty_reference_nonempty_extracted(self) -> None:
        assert _list_cell_accuracy(["a", "b"], []) == pytest.approx(0.0)

    def test_exact_match(self) -> None:
        assert _list_cell_accuracy(["10%", "20%"], ["10%", "20%"]) == pytest.approx(1.0)

    def test_partial_match(self) -> None:
        score = _list_cell_accuracy(["10%", "XX"], ["10%", "20%"])
        assert 0.0 < score < 1.0

    def test_extracted_shorter_than_reference(self) -> None:
        # Missing extracted cells are treated as empty vs reference cells
        score = _list_cell_accuracy(["10%"], ["10%", "20%"])
        # First pair exact match → 1.0; second pair "" vs "20%" → 0.0; avg = 0.5
        assert score == pytest.approx(0.5)

    def test_extracted_longer_than_reference(self) -> None:
        # Extra extracted cells are compared against empty references
        score = _list_cell_accuracy(["10%", "20%", "30%"], ["10%", "20%"])
        # Third pair "30%" vs "" → 0.0; (1.0 + 1.0 + 0.0) / 3 ≈ 0.667
        assert score == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# chart_detection_metrics
# ---------------------------------------------------------------------------


class TestChartDetectionMetrics:
    def test_perfect_detection(self) -> None:
        records = [
            _make_record(reviewer_decision="relevant", predicted_relevant=True),
            _make_record(reviewer_decision="not_relevant", predicted_relevant=False),
        ]
        p, r, f1 = chart_detection_metrics(records)
        assert p == pytest.approx(1.0)
        assert r == pytest.approx(1.0)
        assert f1 == pytest.approx(1.0)

    def test_all_false_positives(self) -> None:
        records = [
            _make_record(reviewer_decision="not_relevant", predicted_relevant=True),
            _make_record(reviewer_decision="not_relevant", predicted_relevant=True),
        ]
        p, r, f1 = chart_detection_metrics(records)
        assert p == pytest.approx(0.0)
        # No positive ground-truth → recall undefined; we return 0.0
        assert r == pytest.approx(0.0)

    def test_all_false_negatives(self) -> None:
        records = [
            _make_record(reviewer_decision="relevant", predicted_relevant=False),
        ]
        p, r, f1 = chart_detection_metrics(records)
        assert r == pytest.approx(0.0)

    def test_mixed(self) -> None:
        records = [
            _make_record(img_id="a", reviewer_decision="relevant", predicted_relevant=True),  # TP
            _make_record(img_id="b", reviewer_decision="relevant", predicted_relevant=False),  # FN
            _make_record(
                img_id="c", reviewer_decision="not_relevant", predicted_relevant=True
            ),  # FP
            _make_record(
                img_id="d", reviewer_decision="not_relevant", predicted_relevant=False
            ),  # TN
        ]
        p, r, f1 = chart_detection_metrics(records)
        # TP=1, FP=1, FN=1
        assert p == pytest.approx(0.5)
        assert r == pytest.approx(0.5)
        assert f1 == pytest.approx(0.5)

    def test_empty_records(self) -> None:
        p, r, f1 = chart_detection_metrics([])
        assert p == 0.0
        assert r == 0.0
        assert f1 == 0.0


# ---------------------------------------------------------------------------
# ocr_cell_accuracy_score
# ---------------------------------------------------------------------------


class TestOcrCellAccuracy:
    def test_no_reference_cells(self) -> None:
        # When no record has reference cells, returns 1.0 (not penalised)
        records = [_make_record()]
        assert ocr_cell_accuracy_score(records) == pytest.approx(1.0)

    def test_perfect_cells(self) -> None:
        records = [
            _make_record(
                ocr_cells_extracted=["10%", "20%"],
                ocr_cells_reference=["10%", "20%"],
            )
        ]
        assert ocr_cell_accuracy_score(records) == pytest.approx(1.0)

    def test_partial_cells(self) -> None:
        records = [
            _make_record(
                ocr_cells_extracted=["10%"],
                ocr_cells_reference=["10%", "20%"],
            )
        ]
        score = ocr_cell_accuracy_score(records)
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# ocr_axis_label_accuracy_score
# ---------------------------------------------------------------------------


class TestAxisLabelAccuracy:
    def test_no_reference_labels(self) -> None:
        records = [_make_record()]
        assert ocr_axis_label_accuracy_score(records) == pytest.approx(1.0)

    def test_exact_match(self) -> None:
        records = [
            _make_record(
                axis_labels_extracted=["2021", "2022"],
                axis_labels_reference=["2021", "2022"],
            )
        ]
        assert ocr_axis_label_accuracy_score(records) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# title_match_score / legend_match_score
# ---------------------------------------------------------------------------


class TestTitleAndLegendScores:
    def test_no_reviewer_notes(self) -> None:
        records = [_make_record(reviewer_notes="")]
        assert title_match_score(records) == pytest.approx(1.0)
        assert legend_match_score(records) == pytest.approx(1.0)

    def test_perfect_title_match(self) -> None:
        records = [
            _make_record(
                reviewer_notes="Cohort Revenue Retention",
                title_extracted="Cohort Revenue Retention",
            )
        ]
        assert title_match_score(records) == pytest.approx(1.0)

    def test_partial_title_match(self) -> None:
        records = [
            _make_record(
                reviewer_notes="Cohort Revenue Retention",
                title_extracted="Revenue Retention",
            )
        ]
        score = title_match_score(records)
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# tier1_fact_recall_score
# ---------------------------------------------------------------------------


class TestTier1FactRecall:
    def test_no_facts_in_db(self) -> None:
        # Images with zero DB facts don't penalise recall
        records = [_make_record(tier1_facts_in_db=0, tier1_facts_extracted=0)]
        assert tier1_fact_recall_score(records) == pytest.approx(1.0)

    def test_perfect_recall(self) -> None:
        records = [_make_record(tier1_facts_in_db=3, tier1_facts_extracted=3)]
        assert tier1_fact_recall_score(records) == pytest.approx(1.0)

    def test_partial_recall(self) -> None:
        records = [_make_record(tier1_facts_in_db=4, tier1_facts_extracted=2)]
        assert tier1_fact_recall_score(records) == pytest.approx(0.5)

    def test_recall_capped_at_one(self) -> None:
        # Model extracted more facts than were in DB (e.g. different counting)
        records = [_make_record(tier1_facts_in_db=2, tier1_facts_extracted=5)]
        assert tier1_fact_recall_score(records) == pytest.approx(1.0)

    def test_multiple_images(self) -> None:
        records = [
            _make_record(img_id="a", tier1_facts_in_db=4, tier1_facts_extracted=2),
            _make_record(img_id="b", tier1_facts_in_db=6, tier1_facts_extracted=6),
        ]
        # total_in_db=10, total_extracted=8 → 0.8
        assert tier1_fact_recall_score(records) == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# parse_failure_rate
# ---------------------------------------------------------------------------


class TestParseFailureRate:
    def test_no_failures(self) -> None:
        records = [_make_record(parse_failed=False), _make_record(parse_failed=False)]
        assert parse_failure_rate(records) == pytest.approx(0.0)

    def test_all_failures(self) -> None:
        records = [_make_record(parse_failed=True), _make_record(parse_failed=True)]
        assert parse_failure_rate(records) == pytest.approx(1.0)

    def test_half_failures(self) -> None:
        records = [_make_record(parse_failed=True), _make_record(parse_failed=False)]
        assert parse_failure_rate(records) == pytest.approx(0.5)

    def test_empty_records(self) -> None:
        assert parse_failure_rate([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# aggregate_results
# ---------------------------------------------------------------------------


class TestAggregateResults:
    def test_empty_corpus(self) -> None:
        result = aggregate_results([])
        assert result.n_images == 0
        assert result.chart_detection_precision == 0.0
        assert result.chart_detection_recall == 0.0
        assert result.chart_detection_f1 == 0.0

    def test_single_correct_prediction(self) -> None:
        records = [_make_record(cost_usd=0.01, latency_ms=500)]
        result = aggregate_results(records)
        assert result.n_images == 1
        assert result.n_relevant == 1
        assert result.n_not_relevant == 0
        assert result.mean_cost_usd == pytest.approx(0.01)
        assert result.mean_latency_ms == pytest.approx(500.0)

    def test_returns_image_eval_result_type(self) -> None:
        result = aggregate_results([_make_record()])
        assert isinstance(result, ImageEvalResult)

    def test_full_metrics_smoke(self) -> None:
        """Smoke: aggregate_results with varied records completes without error."""
        records = [
            _make_record(
                img_id="a",
                reviewer_decision="relevant",
                predicted_relevant=True,
                ocr_cells_extracted=["10%", "20%"],
                ocr_cells_reference=["10%", "20%"],
                axis_labels_extracted=["2021", "2022"],
                axis_labels_reference=["2021", "2022"],
                title_extracted="Cohort Table",
                reviewer_notes="Cohort Table",
                tier1_facts_in_db=2,
                tier1_facts_extracted=2,
                cost_usd=0.005,
                latency_ms=1000,
            ),
            _make_record(
                img_id="b",
                reviewer_decision="not_relevant",
                reviewer_chart_type=None,
                predicted_relevant=False,
                predicted_chart_type=None,
                parse_failed=True,
                cost_usd=0.001,
                latency_ms=200,
            ),
        ]
        result = aggregate_results(records)
        assert result.n_images == 2
        assert result.n_relevant == 1
        assert result.n_not_relevant == 1
        assert result.parse_failure_rate == pytest.approx(0.5)
        assert result.mean_cost_usd == pytest.approx(0.003)
        assert result.chart_detection_precision == pytest.approx(1.0)
        assert result.chart_detection_recall == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# stratum_label / tier helpers
# ---------------------------------------------------------------------------


class TestStratumHelpers:
    def test_relevant_stratum(self) -> None:
        assert stratum_label("relevant", "cohort_table", None) == "chart/cohort_table"

    def test_not_relevant_stratum(self) -> None:
        assert stratum_label("not_relevant", None, "decorative") == "rejection/decorative"

    def test_unknown_stratum(self) -> None:
        assert stratum_label("relevant", None, None) == "unknown"

    def test_is_tier1_image(self) -> None:
        assert is_tier1_image("cohort_table") is True
        assert is_tier1_image("cohort_parfait") is True
        assert is_tier1_image("mixed") is True
        assert is_tier1_image("bar_chart") is False
        assert is_tier1_image(None) is False

    def test_is_hard_ocr_image(self) -> None:
        assert is_hard_ocr_image("cohort_table") is True
        assert is_hard_ocr_image("line_chart") is False
        assert is_hard_ocr_image(None) is False

    def test_chart_types_constant(self) -> None:
        # Verify constant matches the migration 29 values
        assert "cohort_table" in CHART_TYPES
        assert "cohort_parfait" in CHART_TYPES
        assert "line_chart" in CHART_TYPES
        assert len(CHART_TYPES) == 7

    def test_rejection_reasons_constant(self) -> None:
        assert "decorative" in REJECTION_REASONS
        assert "not_a_chart" in REJECTION_REASONS
        assert len(REJECTION_REASONS) == 6


# ---------------------------------------------------------------------------
# Wave B5.x — chart-data fidelity (chart-read mode)
# ---------------------------------------------------------------------------


class TestDataValueMatch:
    """`data_value_match` pairs numeric values within relative tolerance."""

    def test_empty_inputs(self) -> None:
        assert data_value_match([], []) == (0, 0, 0)

    def test_empty_reference_all_extracted_become_fp(self) -> None:
        tp, fp, fn = data_value_match([{"value": 1.0}, {"value": 2.0}], [])
        assert (tp, fp, fn) == (0, 2, 0)

    def test_empty_extracted_all_reference_become_fn(self) -> None:
        tp, fp, fn = data_value_match([], [{"value": 3.0}, {"value": 4.0}])
        assert (tp, fp, fn) == (0, 0, 2)

    def test_exact_match_counts_as_tp(self) -> None:
        tp, fp, fn = data_value_match(
            [{"value": 44.4}, {"value": 55.6}],
            [{"value": 44.4}, {"value": 55.6}],
        )
        assert (tp, fp, fn) == (2, 0, 0)

    def test_tolerance_window(self) -> None:
        # 0.5% off a value of 100 is within the default 2% tolerance.
        tp, fp, fn = data_value_match([{"value": 100.5}], [{"value": 100.0}], rel_tol=0.02)
        assert (tp, fp, fn) == (1, 0, 0)
        # 5% off is outside.
        tp, fp, fn = data_value_match([{"value": 105.0}], [{"value": 100.0}], rel_tol=0.02)
        assert (tp, fp, fn) == (0, 1, 1)

    def test_partial_match_mixed_tp_fp_fn(self) -> None:
        # Model emits [44.4, 99.9]; truth is [44.4, 55.6].
        tp, fp, fn = data_value_match(
            [{"value": 44.4}, {"value": 99.9}],
            [{"value": 44.4}, {"value": 55.6}],
        )
        assert (tp, fp, fn) == (1, 1, 1)

    def test_duplicate_extracted_does_not_double_count(self) -> None:
        # Two extracted 44.4s, one truth 44.4 → TP=1, FP=1 (the spare
        # extracted is not re-matched).
        tp, fp, fn = data_value_match(
            [{"value": 44.4}, {"value": 44.4}],
            [{"value": 44.4}],
        )
        assert (tp, fp, fn) == (1, 1, 0)

    def test_non_numeric_extracted_is_ignored(self) -> None:
        tp, fp, fn = data_value_match(
            [{"value": "not a number"}, {"value": 44.4}, {"value": None}],
            [{"value": 44.4}],
        )
        assert (tp, fp, fn) == (1, 0, 0)


def _record_with_data(*, tp: int, fp: int, fn: int, img_id: str = "img") -> ImageRunRecord:
    """Minimal record carrying chart-read scoring fields."""
    return ImageRunRecord(
        img_id=img_id,
        reviewer_decision="relevant",
        reviewer_chart_type="cohort_table",
        reviewer_notes="",
        tier1_facts_in_db=0,
        predicted_chart_type="cohort_table",
        predicted_relevant=True,
        reference_points=[{"value": 1.0}] * (tp + fn),
        extracted_points=[{"value": 1.0}] * (tp + fp),
        data_value_tp=tp,
        data_value_fp=fp,
        data_value_fn=fn,
    )


class TestDataValueScores:
    """`data_value_scores` micro-averages TP/FP/FN across records."""

    def test_no_records_scored_returns_zeros(self) -> None:
        # Record has no reference_points → not scored.
        rec = ImageRunRecord(
            img_id="x",
            reviewer_decision="relevant",
            reviewer_chart_type="cohort_table",
            reviewer_notes="",
            tier1_facts_in_db=0,
            predicted_chart_type="cohort_table",
            predicted_relevant=True,
        )
        p, r, f1, n = data_value_scores([rec])
        assert (p, r, f1, n) == (0.0, 0.0, 0.0, 0)

    def test_micro_average_across_records(self) -> None:
        # Record A: TP=1, FP=1, FN=1.  Record B: TP=2, FP=0, FN=0.
        # Micro: TP=3, FP=1, FN=1 → P=3/4=0.75, R=3/4=0.75, F1=0.75.
        records = [
            _record_with_data(tp=1, fp=1, fn=1, img_id="a"),
            _record_with_data(tp=2, fp=0, fn=0, img_id="b"),
        ]
        p, r, f1, n = data_value_scores(records)
        assert n == 2
        assert p == pytest.approx(0.75)
        assert r == pytest.approx(0.75)
        assert f1 == pytest.approx(0.75)


class TestAggregateResultsDataFields:
    """`aggregate_results` populates the new chart-data fields."""

    def test_new_fields_defaulted_when_no_data_scoring(self) -> None:
        # A record with no reference_points should leave data fields zeroed.
        rec = ImageRunRecord(
            img_id="x",
            reviewer_decision="relevant",
            reviewer_chart_type="cohort_table",
            reviewer_notes="",
            tier1_facts_in_db=0,
            predicted_chart_type="cohort_table",
            predicted_relevant=True,
        )
        agg = aggregate_results([rec])
        assert agg.data_value_precision == 0.0
        assert agg.data_value_recall == 0.0
        assert agg.data_value_f1 == 0.0
        assert agg.n_images_scored_on_data == 0

    def test_new_fields_populated_when_records_carry_reference(self) -> None:
        records = [_record_with_data(tp=1, fp=1, fn=1)]
        agg = aggregate_results(records)
        assert agg.data_value_precision == pytest.approx(0.5)
        assert agg.data_value_recall == pytest.approx(0.5)
        assert agg.data_value_f1 == pytest.approx(0.5)
        assert agg.n_images_scored_on_data == 1


# ---------------------------------------------------------------------------
# metric-classify — reviewer-disposition scoring
# ---------------------------------------------------------------------------


def _record_with_classify(
    *,
    predicted: list[str],
    reference: list[str],
    confidence: float = 0.8,
    rejection_reason: str | None = None,
    img_id: str = "img",
) -> ImageRunRecord:
    """Minimal record carrying metric-classify scoring fields."""
    return ImageRunRecord(
        img_id=img_id,
        reviewer_decision="relevant",
        reviewer_chart_type="cohort_table",
        reviewer_notes="",
        tier1_facts_in_db=0,
        predicted_chart_type=None,
        predicted_relevant=bool(predicted),
        predicted_metrics=predicted,
        reference_metrics=reference,
        classification_confidence=confidence,
        rejection_reason=rejection_reason,
        reviewer_action=reviewer_action(predicted, reference),
    )


class TestReviewerAction:
    """`reviewer_action` maps (predicted, reference) to a single bucket."""

    def test_both_empty_is_skip(self) -> None:
        assert reviewer_action([], []) == "skip"

    def test_exact_non_empty_match_is_accept(self) -> None:
        assert reviewer_action(["cm_arr"], ["cm_arr"]) == "accept"
        assert (
            reviewer_action(["cm_arr", "cm_mrr"], ["cm_mrr", "cm_arr"]) == "accept"
        )  # set equality, order-agnostic

    def test_reference_empty_is_reject(self) -> None:
        assert reviewer_action(["cm_arr"], []) == "reject"

    def test_predicted_empty_with_reference_is_add(self) -> None:
        assert reviewer_action([], ["cm_arr"]) == "add"

    def test_proper_subset_is_add(self) -> None:
        # Predicted missed a metric; reviewer adds the rest.
        assert reviewer_action(["cm_arr"], ["cm_arr", "cm_mrr"]) == "add"

    def test_proper_superset_is_partial(self) -> None:
        # Predicted added a bogus metric on top of a correct one — reviewer
        # rejects the extra but keeps the accept.
        assert reviewer_action(["cm_arr", "cm_mrr"], ["cm_arr"]) == "partial"

    def test_disjoint_non_empty_is_correct(self) -> None:
        assert reviewer_action(["cm_arr"], ["cm_mrr"]) == "correct"

    def test_overlap_neither_subset_is_partial(self) -> None:
        # Shared: cm_arr; predicted-only: cm_mrr; reference-only: cm_customer_retention_rate.
        assert (
            reviewer_action(["cm_arr", "cm_mrr"], ["cm_arr", "cm_customer_retention_rate"])
            == "partial"
        )

    def test_reviewer_actions_constant_includes_all_buckets(self) -> None:
        assert set(REVIEWER_ACTIONS) == {
            "accept",
            "reject",
            "correct",
            "add",
            "partial",
            "skip",
        }


class TestMetricTagMatch:
    """`metric_tag_match` counts TP/FP/FN from set overlap."""

    def test_both_empty_returns_zero(self) -> None:
        assert metric_tag_match([], []) == (0, 0, 0)

    def test_exact_match(self) -> None:
        assert metric_tag_match(["a", "b"], ["a", "b"]) == (2, 0, 0)

    def test_only_predicted(self) -> None:
        assert metric_tag_match(["a", "b"], []) == (0, 2, 0)

    def test_only_reference(self) -> None:
        assert metric_tag_match([], ["a", "b"]) == (0, 0, 2)

    def test_partial_overlap(self) -> None:
        assert metric_tag_match(["a", "b"], ["a", "c"]) == (1, 1, 1)

    def test_duplicate_predicted_does_not_inflate_tp(self) -> None:
        # Sets dedup — ["a", "a"] is {"a"}.
        assert metric_tag_match(["a", "a"], ["a"]) == (1, 0, 0)


class TestMetricTagScores:
    """`metric_tag_scores` micro-averages across records with reference_metrics."""

    def test_no_records_scored(self) -> None:
        rec = _record_with_classify(predicted=["cm_arr"], reference=[])
        p, r, f1, n = metric_tag_scores([rec])
        assert (p, r, f1, n) == (0.0, 0.0, 0.0, 0)

    def test_micro_average(self) -> None:
        # A: predicted={arr}, ref={arr,mrr} → TP=1, FP=0, FN=1
        # B: predicted={arr,mrr}, ref={arr,mrr} → TP=2, FP=0, FN=0
        # Micro: TP=3, FP=0, FN=1 → P=1.0, R=0.75, F1=0.857
        recs = [
            _record_with_classify(predicted=["cm_arr"], reference=["cm_arr", "cm_mrr"]),
            _record_with_classify(predicted=["cm_arr", "cm_mrr"], reference=["cm_arr", "cm_mrr"]),
        ]
        p, r, f1, n = metric_tag_scores(recs)
        assert n == 2
        assert p == pytest.approx(1.0)
        assert r == pytest.approx(0.75)
        assert f1 == pytest.approx(2 * 1.0 * 0.75 / 1.75)


class TestExpectedCalibrationError:
    """`expected_calibration_error` bins confidence vs accept-accuracy."""

    def test_empty_corpus_returns_zero(self) -> None:
        assert expected_calibration_error([]) == pytest.approx(0.0)

    def test_all_records_without_reference_returns_zero(self) -> None:
        rec = _record_with_classify(predicted=["cm_arr"], reference=[])
        assert expected_calibration_error([rec]) == pytest.approx(0.0)

    def test_perfectly_calibrated_is_zero(self) -> None:
        # 10 records, all at conf=1.0, all accept → bin accuracy=1.0, bin mean_conf=1.0
        records = [
            _record_with_classify(
                predicted=["cm_arr"],
                reference=["cm_arr"],
                confidence=1.0,
                img_id=f"img-{i}",
            )
            for i in range(10)
        ]
        assert expected_calibration_error(records) == pytest.approx(0.0)

    def test_overconfident_all_wrong(self) -> None:
        # 10 records at conf=1.0 all emitting wrong metric → accuracy=0
        # in that bin; ECE = |0 - 1.0| * 1.0 = 1.0.
        records = [
            _record_with_classify(
                predicted=["cm_mrr"],
                reference=["cm_arr"],
                confidence=1.0,
                img_id=f"img-{i}",
            )
            for i in range(10)
        ]
        assert expected_calibration_error(records) == pytest.approx(1.0)

    def test_underconfident_all_right(self) -> None:
        # 10 records at conf=0.1 all accept → bin accuracy=1.0, mean_conf≈0.1
        # ECE = |1.0 - 0.1| = 0.9.
        records = [
            _record_with_classify(
                predicted=["cm_arr"],
                reference=["cm_arr"],
                confidence=0.1,
                img_id=f"img-{i}",
            )
            for i in range(10)
        ]
        assert expected_calibration_error(records) == pytest.approx(0.9)

    def test_confidence_one_falls_in_last_bin(self) -> None:
        """Conf=1.0 must map into bin index ``n_bins - 1`` (not n_bins)."""
        rec = _record_with_classify(predicted=["cm_arr"], reference=["cm_arr"], confidence=1.0)
        assert expected_calibration_error([rec], n_bins=4) == pytest.approx(0.0)

    def test_rejects_non_positive_n_bins(self) -> None:
        rec = _record_with_classify(predicted=["cm_arr"], reference=["cm_arr"])
        with pytest.raises(ValueError, match="n_bins must be positive"):
            expected_calibration_error([rec], n_bins=0)


class TestReviewerActionCounts:
    """`reviewer_action_counts` counts records in each bucket, defaulting zeros."""

    def test_every_bucket_present_with_zero_default(self) -> None:
        counts = reviewer_action_counts([])
        assert set(counts) == set(REVIEWER_ACTIONS)
        assert all(v == 0 for v in counts.values())

    def test_counts_one_per_bucket(self) -> None:
        records = [
            _record_with_classify(predicted=["a"], reference=["a"], img_id="1"),  # accept
            _record_with_classify(predicted=["a"], reference=[], img_id="2"),  # reject
            _record_with_classify(predicted=["a"], reference=["b"], img_id="3"),  # correct
            _record_with_classify(predicted=[], reference=["a"], img_id="4"),  # add
            _record_with_classify(predicted=["a", "b"], reference=["a"], img_id="5"),  # partial
            _record_with_classify(predicted=[], reference=[], img_id="6"),  # skip
        ]
        counts = reviewer_action_counts(records)
        assert counts == {
            "accept": 1,
            "reject": 1,
            "correct": 1,
            "add": 1,
            "partial": 1,
            "skip": 1,
        }


class TestAggregateResultsMetricFields:
    """`aggregate_results` populates the classify-mode fields."""

    def test_rates_sum_to_one(self) -> None:
        records = [
            _record_with_classify(predicted=["a"], reference=["a"], img_id="1"),
            _record_with_classify(predicted=["a"], reference=[], img_id="2"),
            _record_with_classify(predicted=[], reference=[], img_id="3"),
        ]
        agg = aggregate_results(records)
        total = (
            agg.accept_rate
            + agg.reject_rate
            + agg.correct_rate
            + agg.add_rate
            + agg.partial_rate
            + agg.skip_rate
        )
        assert total == pytest.approx(1.0)

    def test_auto_disposition_is_accept_plus_skip(self) -> None:
        records = [
            _record_with_classify(predicted=["a"], reference=["a"], img_id="1"),
            _record_with_classify(predicted=[], reference=[], img_id="2"),
            _record_with_classify(predicted=["a"], reference=["b"], img_id="3"),
        ]
        agg = aggregate_results(records)
        assert agg.accept_rate == pytest.approx(1 / 3)
        assert agg.skip_rate == pytest.approx(1 / 3)
        assert agg.auto_disposition_rate == pytest.approx(2 / 3)

    def test_metric_tag_f1_and_ece_populated_when_reference_present(self) -> None:
        records = [
            _record_with_classify(
                predicted=["cm_arr"],
                reference=["cm_arr"],
                confidence=0.9,
                img_id="1",
            ),
            _record_with_classify(
                predicted=["cm_mrr"],
                reference=["cm_arr"],
                confidence=0.9,
                img_id="2",
            ),
        ]
        agg = aggregate_results(records)
        assert agg.n_images_scored_on_metric_tags == 2
        # TP=1 (img1 arr), FP=1 (img2 mrr), FN=1 (img2 arr missed)
        assert agg.metric_tag_precision == pytest.approx(0.5)
        assert agg.metric_tag_recall == pytest.approx(0.5)
        assert agg.metric_tag_f1 == pytest.approx(0.5)
        # img1 accept, img2 correct — bin at conf=0.9 has accuracy=0.5, mean_conf=0.9 →
        # ECE ~ |0.5 - 0.9| = 0.4
        assert agg.calibration_ece == pytest.approx(0.4)

    def test_classify_fields_zero_when_records_lack_reference(self) -> None:
        records = [_record_with_classify(predicted=["cm_arr"], reference=[], img_id="1")]
        agg = aggregate_results(records)
        assert agg.n_images_scored_on_metric_tags == 0
        assert agg.metric_tag_precision == 0.0
        assert agg.calibration_ece == 0.0

    def test_returns_image_eval_result_type(self) -> None:
        agg = aggregate_results([_record_with_classify(predicted=["a"], reference=["a"])])
        assert isinstance(agg, ImageEvalResult)
