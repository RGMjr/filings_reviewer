"""Integration tests for the per-metric image confirmation stats methods.

Covers:
- DatabaseAdapter.get_image_decision_overall_v2
- DatabaseAdapter.get_image_decisions_by_tier_v2
- DatabaseAdapter.get_image_rejection_reasons_by_tier_v2
- DatabaseAdapter.get_image_decisions_by_metric_v2

These methods power the unified review Statistics page (image tab).
Rows are inserted directly into v2_image_metric_confirmations to keep
the seed isolated from insert_image_metric_confirmations' side-effects
(fact promotion, validation).
"""

from __future__ import annotations

from src.infra.db import DatabaseAdapter
from tests.integration.conftest import create_test_company_and_filing


def _insert_image(
    db: DatabaseAdapter,
    filing_id: int,
    filename: str,
    *,
    classification: str = "chart",
    relevance_score: float = 0.8,
    width: int | None = 600,
    height: int | None = 400,
) -> str:
    rows = db.query(
        """
        INSERT INTO v2_image_assets
            (filing_id, filename, dom_locator, width, height,
             classification, relevance_score, review_status)
        VALUES
            (%(filing_id)s, %(filename)s, %(dom_locator)s, %(width)s, %(height)s,
             %(classification)s, %(relevance_score)s, 'pending')
        RETURNING img_id
        """,
        {
            "filing_id": filing_id,
            "filename": filename,
            "dom_locator": f"body > img[src='{filename}']",
            "width": width,
            "height": height,
            "classification": classification,
            "relevance_score": relevance_score,
        },
    )
    return str(rows[0]["img_id"])


def _insert_confirmation(
    db: DatabaseAdapter,
    img_id: str,
    *,
    decision: str,
    detected_metric_id: str | None = None,
    confirmed_metric_id: str | None = None,
    rejection_reason: str | None = None,
    reviewer_id: str = "test_reviewer",
) -> None:
    db.execute(
        """
        INSERT INTO v2_image_metric_confirmations
            (img_id, detected_metric_id, confirmed_metric_id,
             decision, rejection_reason, reviewer_id)
        VALUES
            (%(img_id)s, %(detected_metric_id)s, %(confirmed_metric_id)s,
             %(decision)s, %(rejection_reason)s, %(reviewer_id)s)
        """,
        {
            "img_id": img_id,
            "detected_metric_id": detected_metric_id,
            "confirmed_metric_id": confirmed_metric_id,
            "decision": decision,
            "rejection_reason": rejection_reason,
            "reviewer_id": reviewer_id,
        },
    )


# tier_1_cohort: classification='chart' AND relevance_score >= 0.6
# tier_2_large: chart|table_image AND width>=300 AND height>=300 AND score<0.6
# tier_3_all: anything else (e.g. small)
def _seed_three_tiers(db: DatabaseAdapter) -> dict[str, str]:
    _, filing_id = create_test_company_and_filing(db)
    return {
        "tier_1": _insert_image(
            db, filing_id, "t1.jpg", classification="chart", relevance_score=0.9
        ),
        "tier_2": _insert_image(
            db,
            filing_id,
            "t2.jpg",
            classification="chart",
            relevance_score=0.3,
            width=600,
            height=400,
        ),
        "tier_3": _insert_image(
            db,
            filing_id,
            "t3.jpg",
            classification="chart",
            relevance_score=0.3,
            width=100,
            height=100,
        ),
    }


class TestGetImageDecisionOverallV2:
    def test_empty_table_returns_zeros(self, clean_db):
        result = clean_db.get_image_decision_overall_v2()
        assert result == {
            "total_decisions": 0,
            "relevant_count": 0,
            "not_relevant_count": 0,
            "relevant_pct": 0.0,
            "not_relevant_pct": 0.0,
        }

    def test_counts_relevant_vs_not_relevant(self, clean_db):
        imgs = _seed_three_tiers(clean_db)
        # 3 relevant: accept, correct, add
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="accept",
            detected_metric_id="cm_a",
            confirmed_metric_id="cm_a",
        )
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="correct",
            detected_metric_id="cm_b",
            confirmed_metric_id="cm_c",
        )
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="add",
            detected_metric_id=None,
            confirmed_metric_id="cm_d",
        )
        # 2 not_relevant: reject + sentinel reject
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="reject",
            detected_metric_id="cm_e",
            rejection_reason="not_a_chart",
        )
        _insert_confirmation(
            clean_db,
            imgs["tier_3"],
            decision="reject",
            detected_metric_id=None,
            confirmed_metric_id=None,
            rejection_reason="no_relevant_metrics",
        )

        result = clean_db.get_image_decision_overall_v2()
        assert result["total_decisions"] == 5
        assert result["relevant_count"] == 3
        assert result["not_relevant_count"] == 2
        assert result["relevant_pct"] == 60.0
        assert result["not_relevant_pct"] == 40.0


class TestGetImageDecisionsByTierV2:
    def test_empty_returns_empty_list(self, clean_db):
        assert clean_db.get_image_decisions_by_tier_v2() == []

    def test_excludes_add_and_sentinel_rows(self, clean_db):
        imgs = _seed_three_tiers(clean_db)
        # tier_1: accept (counted) + add (excluded)
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="accept",
            detected_metric_id="cm_a",
            confirmed_metric_id="cm_a",
        )
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="add",
            detected_metric_id=None,
            confirmed_metric_id="cm_x",
        )
        # tier_2: sentinel reject (excluded — detected_metric_id IS NULL)
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="reject",
            detected_metric_id=None,
            confirmed_metric_id=None,
            rejection_reason="no_relevant_metrics",
        )

        rows = {r["detection_tier"]: r for r in clean_db.get_image_decisions_by_tier_v2()}
        # Only tier_1 should appear (one accept). tier_2's row was a sentinel; excluded.
        assert "tier_1_cohort" in rows
        assert rows["tier_1_cohort"]["relevant_count"] == 1
        assert rows["tier_1_cohort"]["not_relevant_count"] == 0
        assert rows["tier_1_cohort"]["total_decisions"] == 1
        assert rows["tier_1_cohort"]["precision_pct"] == 100.0
        assert "tier_2_large" not in rows

    def test_precision_pct_with_mixed_tiers(self, clean_db):
        imgs = _seed_three_tiers(clean_db)
        # tier_1: 2 accepts, 0 rejects → 100%
        for m in ("cm_a", "cm_b"):
            _insert_confirmation(
                clean_db,
                imgs["tier_1"],
                decision="accept",
                detected_metric_id=m,
                confirmed_metric_id=m,
            )
        # tier_2: 1 correct, 3 rejects → 25%
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="correct",
            detected_metric_id="cm_c",
            confirmed_metric_id="cm_c2",
        )
        for m in ("cm_d", "cm_e", "cm_f"):
            _insert_confirmation(
                clean_db,
                imgs["tier_2"],
                decision="reject",
                detected_metric_id=m,
                rejection_reason="wrong_subject",
            )
        # tier_3: 0 accepts, 1 reject → 0%
        _insert_confirmation(
            clean_db,
            imgs["tier_3"],
            decision="reject",
            detected_metric_id="cm_g",
            rejection_reason="not_a_chart",
        )

        rows = {r["detection_tier"]: r for r in clean_db.get_image_decisions_by_tier_v2()}
        assert rows["tier_1_cohort"]["precision_pct"] == 100.0
        assert rows["tier_2_large"]["relevant_count"] == 1
        assert rows["tier_2_large"]["not_relevant_count"] == 3
        assert rows["tier_2_large"]["precision_pct"] == 25.0
        assert rows["tier_3_all"]["precision_pct"] == 0.0


class TestGetImageRejectionReasonsByTierV2:
    def test_empty_returns_empty_list(self, clean_db):
        assert clean_db.get_image_rejection_reasons_by_tier_v2() == []

    def test_pct_sums_to_100_per_tier_and_includes_sentinel(self, clean_db):
        imgs = _seed_three_tiers(clean_db)
        # tier_2: 3 wrong_subject + 1 unreadable = 4 rejects
        for m in ("cm_a", "cm_b", "cm_c"):
            _insert_confirmation(
                clean_db,
                imgs["tier_2"],
                decision="reject",
                detected_metric_id=m,
                rejection_reason="wrong_subject",
            )
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="reject",
            detected_metric_id="cm_d",
            rejection_reason="unreadable",
        )
        # tier_3: 1 sentinel reject (rejection_reason='no_relevant_metrics')
        _insert_confirmation(
            clean_db,
            imgs["tier_3"],
            decision="reject",
            detected_metric_id=None,
            confirmed_metric_id=None,
            rejection_reason="no_relevant_metrics",
        )

        rows = clean_db.get_image_rejection_reasons_by_tier_v2()

        by_tier: dict[str, list[dict]] = {}
        for r in rows:
            by_tier.setdefault(r["detection_tier"], []).append(r)

        # tier_2 has two reasons; counts and pct sum check
        t2 = {r["rejection_reason"]: r for r in by_tier["tier_2_large"]}
        assert t2["wrong_subject"]["rejection_count"] == 3
        assert t2["unreadable"]["rejection_count"] == 1
        assert t2["wrong_subject"]["pct_of_tier_rejections"] == 75.0
        assert t2["unreadable"]["pct_of_tier_rejections"] == 25.0

        # Sentinel surfaces under tier_3 with 100% of that tier's rejects
        t3 = {r["rejection_reason"]: r for r in by_tier["tier_3_all"]}
        assert t3["no_relevant_metrics"]["rejection_count"] == 1
        assert t3["no_relevant_metrics"]["pct_of_tier_rejections"] == 100.0


class TestGetImageDecisionsByMetricV2:
    def test_empty_returns_empty_list(self, clean_db):
        assert clean_db.get_image_decisions_by_metric_v2() == []

    def test_attribution_per_decision_type(self, clean_db):
        """accept→detected, correct→confirmed, add→confirmed, reject→detected.

        Mixed decisions on different metrics; verify each lands on the right
        metric_id and the sentinel reject is excluded.
        """
        imgs = _seed_three_tiers(clean_db)
        # cm_a: 1 accept (detected=cm_a, confirmed=NULL on accept)
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="accept",
            detected_metric_id="cm_a",
            confirmed_metric_id=None,
        )
        # cm_b: 1 correct from cm_x (detected=cm_x, confirmed=cm_b)
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="correct",
            detected_metric_id="cm_x",
            confirmed_metric_id="cm_b",
        )
        # cm_c: 1 add (detected=NULL, confirmed=cm_c)
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="add",
            detected_metric_id=None,
            confirmed_metric_id="cm_c",
        )
        # cm_x: 1 reject (detected=cm_x, confirmed=NULL) — same metric the
        # correct above flagged as wrongly detected
        _insert_confirmation(
            clean_db,
            imgs["tier_2"],
            decision="reject",
            detected_metric_id="cm_x",
            rejection_reason="not_present",
        )
        # Sentinel reject (no metric to attribute) — must be excluded
        _insert_confirmation(
            clean_db,
            imgs["tier_3"],
            decision="reject",
            detected_metric_id=None,
            confirmed_metric_id=None,
            rejection_reason="no_relevant_metrics",
        )

        rows = {r["metric_id"]: r for r in clean_db.get_image_decisions_by_metric_v2()}

        assert set(rows.keys()) == {"cm_a", "cm_b", "cm_c", "cm_x"}
        assert rows["cm_a"]["accepted_count"] == 1
        assert rows["cm_a"]["confirmed_images"] == 1
        assert rows["cm_a"]["rejected_count"] == 0
        assert rows["cm_a"]["precision_pct"] == 100.0

        assert rows["cm_b"]["corrected_count"] == 1
        assert rows["cm_b"]["confirmed_images"] == 1

        assert rows["cm_c"]["added_count"] == 1
        assert rows["cm_c"]["confirmed_images"] == 1
        # No accept/correct + no reject → precision is undefined
        assert rows["cm_c"]["precision_pct"] is None

        assert rows["cm_x"]["rejected_count"] == 1
        assert rows["cm_x"]["confirmed_images"] == 0
        assert rows["cm_x"]["precision_pct"] == 0.0

    def test_precision_combines_accept_and_correct(self, clean_db):
        imgs = _seed_three_tiers(clean_db)
        # cm_y: 2 accept + 1 correct + 1 reject = 3/4 → 75%
        for img in (imgs["tier_1"], imgs["tier_2"]):
            _insert_confirmation(
                clean_db,
                img,
                decision="accept",
                detected_metric_id="cm_y",
                confirmed_metric_id=None,
            )
        _insert_confirmation(
            clean_db,
            imgs["tier_3"],
            decision="correct",
            detected_metric_id="cm_other",
            confirmed_metric_id="cm_y",
        )
        _insert_confirmation(
            clean_db,
            imgs["tier_3"],
            decision="reject",
            detected_metric_id="cm_y",
            rejection_reason="not_present",
        )

        rows = {r["metric_id"]: r for r in clean_db.get_image_decisions_by_metric_v2()}
        assert rows["cm_y"]["accepted_count"] == 2
        assert rows["cm_y"]["corrected_count"] == 1
        assert rows["cm_y"]["rejected_count"] == 1
        assert rows["cm_y"]["confirmed_images"] == 3  # 2 accept + 1 correct + 0 add
        assert rows["cm_y"]["precision_pct"] == 75.0

    def test_sort_desc_by_confirmed_images(self, clean_db):
        imgs = _seed_three_tiers(clean_db)
        # cm_low: 1 accept
        _insert_confirmation(
            clean_db,
            imgs["tier_1"],
            decision="accept",
            detected_metric_id="cm_low",
            confirmed_metric_id=None,
        )
        # cm_high: 3 accepts (one per tier image)
        for img in imgs.values():
            _insert_confirmation(
                clean_db,
                img,
                decision="accept",
                detected_metric_id="cm_high",
                confirmed_metric_id=None,
            )

        rows = clean_db.get_image_decisions_by_metric_v2()
        metric_ids = [r["metric_id"] for r in rows]
        assert metric_ids == ["cm_high", "cm_low"]
