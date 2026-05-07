"""
Unit tests for get_image_review_candidates_for_filing_v2 SQL shape.

Verifies that:
- The shared _V2_IMAGE_CANDIDATE_SELECT constant is not modified (regression guard)
- The candidate query includes the LATERAL join + classification columns
- The returned dict exposes predicted_metrics=None when no classification row exists
"""

from unittest.mock import MagicMock

import pytest

from src.infra.db import DatabaseAdapter
from src.review.models import IMAGE_REVIEW_FILTER_STATUSES, IMAGE_REVIEW_STATUSES


@pytest.fixture
def db():
    adapter = DatabaseAdapter.__new__(DatabaseAdapter)
    adapter.query = MagicMock(return_value=[])
    return adapter


class TestSharedConstantUnchanged:
    def test_constant_does_not_contain_ic_prefix(self):
        """_V2_IMAGE_CANDIDATE_SELECT must not reference ic.* — it is used in
        multiple queries, only one of which has the classification LATERAL join."""
        assert "ic." not in DatabaseAdapter._V2_IMAGE_CANDIDATE_SELECT

    def test_constant_includes_imc_rollup_columns(self):
        """The shared projection must surface the per-metric confirmation rollup
        so every consumer (list, single-fetch, next-pending) sees the same shape."""
        select = DatabaseAdapter._V2_IMAGE_CANDIDATE_SELECT
        assert "imc_rollup.positive_count" in select
        assert "imc_rollup.detected_decided_count" in select
        assert "imc_rollup.total_confirmation_count" in select
        assert "imc_rollup.has_add" in select


class TestConfirmationRollupJoin:
    def test_join_uses_count_distinct_for_multi_reviewer_safety(self):
        """The unique index on v2_image_metric_confirmations is per-reviewer, so
        raw COUNT(*) double-counts when two reviewers decide the same metric."""
        join = DatabaseAdapter._V2_IMAGE_CONFIRMATION_ROLLUP_JOIN
        assert "COUNT(DISTINCT confirmed_metric_id)" in join
        assert "COUNT(DISTINCT detected_metric_id)" in join

    def test_decided_filter_excludes_skip(self):
        """Skip is a punt — does not count toward 'every detected metric decided'."""
        join = DatabaseAdapter._V2_IMAGE_CONFIRMATION_ROLLUP_JOIN
        # The detected_decided_count filter must explicitly enumerate accept/reject/correct
        assert "decision IN ('accept', 'reject', 'correct')" in join


class TestImageCandidateSqlShape:
    def test_query_contains_lateral_join(self, db):
        db.get_image_review_candidates_for_filing_v2(filing_id=1)
        sql = db.query.call_args[0][0]
        assert "LATERAL" in sql
        assert "v2_image_classifications" in sql

    def test_query_selects_classification_columns(self, db):
        db.get_image_review_candidates_for_filing_v2(filing_id=1)
        sql = db.query.call_args[0][0]
        assert "ic.classification_id" in sql
        assert "ic.predicted_metrics" in sql
        assert "ic.confidence" in sql

    def test_lateral_orders_by_created_at_desc(self, db):
        db.get_image_review_candidates_for_filing_v2(filing_id=1)
        sql = db.query.call_args[0][0]
        assert "ORDER BY created_at DESC" in sql
        assert "LIMIT 1" in sql


class TestDeriveImageReviewState:
    """Pure-function tests for _derive_image_review_state — the rollup-to-glyph mapper."""

    def _row(self, **kwargs):
        base = {
            "review_status": "pending",
            "detected_metrics": [],
            "total_confirmation_count": 0,
            "detected_decided_count": 0,
            "positive_count": 0,
            "has_add": False,
        }
        base.update(kwargs)
        return base

    def test_image_skipped_short_circuits_to_no_relevant(self):
        row = self._row(review_status="skipped")
        assert DatabaseAdapter._derive_image_review_state(row) == "no_relevant"

    def test_auto_rejected_is_no_relevant(self):
        row = self._row(review_status="auto_rejected")
        assert DatabaseAdapter._derive_image_review_state(row) == "no_relevant"

    def test_no_detections_no_confirmations_is_pending(self):
        assert DatabaseAdapter._derive_image_review_state(self._row()) == "pending"

    def test_all_detected_accepted_is_relevant(self):
        row = self._row(
            detected_metrics=[{"metric_id": "cm_a"}, {"metric_id": "cm_b"}],
            total_confirmation_count=2,
            detected_decided_count=2,
            positive_count=2,
        )
        assert DatabaseAdapter._derive_image_review_state(row) == "relevant"

    def test_all_detected_rejected_is_no_relevant(self):
        row = self._row(
            detected_metrics=[{"metric_id": "cm_a"}, {"metric_id": "cm_b"}],
            total_confirmation_count=2,
            detected_decided_count=2,
            positive_count=0,
        )
        assert DatabaseAdapter._derive_image_review_state(row) == "no_relevant"

    def test_partial_decision_is_pending(self):
        row = self._row(
            detected_metrics=[{"metric_id": "cm_a"}, {"metric_id": "cm_b"}, {"metric_id": "cm_c"}],
            total_confirmation_count=1,
            detected_decided_count=1,
            positive_count=1,
        )
        assert DatabaseAdapter._derive_image_review_state(row) == "pending"

    def test_skip_does_not_count_as_decided(self):
        # Two detected, one accepted, one skipped — coverage incomplete.
        row = self._row(
            detected_metrics=[{"metric_id": "cm_a"}, {"metric_id": "cm_b"}],
            total_confirmation_count=2,
            detected_decided_count=1,  # only the accept counts; skip excluded by SQL filter
            positive_count=1,
        )
        assert DatabaseAdapter._derive_image_review_state(row) == "pending"

    def test_add_only_on_zero_detected_is_relevant(self):
        # Reviewer added a missed metric on an image with no detections.
        row = self._row(
            detected_metrics=[],
            total_confirmation_count=1,
            detected_decided_count=0,
            positive_count=1,
            has_add=True,
        )
        assert DatabaseAdapter._derive_image_review_state(row) == "relevant"


class TestClassificationFallback:
    def test_predicted_metrics_is_none_when_no_classification_row(self, db):
        """When ic.* columns are NULL (no classification exists for the image),
        the returned dict should have predicted_metrics=None so the template
        falls back to detected_metrics (rule-based)."""
        db.query.return_value = [
            {
                "img_id": "00000000-0000-0000-0000-000000000001",
                "detected_metrics": [{"metric_id": "cm_customers_period_end", "score": 0.9}],
                "classification_id": None,
                "predicted_metrics": None,
                "classification_confidence": None,
                "review_status": "pending",
                "decision": None,
            }
        ]
        results = db.get_image_review_candidates_for_filing_v2(filing_id=1)
        assert len(results) == 1
        assert results[0]["predicted_metrics"] is None
        assert results[0]["classification_id"] is None

    def test_predicted_metrics_present_when_classification_exists(self, db):
        predicted = [{"metric_id": "cm_net_revenue_retention", "score": 0.92}]
        db.query.return_value = [
            {
                "img_id": "00000000-0000-0000-0000-000000000002",
                "detected_metrics": [],
                "classification_id": 42,
                "predicted_metrics": predicted,
                "classification_confidence": 0.92,
                "review_status": "pending",
                "decision": None,
            }
        ]
        results = db.get_image_review_candidates_for_filing_v2(filing_id=1)
        assert results[0]["predicted_metrics"] == predicted
        assert results[0]["classification_id"] == 42


class TestLegacyBackfillFilter:
    def test_legacy_backfill_generates_exists_not_exists(self, db):
        db.get_image_review_candidates_for_filing_v2(filing_id=1, status="legacy_backfill")
        sql = db.query.call_args[0][0]
        assert "NOT EXISTS" in sql
        # The backfill EXISTS filter uses specific alias 'ird' and 'imc'.
        assert "v2_image_review_decisions ird" in sql
        assert "v2_image_metric_confirmations imc" in sql

    def test_legacy_backfill_does_not_use_review_status_filter(self, db):
        db.get_image_review_candidates_for_filing_v2(filing_id=1, status="legacy_backfill")
        sql = db.query.call_args[0][0]
        assert "review_status = %(status)s" not in sql

    def test_normal_status_uses_review_status_column(self, db):
        db.get_image_review_candidates_for_filing_v2(filing_id=1, status="pending")
        sql = db.query.call_args[0][0]
        assert "review_status = %(status)s" in sql
        # The backfill EXISTS filter uses alias 'ird' — must be absent for normal statuses.
        assert "v2_image_review_decisions ird" not in sql

    def test_legacy_decision_field_in_shared_constant(self):
        assert "legacy_decision" in DatabaseAdapter._V2_IMAGE_CANDIDATE_SELECT
        assert "d.decision = 'relevant'" in DatabaseAdapter._V2_IMAGE_CANDIDATE_SELECT


class TestImageReviewFilterStatuses:
    def test_filter_statuses_is_superset_of_review_statuses(self):
        for s in IMAGE_REVIEW_STATUSES:
            assert s in IMAGE_REVIEW_FILTER_STATUSES

    def test_legacy_backfill_in_filter_statuses(self):
        assert "legacy_backfill" in IMAGE_REVIEW_FILTER_STATUSES

    def test_legacy_backfill_not_in_review_statuses(self):
        assert "legacy_backfill" not in IMAGE_REVIEW_STATUSES

    def test_garbage_value_not_in_filter_statuses(self):
        assert "garbage_value" not in IMAGE_REVIEW_FILTER_STATUSES
