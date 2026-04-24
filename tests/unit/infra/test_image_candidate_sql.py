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
