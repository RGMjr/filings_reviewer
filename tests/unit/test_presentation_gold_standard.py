"""
Unit tests for the presentation gold standard pipeline scripts.

Tests cover:
  - merge_presentation_annotations: filter_valid_annotations, dedup_annotations, assign_split
  - validate_presentation_extraction: match_facts_to_annotations, compute_scores
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.merge_presentation_annotations import (  # noqa: E402
    assign_split,
    dedup_annotations,
    filter_valid_annotations,
)
from scripts.validate_presentation_extraction import (  # noqa: E402
    compute_scores,
    match_facts_to_annotations,
)

# ============================================================================
# filter_valid_annotations
# ============================================================================


class TestFilterValidAnnotations:
    def _row(self, disposition: str, is_trap: str = "false") -> dict:
        return {
            "ticker": "CRM",
            "date": "2025-01-01",
            "metric_id": "cm_arr",
            "value": "100",
            "disposition": disposition,
            "is_trap": is_trap,
        }

    def test_accept_kept(self):
        rows = [self._row("ACCEPT")]
        assert len(filter_valid_annotations(rows)) == 1

    def test_edit_kept(self):
        rows = [self._row("EDIT")]
        assert len(filter_valid_annotations(rows)) == 1

    def test_reject_excluded(self):
        rows = [self._row("REJECT")]
        assert filter_valid_annotations(rows) == []

    def test_skip_excluded(self):
        rows = [self._row("SKIP")]
        assert filter_valid_annotations(rows) == []

    def test_is_trap_excluded(self):
        rows = [self._row("ACCEPT", is_trap="true")]
        assert filter_valid_annotations(rows) == []

    def test_is_trap_true_upper_excluded(self):
        rows = [self._row("ACCEPT", is_trap="True")]
        assert filter_valid_annotations(rows) == []

    def test_mixed_batch(self):
        rows = [
            self._row("ACCEPT"),
            self._row("EDIT"),
            self._row("REJECT"),
            self._row("SKIP"),
            self._row("ACCEPT", is_trap="true"),
        ]
        valid = filter_valid_annotations(rows)
        assert len(valid) == 2
        assert all(r["disposition"] in ("ACCEPT", "EDIT") for r in valid)

    def test_empty_input(self):
        assert filter_valid_annotations([]) == []

    def test_case_insensitive_disposition(self):
        rows = [self._row("accept"), self._row("EDIT")]
        valid = filter_valid_annotations(rows)
        assert len(valid) == 2


# ============================================================================
# dedup_annotations
# ============================================================================


class TestDedupAnnotations:
    def _row(self, ticker: str, date: str, metric_id: str, value: str) -> dict:
        return {
            "ticker": ticker,
            "date": date,
            "metric_id": metric_id,
            "value": value,
            "unit": "count",
        }

    def test_no_duplicates_kept_as_is(self):
        rows = [
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
            self._row("CRM", "2025-01-01", "cm_arr", "200"),
        ]
        result = dedup_annotations(rows)
        assert len(result) == 2

    def test_duplicate_removed(self):
        rows = [
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
        ]
        result = dedup_annotations(rows)
        assert len(result) == 1

    def test_different_ticker_not_deduped(self):
        rows = [
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
            self._row("ADBE", "2025-01-01", "cm_arr", "100"),
        ]
        result = dedup_annotations(rows)
        assert len(result) == 2

    def test_different_date_not_deduped(self):
        rows = [
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
            self._row("CRM", "2025-04-01", "cm_arr", "100"),
        ]
        result = dedup_annotations(rows)
        assert len(result) == 2

    def test_first_occurrence_kept(self):
        rows = [
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
            self._row("CRM", "2025-01-01", "cm_arr", "100"),
        ]
        rows[0]["unit"] = "currency"
        rows[1]["unit"] = "count"
        result = dedup_annotations(rows)
        assert result[0]["unit"] == "currency"

    def test_empty_input(self):
        assert dedup_annotations([]) == []


# ============================================================================
# assign_split
# ============================================================================


class TestAssignSplit:
    def test_fresh_split_test_companies_assigned_to_test(self):
        tickers = {"CRM", "ADBE", "META", "MSFT"}
        split = assign_split(tickers, None, {"META", "MSFT"}, force_resplit=False)
        assert split["META"] == "test"
        assert split["MSFT"] == "test"
        assert split["CRM"] == "tuning"
        assert split["ADBE"] == "tuning"

    def test_fresh_split_unknown_companies_go_to_tuning(self):
        tickers = {"CRM", "UNKNOWN_CO"}
        split = assign_split(tickers, None, {"META"}, force_resplit=False)
        assert split["CRM"] == "tuning"
        assert split["UNKNOWN_CO"] == "tuning"

    def test_existing_split_preserved_without_force(self):
        existing = {"assignments": {"CRM": "test", "ADBE": "tuning"}}
        tickers = {"CRM", "ADBE"}
        split = assign_split(tickers, existing, set(), force_resplit=False)
        assert split["CRM"] == "test"
        assert split["ADBE"] == "tuning"

    def test_new_company_added_to_tuning_when_not_in_test_set(self):
        existing = {"assignments": {"CRM": "tuning"}}
        tickers = {"CRM", "NEWCO"}
        split = assign_split(tickers, existing, set(), force_resplit=False)
        assert split["NEWCO"] == "tuning"

    def test_new_company_added_to_test_when_in_test_set(self):
        existing = {"assignments": {"CRM": "tuning"}}
        tickers = {"CRM", "META"}
        split = assign_split(tickers, existing, {"META"}, force_resplit=False)
        assert split["META"] == "test"

    def test_force_resplit_overwrites_existing(self):
        existing = {"assignments": {"CRM": "test"}}
        tickers = {"CRM"}
        split = assign_split(tickers, existing, set(), force_resplit=True)
        assert split["CRM"] == "tuning"

    def test_deterministic_alphabetical_order(self):
        tickers = {"ZZZZ", "AAAA", "MMMM"}
        split1 = assign_split(tickers, None, set(), force_resplit=False)
        split2 = assign_split(tickers, None, set(), force_resplit=False)
        assert split1 == split2

    def test_empty_tickers(self):
        split = assign_split(set(), None, set(), force_resplit=False)
        assert split == {}


# ============================================================================
# match_facts_to_annotations (validate_presentation_extraction)
# ============================================================================


def _make_fact(metric_id: str, value: float | None) -> MagicMock:
    """Create a mock MetricFact-like object."""
    fact = MagicMock()
    fact.canonical_metric_id = metric_id
    fact.value = value
    return fact


def _make_ann(metric_id: str, value: str) -> dict:
    return {"metric_id": metric_id, "value": value}


class TestMatchFactsToAnnotations:
    def test_exact_match(self):
        facts = [_make_fact("cm_arr", 100.0)]
        anns = [_make_ann("cm_arr", "100")]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 1
        assert len(result["unmatched_annotations"]) == 0
        assert len(result["unmatched_facts"]) == 0

    def test_within_5pct_tolerance_lower_bound(self):
        # 0.95 * reference = lower tolerance boundary (exactly on edge)
        reference = 100.0
        value = reference * 0.95
        facts = [_make_fact("cm_arr", value)]
        anns = [_make_ann("cm_arr", str(reference))]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 1

    def test_within_5pct_tolerance_upper_bound(self):
        # 1.05 * reference = upper tolerance boundary (exactly on edge)
        reference = 100.0
        value = reference * 1.05
        facts = [_make_fact("cm_arr", value)]
        anns = [_make_ann("cm_arr", str(reference))]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 1

    def test_outside_tolerance_not_matched(self):
        facts = [_make_fact("cm_arr", 106.0)]
        anns = [_make_ann("cm_arr", "100")]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 0
        assert len(result["unmatched_annotations"]) == 1
        assert len(result["unmatched_facts"]) == 1

    def test_metric_id_mismatch_not_matched(self):
        facts = [_make_fact("cm_arr", 100.0)]
        anns = [_make_ann("cm_mrr", "100")]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 0

    def test_zero_value_exact_match(self):
        facts = [_make_fact("cm_arr", 0.0)]
        anns = [_make_ann("cm_arr", "0")]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 1

    def test_non_numeric_annotation_matches_on_metric_id_only(self):
        facts = [_make_fact("cm_arr", 100.0)]
        anns = [_make_ann("cm_arr", "N/A")]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 1

    def test_no_double_match(self):
        # Two facts same metric_id/value — should match only first annotation
        facts = [_make_fact("cm_arr", 100.0), _make_fact("cm_arr", 100.0)]
        anns = [_make_ann("cm_arr", "100")]
        result = match_facts_to_annotations(facts, anns)
        assert len(result["matched"]) == 1
        assert len(result["unmatched_facts"]) == 1

    def test_empty_facts(self):
        anns = [_make_ann("cm_arr", "100")]
        result = match_facts_to_annotations([], anns)
        assert len(result["matched"]) == 0
        assert len(result["unmatched_annotations"]) == 1
        assert len(result["unmatched_facts"]) == 0

    def test_empty_annotations(self):
        facts = [_make_fact("cm_arr", 100.0)]
        result = match_facts_to_annotations(facts, [])
        assert len(result["matched"]) == 0
        assert len(result["unmatched_facts"]) == 1

    def test_none_value_fact_not_matched_on_numeric_ann(self):
        facts = [_make_fact("cm_arr", None)]
        anns = [_make_ann("cm_arr", "100")]
        result = match_facts_to_annotations(facts, anns)
        # fact.value is None and ann is numeric — no match
        assert len(result["matched"]) == 0


# ============================================================================
# compute_scores
# ============================================================================


class TestComputeScores:
    def _match_result(self, matched: int, fn: int, fp: int) -> dict:
        return {
            "matched": [MagicMock()] * matched,
            "unmatched_annotations": [{}] * fn,
            "unmatched_facts": [MagicMock()] * fp,
        }

    def test_perfect_recall_precision(self):
        scores = compute_scores(self._match_result(5, 0, 0))
        assert scores["recall"] == pytest.approx(1.0)
        assert scores["precision"] == pytest.approx(1.0)
        assert scores["f1"] == pytest.approx(1.0)

    def test_all_missed(self):
        scores = compute_scores(self._match_result(0, 5, 0))
        assert scores["recall"] == pytest.approx(0.0)
        assert scores["precision"] == pytest.approx(0.0)
        assert scores["f1"] == pytest.approx(0.0)

    def test_all_false_positives(self):
        scores = compute_scores(self._match_result(0, 0, 5))
        assert scores["recall"] == pytest.approx(0.0)
        assert scores["precision"] == pytest.approx(0.0)
        assert scores["f1"] == pytest.approx(0.0)

    def test_partial_recall_perfect_precision(self):
        scores = compute_scores(self._match_result(3, 2, 0))
        assert scores["recall"] == pytest.approx(3 / 5)
        assert scores["precision"] == pytest.approx(1.0)

    def test_perfect_recall_partial_precision(self):
        scores = compute_scores(self._match_result(3, 0, 2))
        assert scores["recall"] == pytest.approx(1.0)
        assert scores["precision"] == pytest.approx(3 / 5)

    def test_f1_harmonic_mean(self):
        scores = compute_scores(self._match_result(3, 2, 2))
        r = 3 / 5
        p = 3 / 5
        expected_f1 = 2 * r * p / (r + p)
        assert scores["f1"] == pytest.approx(expected_f1)

    def test_zero_division_safe(self):
        scores = compute_scores(self._match_result(0, 0, 0))
        assert scores["recall"] == 0.0
        assert scores["precision"] == 0.0
        assert scores["f1"] == 0.0
