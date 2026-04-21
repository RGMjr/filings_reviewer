"""
Smoke test: every Flask endpoint referenced in the review-UI templates is
registered and resolvable by `url_for`.

Catches the class of bug where a template calls `url_for('blueprint.missing')`
and the page 500s on first render in production (one of the historical
"lost the links" incidents). Runs purely in-process — no DB, no network.
"""

from __future__ import annotations

import pytest
from flask import url_for

from src.web.app import create_app  # noqa: I001

# Endpoint, kwargs — one call per distinct endpoint referenced in
# unified_review.html, unified_filing_list.html, and base.html.
_ENDPOINTS: list[tuple[str, dict]] = [
    ("review_unified.filing_list", {}),
    ("review_unified.review_filing", {"filing_id": 1}),
    ("review_unified.stats", {}),
    ("review_unified.image_crop", {"img_id": "00000000-0000-0000-0000-000000000000"}),
    ("review_unified.next_filing", {}),
    ("review_pres_images.index", {}),
    ("static", {"filename": "css/review.css"}),
    ("static", {"filename": "js/review_images_v2.js"}),
    # Ingest HTML routes
    ("ingest.ingest_form", {}),
    ("ingest.ingest_preview", {}),
    ("ingest.ingest_start", {}),
    ("ingest.populate", {}),
    ("ingest.ingest_batch", {"batch_id": "00000000-0000-0000-0000-000000000000"}),
    # Ingest API routes
    ("api_ingest.batch_status", {"batch_id": "00000000-0000-0000-0000-000000000000"}),
    ("api_ingest.batch_cancel", {"batch_id": "00000000-0000-0000-0000-000000000000"}),
]


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = "postgresql://test"
    app.config["_db_pool"] = None
    return app


@pytest.mark.parametrize("endpoint, kwargs", _ENDPOINTS)
def test_endpoint_resolves(app, endpoint: str, kwargs: dict) -> None:
    with app.test_request_context():
        url = url_for(endpoint, **kwargs)
    assert url, f"url_for({endpoint!r}) returned empty string"
    assert url.startswith("/"), f"url_for({endpoint!r}) did not return a path: {url!r}"
