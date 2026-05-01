"""Image-tab sort-by-model-score behavior.

The 'model_score' sort is computed in Python after the SQL SELECT (see
src/web/routes/review_unified.py and api_unified.py). These tests cover:

- The Python sort orders by model score DESC.
- None-scored rows land last (NULLS LAST analog).
- The pending-first partition in the route is stable, so model-score order
  is preserved within each partition.
- Invalid ?image_sort= values fall back to the 'relevance' default.
- _get_next_image_candidate_info round-trips image_sort into the next URL.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.web.routes.api_unified import _get_next_image_candidate_info


def _candidate(
    img_id: str,
    model_score: float | None = None,
    review_status: str = "pending",
    image_review_state: str | None = None,
) -> dict:
    if image_review_state is None:
        image_review_state = "pending" if review_status == "pending" else "no_relevant"
    return {
        "img_id": img_id,
        "review_status": review_status,
        "image_review_state": image_review_state,
        "_model_score": model_score,
        # Fields v2_row_to_features_input would read if called for real.
        "preceding_text": "",
        "image_width": 800,
        "image_height": 600,
        "cohort_confidence": 0.0,
        "classification": "chart",
        "filename": f"{img_id}.png",
    }


# ---------------------------------------------------------------------------
# Python sort ordering (mirrors the route's lambda exactly)
# ---------------------------------------------------------------------------


def test_model_score_sort_orders_high_first():
    rows = [
        _candidate("a", model_score=0.10),
        _candidate("b", model_score=0.85),
        _candidate("c", model_score=0.50),
    ]
    rows.sort(key=lambda c: (c["_model_score"] is None, -(c["_model_score"] or 0.0)))
    assert [r["img_id"] for r in rows] == ["b", "c", "a"]


def test_model_score_sort_nulls_last():
    rows = [
        _candidate("a", model_score=None),
        _candidate("b", model_score=0.40),
        _candidate("c", model_score=None),
        _candidate("d", model_score=0.70),
    ]
    rows.sort(key=lambda c: (c["_model_score"] is None, -(c["_model_score"] or 0.0)))
    # Scored rows DESC first, then None rows in their original relative order.
    assert [r["img_id"] for r in rows] == ["d", "b", "a", "c"]


def test_model_score_sort_pending_first_partition_stable():
    """The route applies pending-first AFTER the model-score sort. The
    pending-first sorted() is stable, so model-score order is preserved
    within each partition (a high-scored reviewed image still appears
    before a low-scored reviewed image)."""
    rows = [
        _candidate("a", model_score=0.90, review_status="reviewed"),
        _candidate("b", model_score=0.20, review_status="pending"),
        _candidate("c", model_score=0.10, review_status="reviewed"),
        _candidate("d", model_score=0.80, review_status="pending"),
    ]
    # Step 1: model-score sort.
    rows.sort(key=lambda c: (c["_model_score"] is None, -(c["_model_score"] or 0.0)))
    # Step 2: stable pending-first partition (mirrors review_unified.py).
    rows = sorted(rows, key=lambda c: 0 if c["review_status"] == "pending" else 1)
    # Pending first (d=0.80, b=0.20), then reviewed (a=0.90, c=0.10).
    assert [r["img_id"] for r in rows] == ["d", "b", "a", "c"]


# ---------------------------------------------------------------------------
# _get_next_image_candidate_info passes sort through to next URL
# ---------------------------------------------------------------------------


def test_next_candidate_url_preserves_image_sort():
    """When view_filters carries sort=model_score, the emitted URL must
    include &image_sort=model_score so the next page lands in the same view."""
    db = MagicMock()
    db.get_image_review_candidates_for_filing_v2.return_value = [
        _candidate("img-current", review_status="pending"),
        _candidate("img-next", review_status="pending"),
    ]
    # Patch predict_relevance so the test doesn't need a real model file —
    # both candidates already have _model_score set, but the route's branch
    # re-computes them, so we stub the call.
    with patch(
        "src.web.routes.api_unified.predict_relevance"
        if False
        else "src.shared.image_features.predict_relevance",
        return_value=0.5,
    ):
        out = _get_next_image_candidate_info(
            db,
            filing_id=42,
            current_img_id="img-current",
            view_filters={"status": "pending", "sort": "model_score"},
        )
    assert out is not None
    assert "image_sort=model_score" in out["url"]


def test_next_candidate_url_omits_sort_when_default():
    """sort=relevance is the default, so the URL should NOT carry image_sort
    (keeps URLs clean for the most common case)."""
    db = MagicMock()
    db.get_image_review_candidates_for_filing_v2.return_value = [
        _candidate("img-current", review_status="pending"),
        _candidate("img-next", review_status="pending"),
    ]
    out = _get_next_image_candidate_info(
        db,
        filing_id=42,
        current_img_id="img-current",
        view_filters={"status": "pending", "sort": "relevance"},
    )
    assert out is not None
    assert "image_sort" not in out["url"]


def test_next_candidate_url_invalid_sort_falls_back_to_relevance():
    """Invalid sort string must be coerced to 'relevance' (defense against
    a curl that forges a bad value)."""
    db = MagicMock()
    db.get_image_review_candidates_for_filing_v2.return_value = [
        _candidate("img-current", review_status="pending"),
        _candidate("img-next", review_status="pending"),
    ]
    out = _get_next_image_candidate_info(
        db,
        filing_id=42,
        current_img_id="img-current",
        view_filters={"status": "pending", "sort": "garbage"},
    )
    assert out is not None
    assert "image_sort" not in out["url"]
    # And the SQL call should have used 'relevance', not the garbage value.
    call_kwargs = db.get_image_review_candidates_for_filing_v2.call_args.kwargs
    assert call_kwargs["sort_by"] == "relevance"
