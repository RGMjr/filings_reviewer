"""Unit tests for src/web/text_decision_category_actions.py.

Pure-function tests — no Flask, no DB.  Covers CATEGORY_ACTIONS content,
compute_category_rollup aggregation, severity thresholds, and empty-input
contract.
"""

from __future__ import annotations

from src.web.text_decision_category_actions import (
    CATEGORY_ACTIONS,
    compute_category_rollup,
)

# ---------------------------------------------------------------------------
# CATEGORY_ACTIONS sanity checks
# ---------------------------------------------------------------------------


class TestCategoryActionsDict:
    EXPECTED_KEYS = {
        "part_of_date",
        "wrong_period",
        "not_a_metric",
        "wrong_metric",
        "wrong_value",
        "duplicate",
        "other",
    }

    def test_all_expected_keys_present(self):
        assert self.EXPECTED_KEYS <= set(CATEGORY_ACTIONS.keys())

    def test_each_entry_has_required_fields(self):
        required = {
            "label",
            "description",
            "example",
            "action",
            "target_file",
            "severity_thresholds",
        }
        for cat, meta in CATEGORY_ACTIONS.items():
            missing = required - set(meta.keys())
            assert not missing, f"Category '{cat}' is missing fields: {missing}"

    def test_reject_form_metadata_is_reviewer_facing(self):
        """Every category that appears in the Reject-form dropdown needs a
        non-empty label, description, and example so the inline help in
        unified_review.html has something to render.

        Coverage check: every enum value in REJECTION_CATEGORIES must be a key
        in CATEGORY_ACTIONS — otherwise the Jinja loop emits an empty option.
        """
        from src.review.models import REJECTION_CATEGORIES

        for cat in REJECTION_CATEGORIES:
            assert cat in CATEGORY_ACTIONS, (
                f"Enum value '{cat}' from REJECTION_CATEGORIES is missing in CATEGORY_ACTIONS"
            )
            meta = CATEGORY_ACTIONS[cat]
            assert meta["label"], f"'{cat}' must have a non-empty label"
            assert meta["description"], f"'{cat}' must have a non-empty description"
            assert meta["example"], f"'{cat}' must have a non-empty example"

    def test_severity_thresholds_are_ordered(self):
        for cat, meta in CATEGORY_ACTIONS.items():
            medium, high = meta["severity_thresholds"]
            assert medium < high, (
                f"Category '{cat}' severity_thresholds must be (medium, high) in ascending order"
            )

    def test_part_of_date_has_target_file(self):
        assert "false_positive_filter" in CATEGORY_ACTIONS["part_of_date"]["target_file"]

    def test_not_a_metric_targets_yaml(self):
        assert "metric_keywords.yaml" in CATEGORY_ACTIONS["not_a_metric"]["target_file"]


# ---------------------------------------------------------------------------
# compute_category_rollup — basic aggregation
# ---------------------------------------------------------------------------


def _summary(metric_id: str = "cm_x", rejection_categories: dict | None = None) -> dict:
    return {
        "metric_id": metric_id,
        "total_decisions": 50,
        "accept_count": 5,
        "reject_count": 31,
        "correct_count": 14,
        "rejection_categories": rejection_categories or {},
        "top_correction_targets": [],
    }


class TestComputeCategoryRollup:
    def test_empty_summaries_return_empty_list(self):
        assert compute_category_rollup([]) == []

    def test_summaries_with_no_rejection_categories_return_empty(self):
        out = compute_category_rollup([_summary(rejection_categories={})])
        assert out == []

    def test_single_category_appears_in_output(self):
        s = _summary(rejection_categories={"part_of_date": 10})
        out = compute_category_rollup([s])
        assert len(out) == 1
        row = out[0]
        assert row["category"] == "part_of_date"
        assert row["count"] == 10
        assert row["pct_of_rejects"] == 100.0

    def test_multiple_categories_aggregated_across_metrics(self):
        s1 = _summary("cm_a", {"part_of_date": 10, "wrong_value": 5})
        s2 = _summary("cm_b", {"part_of_date": 5, "not_a_metric": 3})
        out = compute_category_rollup([s1, s2])
        by_cat = {r["category"]: r for r in out}
        assert by_cat["part_of_date"]["count"] == 15
        assert by_cat["wrong_value"]["count"] == 5
        assert by_cat["not_a_metric"]["count"] == 3

    def test_sorted_desc_by_count(self):
        s = _summary(rejection_categories={"other": 2, "part_of_date": 20, "wrong_value": 5})
        out = compute_category_rollup([s])
        counts = [r["count"] for r in out]
        assert counts == sorted(counts, reverse=True)

    def test_pct_of_rejects_sums_to_100(self):
        s = _summary(rejection_categories={"part_of_date": 50, "wrong_value": 50})
        out = compute_category_rollup([s])
        total_pct = sum(r["pct_of_rejects"] for r in out)
        assert abs(total_pct - 100.0) < 0.5  # rounding tolerance

    def test_label_populated_from_category_actions(self):
        s = _summary(rejection_categories={"part_of_date": 10})
        out = compute_category_rollup([s])
        assert out[0]["label"] == CATEGORY_ACTIONS["part_of_date"]["label"]

    def test_action_populated(self):
        s = _summary(rejection_categories={"part_of_date": 10})
        out = compute_category_rollup([s])
        assert out[0]["action"] == CATEGORY_ACTIONS["part_of_date"]["action"]

    def test_target_file_populated(self):
        s = _summary(rejection_categories={"part_of_date": 10})
        out = compute_category_rollup([s])
        assert "false_positive_filter" in out[0]["target_file"]

    def test_unknown_category_gets_fallback_label(self):
        s = _summary(rejection_categories={"future_category_xyz": 7})
        out = compute_category_rollup([s])
        assert out[0]["label"] == "Future Category Xyz"

    def test_unknown_category_gets_empty_target_file(self):
        s = _summary(rejection_categories={"future_category_xyz": 7})
        out = compute_category_rollup([s])
        assert out[0]["target_file"] == ""


# ---------------------------------------------------------------------------
# Severity thresholds
# ---------------------------------------------------------------------------


class TestSeverityThresholds:
    """Severity is derived from the category's share of total run rejects.

    part_of_date thresholds are (10.0, 25.0): medium at >=10%, high at >=25%.
    """

    def _rollup_for(self, cat_count: int, other_count: int) -> dict:
        s = _summary(rejection_categories={"part_of_date": cat_count, "filler": other_count})
        out = compute_category_rollup(s if isinstance(s, list) else [s])
        by_cat = {r["category"]: r for r in out}
        return by_cat["part_of_date"]

    def test_severity_none_below_medium_floor(self):
        # part_of_date 9 / 100 = 9% < 10% medium floor
        row = self._rollup_for(9, 91)
        assert row["severity"] is None

    def test_severity_medium_at_medium_floor(self):
        # part_of_date 10 / 100 = 10%
        row = self._rollup_for(10, 90)
        assert row["severity"] == "medium"

    def test_severity_medium_between_floors(self):
        # part_of_date 20 / 100 = 20% (between 10% and 25%)
        row = self._rollup_for(20, 80)
        assert row["severity"] == "medium"

    def test_severity_high_at_high_floor(self):
        # part_of_date 25 / 100 = 25%
        row = self._rollup_for(25, 75)
        assert row["severity"] == "high"

    def test_severity_high_above_floor(self):
        # part_of_date 50 / 100 = 50%
        row = self._rollup_for(50, 50)
        assert row["severity"] == "high"

    def test_severity_none_when_only_category_but_count_zero(self):
        # Edge case: count=0 should not appear (no zero-count categories emitted).
        s = _summary(rejection_categories={"part_of_date": 0})
        out = compute_category_rollup([s])
        # Grand total = 0 → empty list
        assert out == []
