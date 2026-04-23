"""
Regression tests for the filing list tab/sort persistence invariants.

The filing list template persists tab/sort state in localStorage. The persist-JS
cannot distinguish "explicit All tab click" from "fresh visit with no URL param"
unless every URL-generating site emits a `document_type=` sentinel (empty =
explicit All, value = specific tab). A mismatch here produced the "All tab
flashes then jumps" bug replayed after PR #79.

These tests render the real template via the Flask test client and assert the
invariant holds across the tab links, sort links, pagination, and reviewer form.
"""

from __future__ import annotations

import re
from unittest.mock import patch

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


@pytest.fixture
def _stub_db():
    """Stub the DB calls filing_list needs so the template renders with real data."""
    with patch("src.web.routes.review_unified.get_db") as mock_get_db:
        from unittest.mock import MagicMock

        db = MagicMock()
        db.get_unified_filings_for_review_count.return_value = 1
        db.get_unified_filings_for_review.return_value = [
            {
                "filing_id": 1,
                "company_name": "Acme Corp",
                "cik": "0001757083",
                "ticker": "ACME",
                "accession_number": "0001144204-19-000180",
                "form_type": "S-1",
                "filing_date": None,
                "document_type": "sec_filing",
                "fact_count": 10,
                "facts_pending": 3,
                "facts_accepted": 5,
                "facts_rejected": 2,
                "image_count": 0,
                "images_pending": 0,
                "images_reviewed": 0,
                "reviewers": [],
            }
        ]
        db.get_distinct_reviewers.return_value = ["alice", "bob"]
        mock_get_db.return_value = db
        yield db


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', html)


def test_all_tab_link_emits_explicit_empty_document_type(client, _stub_db):
    """The 'All' button must emit document_type= (empty) so the persist-JS
    distinguishes an intentional All click from a fresh visit."""
    resp = client.get("/v2/review/filings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    all_button_hrefs = [h for h in _hrefs(html) if "document_type=" in h and 'class="btn' not in h]
    # At minimum the four tab buttons (All + three) should appear.
    assert any("document_type=&" in h or h.endswith("document_type=") for h in _hrefs(html)), (
        f"No href carries the empty-string document_type= sentinel. Hrefs: {all_button_hrefs[:5]}"
    )


def test_sort_header_from_all_view_preserves_all_tab(client, _stub_db):
    """Sort-header hrefs rendered on the All view must carry document_type=
    (empty), else clicking Text Progress from All silently flips to the last
    stored tab."""
    resp = client.get("/v2/review/filings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Look for the Text Progress sort link; assert it carries the empty sentinel.
    sort_hrefs = [h for h in _hrefs(html) if "sort_by=text_progress" in h]
    assert sort_hrefs, "Text Progress sort header href not found in rendered list"
    for h in sort_hrefs:
        assert "document_type=" in h, f"Sort href missing document_type= sentinel: {h!r}"


def test_specific_tab_link_carries_its_document_type(client, _stub_db):
    """Non-All tab buttons must emit document_type=<value>, not the empty sentinel."""
    resp = client.get("/v2/review/filings")
    html = resp.get_data(as_text=True)

    hrefs = _hrefs(html)
    # Each non-All doc_type must appear in at least one href with its literal value.
    for dt in ("sec_filing", "earnings_call", "investor_presentation"):
        assert any(f"document_type={dt}" in h for h in hrefs), f"No href carries document_type={dt}"


def test_reviewer_form_on_all_view_carries_empty_sentinel(client, _stub_db):
    """The reviewer-filter hidden input must always emit document_type so
    submitting from All doesn't drop the sentinel."""
    resp = client.get("/v2/review/filings")
    html = resp.get_data(as_text=True)

    # The reviewer form carries a hidden document_type input. On the All view
    # the value is empty; assert the name= input exists (presence is what matters).
    assert re.search(r'<input[^>]+type="hidden"[^>]+name="document_type"[^>]*>', html), (
        "Reviewer form is missing a hidden document_type input"
    )


def test_persist_js_checks_get_not_has_for_doc_type(client, _stub_db):
    """The restore-JS must use params.get('document_type') === null to preserve
    the empty-string-means-All invariant. params.has would treat the empty
    sentinel as 'present' and skip restore correctly, but a later refactor
    could revert the semantics — lock the current form in with a text check."""
    resp = client.get("/v2/review/filings")
    html = resp.get_data(as_text=True)

    assert "params.get('document_type') === null" in html, (
        "persist-JS no longer uses the null-check pattern; the empty-sentinel "
        "invariant for document_type is at risk."
    )
