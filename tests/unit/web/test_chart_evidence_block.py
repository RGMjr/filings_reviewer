"""
Template + route tests for the "Chart Evidence" block in unified_review.html.

The block must render a usable placeholder for chart-sourced facts whose
image is unresolvable, instead of silently omitting the block or showing a
broken-image icon. Status strings come from
`review_unified._resolve_chart_image_status`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app
from src.web.routes.review_unified import _resolve_chart_image_status


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


def _fake_filing() -> dict:
    return {
        "filing_id": 1846,
        "company_id": 1,
        "company_name": "BOX INC",
        "ticker": "BOX",
        "cik": "0001372612",
        "accession_number": "0001193125-14-152774",
        "sec_html_url": "https://www.sec.gov/Archives/edgar/data/1372612/000119312514152774/",
        "form_type": "S-1/A",
        "filing_date": None,
        "document_type": "sec_filing",
    }


def _fake_chart_fact(img_id: str | None) -> dict:
    return {
        "fact_id": "00000000-0000-0000-0000-000000000001",
        "doc_id": 1846,
        "canonical_metric_id": "cm_revenue_by_cohort",
        "value": 2.8,
        "value_raw": "$2.8 million",
        "unit": "usd_millions",
        "currency": "USD",
        "source_type": "chart",
        "source_locator": {"img_id": img_id, "bbox": None} if img_id else {},
        "evidence_pack": {},
        "confidence": 0.8,
        "review_status": "pending_review",
        "extraction_method": "llm",
        "requires_review": True,
        "decision_id": None,
    }


# ---------------------------------------------------------------------------
# _resolve_chart_image_status unit tests
# ---------------------------------------------------------------------------


class TestResolveChartImageStatus:
    def test_returns_none_for_non_chart_fact(self) -> None:
        fact = {"source_type": "text", "source_locator": {}}
        assert _resolve_chart_image_status(MagicMock(), fact) is None

    def test_missing_img_id_when_source_locator_empty(self) -> None:
        fact = {"source_type": "chart", "source_locator": {}}
        assert _resolve_chart_image_status(MagicMock(), fact) == {
            "status": "missing_img_id"
        }

    def test_missing_img_id_when_img_id_is_null(self) -> None:
        fact = {"source_type": "chart", "source_locator": {"img_id": None}}
        assert _resolve_chart_image_status(MagicMock(), fact) == {
            "status": "missing_img_id"
        }

    def test_asset_missing_when_db_returns_no_rows(self) -> None:
        fact = {"source_type": "chart", "source_locator": {"img_id": "abc"}}
        db = MagicMock()
        db.query.return_value = []
        assert _resolve_chart_image_status(db, fact) == {"status": "asset_missing"}

    def test_file_missing_when_path_outside_data_dir(self, app) -> None:
        fact = {"source_type": "chart", "source_locator": {"img_id": "abc"}}
        db = MagicMock()
        db.query.return_value = [{"file_path": "/var/folders/99/tmp_cache/chart.jpg"}]
        with app.app_context():
            result = _resolve_chart_image_status(db, fact)
        assert result == {"status": "file_missing"}

    def test_file_missing_when_path_empty(self, app) -> None:
        fact = {"source_type": "chart", "source_locator": {"img_id": "abc"}}
        db = MagicMock()
        db.query.return_value = [{"file_path": None}]
        with app.app_context():
            result = _resolve_chart_image_status(db, fact)
        assert result == {"status": "file_missing"}


# ---------------------------------------------------------------------------
# Template render tests — full Flask render to assert placeholder copy appears
# ---------------------------------------------------------------------------


def _render_with_chart_fact(client, fact: dict, image_status_query: dict | None) -> str:
    filing = _fake_filing()
    mock_db = MagicMock()
    mock_db.query.return_value = [filing]
    mock_db.get_v2_facts_for_filing.return_value = [fact]
    mock_db.count_v2_facts_for_filing.return_value = 1
    mock_db.get_image_review_candidates_for_filing_v2.return_value = []
    mock_db.get_next_filing_with_pending_work.return_value = None

    with (
        patch("src.web.routes.review_unified.get_db", return_value=mock_db),
        patch("src.web.routes._metrics.get_db", return_value=mock_db),
        patch(
            "src.web.routes.review_unified.get_active_metrics",
            return_value=[],
        ),
        patch(
            "src.web.routes.review_unified._resolve_chart_image_status",
            return_value=image_status_query,
        ),
    ):
        response = client.get(f"/v2/review/{filing['filing_id']}?tab=text")
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_data(as_text=True)


def test_missing_img_id_placeholder_rendered(client):
    fact = _fake_chart_fact(img_id=None)
    body = _render_with_chart_fact(
        client, fact, image_status_query={"status": "missing_img_id"}
    )
    assert "Chart Evidence" in body
    assert "Chart-sourced fact without a linked image" in body


def test_asset_missing_placeholder_rendered(client):
    fact = _fake_chart_fact(img_id="6a780d0c-e68c-4a09-8c03-6cd5196acdf7")
    body = _render_with_chart_fact(
        client, fact, image_status_query={"status": "asset_missing"}
    )
    assert "linked asset row was deleted" in body


def test_file_missing_placeholder_rendered(client):
    fact = _fake_chart_fact(img_id="6a780d0c-e68c-4a09-8c03-6cd5196acdf7")
    body = _render_with_chart_fact(
        client, fact, image_status_query={"status": "file_missing"}
    )
    assert "file missing on disk" in body
    assert "--force-reextract" in body


def test_ok_status_renders_img_tag(client):
    fact = _fake_chart_fact(img_id="6a780d0c-e68c-4a09-8c03-6cd5196acdf7")
    body = _render_with_chart_fact(client, fact, image_status_query={"status": "ok"})
    assert '<img src="/v2/review/image_crop/' in body
    # onerror fallback must be wired up
    assert "onerror=" in body
