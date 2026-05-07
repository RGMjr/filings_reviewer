"""Tests for the cross-filing decisions_review route."""

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


@pytest.fixture
def mock_db():
    with (
        patch("src.web.routes.review_unified.get_db") as mock_get_db,
        patch("src.web.routes._metrics.get_db") as mock_metrics_get_db,
    ):
        mock = MagicMock()
        mock_get_db.return_value = mock
        mock_metrics_get_db.return_value = mock
        yield mock


@pytest.fixture(autouse=True)
def mock_render():
    with patch("src.web.routes.review_unified.render_template") as mock:
        mock.return_value = "mocked template"
        yield mock


def _make_image(img_id="img-1", filing_id=1, company_name="Acme Corp"):
    return {
        "img_id": img_id,
        "filing_id": filing_id,
        "filename": "chart.png",
        "image_src": "chart.png",
        "image_url": "/images/cache/123/chart.png",
        "image_src_url": "https://www.sec.gov/chart.png",
        "image_width": 400,
        "image_height": 300,
        "preceding_text": "Revenue chart",
        "detected_keywords": [],
        "classification": "chart",
        "cohort_confidence": 0.8,
        "predicted_relevance": None,
        "review_status": "reviewed",
        "section_type": None,
        "is_decorative": False,
        "auto_reject_candidate": False,
        "detection_tier": "tier_1_cohort",
        "detected_metrics": [{"metric_id": "cm_revenue_by_cohort", "score": 0.9}],
        "created_at": None,
        "image_decision_id": None,
        "decision": None,
        "legacy_decision": False,
        "chart_type": None,
        "rejection_reason": None,
        "decision_notes": None,
        "review_time_seconds": None,
        "decided_against_hash": None,
        "current_ocr_text": None,
        "current_chart_data_json": None,
        "positive_count": 1,
        "detected_decided_count": 1,
        "total_confirmation_count": 1,
        "has_add": False,
        "accession_number": "0001234567-23-000001",
        "company_name": company_name,
        "cik": "123456",
        "ticker": "ACM",
        "classification_id": None,
        "predicted_metrics": None,
        "classification_confidence": None,
        "image_review_state": "relevant",
        "is_stale_vs_decision": False,
    }


def test_decisions_review_accepted_renders_200(client, mock_db, mock_render):
    """GET /v2/review/decisions/accepted renders 200."""
    img = _make_image()
    mock_db.get_images_with_decision_type.return_value = [img]
    mock_db.get_image_metric_confirmations.return_value = []

    response = client.get("/v2/review/decisions/accepted")
    assert response.status_code == 200

    mock_db.get_images_with_decision_type.assert_called_once_with("accepted")
    _, kwargs = mock_render.call_args
    assert kwargs["cross_filing_decisions_mode"] == "accepted"
    assert kwargs["image_candidates"] == [img]
    assert kwargs["current_image"] == img


def test_decisions_review_corrected_renders_200(client, mock_db, mock_render):
    """GET /v2/review/decisions/corrected renders 200."""
    mock_db.get_images_with_decision_type.return_value = []
    mock_db.get_image_metric_confirmations.return_value = []

    response = client.get("/v2/review/decisions/corrected")
    assert response.status_code == 200

    mock_db.get_images_with_decision_type.assert_called_once_with("corrected")


def test_decisions_review_added_renders_200(client, mock_db, mock_render):
    """GET /v2/review/decisions/added renders 200."""
    mock_db.get_images_with_decision_type.return_value = []
    mock_db.get_image_metric_confirmations.return_value = []

    response = client.get("/v2/review/decisions/added")
    assert response.status_code == 200


def test_decisions_review_unknown_type_returns_404(client, mock_db):
    """Unknown decision_type returns 404."""
    response = client.get("/v2/review/decisions/rejected")
    assert response.status_code == 404


def test_decisions_review_skipped_returns_404(client, mock_db):
    """'skipped' is not a valid decision_type — returns 404."""
    response = client.get("/v2/review/decisions/skipped")
    assert response.status_code == 404


def test_decisions_review_img_id_focuses_requested_image(client, mock_db, mock_render):
    """?img_id=<X> focuses the requested image when present in the set."""
    img1 = _make_image("img-1", filing_id=1)
    img2 = _make_image("img-2", filing_id=2, company_name="Beta Corp")
    mock_db.get_images_with_decision_type.return_value = [img1, img2]
    mock_db.get_image_metric_confirmations.return_value = []

    response = client.get("/v2/review/decisions/accepted?img_id=img-2")
    assert response.status_code == 200

    _, kwargs = mock_render.call_args
    assert kwargs["current_image"]["img_id"] == "img-2"


def test_decisions_review_img_id_defaults_to_first(client, mock_db, mock_render):
    """Without ?img_id, the first image in the set is focused."""
    img1 = _make_image("img-1", filing_id=1)
    img2 = _make_image("img-2", filing_id=2)
    mock_db.get_images_with_decision_type.return_value = [img1, img2]
    mock_db.get_image_metric_confirmations.return_value = []

    client.get("/v2/review/decisions/accepted")
    _, kwargs = mock_render.call_args
    assert kwargs["current_image"]["img_id"] == "img-1"


def test_decisions_review_empty_set_no_current_image(client, mock_db, mock_render):
    """Empty image set renders without current_image (e.g. corrected=0)."""
    mock_db.get_images_with_decision_type.return_value = []
    mock_db.get_image_metric_confirmations.return_value = []

    response = client.get("/v2/review/decisions/corrected")
    assert response.status_code == 200

    _, kwargs = mock_render.call_args
    assert kwargs["current_image"] is None
    assert kwargs["cross_filing_decisions_mode"] == "corrected"


def test_decisions_review_passes_text_tab_stubs(client, mock_db, mock_render):
    """Route passes all text-tab stubs to prevent Jinja StrictUndefined errors."""
    mock_db.get_images_with_decision_type.return_value = []
    mock_db.get_image_metric_confirmations.return_value = []

    client.get("/v2/review/decisions/added")
    _, kwargs = mock_render.call_args

    assert kwargs["facts"] == []
    assert kwargs["current_fact"] is None
    assert kwargs["total_facts"] == 0
    assert kwargs["pending_count"] == 0
    assert kwargs["image_ocr_segments"] == []


def test_decisions_review_label_includes_count(client, mock_db, mock_render):
    """cross_filing_decisions_label includes the image count."""
    img = _make_image()
    mock_db.get_images_with_decision_type.return_value = [img]
    mock_db.get_image_metric_confirmations.return_value = []

    client.get("/v2/review/decisions/accepted")
    _, kwargs = mock_render.call_args
    assert "(1)" in kwargs["cross_filing_decisions_label"]
    assert "accepted" in kwargs["cross_filing_decisions_label"].lower()
