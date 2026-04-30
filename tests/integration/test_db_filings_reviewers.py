"""Integration tests for get_unified_filings_for_review reviewer aggregation (KNOWN_ISSUES #76).

Guards `DatabaseAdapter.get_unified_filings_for_review` against future CTE refactors
silently dropping a reviewer source from the text+image UNION.
"""

from __future__ import annotations

from src.infra.db import DatabaseAdapter
from tests.integration.conftest import (
    create_test_company_and_filing,
    create_test_v2_decision,
    create_test_v2_document,
    create_test_v2_fact,
)


def _insert_v2_image(
    db: DatabaseAdapter,
    filing_id: int,
    filename: str,
    classification: str = "chart",
    review_status: str = "pending",
) -> str:
    """Insert a v2_image_assets row and return img_id as string."""
    rows = db.query(
        """
        INSERT INTO v2_image_assets
            (filing_id, filename, dom_locator, width, height, nearby_text,
             classification, relevance_score, review_status, section_type)
        VALUES
            (%(filing_id)s, %(filename)s, %(dom_locator)s, %(width)s, %(height)s,
             %(nearby_text)s, %(classification)s, %(relevance_score)s,
             %(review_status)s, %(section_type)s)
        RETURNING img_id
        """,
        {
            "filing_id": filing_id,
            "filename": filename,
            "dom_locator": f"body > img[src='{filename}']",
            "width": 600,
            "height": 400,
            "nearby_text": "retention chart",
            "classification": classification,
            "relevance_score": 0.8,
            "review_status": review_status,
            "section_type": "mda",
        },
    )
    return str(rows[0]["img_id"])


def _insert_image_decision(
    db: DatabaseAdapter,
    img_id: str,
    reviewer_id: str | None = "reviewer",
) -> int:
    """Insert a v2_image_review_decisions row and return image_decision_id."""
    rows = db.query(
        """
        INSERT INTO v2_image_review_decisions
            (img_id, decision, chart_type, reviewer_id)
        VALUES
            (%(img_id)s, %(decision)s, %(chart_type)s, %(reviewer_id)s)
        RETURNING image_decision_id
        """,
        {
            "img_id": img_id,
            "decision": "relevant",
            "chart_type": "cohort_table",
            "reviewer_id": reviewer_id,
        },
    )
    return int(rows[0]["image_decision_id"])


def _find_filing_row(rows: list[dict], filing_id: int) -> dict | None:
    for row in rows:
        if row["filing_id"] == filing_id:
            return row
    return None


class TestReviewerAggregation:
    def test_reviewers_aggregates_text_and_image_sources(self, clean_db: DatabaseAdapter) -> None:
        """Text decision from alice + image decision from bob both appear in reviewers."""
        _, filing_id = create_test_company_and_filing(clean_db)
        create_test_v2_document(clean_db, filing_id)

        fact_id = create_test_v2_fact(clean_db, filing_id)
        create_test_v2_decision(clean_db, fact_id, reviewer_id="alice")

        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg", review_status="reviewed")
        _insert_image_decision(clean_db, img_id, reviewer_id="bob")

        rows = clean_db.get_unified_filings_for_review()
        row = _find_filing_row(rows, filing_id)

        assert row is not None
        assert sorted(row["reviewers"]) == ["alice", "bob"]

    def test_reviewer_ids_filter_narrows_correctly(self, clean_db: DatabaseAdapter) -> None:
        """reviewer_ids kwarg returns filing for matched reviewer and excludes it for others."""
        _, filing_id = create_test_company_and_filing(clean_db)
        create_test_v2_document(clean_db, filing_id)

        fact_id = create_test_v2_fact(clean_db, filing_id)
        create_test_v2_decision(clean_db, fact_id, reviewer_id="alice")

        img_id = _insert_v2_image(clean_db, filing_id, "chart.jpg", review_status="reviewed")
        _insert_image_decision(clean_db, img_id, reviewer_id="bob")

        matched = clean_db.get_unified_filings_for_review(reviewer_ids=["alice"])
        assert _find_filing_row(matched, filing_id) is not None

        not_matched = clean_db.get_unified_filings_for_review(reviewer_ids=["zoe"])
        assert _find_filing_row(not_matched, filing_id) is None

    def test_null_reviewer_ids_yield_empty_reviewer_list(self, clean_db: DatabaseAdapter) -> None:
        """Image decision rows with NULL reviewer_id produce an empty reviewers array."""
        _, filing_id = create_test_company_and_filing(clean_db)
        create_test_v2_document(clean_db, filing_id)

        img_id = _insert_v2_image(clean_db, filing_id, "anon.jpg", review_status="reviewed")
        _insert_image_decision(clean_db, img_id, reviewer_id=None)

        rows = clean_db.get_unified_filings_for_review()
        row = _find_filing_row(rows, filing_id)

        assert row is not None
        assert row["reviewers"] == []


class TestImagesReviewedCount:
    """Guards the filings-list `images_reviewed` counter against under-reporting
    images that the reviewer flipped to 'skipped' via "Reject all (no relevant
    metrics)" — those carry per-metric reject rows in
    v2_image_metric_confirmations and should count as reviewed."""

    def test_skipped_with_confirmations_counts_as_reviewed(self, clean_db: DatabaseAdapter) -> None:
        _, filing_id = create_test_company_and_filing(clean_db)
        create_test_v2_document(clean_db, filing_id)

        # Image #1 — finalized via Mark Complete: counts.
        _insert_v2_image(clean_db, filing_id, "img1.jpg", review_status="reviewed")
        # Image #2 — Reject-all: skipped + per-metric reject row. Should count.
        img2 = _insert_v2_image(clean_db, filing_id, "img2.jpg", review_status="skipped")
        clean_db.execute(
            """
            INSERT INTO v2_image_metric_confirmations
                (img_id, detected_metric_id, confirmed_metric_id,
                 decision, rejection_reason, reviewer_id)
            VALUES
                (%(img_id)s, NULL, NULL, 'reject', 'no_relevant_metrics', 'rgm')
            """,
            {"img_id": img2},
        )
        # Image #3 — pure "Skip whole image" with zero confirmations. Should NOT count.
        _insert_v2_image(clean_db, filing_id, "img3.jpg", review_status="skipped")
        # Image #4 — pending. Should NOT count toward reviewed.
        _insert_v2_image(clean_db, filing_id, "img4.jpg", review_status="pending")

        rows = clean_db.get_unified_filings_for_review()
        row = _find_filing_row(rows, filing_id)

        assert row is not None
        assert row["images_pending"] == 1
        assert row["images_reviewed"] == 2  # img1 (reviewed) + img2 (skipped+confirmation)
