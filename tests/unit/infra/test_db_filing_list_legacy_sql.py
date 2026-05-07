"""Unit tests for legacy_backfill_only SQL shape in filing-list DB helpers.

Verifies that:
- get_unified_filings_for_review with legacy_backfill_only=True injects the
  images_legacy_pending > 0 predicate into the WHERE clause.
- images_legacy_pending is projected in the image_progress CTE in the same query.
- The predicate is absent when legacy_backfill_only=False (default).
"""

from unittest.mock import MagicMock

import pytest

from src.infra.db import DatabaseAdapter


@pytest.fixture
def db():
    adapter = DatabaseAdapter.__new__(DatabaseAdapter)
    adapter.query = MagicMock(return_value=[])
    return adapter


class TestFilingListLegacyBackfillFilter:
    def test_legacy_backfill_only_injects_filter_predicate(self, db):
        db.get_unified_filings_for_review(legacy_backfill_only=True)
        sql = db.query.call_args[0][0]
        assert "images_legacy_pending" in sql
        # Filter uses COALESCE guard around the column reference
        assert "images_legacy_pending, 0) > 0" in sql

    def test_legacy_backfill_only_false_omits_filter_predicate(self, db):
        db.get_unified_filings_for_review(legacy_backfill_only=False)
        sql = db.query.call_args[0][0]
        # images_legacy_pending is still projected in CTE, but the > 0 filter is absent
        assert "images_legacy_pending, 0) > 0" not in sql

    def test_default_omits_filter_predicate(self, db):
        db.get_unified_filings_for_review()
        sql = db.query.call_args[0][0]
        assert "images_legacy_pending, 0) > 0" not in sql

    def test_images_legacy_pending_column_in_cte(self, db):
        db.get_unified_filings_for_review()
        sql = db.query.call_args[0][0]
        assert "images_legacy_pending" in sql
        assert "v2_image_review_decisions" in sql
        assert "v2_image_metric_confirmations" in sql


class TestFilingListCountLegacyBackfillFilter:
    def test_count_legacy_backfill_only_injects_filter_predicate(self, db):
        db.get_unified_filings_for_review_count(legacy_backfill_only=True)
        sql = db.query.call_args[0][0]
        assert "images_legacy_pending, 0) > 0" in sql

    def test_count_default_omits_filter_predicate(self, db):
        db.get_unified_filings_for_review_count(legacy_backfill_only=False)
        sql = db.query.call_args[0][0]
        assert "images_legacy_pending, 0) > 0" not in sql


class TestNextFilingLegacyBackfillFilter:
    def test_next_filing_legacy_backfill_only_replaces_pending_filter(self, db):
        db.get_next_filing_with_pending_work(current_filing_id=1, legacy_backfill_only=True)
        sql = db.query.call_args[0][0]
        assert "images_legacy_pending > 0" in sql
        # The normal pending guard must NOT appear — it excludes legacy-only filings
        # because legacy-backfill images have images_pending=0.
        assert "facts_pending > 0 OR images_pending > 0" not in sql

    def test_next_filing_default_uses_normal_pending_filter(self, db):
        db.get_next_filing_with_pending_work(current_filing_id=1, legacy_backfill_only=False)
        sql = db.query.call_args[0][0]
        assert "images_pending > 0" in sql
        assert "images_legacy_pending > 0" not in sql
