"""
Unit tests for DatabaseAdapter.bridge_v2_images_to_review_candidates.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infra.db import DatabaseAdapter  # noqa: E402


def _make_db() -> DatabaseAdapter:
    """Return a DatabaseAdapter with a stub connection string (no real DB)."""
    return DatabaseAdapter("postgresql://test/db")


def _image_row(
    filename: str,
    classification: str,
    relevance_score: float,
    width: int = 0,
    height: int = 0,
    nearby_text: str = "",
) -> dict:
    return {
        "img_id": "test-uuid",
        "filename": filename,
        "classification": classification,
        "relevance_score": relevance_score,
        "width": width,
        "height": height,
        "nearby_text": nearby_text,
    }


class TestBridgeTierMapping:
    """Tier classification logic applied to v2_image_assets rows."""

    def _run_bridge(self, rows: list[dict]) -> list[dict]:
        """Run the bridge with mocked query/insert and return insert call kwargs."""
        db = _make_db()
        insert_calls: list[dict] = []

        def fake_insert(**kwargs):
            insert_calls.append(kwargs)
            return 1  # simulate successful insert

        with patch.object(db, "query", return_value=rows):
            with patch.object(db, "insert_image_review_candidate", side_effect=fake_insert):
                db.bridge_v2_images_to_review_candidates(
                    filing_id=1,
                    company_id=10,
                    cik="0001234567",
                    accession_number="0001234567-24-000001",
                )

        return insert_calls

    def test_high_relevance_chart_is_tier_1_cohort(self):
        rows = [_image_row("chart.jpg", "chart", relevance_score=0.7)]
        calls = self._run_bridge(rows)
        assert len(calls) == 1
        assert calls[0]["detection_tier"] == "tier_1_cohort"

    def test_chart_at_exactly_0_6_is_tier_1_cohort(self):
        rows = [_image_row("chart.jpg", "chart", relevance_score=0.6)]
        calls = self._run_bridge(rows)
        assert calls[0]["detection_tier"] == "tier_1_cohort"

    def test_chart_below_0_6_large_dims_is_tier_2(self):
        rows = [_image_row("chart.jpg", "chart", relevance_score=0.4, width=400, height=400)]
        calls = self._run_bridge(rows)
        assert calls[0]["detection_tier"] == "tier_2_large"

    def test_table_image_large_dims_is_tier_2(self):
        rows = [_image_row("table.jpg", "table_image", relevance_score=0.3, width=500, height=300)]
        calls = self._run_bridge(rows)
        assert calls[0]["detection_tier"] == "tier_2_large"

    def test_small_chart_is_tier_3(self):
        rows = [_image_row("small.jpg", "chart", relevance_score=0.3, width=200, height=200)]
        calls = self._run_bridge(rows)
        assert calls[0]["detection_tier"] == "tier_3_all"

    def test_unknown_classification_is_tier_3(self):
        rows = [_image_row("unk.jpg", "unknown", relevance_score=0.2)]
        calls = self._run_bridge(rows)
        assert calls[0]["detection_tier"] == "tier_3_all"

    def test_table_image_small_dims_is_tier_3(self):
        rows = [_image_row("t.jpg", "table_image", relevance_score=0.4, width=100, height=100)]
        calls = self._run_bridge(rows)
        assert calls[0]["detection_tier"] == "tier_3_all"


class TestBridgeExclusions:
    """Decorative/logo/signature images must be excluded by the SQL query."""

    def test_empty_rows_returns_zero(self):
        db = _make_db()
        with patch.object(db, "query", return_value=[]):
            result = db.bridge_v2_images_to_review_candidates(
                filing_id=1, company_id=10, cik="001", accession_number="0001-01-000001"
            )
        assert result == 0

    def test_query_excludes_decorative_logo_signature(self):
        """The SQL WHERE clause filters out unwanted classifications."""
        db = _make_db()
        captured_sql: list[str] = []

        def capture_query(sql, params=None):
            captured_sql.append(sql)
            return []

        with patch.object(db, "query", side_effect=capture_query):
            db.bridge_v2_images_to_review_candidates(
                filing_id=5, company_id=10, cik="001", accession_number="0001-01-000001"
            )

        assert captured_sql, "query() should have been called"
        sql = captured_sql[0]
        assert "decorative" in sql
        assert "logo" in sql
        assert "signature" in sql
        assert "NOT IN" in sql


class TestBridgeURLConstruction:
    """Image URLs are constructed from cik + accession_number + filename."""

    def test_url_strips_leading_zeros_from_cik(self):
        db = _make_db()
        rows = [_image_row("img.jpg", "chart", relevance_score=0.7)]
        inserted_urls: list[str] = []

        def fake_insert(**kwargs):
            inserted_urls.append(kwargs["image_url"])
            return 1

        with patch.object(db, "query", return_value=rows):
            with patch.object(db, "insert_image_review_candidate", side_effect=fake_insert):
                db.bridge_v2_images_to_review_candidates(
                    filing_id=1,
                    company_id=10,
                    cik="0001234567",
                    accession_number="0001234567-24-000001",
                )

        assert len(inserted_urls) == 1
        url = inserted_urls[0]
        # CIK leading zeros stripped, dashes removed from accession number
        assert "1234567" in url
        assert "000123456724000001" in url
        assert url.endswith("img.jpg")
        assert url.startswith("https://www.sec.gov/")

    def test_url_uses_correct_filename(self):
        db = _make_db()
        rows = [_image_row("g55348g55a01.jpg", "chart", relevance_score=0.5)]
        inserted_urls: list[str] = []

        def fake_insert(**kwargs):
            inserted_urls.append(kwargs["image_url"])
            return 1

        with patch.object(db, "query", return_value=rows):
            with patch.object(db, "insert_image_review_candidate", side_effect=fake_insert):
                db.bridge_v2_images_to_review_candidates(
                    filing_id=1, company_id=10, cik="001", accession_number="0001-01-000001"
                )

        assert inserted_urls[0].endswith("g55348g55a01.jpg")


class TestBridgeInsertCount:
    """Return value counts successfully inserted candidates."""

    def test_returns_count_of_successful_inserts(self):
        db = _make_db()
        rows = [
            _image_row("a.jpg", "chart", 0.7),
            _image_row("b.jpg", "chart", 0.5, width=400, height=400),
            _image_row("c.jpg", "unknown", 0.2),
        ]

        with patch.object(db, "query", return_value=rows):
            with patch.object(db, "insert_image_review_candidate", return_value=1):
                count = db.bridge_v2_images_to_review_candidates(
                    filing_id=1, company_id=10, cik="001", accession_number="0001-01-000001"
                )

        assert count == 3

    def test_zero_returned_when_all_already_exist(self):
        """insert_image_review_candidate returns 0 on conflict — bridge count reflects that."""
        db = _make_db()
        rows = [_image_row("a.jpg", "chart", 0.7)]

        with patch.object(db, "query", return_value=rows):
            with patch.object(db, "insert_image_review_candidate", return_value=0):
                count = db.bridge_v2_images_to_review_candidates(
                    filing_id=1, company_id=10, cik="001", accession_number="0001-01-000001"
                )

        assert count == 0

    def test_is_decorative_always_false(self):
        """Bridged candidates are never marked decorative (already filtered by SQL)."""
        db = _make_db()
        rows = [_image_row("a.jpg", "chart", 0.7)]
        inserted: list[dict] = []

        def fake_insert(**kwargs):
            inserted.append(kwargs)
            return 1

        with patch.object(db, "query", return_value=rows):
            with patch.object(db, "insert_image_review_candidate", side_effect=fake_insert):
                db.bridge_v2_images_to_review_candidates(
                    filing_id=1, company_id=10, cik="001", accession_number="0001-01-000001"
                )

        assert inserted[0]["is_decorative"] is False
