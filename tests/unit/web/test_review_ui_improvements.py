"""
Regression tests for the reviewer-flow UI improvements:

- A1: default tab picks images when text is empty and images have pending work.
- A1: explicit ?tab= query param wins over the default.
- B1: image thumbnail strip shows pending items before reviewed ones.
- A3/fix: next-filing redirect omits tab= so the landing route can pick the tab.

Uses Flask's test_client against real Jinja rendering (no render_template mock).
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app

_FILING = {
    "filing_id": 42,
    "company_id": 1,
    "company_name": "Acme Corp",
    "ticker": "ACME",
    "cik": "0001757083",
    "accession_number": "0001144204-19-000180",
    "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1757083/000114420419000180/",
    "form_type": "S-1",
    "filing_date": None,
    "document_type": "sec_filing",
}


def _fact(fact_id: str, status: str = "pending_review") -> dict:
    return {
        "fact_id": fact_id,
        "canonical_metric_id": "cm_net_revenue_retention",
        "review_status": status,
        "confidence": 0.9,
        "value_raw": "115%",
        "value": 115.0,
        "unit": "percent",
        "period_start": None,
        "period_end": None,
        "period_type": "annual",
        "scope": "company",
        "scope_detail": None,
        "customer_type": None,
        "source_type": "text",
        "extraction_method": "keyword",
        "review_reason": None,
        "evidence_pack": {
            "context_before": "",
            "highlighted_html": "",
            "context_after": "",
            "header_path": [],
            "stub_path": None,
            "snippet_html": None,
        },
        "source_locator": {"segment_id": "1"},
        "_table_context": None,
        "_segment_context": None,
        "decision_id": None,
        "decision": None,
        "decision_metric_id": None,
        "corrected_value": None,
        "rejection_reason": None,
        "rejection_category": None,
        "reviewer_notes": None,
        "reviewer_id": None,
    }


def _image(img_id: str, status: str = "pending", relevance: float = 0.9) -> dict:
    filename = f"{img_id[:8]}.jpg"
    return {
        "img_id": img_id,
        "filing_id": _FILING["filing_id"],
        "filename": filename,
        "image_src": filename,
        "image_url": f"/images/cache/1757083/000114420419000180/{filename}",
        "image_src_url": f"https://example.com/{filename}",
        "image_width": 800,
        "image_height": 600,
        "preceding_text": "",
        "detected_keywords": [],
        "classification": "chart",
        "cohort_confidence": 0.8,
        "predicted_relevance": relevance,
        "review_status": status,
        "section_type": "body",
        "is_decorative": False,
        "detection_tier": "tier_1_cohort",
        "created_at": None,
        "image_decision_id": None,
        "decision": None,
        "chart_type": None,
        "rejection_reason": None,
        "decision_notes": None,
        "review_time_seconds": None,
        "decision_created_at": None,
    }


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = "postgresql://test"
    app.config["_db_pool"] = None
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_db_for_review(facts: list[dict], images: list[dict]) -> MagicMock:
    mock_db = MagicMock()
    mock_db.query.return_value = [_FILING]
    mock_db.get_v2_facts_for_filing.return_value = facts
    mock_db.count_v2_facts_for_filing.return_value = len(facts)
    mock_db.get_image_review_candidates_for_filing_v2.return_value = images
    return mock_db


def _render_review(client, mock_db, query: str = "") -> str:
    with (
        patch("src.web.routes.review_unified.get_db", return_value=mock_db),
        patch("src.web.routes._metrics.get_db", return_value=mock_db),
        patch(
            "src.web.routes.review_unified.get_active_metrics",
            return_value=[],
        ),
    ):
        url = f"/v2/review/{_FILING['filing_id']}"
        if query:
            url += f"?{query}"
        response = client.get(url)
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. "
        f"Body head: {response.get_data(as_text=True)[:400]}"
    )
    return response.get_data(as_text=True)


def _tab_is_active(body: str, which: str) -> bool:
    """True iff the nav-link for `which` ('text'|'images') carries `active`."""
    pattern = rf'<a class="nav-link[^"]*\bactive\b[^"]*"[^>]*href="[^"]*\btab={which}\b'
    return bool(re.search(pattern, body))


def test_default_tab_is_images_when_text_empty_and_images_pending(client):
    mock_db = _mock_db_for_review(facts=[], images=[_image("aaaa", status="pending")])

    body = _render_review(client, mock_db)  # no ?tab=

    assert _tab_is_active(body, "images"), (
        "With 0 pending text and >0 pending images, the Images tab should be active by default."
    )
    assert not _tab_is_active(body, "text")


def test_default_tab_is_text_when_text_has_pending(client):
    mock_db = _mock_db_for_review(
        facts=[_fact("f1", "pending_review")],
        images=[_image("aaaa", status="pending")],
    )

    body = _render_review(client, mock_db)

    assert _tab_is_active(body, "text")
    assert not _tab_is_active(body, "images")


def test_default_tab_is_text_when_both_empty(client):
    mock_db = _mock_db_for_review(facts=[], images=[])

    body = _render_review(client, mock_db)

    assert _tab_is_active(body, "text")


def test_explicit_tab_text_overrides_default(client):
    # Text is empty, images pending → default would be images.
    # Explicit ?tab=text must still win.
    mock_db = _mock_db_for_review(facts=[], images=[_image("aaaa", status="pending")])

    body = _render_review(client, mock_db, query="tab=text")

    assert _tab_is_active(body, "text")
    assert not _tab_is_active(body, "images")


def test_explicit_tab_images_overrides_default(client):
    mock_db = _mock_db_for_review(
        facts=[_fact("f1", "pending_review")],
        images=[_image("aaaa", status="pending")],
    )

    body = _render_review(client, mock_db, query="tab=images")

    assert _tab_is_active(body, "images")


def test_image_thumbnails_pending_items_first(client):
    # Mix pending and reviewed; backend returns them interleaved.
    # Template must render pending ones first (stable within each partition).
    reviewed = _image("11111111-1111-1111-1111-111111111111", status="reviewed")
    pending_a = _image("22222222-2222-2222-2222-222222222222", status="pending")
    pending_b = _image("33333333-3333-3333-3333-333333333333", status="pending")
    skipped = _image("44444444-4444-4444-4444-444444444444", status="skipped")

    mock_db = _mock_db_for_review(
        facts=[],
        images=[reviewed, pending_a, skipped, pending_b],
    )

    body = _render_review(client, mock_db, query="tab=images")

    # Extract thumbnail-item data-img-id values in DOM order.
    thumb_ids = re.findall(
        r'class="[^"]*thumbnail-item[^"]*"[^>]*data-img-id="([^"]+)"',
        body,
    )
    assert thumb_ids, "No thumbnails rendered in the sidebar"

    pending_ids = {pending_a["img_id"], pending_b["img_id"]}
    first_two = thumb_ids[:2]
    assert set(first_two) == pending_ids, (
        f"Expected pending thumbnails first, got DOM order: {thumb_ids}"
    )


def test_next_filing_redirect_omits_tab_param(client):
    mock_db = MagicMock()
    mock_db.get_next_filing_with_pending_work.return_value = 99

    with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
        response = client.get(
            "/v2/review/next-filing?current_filing_id=42"
            "&list_sort_by=date&list_sort_dir=desc&list_hide_completed=0"
        )

    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith("/v2/review/99"), (
        f"Expected redirect to /v2/review/99, got {location!r}"
    )
    assert "tab=" not in location, f"next-filing redirect must not hardcode tab=; got {location!r}"


def test_window_text_pending_exposed_on_images_tab(client):
    # The images-tab IIFE reads window.TEXT_PENDING to mirror the text-tab
    # handoff behavior. Regression guard: keep the global exposed.
    mock_db = _mock_db_for_review(
        facts=[_fact("f1", "pending_review"), _fact("f2", "pending_review")],
        images=[_image("aaaa", status="pending")],
    )

    body = _render_review(client, mock_db, query="tab=images")

    assert "window.TEXT_PENDING = 2" in body, (
        "Expected window.TEXT_PENDING = <pending_count> to be set in the template"
    )


def _mock_db_for_filtered_images(all_images: list[dict], filtered_images: list[dict]) -> MagicMock:
    """Mock that returns different lists for unfiltered vs status-filtered calls.

    Matches the route's two-call pattern at review_unified.py:376-388 — the
    first (no status=) populates all_image_candidates / the pending badge,
    the second (with status=) populates image_candidates / the tab body.
    """
    mock_db = MagicMock()
    mock_db.query.return_value = [_FILING]
    mock_db.get_v2_facts_for_filing.return_value = []
    mock_db.count_v2_facts_for_filing.return_value = 0

    def _images(*args, **kwargs):
        return filtered_images if kwargs.get("status") else all_images

    mock_db.get_image_review_candidates_for_filing_v2.side_effect = _images
    return mock_db


def test_images_tab_empty_filter_shows_clear_link(client):
    # Bug: filing with only pending images, visited with ?image_status=reviewed
    # rendered "No image candidates have been generated for this filing yet"
    # and hid the filter bar, leaving the reviewer stuck. The empty-state must
    # now distinguish "filter excluded everything" from "truly no images".
    mock_db = _mock_db_for_filtered_images(
        all_images=[_image("aaaa", status="pending")],
        filtered_images=[],
    )

    body = _render_review(client, mock_db, query="tab=images&image_status=reviewed")

    assert "No Images Match Filter" in body
    assert "No image candidates have been generated for this filing yet" not in body, (
        "Must NOT claim no images exist when they do — the filter is the reason"
    )
    # Clear link routes the user to ?image_status=all, which also overwrites
    # the sticky localStorage value at unified_review.html:71-76.
    assert "image_status=all" in body
    # Filter bar must also be visible so the user can change the filter directly.
    assert 'id="imgStatusFilter"' in body


def test_images_tab_genuinely_empty_keeps_back_to_list(client):
    # Regression guard: a filing with zero images must still render the
    # original "No image candidates have been generated for this filing yet"
    # copy and Back to Filing List button — not the new filter-clear branch.
    mock_db = _mock_db_for_filtered_images(all_images=[], filtered_images=[])

    body = _render_review(client, mock_db, query="tab=images&image_status=reviewed")

    assert "No image candidates have been generated for this filing yet" in body
    assert "No Images Match Filter" not in body
    assert "Back to Filing List" in body
