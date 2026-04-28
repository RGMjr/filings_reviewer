"""Filter-aware advancement on the review page.

Covers:
- _get_next_pending_fact walks the same filtered+sorted list the reviewer is
  looking at, including the anchor_index fallback when the just-decided fact
  drops out of the filter.
- _get_next_image_candidate_info walks the pending-first partition + relevance
  ordering of the candidate list, scoped to the active image_status filter,
  and returns None at the end (no wrap-around).
- infer_tab_from_filing maps document_type/form_type back to the analytical
  tab so cross-filing advance can scope to the same view.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.infra.db import infer_tab_from_filing
from src.web.routes.api_unified import (
    _get_next_image_candidate_info,
    _get_next_pending_fact,
)


def _fact(fact_id: str, status: str = "pending_review") -> dict:
    return {"fact_id": fact_id, "review_status": status}


def _image(img_id: str, status: str = "pending") -> dict:
    return {"img_id": img_id, "review_status": status}


# ---------------------------------------------------------------------------
# infer_tab_from_filing
# ---------------------------------------------------------------------------


def test_infer_tab_from_filing_ipo():
    assert infer_tab_from_filing("sec_filing", "S-1") == "ipo"
    assert infer_tab_from_filing("sec_filing", "F-1/A") == "ipo"


def test_infer_tab_from_filing_earnings():
    assert infer_tab_from_filing("earnings_call", None) == "earnings"
    assert infer_tab_from_filing("sec_filing", "10-Q") == "earnings"
    assert infer_tab_from_filing("sec_filing", "8-K") == "earnings"


def test_infer_tab_from_filing_investor_day():
    assert infer_tab_from_filing("investor_presentation", None) == "investor_day"


def test_infer_tab_from_filing_unknown_returns_none():
    assert infer_tab_from_filing(None, None) is None
    assert infer_tab_from_filing("sec_filing", "DEF 14A") is None


# ---------------------------------------------------------------------------
# _get_next_pending_fact: filter+sort awareness
# ---------------------------------------------------------------------------


def test_get_next_pending_fact_walks_filtered_view():
    """Advancement honors view_filters: status=accepted should walk only
    accepted facts in the current sort order, not pending ones."""
    db = MagicMock()
    db.get_v2_facts_for_filing.return_value = [
        _fact("a", "accepted"),
        _fact("b", "accepted"),
        _fact("c", "accepted"),
    ]
    out = _get_next_pending_fact(
        db,
        filing_id=1,
        current_fact_id="a",
        view_filters={"status": "accepted", "metric": "all", "sort": "metric"},
        anchor_index=0,
    )
    db.get_v2_facts_for_filing.assert_called_once_with(
        1, status="accepted", metric_id=None, sort_by="metric"
    )
    assert out == {"fact_id": "b", "url": "/v2/review/1?fact_id=b"}


def test_get_next_pending_fact_anchor_fallback_when_dropped_out():
    """When the just-decided fact left the filter (e.g. reject under
    status=pending_review), the freshly-queried list shrunk by one — so the
    same anchor_index now points at what used to be anchor_index+1."""
    db = MagicMock()
    db.get_v2_facts_for_filing.return_value = [
        _fact("p1"),
        _fact("p2"),
        _fact("p3"),
    ]
    # User just rejected fact "p0" at anchor_index=0; "p0" is gone from the
    # filtered list. Server returns facts[0] = "p1".
    out = _get_next_pending_fact(
        db,
        filing_id=1,
        current_fact_id="p0",
        view_filters={"status": "pending_review"},
        anchor_index=0,
    )
    assert out["fact_id"] == "p1"


def test_get_next_pending_fact_returns_none_at_end_of_view():
    db = MagicMock()
    db.get_v2_facts_for_filing.return_value = [_fact("only")]
    out = _get_next_pending_fact(
        db,
        filing_id=1,
        current_fact_id="only",
        view_filters={"status": "pending_review"},
        anchor_index=0,
    )
    assert out is None


def test_get_next_pending_fact_invalid_filter_falls_back_to_defaults():
    """Garbage in view_filters does not crash; it normalizes to the route's
    ground-truth defaults (status=None, sort=confidence_desc)."""
    db = MagicMock()
    db.get_v2_facts_for_filing.return_value = [_fact("a"), _fact("b")]
    _get_next_pending_fact(
        db,
        filing_id=1,
        current_fact_id="a",
        view_filters={"status": "garbage", "sort": "garbage"},
        anchor_index=0,
    )
    db.get_v2_facts_for_filing.assert_called_once_with(
        1, status=None, metric_id=None, sort_by="confidence_desc"
    )


# ---------------------------------------------------------------------------
# _get_next_image_candidate_info: filter awareness
# ---------------------------------------------------------------------------


def test_get_next_image_candidate_walks_pending_first_partition():
    """Pending images come before everything else, then relevance order is
    preserved within each partition (matches the rendered thumbnail strip)."""
    db = MagicMock()
    db.get_image_review_candidates_for_filing_v2.return_value = [
        _image("a", "pending"),
        _image("b", "reviewed"),
        _image("c", "pending"),
    ]
    out = _get_next_image_candidate_info(db, filing_id=1, current_img_id="a")
    # After partitioning: [a (pending), c (pending), b (reviewed)]; next of a is c.
    assert out["img_id"] == "c"


def test_get_next_image_candidate_respects_status_filter():
    db = MagicMock()
    db.get_image_review_candidates_for_filing_v2.return_value = [
        _image("a", "pending"),
        _image("c", "pending"),
    ]
    out = _get_next_image_candidate_info(
        db,
        filing_id=1,
        current_img_id="a",
        view_filters={"status": "pending"},
    )
    db.get_image_review_candidates_for_filing_v2.assert_called_once_with(
        filing_id=1,
        status="pending",
        sort_by="relevance",
        limit=1000,
    )
    assert out["img_id"] == "c"
    # The next URL preserves the active filter so the strip the user lands on
    # shows the same scope.
    assert "image_status=pending" in out["url"]


def test_get_next_image_candidate_returns_none_at_end_no_wraparound():
    """Old behavior wrapped around to skipped images when the queue emptied;
    new behavior returns None so the cross-tab cascade fires correctly."""
    db = MagicMock()
    db.get_image_review_candidates_for_filing_v2.return_value = [
        _image("a", "pending"),
    ]
    out = _get_next_image_candidate_info(db, filing_id=1, current_img_id="a")
    assert out is None
