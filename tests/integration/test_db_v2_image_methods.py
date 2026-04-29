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
            (filing_id, filename, dom_locator, width, height, nearby_text,
             classification, relevance_score, predicted_relevance,
             review_status, section_type)
        VALUES
            (%(filing_id)s, %(filename)s, %(dom_locator)s, %(width)s, %(height)s,
             %(nearby_text)s, %(classification)s, %(relevance_score)s,
             %(predicted_relevance)s, %(review_status)s, %(section_type)s)
        RETURNING img_id
        """,
        {
            "filing_id": filing_id,
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
            clean_db,
            filing_id,
            "chart.jpg",
            classification="chart",
            relevance_score=0.9,
            width=800,
            height=600,
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
            "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001/chart.jpg"
        )
        # decision fields NULL when no decision exists
        assert row["image_decision_id"] is None
        assert row["decision"] is None

    def test_detection_tier_derivation(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(
            clean_db,
            filing_id,
            "t1.jpg",
            classification="chart",
            relevance_score=0.7,
            width=100,
            height=100,
        )
        _insert_v2_image(
            clean_db,
            filing_id,
            "t2.jpg",
            classification="table_image",
            relevance_score=0.3,
            width=400,
            height=400,
        )
        _insert_v2_image(
            clean_db,
            filing_id,
            "t3.jpg",
            classification="unknown",
            relevance_score=0.1,
            width=100,
            height=100,
        )

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
        _insert_v2_image(
            clean_db, filing_id, "low.jpg", relevance_score=0.5, predicted_relevance=0.2
        )
        _insert_v2_image(
            clean_db, filing_id, "high.jpg", relevance_score=0.5, predicted_relevance=0.9
        )

        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id, sort_by="relevance")

        assert [r["filename"] for r in rows] == ["high.jpg", "low.jpg"]


def _set_detected_metrics(db: DatabaseAdapter, img_id: str, metrics: list[dict]) -> None:
    """Set v2_image_assets.detected_metrics directly for rollup-state fixtures."""
    import json

    db.execute(
        "UPDATE v2_image_assets SET detected_metrics = %(m)s::jsonb WHERE img_id = %(id)s",
        {"m": json.dumps(metrics), "id": img_id},
    )


def _insert_confirmation(
    db: DatabaseAdapter,
    img_id: str,
    decision: str,
    detected_metric_id: str | None = None,
    confirmed_metric_id: str | None = None,
    reviewer_id: str = "RGM",
    rejection_reason: str | None = None,
) -> None:
    db.execute(
        """
        INSERT INTO v2_image_metric_confirmations
            (img_id, detected_metric_id, confirmed_metric_id, decision,
             rejection_reason, reviewer_id)
        VALUES
            (%(img_id)s, %(d)s, %(c)s, %(decision)s, %(rej)s, %(rev)s)
        """,
        {
            "img_id": img_id,
            "d": detected_metric_id,
            "c": confirmed_metric_id,
            "decision": decision,
            "rej": rejection_reason,
            "rev": reviewer_id,
        },
    )


class TestImageReviewStateRollup:
    """End-to-end coverage of the lateral-join rollup + Python derivation."""

    def test_no_confirmations_no_detections_pending(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "chart.jpg")
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        assert rows[0]["image_review_state"] == "pending"

    def test_all_detected_accepted_is_relevant(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")
        _set_detected_metrics(
            clean_db,
            img_id,
            [{"metric_id": "cm_a", "score": 0.9}, {"metric_id": "cm_b", "score": 0.7}],
        )
        _insert_confirmation(clean_db, img_id, "accept", "cm_a", "cm_a")
        _insert_confirmation(clean_db, img_id, "accept", "cm_b", "cm_b")
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        assert rows[0]["image_review_state"] == "relevant"

    def test_all_detected_rejected_is_no_relevant(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")
        _set_detected_metrics(
            clean_db,
            img_id,
            [{"metric_id": "cm_a", "score": 0.9}],
        )
        _insert_confirmation(
            clean_db,
            img_id,
            "reject",
            "cm_a",
            rejection_reason="not_present",
        )
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        assert rows[0]["image_review_state"] == "no_relevant"

    def test_image_skipped_short_circuits_to_no_relevant(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(
            clean_db,
            filing_id,
            "chart.jpg",
            review_status="skipped",
        )
        _set_detected_metrics(
            clean_db,
            img_id,
            [{"metric_id": "cm_a", "score": 0.9}],
        )
        rows = clean_db.get_image_review_candidates_for_filing_v2(
            filing_id,
            status="skipped",
        )
        assert rows[0]["image_review_state"] == "no_relevant"

    def test_partial_decision_is_pending(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")
        _set_detected_metrics(
            clean_db,
            img_id,
            [{"metric_id": "cm_a", "score": 0.9}, {"metric_id": "cm_b", "score": 0.7}],
        )
        _insert_confirmation(clean_db, img_id, "accept", "cm_a", "cm_a")
        # cm_b not yet decided
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        assert rows[0]["image_review_state"] == "pending"

    def test_skip_does_not_count_as_decided(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")
        _set_detected_metrics(
            clean_db,
            img_id,
            [{"metric_id": "cm_a", "score": 0.9}, {"metric_id": "cm_b", "score": 0.7}],
        )
        _insert_confirmation(clean_db, img_id, "accept", "cm_a", "cm_a")
        _insert_confirmation(clean_db, img_id, "skip", "cm_b")
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        # skip is a punt, not a decision — coverage incomplete
        assert rows[0]["image_review_state"] == "pending"

    def test_add_only_with_zero_detected_is_relevant(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")
        _set_detected_metrics(clean_db, img_id, [])
        _insert_confirmation(
            clean_db,
            img_id,
            "add",
            detected_metric_id=None,
            confirmed_metric_id="cm_added",
        )
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        assert rows[0]["image_review_state"] == "relevant"

    def test_multi_reviewer_does_not_double_count_coverage(self, clean_db):
        """If two reviewers each accept the same detected metric, coverage
        counts that metric ONCE — without DISTINCT this would tip an
        incomplete coverage to "relevant" prematurely."""
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")
        _set_detected_metrics(
            clean_db,
            img_id,
            [{"metric_id": "cm_a", "score": 0.9}, {"metric_id": "cm_b", "score": 0.7}],
        )
        _insert_confirmation(clean_db, img_id, "accept", "cm_a", "cm_a", reviewer_id="alice")
        _insert_confirmation(clean_db, img_id, "accept", "cm_a", "cm_a", reviewer_id="bob")
        # cm_b still not decided — must remain pending
        rows = clean_db.get_image_review_candidates_for_filing_v2(filing_id)
        assert rows[0]["image_review_state"] == "pending"


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
        result = clean_db.get_image_review_candidate_v2("00000000-0000-0000-0000-000000000000")
        assert result is None


class TestInsertImageReviewDecisionV2:
    def test_insert_relevant_sets_status_reviewed(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        decision_id = clean_db.insert_image_review_decision_v2(
            img_id=img_id,
            decision="relevant",
            chart_type="cohort_table",
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
                img_id=img_id,
                decision="not_relevant",
            )

    def test_insert_relevant_requires_chart_type(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        with pytest.raises(ValidationError, match="chart_type"):
            clean_db.insert_image_review_decision_v2(
                img_id=img_id,
                decision="relevant",
            )

    def test_invalid_chart_type_raises(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        with pytest.raises(ValidationError):
            clean_db.insert_image_review_decision_v2(
                img_id=img_id,
                decision="relevant",
                chart_type="bogus",
            )


class TestDeleteImageReviewDecisionV2:
    def test_delete_reverts_status_to_pending(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")
        decision_id = clean_db.insert_image_review_decision_v2(
            img_id=img_id,
            decision="relevant",
            chart_type="bar_chart",
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
        assert clean_db.skip_image_candidate_v2("00000000-0000-0000-0000-000000000000") is False


class TestMarkImageReviewedV2:
    def test_mark_pending_to_reviewed(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg")

        assert clean_db.mark_image_reviewed_v2(img_id) is True

        rows = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert rows[0]["review_status"] == "reviewed"

    def test_idempotent_when_already_reviewed(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg", review_status="reviewed")

        assert clean_db.mark_image_reviewed_v2(img_id) is True
        rows = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert rows[0]["review_status"] == "reviewed"

    def test_does_not_clobber_skipped(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg", review_status="skipped")

        assert clean_db.mark_image_reviewed_v2(img_id) is False
        rows = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert rows[0]["review_status"] == "skipped"

    def test_does_not_clobber_auto_rejected(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "c.jpg", review_status="auto_rejected")

        assert clean_db.mark_image_reviewed_v2(img_id) is False
        rows = clean_db.query(
            "SELECT review_status FROM v2_image_assets WHERE img_id = %(id)s",
            {"id": img_id},
        )
        assert rows[0]["review_status"] == "auto_rejected"

    def test_missing_img_id_returns_false(self, clean_db):
        assert clean_db.mark_image_reviewed_v2("00000000-0000-0000-0000-000000000000") is False


class TestGetImageReviewProgressV2:
    def test_filing_scoped_counts(self, clean_db):
        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "a.jpg", review_status="pending")
        _insert_v2_image(clean_db, filing_id, "b.jpg", review_status="reviewed")
        _insert_v2_image(clean_db, filing_id, "c.jpg", review_status="skipped")
        _insert_v2_image(clean_db, filing_id, "d.jpg", review_status="auto_rejected")
        _insert_v2_image(
            clean_db, filing_id, "logo.jpg", classification="logo", review_status="pending"
        )  # excluded from queue

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


class TestPersistImagesStableImgId:
    """Regression coverage for sql/34 + the persistence upsert preserving img_id.

    Before the fix, re-extracting a filing produced duplicate v2_image_assets rows
    (random img_id per run, ON CONFLICT (img_id) never fired). Decisions stayed
    attached to the original row; new duplicates defaulted to review_status='pending'
    and inflated the progress counter (Maplebear S-1: 220 pending but the review UI
    showed every image as already reviewed).
    """

    def _make_asset(self, filename: str, img_id: str | None = None):
        from src.extraction_v2.models import (
            ImageAsset,
            ImageClassification,
            SectionType,
        )

        kwargs: dict = {
            "filename": filename,
            "dom_locator": f"body > img[src='{filename}']",
            "width": 600,
            "height": 400,
            "nearby_text": "cohort retention",
            "classification": ImageClassification.CHART,
            "relevance_score": 0.8,
            "section_type": SectionType.MDA,
        }
        if img_id is not None:
            kwargs["img_id"] = img_id
        return ImageAsset(**kwargs)

    def test_reextraction_preserves_img_id_and_does_not_duplicate(self, clean_db):
        from src.extraction_v2.persistence import V2PersistenceAdapter

        _, filing_id = create_test_company_and_filing(clean_db)
        adapter = V2PersistenceAdapter(clean_db)

        # First run: persist a single image. Record its DB-assigned img_id.
        original = self._make_asset("chart1.jpg")
        adapter.persist_images([original], filing_id)
        rows = clean_db.query(
            "SELECT img_id FROM v2_image_assets WHERE filing_id=%(d)s AND filename=%(f)s",
            {"d": filing_id, "f": "chart1.jpg"},
        )
        assert len(rows) == 1
        stable_img_id = str(rows[0]["img_id"])

        # Reviewer decides on the image.
        clean_db.insert_image_review_decision_v2(
            img_id=stable_img_id,
            decision="relevant",
            chart_type="cohort_table",
        )

        # Second run: same filename, fresh random img_id (simulating re-extraction).
        refreshed = self._make_asset("chart1.jpg")
        assert refreshed.img_id != stable_img_id
        adapter.persist_images([refreshed], filing_id)

        # Row count unchanged; img_id is still the original; decision survives.
        rows_after = clean_db.query(
            "SELECT img_id FROM v2_image_assets WHERE filing_id=%(d)s AND filename=%(f)s",
            {"d": filing_id, "f": "chart1.jpg"},
        )
        assert len(rows_after) == 1
        assert str(rows_after[0]["img_id"]) == stable_img_id

        candidate = clean_db.get_image_review_candidate_v2(stable_img_id)
        assert candidate is not None
        assert candidate["decision"] == "relevant"

        progress = clean_db.get_image_review_progress_v2(filing_id=filing_id)
        assert progress["pending_count"] == 0
        assert progress["reviewed_count"] == 1

    def test_unique_constraint_rejects_manual_duplicate(self, clean_db):
        """sql/34 guards against any future code path inserting a duplicate directly."""
        from psycopg.errors import UniqueViolation

        _, filing_id = create_test_company_and_filing(clean_db)
        _insert_v2_image(clean_db, filing_id, "dup.jpg")

        with pytest.raises(UniqueViolation):
            _insert_v2_image(clean_db, filing_id, "dup.jpg")

    def test_source_locator_img_id_remapped_in_persist_pipeline_result(self, clean_db):
        """After persist_pipeline_result, facts reference the stable DB img_id,
        not the fresh in-memory uuid4 from this extraction run."""
        from src.extraction_v2.models import (
            Document,
            MetricFact,
            Scope,
            SourceLocator,
            SourceType,
            Unit,
        )
        from src.extraction_v2.persistence import V2PersistenceAdapter
        from src.extraction_v2.pipeline import PipelineResult

        _, filing_id = create_test_company_and_filing(clean_db)
        adapter = V2PersistenceAdapter(clean_db)

        # Seed: an image already exists at (doc_id, filename=chart2.jpg) with
        # its own stable img_id (simulates a prior extraction run).
        seed = self._make_asset("chart2.jpg")
        adapter.persist_images([seed], filing_id)
        stable_img_id = str(
            clean_db.query(
                "SELECT img_id FROM v2_image_assets WHERE filing_id=%(d)s AND filename=%(f)s",
                {"d": filing_id, "f": "chart2.jpg"},
            )[0]["img_id"]
        )

        # Build a fresh PipelineResult as if re-extraction just ran: the new
        # in-memory ImageAsset has a random img_id, and one fact references it.
        refreshed = self._make_asset("chart2.jpg")
        assert refreshed.img_id != stable_img_id
        fact = MetricFact(
            canonical_metric_id="cm_revenue_by_cohort",
            value=1000.0,
            value_raw="$1,000",
            unit=Unit.CURRENCY,
            currency="USD",
            scope=Scope.COMPANY,
            source_type=SourceType.CHART,
            source_locator=SourceLocator(
                img_id=refreshed.img_id,
                dom_locator=refreshed.dom_locator,
            ),
            confidence=0.9,
        )
        result = PipelineResult(
            document=Document(),
            facts=[fact],
            tables=[],
            images=[refreshed],
            segments=[],
            stage_results=[],
            total_duration_ms=0,
            success=True,
        )

        adapter.persist_pipeline_result(result, filing_id, force=True)

        # In-memory fact was remapped to the stable DB img_id.
        assert fact.source_locator.img_id == stable_img_id
        # In-memory image was remapped too (defensive).
        assert refreshed.img_id == stable_img_id


class TestStalOcrBadgeHashRoundtrip:
    """Integration coverage for the decided_against_hash write-then-read path.

    Verifies that:
    1. Inserting a decision writes a non-NULL decided_against_hash.
    2. When content is unchanged, is_stale_vs_decision is False.
    3. When ocr_text changes after the decision, is_stale_vs_decision is True.
    4. When decided_against_hash is NULL (pre-deploy row), stale is False
       (grandfather clause).
    """

    def test_insert_decision_writes_hash(self, clean_db: DatabaseAdapter):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(
            clean_db,
            filing_id,
            "chart.jpg",
            nearby_text="cohort retention data here",
        )

        clean_db.insert_image_review_decision_v2(
            img_id=img_id,
            decision="relevant",
            chart_type="cohort_table",
        )

        rows = clean_db.query(
            "SELECT decided_against_hash FROM v2_image_review_decisions WHERE img_id = %(img_id)s",
            {"img_id": img_id},
        )
        assert rows, "Decision row should exist after insert"
        stored_hash = rows[0]["decided_against_hash"]
        # Hash must be a non-empty 64-char hex string.
        assert stored_hash is not None
        assert len(stored_hash) == 64

    def test_content_unchanged_is_not_stale(self, clean_db: DatabaseAdapter):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")

        clean_db.insert_image_review_decision_v2(
            img_id=img_id,
            decision="relevant",
            chart_type="bar_chart",
        )

        row = clean_db.get_image_review_candidate_v2(img_id)
        assert row is not None
        assert row["is_stale_vs_decision"] is False

    def test_ocr_text_change_flips_stale_true(self, clean_db: DatabaseAdapter):
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")

        clean_db.insert_image_review_decision_v2(
            img_id=img_id,
            decision="relevant",
            chart_type="bar_chart",
        )

        # Simulate re-extraction writing fresh OCR text.
        clean_db.execute(
            "UPDATE v2_image_assets SET ocr_text = %(t)s WHERE img_id = %(id)s",
            {"t": "completely different ocr output after re-extraction", "id": img_id},
        )

        row = clean_db.get_image_review_candidate_v2(img_id)
        assert row is not None
        assert row["is_stale_vs_decision"] is True

    def test_null_hash_is_not_stale_grandfather_clause(self, clean_db: DatabaseAdapter):
        """Pre-deploy decision rows with NULL decided_against_hash must not be
        flagged as stale — the grandfather clause protects existing decisions."""
        _, filing_id = create_test_company_and_filing(clean_db)
        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg")

        # Insert a legacy decision row with no hash (simulates pre-deploy state).
        clean_db.execute(
            """
            INSERT INTO v2_image_review_decisions
                (img_id, decision, chart_type, reviewer_id, decided_against_hash)
            VALUES
                (%(img_id)s, 'relevant', 'bar_chart', 'RGM', NULL)
            """,
            {"img_id": img_id},
        )

        row = clean_db.get_image_review_candidate_v2(img_id)
        assert row is not None
        assert row["is_stale_vs_decision"] is False
