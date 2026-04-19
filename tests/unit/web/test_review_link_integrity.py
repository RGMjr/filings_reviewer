"""
Regression test: links in the review UI stay well-formed across filing shapes.

Two layers:

1. Unit-level invariants for `src.web.url_builders` — every filing shape the
   ingest paths produce (sec_filing, investor_presentation pre-backfill,
   investor_presentation post-backfill, malformed) yields a URL that passes
   the SEC EDGAR path pattern, or None.

2. Full Flask `test_client` render of `/v2/review/<id>` for each
   document_type, with DB mocked just enough to get the template to render.
   Asserts the rendered HTML contains a well-formed SEC link and image URLs
   that match the three-segment `/images/cache/<cik>/<acc>/<filename>` route.

Closes the gap where `tests/unit/web/test_review_v2_routes.py` mocks
`render_template`, so template-level link regressions slipped through.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app
from src.web.url_builders import (
    build_image_cache_url,
    resolve_sec_filing_url,
)

# A valid SEC EDGAR URL that anchors the review UI's source link. Directory
# URLs end in `/`; file URLs end in a real filename (.htm/.html/.pdf).
_SEC_URL_RE = re.compile(
    r"^https://www\.sec\.gov/Archives/edgar/data/\d+/\d+/"
    r"([A-Za-z0-9._-]+\.(?:htm|html|pdf))?$"
)

# Image-cache proxy route shape enforced at src/web/routes/image_cache.py:24.
_IMAGE_CACHE_URL_RE = re.compile(r"^/images/cache/\d+/\d+/[A-Za-z0-9._-]+$")


# ---------------------------------------------------------------------------
# Layer 1: URL-builder invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filing, expect_prefix",
    [
        (
            {
                "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1757083/000114420419000180/",
                "cik": "0001757083",
                "accession_number": "0001144204-19-000180",
            },
            "https://www.sec.gov/Archives/edgar/data/1757083/000114420419000180/",
        ),
        (
            # Investor presentation pre-backfill — sec_html_url NULL, cik NULL,
            # accession_number carries the encoded form. Must still resolve.
            {
                "sec_html_url": None,
                "cik": None,
                "accession_number": "presentation:0001108524/0001108524-25-000168/investorday2025.htm",
            },
            "https://www.sec.gov/Archives/edgar/data/1108524/000110852425000168/investorday2025.htm",
        ),
        (
            # Investor presentation post-backfill — sec_html_url populated.
            {
                "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1108524/000110852425000168/investorday2025.htm",
                "cik": "0001108524",
                "accession_number": "presentation:0001108524/0001108524-25-000168/investorday2025.htm",
            },
            "https://www.sec.gov/Archives/edgar/data/1108524/000110852425000168/investorday2025.htm",
        ),
    ],
)
def test_resolve_sec_filing_url_produces_well_formed_url(filing, expect_prefix):
    url = resolve_sec_filing_url(filing)
    assert url is not None
    assert url.startswith(expect_prefix) or url == expect_prefix, (
        f"Expected URL to start with {expect_prefix!r}, got {url!r}"
    )
    assert _SEC_URL_RE.match(url), f"Malformed SEC URL: {url!r}"
    assert "presentation:" not in url


def test_resolve_sec_filing_url_returns_none_when_unresolvable():
    # No sec_html_url, no cik, no valid presentation accession → None (anchor hidden).
    assert resolve_sec_filing_url({"sec_html_url": None, "cik": None}) is None
    assert (
        resolve_sec_filing_url(
            {"sec_html_url": "", "cik": "", "accession_number": "not-a-real-format"}
        )
        is None
    )


@pytest.mark.parametrize(
    "cik, accession, filename",
    [
        ("0001757083", "0001144204-19-000180", "s1.htm"),
        # Presentation form — the encoded accession must be parsed out so the URL
        # matches the three-segment route pattern.
        (
            "0001108524",
            "presentation:0001108524/0001108524-25-000168/investorday2025.htm",
            "investorday2025001.jpg",
        ),
    ],
)
def test_build_image_cache_url_matches_route_pattern(cik, accession, filename):
    url = build_image_cache_url(cik, accession, filename)
    assert _IMAGE_CACHE_URL_RE.match(url), f"Malformed image-cache URL: {url!r}"
    assert "presentation:" not in url


# ---------------------------------------------------------------------------
# Layer 2: rendered-HTML assertion
# ---------------------------------------------------------------------------


def _fake_filing(document_type: str) -> dict:
    if document_type == "investor_presentation":
        return {
            "filing_id": 1560,
            "company_id": 1,
            "company_name": "Acme Corp",
            "ticker": "ACME",
            "cik": "0001108524",
            "accession_number": "presentation:0001108524/0001108524-25-000168/investorday2025.htm",
            "sec_html_url": (
                "https://www.sec.gov/Archives/edgar/data/1108524/"
                "000110852425000168/investorday2025.htm"
            ),
            "form_type": "8-K",
            "filing_date": None,
            "document_type": "investor_presentation",
        }
    return {
        "filing_id": 1,
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


def _fake_image_candidate(filing: dict) -> dict:
    # Compute the image_url the same way the SQL does so we test the shape the
    # template will actually receive.
    from src.web.url_builders import build_image_cache_url

    filename = "chart001.jpg"
    url = build_image_cache_url(filing["cik"], filing["accession_number"], filename)
    return {
        "img_id": "00000000-0000-0000-0000-000000000001",
        "filing_id": filing["filing_id"],
        "filename": filename,
        "image_src": filename,
        "image_url": url,
        "image_src_url": url.replace("/images/cache/", "https://www.sec.gov/Archives/edgar/data/"),
        "image_width": 800,
        "image_height": 600,
        "preceding_text": "",
        "detected_keywords": [],
        "classification": "chart",
        "cohort_confidence": 0.8,
        "predicted_relevance": 0.9,
        "review_status": "pending",
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


@pytest.mark.parametrize("document_type", ["sec_filing", "investor_presentation"])
def test_review_page_renders_well_formed_links(client, document_type):
    filing = _fake_filing(document_type)
    image_candidate = _fake_image_candidate(filing)

    mock_db = MagicMock()
    mock_db.query.return_value = [filing]
    mock_db.get_v2_facts_for_filing.return_value = []
    mock_db.count_v2_facts_for_filing.return_value = 0
    mock_db.get_image_review_candidates_for_filing_v2.return_value = [image_candidate]
    mock_db.get_next_filing_with_pending_work.return_value = None

    with (
        patch("src.web.routes.review_unified.get_db", return_value=mock_db),
        patch("src.web.routes._metrics.get_db", return_value=mock_db),
        patch(
            "src.web.routes.review_unified.get_active_metrics",
            return_value=[],
        ),
    ):
        response = client.get(f"/v2/review/{filing['filing_id']}?tab=images")

    assert response.status_code == 200, (
        f"Expected 200 for {document_type}, got {response.status_code}\n"
        f"Body (first 500): {response.get_data(as_text=True)[:500]}"
    )
    body = response.get_data(as_text=True)

    # "View source" anchor must render and point at a well-formed SEC URL.
    sec_anchor = re.search(
        r'<a\s+href="(https://www\.sec\.gov/Archives/edgar/data/[^"]+)"', body
    )
    assert sec_anchor, (
        f"No SEC anchor rendered for document_type={document_type!r}. "
        f"sec_filing_url is being silently dropped; the template guard hid the link."
    )
    sec_url = sec_anchor.group(1)
    assert _SEC_URL_RE.match(sec_url), f"Malformed rendered SEC URL: {sec_url!r}"
    assert "presentation:" not in sec_url

    # Every /images/cache/ src must have exactly three path segments after the prefix.
    image_srcs = re.findall(r'src="(/images/cache/[^"]+)"', body)
    assert image_srcs, "No /images/cache/ <img> src rendered in image tab"
    for src in image_srcs:
        assert _IMAGE_CACHE_URL_RE.match(src), (
            f"Image src does not match route pattern: {src!r} "
            f"(document_type={document_type!r})"
        )
        assert "presentation:" not in src
