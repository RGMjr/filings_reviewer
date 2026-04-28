"""Smart-default landing for the Review button on the filings list.

The button URL is computed per-filing from `f.facts_pending` and
`f.images_pending` already in the filings-list query. Three branches:

- text pending → `?status=pending_review`
- only images pending → `?tab=images`
- nothing pending → `?status=all`

Setting the param explicitly (rather than letting the route default) is
required so the review-page localStorage restore does not silently swap in a
filter saved on a previous filing.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


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


def _filing_row(filing_id: int, facts_pending: int, images_pending: int) -> dict:
    return {
        "filing_id": filing_id,
        "company_id": 1,
        "company_name": "Acme Corp",
        "ticker": "ACME",
        "cik": "0001234567",
        "accession_number": f"0001234567-25-{filing_id:06d}",
        "form_type": "S-1",
        "filing_date": None,
        "document_type": "sec_filing",
        "fact_count": facts_pending + 5,
        "facts_pending": facts_pending,
        "facts_accepted": 0,
        "facts_auto_accepted": 0,
        "facts_rejected": 0,
        "image_count": images_pending + 5,
        "images_pending": images_pending,
        "images_reviewed": 0,
        "reviewers": [],
    }


def _review_url_for(body: str, filing_id: int) -> str:
    """Pull the Review-button href for `filing_id` out of the rendered list.

    The list rows aren't isomorphic to anchors — match on the row's
    accession number embedded in the same row, then locate the anchor whose
    target route is review_filing.
    """
    # The Review button anchors all use review_unified.review_filing. Match
    # the anchor whose query string carries filing_id={filing_id}.
    pattern = rf'<a\s+href="(/v2/review/{filing_id}\?[^"]*)"'
    match = re.search(pattern, body)
    if not match:
        # Fall back: maybe the path is /v2/review/<id>/ or no query string.
        pattern2 = rf'<a\s+href="(/v2/review/{filing_id}[^"]*)"'
        match = re.search(pattern2, body)
    assert match, f"No Review button anchor found for filing_id={filing_id}"
    return match.group(1)


def _list_response(client, filings: list[dict]):
    mock_db = MagicMock()
    mock_db.get_unified_filings_for_review.return_value = filings
    mock_db.get_unified_filings_for_review_count.return_value = len(filings)
    mock_db.get_distinct_reviewers.return_value = []
    with patch("src.web.routes.review_unified.get_db", return_value=mock_db):
        resp = client.get("/v2/review/filings")
    return resp


def test_review_button_text_pending_lands_on_pending_review(client):
    filings = [_filing_row(1, facts_pending=5, images_pending=0)]
    resp = _list_response(client, filings)
    assert resp.status_code == 200
    href = _review_url_for(resp.get_data(as_text=True), 1)
    assert "status=pending_review" in href
    assert "tab=" not in href


def test_review_button_only_images_pending_lands_on_images(client):
    filings = [_filing_row(2, facts_pending=0, images_pending=4)]
    resp = _list_response(client, filings)
    assert resp.status_code == 200
    href = _review_url_for(resp.get_data(as_text=True), 2)
    assert "tab=images" in href
    assert "status=" not in href


def test_review_button_nothing_pending_lands_on_all_statuses(client):
    filings = [_filing_row(3, facts_pending=0, images_pending=0)]
    resp = _list_response(client, filings)
    assert resp.status_code == 200
    href = _review_url_for(resp.get_data(as_text=True), 3)
    assert "status=all" in href
    assert "tab=" not in href
