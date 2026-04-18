"""
Integration tests for V2 image review DatabaseAdapter methods.

Exercises the V2-native read/write path introduced in Phase B:
- v2_image_assets (with new review_status, predicted_relevance columns)
- v2_image_review_decisions

Requires:
- TEST_DATABASE_URL environment variable set
- Migrations 28_extend_v2_image_assets_review.sql and
  29_create_v2_image_review_decisions.sql applied.
"""

from __future__ import annotations

import pytest

from src.infra.db import DatabaseAdapter
from src.infra.validation import ValidationError
from tests.integration.conftest import create_test_company_and_filing


def _insert_v2_image(
    db: DatabaseAdapter,
    filing_id: int,
    filename: str,
    classification: str = "chart",
    relevance_score: float = 0.8,
    width: int | None = 600,
    height: int | None = 400,
    nearby_text: str | None = "Our cohort retention chart shows...",
    predicted_relevance: float | None = None,
    review_status: str = "pending",
    section_type: str = "mda",
) -> str:
    """Insert a v2_image_assets row and return its img_id."""
    rows = db.query(
        """
        INSERT INTO v2_image_assets
            (doc_id, filename, dom_locator, width, height, nearby_text,
             classification, relevance_score, predicted_relevance,
             review_status, section_type)
        VALUES
            (%(doc_id)s, %(filename)s, %(dom_locator)s, %(width)s, %(height)s,
             %(nearby_text)s, %(classification)s, %(relevance_score)s,
             %(predicted_relevance)s, %(review_status)s, %(section_type)s)
        RETURNING img_id
        """,
        {
            "doc_id": filing_id,
            "filename": filename,
            "dom_locator": f"body > img[src='{filename}']",
            "width": width,
            "height": height,
            "nearby_text": nearby_text,
            "classification": classification,
            "relevance_score": relevance_score,
            "predicted_relevance": predicted_relevance,
            "review_status": review_status,
            "section_type": section_type,
        },
    )
    return str(rows[0]["img_id"])


class TestGetImageReviewCandidatesForFilingV2:
    def test_returns_non_decorative_images_only(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        chart_id = _insert_v2_image(clean_db, filing_id, "chart.jpg", classification="chart")
        _insert_v2_image(clean_db, filing_id, "logo.jpg", classification="logo")
        _insert_v2_image(clean_db, filing_id, "sig.jpg", classification="signature")
        _insert_v2_image(clean_db, filing_id, "dec.jpg", classification="decorative")

        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)

        assert len(rows) == 1
        assert str(rows[0]["img_id"]) == chart_id
        assert rows[0]["classification"] == "chart"

    def test_projects_v1_compatible_row_shape(self, clean_db):
        _, filing_id = create_test_company_and_filing(
            clean_db, cik="0001234567", accession_number="0001234567-24-000001"
        )
        _insert_v2_image(
            clean_db, filing_id, "chart.jpg",
            classification="chart", relevance_score=0.9, width=800, height=600,
        )

        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        row = rows[0]

        assert row["image_src"] == "chart.jpg"
        assert row["filename"] == "chart.jpg"
        assert row["image_width"] == 800
        assert row["image_height"] == 600
        assert row["preceding_text"] == "Our cohort retention chart shows..."
        assert float(row["cohort_confidence"]) == pytest.approx(0.9)
        assert row["is_decorative"] is False
        assert row["detection_tier"] == "tier_1_cohort"  # chart + relevance >= 0.6
        assert row["image_url"] == "/images/cache/1234567/000123456724000001/chart.jpg"
        assert row["image_src_url"] == (
            "https://www.sec.gov/Archives/edgar/data/"
            "1234567/000123456724000001/chart.jpg"
        )
        # decision fields NULL when no decision exists
        assert row["image_decision_id"] is None
        assert row["decision"] is None

    def test_detection_tier_derivation(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "t1.jpg",
                         classification="chart", relevance_score=0.7, width=100, height=100)
        _insert_v2_image(clean_db, filing_id, "t2.jpg",
                         classification="table_image", relevance_score=0.3, width=400, height=400)
        _insert_v2_image(clean_db, filing_id, "t3.jpg",
                         classification="unknown", relevance_score=0.1, width=100, height=100)

        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id, sort_by="position")
        tiers = {row["filename"]: row["detection_tier"] for row in rows}
        assert tiers["t1.jpg"] == "tier_1_cohort"
        assert tiers["t2.jpg"] == "tier_2_large"
        assert tiers["t3.jpg"] == "tier_3_all"

    def test_filters_by_status(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "a.jpg", review_status="pending")
        _insert_v2_image(clean_db, filing_id, "b.jpg", review_status="reviewed")
        _insert_v2_image(clean_db, filing_id, "c.jpg", review_status="skipped")

        pending = clean_db.get_image_review_candidates_for_filing_v2(filing_id, status="pending")
        reviewed = clean_db.get_image_review_candidates_for_filing_v2(filing_id, status="reviewed")

        assert {r["filename"] for r in pending} == {"a.jpg"}
        assert {r["filename"] for r in reviewed} == {"b.jpg"}

    def test_invalid_status_raises(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        with pytest.raises(ValidationError):
            clean_db.get_image_review_candidates_for_filing_v2(filing_id, status="bogus")

    def test_invalid_sort_raises(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        with pytest.raises(ValidationError):
            clean_db.get_image_review_candidates_for_filing_v2(filing_id, sort_by="bogus")

    def test_sort_by_relevance_orders_predicted_first(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "low.jpg", relevance_score=0.5, predicted_relevance=0.2)
        _insert_v2_image(clean_db, filing_id, "high.jpg", relevance_score=0.5, predicted_relevance=0.9)

        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id, sort_by="relevance")

        assert [r["filename"] for r in rows] == ["high.jpg", "low.jpg"]


class TestGetImageReviewCandidateV2:
    def test_returns_single_row_with_filing_context(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")

        row = clean_db.get_image_review_candidate_v2(img_id)

        assert row is not None
        assert str(row["img_id"]) == img_id
        assert row["accession_number"] == "0001234567-24-000001"
        assert row["company_name"] == "Test Corp"

    def test_returns_none_for_unknown_img(self, clean_db):
        result = clean_db.get_image_review_candidate_v2(
            "00000000-0000-0000-0000-000000000000"
        )
        assert result is None


class TestInsertImageReviewDecisionV2:
    def test_insert_relevant_sets_status_reviewed(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        decision_id = clean_db.insert_image_review_decision_v2(
            img_id=img_id, decision="relevant", chart_type="cohort_table",
        )

        assert decision_id > 0
        asset = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert asset[0]["review_status"] == "reviewed"
        cand = clean_db.get_image_review_candidate_v2(img_id)
        assert cand["decision"] == "relevant"
        assert cand["chart_type"] == "cohort_table"

    def test_insert_not_relevant_requires_rejection_reason(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        with pytest.raises(ValidationError, match="rejection_reason"):
            clean_db.insert_image_review_decision_v2(
                img_id=img_id, decision="not_relevant",
            )

    def test_insert_relevant_requires_chart_type(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        with pytest.raises(ValidationError, match="chart_type"):
            clean_db.insert_image_review_decision_v2(
                img_id=img_id, decision="relevant",
            )

    def test_invalid_chart_type_raises(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        with pytest.raises(ValidationError):
            clean_db.insert_image_review_decision_v2(
                img_id=img_id, decision="relevant", chart_type="bogus",
            )


class TestDeleteImageReviewDecisionV2:
    def test_delete_reverts_status_to_pending(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")
        decision_id = clean_db.insert_image_review_decision_v2(
            img_id=img_id, decision="relevant", chart_type="bar_chart",
        )

        result = clean_db.delete_image_review_decision_v2(decision_id)

        assert result is True
        asset = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert asset[0]["review_status"] == "pending"

    def test_delete_missing_returns_false(self, clean_db):
        assert clean_db.delete_image_review_decision_v2(999_999) is False


class TestSkipImageCandidateV2:
    def test_skip_sets_status(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        assert clean_db.skip_image_candidate_v2(img_id) is True

        rows = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert rows[0]["review_status"] == "skipped"

    def test_skip_missing_returns_false(self, clean_db):
        assert (
            clean_db.skip_image_candidate_v2("00000000-0000-0000-0000-000000000000")
            is False
        )


class TestGetImageReviewProgressV2:
    def test_filing_scoped_counts(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "a.jpg", review_status="pending")
        _insert_v2_image(clean_db, filing_id, "b.jpg", review_status="reviewed")
        _insert_v2_image(clean_db, filing_id, "c.jpg", review_status="skipped")
        _insert_v2_image(clean_db, filing_id, "d.jpg", review_status="auto_rejected")
        _insert_v2_image(clean_db, filing_id, "logo.jpg", classification="logo",
                         review_status="pending")  # excluded from queue

        progress = clean_db.get_image_review_progress_v2(filing_id=filing_id)

        assert progress["total_candidates"] == 4
        assert progress["pending_count"] == 1
        assert progress["reviewed_count"] == 1
        assert progress["skipped_count"] == 1
        assert progress["auto_rejected_count"] == 1
        assert progress["review_pct"] == 25.0

    def test_global_counts_when_no_filing(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "a.jpg", review_status="pending")
        progress = clean_db.get_image_review_progress_v2()
        assert progress["total_candidates"] >= 1


class TestGetNextPendingImageCandidateV2:
    def test_returns_first_pending(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "a.jpg", predicted_relevance=0.3)
        _insert_v2_image(clean_db, filing_id, "b.jpg", predicted_relevance=0.9)

        nxt = clean_db.get_next_pending_image_candidate_v2(filing_id)

        assert nxt is not None
        assert nxt["filename"] == "b.jpg"

    def test_returns_none_when_all_reviewed(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "a.jpg", review_status="reviewed")

        assert clean_db.get_next_pending_image_candidate_v2(filing_id) is None
