"""
Minimal Flask server for Playwright UI tests of the unified review interface.
Renders unified_review.html with mock data and stub API endpoints.
Port 5200.
"""

import os
import sys

from flask import Blueprint, Flask, jsonify, render_template, request, send_from_directory

# Import the canonical Reject-form category metadata from src so the mock
# template render mirrors production. The module is pure-Python with no DB or
# extraction-pipeline imports (see its docstring).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.web.text_decision_category_actions import CATEGORY_ACTIONS  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

app = Flask(
    __name__,
    template_folder=os.path.join(PROJECT_ROOT, "src", "web", "templates"),
    static_folder=os.path.join(PROJECT_ROOT, "src", "web", "static"),
)
app.config["TESTING"] = True

# Blueprint stubs matching real endpoint names used in templates
review_unified_bp = Blueprint("review_unified", __name__)
review_images_bp = Blueprint("review_images", __name__)


@app.context_processor
def inject_app_globals():
    """Mirror real app's context processor."""
    return {
        "app_name": "Filings Review",
        "app_version": "0.1.0",
        "metabase_url": "https://filings-metabase.onrender.com",
    }


# --- Blueprint stub routes ---


@review_unified_bp.route("/filings")
def filing_list():
    return "Filing List (stub)"


@review_unified_bp.route("/stats")
def stats():
    return "Stats (stub)"


@review_unified_bp.route("/<int:filing_id>")
def review_filing(filing_id):
    return "Review Filing (stub)"


@review_images_bp.route("/<int:filing_id>/next")
def next_candidate(filing_id):
    return "Next Candidate (stub)"


# --- Mock data ---

MOCK_FILING = {
    "filing_id": 1,
    "company_name": "Acme Corp",
    "form_type": "S-1",
    "accession_number": "0001234567-25-000001",
    "cik": "0001234567",
    "ticker": None,
}

MOCK_FILING_B = {
    "filing_id": 2,
    "company_name": "Acme Corp B",
    "form_type": "S-1",
    "accession_number": "0001234567-25-000002",
    "cik": "0001234567",
    "ticker": None,
}

MOCK_FACT_PENDING = {
    "fact_id": "fact-001",
    "canonical_metric_id": "cm_net_revenue_retention",
    "review_status": "pending_review",
    "confidence": 0.87,
    "value_raw": "115%",
    "value": 115.0,
    "unit": "percent",
    "period_start": "2024-01-01",
    "period_end": "2024-12-31",
    "period_type": "annual",
    "scope": "company",
    "scope_detail": None,
    "customer_type": None,
    "source_type": "text",
    "extraction_method": "keyword",
    "review_reason": "High confidence text match",
    "evidence_pack": {
        "context_before": "Our net",
        "highlighted_html": "<mark>net revenue retention</mark> was 115%",
        "context_after": "in fiscal year 2024.",
        "header_path": ["Financial Performance", "Key Metrics"],
        "stub_path": None,
        "snippet_html": None,
    },
    "source_locator": {"segment_id": "42", "img_id": None},
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
    "confirming_source_types": None,
    "_chart_image_status": None,
}

MOCK_FACT_ACCEPTED = {
    "fact_id": "fact-002",
    "canonical_metric_id": "cm_total_customers",
    "review_status": "accepted",
    "confidence": 0.72,
    "value_raw": "50,000",
    "value": 50000.0,
    "unit": "count",
    "period_start": None,
    "period_end": "2024-12-31",
    "period_type": "annual",
    "scope": "company",
    "scope_detail": None,
    "customer_type": None,
    "source_type": "text",
    "extraction_method": "keyword",
    "review_reason": None,
    "evidence_pack": {},
    "source_locator": {"segment_id": "43", "img_id": None},
    "_table_context": None,
    "_segment_context": None,
    "decision_id": "decision-001",
    "decision": "accept",
    "decision_metric_id": "cm_total_customers",
    "corrected_value": None,
    "rejection_reason": None,
    "rejection_category": None,
    "reviewer_notes": None,
    "reviewer_id": "test_reviewer",
    "confirming_source_types": None,
    "_chart_image_status": None,
}

MOCK_FACT_REJECTED = {
    "fact_id": "fact-003",
    "canonical_metric_id": "cm_churn_rate",
    "review_status": "rejected",
    "confidence": 0.45,
    "value_raw": "5.2%",
    "value": 5.2,
    "unit": "percent",
    "period_start": None,
    "period_end": None,
    "period_type": None,
    "scope": "company",
    "scope_detail": None,
    "customer_type": None,
    "source_type": "text",
    "extraction_method": "keyword",
    "review_reason": None,
    "evidence_pack": {},
    "source_locator": {"segment_id": None, "img_id": None},
    "_table_context": None,
    "_segment_context": None,
    "decision_id": "decision-002",
    "decision": "reject",
    "decision_metric_id": None,
    "corrected_value": None,
    "rejection_reason": "Not a metric value",
    "rejection_category": "not_a_metric",
    "reviewer_notes": None,
    "reviewer_id": "test_reviewer",
    "confirming_source_types": None,
    "_chart_image_status": None,
}

MOCK_FACTS = [MOCK_FACT_PENDING, MOCK_FACT_ACCEPTED, MOCK_FACT_REJECTED]

MOCK_AVAILABLE_METRICS = [
    "cm_net_revenue_retention",
    "cm_total_customers",
    "cm_arpu",
    "cm_churn_rate",
    "cm_gross_revenue_retention",
]

MOCK_ALL_METRICS = [
    {"metric_id": "cm_net_revenue_retention", "display_name": "Net Revenue Retention"},
    {"metric_id": "cm_gross_revenue_retention", "display_name": "Gross Revenue Retention"},
    {"metric_id": "cm_customer_retention_rate", "display_name": "Customer Retention Rate"},
    {"metric_id": "cm_total_customers", "display_name": "Total Customers"},
    {"metric_id": "cm_arpu", "display_name": "Average Revenue Per User"},
    {"metric_id": "cm_churn_rate", "display_name": "Churn Rate"},
    {"metric_id": "cm_customer_acquisition_cost", "display_name": "Customer Acquisition Cost"},
    {"metric_id": "cm_lifetime_value_per_customer", "display_name": "Lifetime Value per Customer"},
]

MOCK_CURRENT_FILTERS = {
    "status": "all",
    "metric": "all",
    "sort": "confidence_desc",
    "has_active_filters": False,
}

MOCK_IMAGE_CANDIDATE_PENDING = {
    "image_candidate_id": 10,
    "img_id": "img-pending-10",
    "filing_id": 1,
    "image_url": "https://via.placeholder.com/400x300?text=Chart1",
    "image_src_url": "https://via.placeholder.com/400x300?text=Chart1",
    "image_alt": "Net Revenue Retention Chart",
    "image_src": "chart1.png",
    "image_width": 400,
    "image_height": 300,
    "review_status": "pending",
    "decision": None,
    "image_decision_id": None,
    "detection_tier": "tier_1_cohort",
    "cohort_confidence": 0.85,
    "preceding_text": "The following chart shows net revenue retention over time.",
    "detected_keywords": ["retention", "cohort"],
    "is_decorative": False,
    "chart_type": None,
    "rejection_reason": None,
    "decision_notes": None,
    "image_index": 1,
    "detected_metrics": [],
    "classification_id": None,
    "predicted_metrics": None,
    "classification_confidence": None,
    "image_review_state": "pending",
    "is_stale_vs_decision": False,
    "auto_reject_candidate": False,
    "legacy_decision": False,
}

MOCK_IMAGE_CANDIDATE_WITH_CLASSIFICATION = {
    "image_candidate_id": 13,
    "img_id": "img-vision-13",
    "filing_id": 1,
    "image_url": "https://via.placeholder.com/400x300?text=Chart4",
    "image_src_url": "https://via.placeholder.com/400x300?text=Chart4",
    "image_alt": "Revenue by Cohort Chart (Vision)",
    "image_src": "chart4.png",
    "image_width": 600,
    "image_height": 400,
    "review_status": "pending",
    "decision": None,
    "image_decision_id": None,
    "detection_tier": "tier_1_cohort",
    "cohort_confidence": 0.92,
    "preceding_text": "Revenue by cohort as classified by vision model.",
    "detected_keywords": ["cohort", "revenue"],
    "is_decorative": False,
    "chart_type": None,
    "rejection_reason": None,
    "decision_notes": None,
    "image_index": 4,
    "detected_metrics": [],
    "classification_id": "cls-vision-001",
    "predicted_metrics": [
        {"metric_id": "cm_revenue_by_cohort", "score": 0.93},
        {"metric_id": "cm_gross_margin_by_cohort", "score": 0.78},
    ],
    "classification_confidence": 0.93,
    "image_review_state": "pending",
    "is_stale_vs_decision": False,
    "auto_reject_candidate": False,
    "legacy_decision": False,
}

MOCK_IMAGE_CANDIDATE_WITH_DETECTED = {
    **{
        "image_candidate_id": 12,
        "img_id": "img-detected-12",
        "filing_id": 1,
        "image_url": "https://via.placeholder.com/400x300?text=Chart3",
        "image_src_url": "https://via.placeholder.com/400x300?text=Chart3",
        "image_alt": "Cohort Retention Chart",
        "image_src": "chart3.png",
        "image_width": 600,
        "image_height": 400,
        "review_status": "pending",
        "decision": None,
        "image_decision_id": None,
        "detection_tier": "tier_1_cohort",
        "cohort_confidence": 0.90,
        "preceding_text": "Retention by cohort.",
        "detected_keywords": ["retention", "cohort"],
        "is_decorative": False,
        "chart_type": None,
        "rejection_reason": None,
        "decision_notes": None,
        "image_index": 3,
    },
    "detected_metrics": [
        {"metric_id": "cm_customer_retention_rate", "score": 0.95},
        {"metric_id": "cm_net_revenue_retention", "score": 0.82},
        {"metric_id": "cm_revenue_by_cohort", "score": 0.71},
        {"metric_id": "cm_churn_rate", "score": 0.55},
    ],
    "classification_id": None,
    "predicted_metrics": None,
    "classification_confidence": None,
    "image_review_state": "pending",
    "is_stale_vs_decision": False,
    "auto_reject_candidate": False,
    "legacy_decision": False,
}

MOCK_IMAGE_CANDIDATE_REVIEWED = {
    "image_candidate_id": 11,
    "img_id": "img-reviewed-11",
    "filing_id": 1,
    "image_url": "https://via.placeholder.com/400x300?text=Chart2",
    "image_src_url": "https://via.placeholder.com/400x300?text=Chart2",
    "image_alt": "Churn Rate Chart",
    "image_src": "chart2.png",
    "image_width": 400,
    "image_height": 300,
    "review_status": "reviewed",
    "decision": "relevant",
    "image_decision_id": 99,
    "detection_tier": "tier_2_large",
    "cohort_confidence": 0.65,
    "preceding_text": "Churn rate by cohort.",
    "detected_keywords": ["churn"],
    "is_decorative": False,
    "chart_type": "bar_chart",
    "rejection_reason": None,
    "decision_notes": "Clear cohort retention chart",
    "image_index": 2,
    "detected_metrics": [],
    "classification_id": None,
    "predicted_metrics": None,
    "classification_confidence": None,
    "image_review_state": "relevant",
    "is_stale_vs_decision": False,
    "auto_reject_candidate": False,
    "legacy_decision": False,
}

IMAGE_CHART_TYPES = [
    ("bar_chart", "Bar Chart"),
    ("line_chart", "Line Chart"),
    ("cohort_table", "Cohort Table"),
    ("other", "Other"),
]

IMAGE_REJECTION_REASONS = [
    ("no_metric", "Does Not Contain a Metric"),
    ("decorative", "Decorative or Logo"),
    ("duplicate", "Duplicate Image"),
    ("other", "Other"),
]

IMAGE_DECISIONS = ["relevant", "not_relevant"]
IMAGE_REVIEW_STATUSES = ["pending", "reviewed", "skipped"]

V2_REVIEW_STATUSES = ("pending_review", "accepted", "rejected", "corrected", "auto_accepted")
V2_SORT_OPTIONS = ("confidence_desc", "confidence_asc", "metric", "period")


_UNSET = object()  # Sentinel to distinguish "not provided" from None


def _shared_template_vars(
    active_tab="text",
    current_fact=_UNSET,
    existing_decision=None,
    image_candidates=_UNSET,
    all_image_candidates=_UNSET,
    current_image=_UNSET,
    current_image_confirmations=None,
    facts=_UNSET,
):
    """Build shared template context."""
    if image_candidates is _UNSET:
        image_candidates = [MOCK_IMAGE_CANDIDATE_PENDING, MOCK_IMAGE_CANDIDATE_REVIEWED]
    if all_image_candidates is _UNSET:
        all_image_candidates = [MOCK_IMAGE_CANDIDATE_PENDING, MOCK_IMAGE_CANDIDATE_REVIEWED]
    if facts is _UNSET:
        facts = MOCK_FACTS
    if current_image is _UNSET:
        current_image = MOCK_IMAGE_CANDIDATE_PENDING
    if current_fact is _UNSET:
        current_fact = MOCK_FACT_PENDING

    return dict(
        filing=MOCK_FILING,
        document_type="sec_filing",
        active_tab=active_tab,
        # Text tab
        facts=facts,
        current_fact=current_fact,
        existing_decision=existing_decision,
        available_metrics=MOCK_AVAILABLE_METRICS,
        all_metrics=MOCK_ALL_METRICS,
        current_filters=MOCK_CURRENT_FILTERS,
        total_facts=len(facts),
        total_facts_unfiltered=len(MOCK_FACTS),
        pending_count=1,
        accepted_count=1,
        rejected_count=1,
        review_statuses=V2_REVIEW_STATUSES,
        sort_options=V2_SORT_OPTIONS,
        rejection_categories=CATEGORY_ACTIONS,
        page=1,
        per_page=100,
        total_pages=1,
        sec_filing_url=None,
        image_ocr_segments=[],
        # Image tab
        image_candidates=image_candidates,
        all_image_candidates=all_image_candidates,
        current_image=current_image,
        current_image_confirmations=current_image_confirmations or [],
        image_pending=1,
        image_reviewed=1,
        image_skipped=0,
        image_auto_reject_candidates=0,
        image_filters={"status": "all", "sort": "relevance"},
        chart_types=IMAGE_CHART_TYPES,
        rejection_reasons=IMAGE_REJECTION_REASONS,
        image_decisions=IMAGE_DECISIONS,
        review_statuses_images=IMAGE_REVIEW_STATUSES,
        sec_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/",
        next_filing_url="#",
    )


# --- App-level test routes ---


@app.route("/")
def review_pending():
    """Text tab with a pending fact (default state)."""
    return render_template("unified_review.html", **_shared_template_vars())


@app.route("/reviewed-fact")
def review_accepted_fact():
    """Text tab: already-accepted fact with existing decision (shows undo)."""
    existing = {
        "decision_id": "decision-001",
        "decision": "accept",
        "reviewer_id": "test_reviewer",
        "rejection_reason": None,
    }
    return render_template(
        "unified_review.html",
        **_shared_template_vars(current_fact=MOCK_FACT_ACCEPTED, existing_decision=existing),
    )


@app.route("/rejected-fact")
def review_rejected_fact():
    """Text tab: rejected fact with existing decision."""
    existing = {
        "decision_id": "decision-002",
        "decision": "reject",
        "reviewer_id": "test_reviewer",
        "rejection_reason": "Not a metric value",
    }
    return render_template(
        "unified_review.html",
        **_shared_template_vars(current_fact=MOCK_FACT_REJECTED, existing_decision=existing),
    )


@app.route("/no-facts")
def review_no_facts():
    """Text tab with no facts (empty state)."""
    return render_template(
        "unified_review.html",
        **_shared_template_vars(
            facts=[],
            current_fact=None,  # Explicitly None — sentinel handles this correctly
            image_candidates=[],
            all_image_candidates=[],
            current_image=None,
        ),
    )


@app.route("/images-tab-empty")
def review_images_tab_empty():
    """Images tab with no image candidates (empty state)."""
    return render_template(
        "unified_review.html",
        **_shared_template_vars(
            active_tab="images",
            image_candidates=[],
            all_image_candidates=[],
            current_image=None,
        ),
    )


@app.route("/images-tab")
def review_images_tab():
    """Images tab with a pending image candidate."""
    return render_template("unified_review.html", **_shared_template_vars(active_tab="images"))


@app.route("/images-tab-reviewed")
def review_images_tab_reviewed():
    """Images tab with the reviewed image as current."""
    return render_template(
        "unified_review.html",
        **_shared_template_vars(active_tab="images", current_image=MOCK_IMAGE_CANDIDATE_REVIEWED),
    )


@app.route("/images-tab-detected")
def review_images_tab_detected():
    """Images tab with a current image carrying detected_metrics (PR 3b)."""
    return render_template(
        "unified_review.html",
        **_shared_template_vars(
            active_tab="images",
            current_image=MOCK_IMAGE_CANDIDATE_WITH_DETECTED,
            image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_DETECTED],
            all_image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_DETECTED],
        ),
    )


@app.route("/images-tab-detected-preseeded")
def review_images_tab_detected_preseeded():
    """Images tab with detected_metrics and pre-existing reviewer confirmations."""
    preseeded = [
        {
            "confirmation_id": "c-1",
            "img_id": MOCK_IMAGE_CANDIDATE_WITH_DETECTED["img_id"],
            "detected_metric_id": "cm_customer_retention_rate",
            "confirmed_metric_id": "cm_customer_retention_rate",
            "decision": "accept",
            "rejection_reason": None,
            "reviewer_id": "test_reviewer",
            "created_at": "2026-04-23T00:00:00+00:00",
            "updated_at": "2026-04-23T00:00:00+00:00",
        },
    ]
    return render_template(
        "unified_review.html",
        **_shared_template_vars(
            active_tab="images",
            current_image=MOCK_IMAGE_CANDIDATE_WITH_DETECTED,
            image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_DETECTED],
            all_image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_DETECTED],
            current_image_confirmations=preseeded,
        ),
    )


@app.route("/images-tab-vision")
def review_images_tab_vision():
    """Images tab with a current image carrying predicted_metrics (Vision classifier branch)."""
    return render_template(
        "unified_review.html",
        **_shared_template_vars(
            active_tab="images",
            current_image=MOCK_IMAGE_CANDIDATE_WITH_CLASSIFICATION,
            image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_CLASSIFICATION],
            all_image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_CLASSIFICATION],
        ),
    )


@app.route("/images-tab-detected-with-added")
def review_images_tab_detected_with_added():
    """Images tab with detected_metrics + a prior 'add' confirmation — verifies user-added metrics are visible on reopen."""
    preseeded = [
        {
            "confirmation_id": "c-add-1",
            "img_id": MOCK_IMAGE_CANDIDATE_WITH_DETECTED["img_id"],
            "detected_metric_id": None,
            "confirmed_metric_id": "cm_lifetime_value_per_customer",
            "decision": "add",
            "rejection_reason": None,
            "reviewer_id": "test_reviewer",
            "created_at": "2026-04-23T00:00:00+00:00",
            "updated_at": "2026-04-23T00:00:00+00:00",
        },
    ]
    return render_template(
        "unified_review.html",
        **_shared_template_vars(
            active_tab="images",
            current_image=MOCK_IMAGE_CANDIDATE_WITH_DETECTED,
            image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_DETECTED],
            all_image_candidates=[MOCK_IMAGE_CANDIDATE_WITH_DETECTED],
            current_image_confirmations=preseeded,
        ),
    )


# ---- Cross-filing auto-advance routes ----

MOCK_FACT_LAST_PENDING = {
    "fact_id": "fact-last-001",
    "canonical_metric_id": "cm_net_revenue_retention",
    "review_status": "pending_review",
    "confidence": 0.90,
    "value_raw": "120%",
    "value": 120.0,
    "unit": "percent",
    "period_start": "2024-01-01",
    "period_end": "2024-12-31",
    "period_type": "annual",
    "scope": "company",
    "scope_detail": None,
    "customer_type": None,
    "source_type": "text",
    "extraction_method": "keyword",
    "review_reason": "Last pending fact in filing A",
    "evidence_pack": {
        "context_before": "Filing A context",
        "highlighted_html": "<mark>net revenue retention</mark> was 120%",
        "context_after": "for fiscal year 2024.",
        "header_path": ["Key Metrics"],
        "stub_path": None,
        "snippet_html": None,
    },
    "source_locator": {"segment_id": "99", "img_id": None},
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
    "confirming_source_types": None,
    "_chart_image_status": None,
}

MOCK_FACT_B_PENDING = {
    "fact_id": "fact-b-001",
    "canonical_metric_id": "cm_total_customers",
    "review_status": "pending_review",
    "confidence": 0.80,
    "value_raw": "75,000",
    "value": 75000.0,
    "unit": "count",
    "period_start": None,
    "period_end": "2024-12-31",
    "period_type": "annual",
    "scope": "company",
    "scope_detail": None,
    "customer_type": None,
    "source_type": "text",
    "extraction_method": "keyword",
    "review_reason": None,
    "evidence_pack": {},
    "source_locator": {"segment_id": "100", "img_id": None},
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
    "confirming_source_types": None,
    "_chart_image_status": None,
}

MOCK_IMAGE_CANDIDATE_A_LAST = {
    "image_candidate_id": 20,
    "img_id": "img-a-last-20",
    "filing_id": 1,
    "image_url": "https://via.placeholder.com/400x300?text=FilingA",
    "image_src_url": "https://via.placeholder.com/400x300?text=FilingA",
    "image_alt": "Filing A Last Image",
    "image_src": "chart_a_last.png",
    "image_width": 400,
    "image_height": 300,
    "review_status": "pending",
    "decision": None,
    "image_decision_id": None,
    "detection_tier": "tier_1_cohort",
    "cohort_confidence": 0.88,
    "preceding_text": "Last pending chart in filing A.",
    "detected_keywords": ["retention"],
    "is_decorative": False,
    "chart_type": None,
    "rejection_reason": None,
    "decision_notes": None,
    "image_index": 1,
    "detected_metrics": [],
    "is_stale_vs_decision": False,
    "auto_reject_candidate": False,
    "legacy_decision": False,
}

MOCK_IMAGE_CANDIDATE_B_PENDING = {
    "image_candidate_id": 21,
    "img_id": "img-b-pending-21",
    "filing_id": 2,
    "image_url": "https://via.placeholder.com/400x300?text=FilingB",
    "image_src_url": "https://via.placeholder.com/400x300?text=FilingB",
    "image_alt": "Filing B Pending Image",
    "image_src": "chart_b_pending.png",
    "image_width": 400,
    "image_height": 300,
    "review_status": "pending",
    "decision": None,
    "image_decision_id": None,
    "detection_tier": "tier_1_cohort",
    "cohort_confidence": 0.75,
    "preceding_text": "Pending chart in filing B.",
    "detected_keywords": ["cohort"],
    "is_decorative": False,
    "chart_type": None,
    "rejection_reason": None,
    "decision_notes": None,
    "image_index": 1,
    "detected_metrics": [],
    "is_stale_vs_decision": False,
    "auto_reject_candidate": False,
    "legacy_decision": False,
}


def _cross_filing_template_vars_a_text():
    """Template vars for filing A with exactly one pending text fact, no pending images."""
    base = _shared_template_vars(
        active_tab="text",
        current_fact=MOCK_FACT_LAST_PENDING,
        facts=[MOCK_FACT_LAST_PENDING],
        image_candidates=[],
        all_image_candidates=[],
        current_image=None,
    )
    base["filing"] = MOCK_FILING
    base["pending_count"] = 1
    base["accepted_count"] = 0
    base["rejected_count"] = 0
    base["total_facts"] = 1
    base["total_facts_unfiltered"] = 1
    base["image_pending"] = 0
    base["image_reviewed"] = 0
    base["image_skipped"] = 0
    base["next_filing_url"] = "/filing-b-pending"
    return base


def _cross_filing_template_vars_b_text():
    """Template vars for filing B with one pending text fact."""
    base = _shared_template_vars(
        active_tab="text",
        current_fact=MOCK_FACT_B_PENDING,
        facts=[MOCK_FACT_B_PENDING],
        image_candidates=[],
        all_image_candidates=[],
        current_image=None,
    )
    base["filing"] = MOCK_FILING_B
    base["pending_count"] = 1
    base["accepted_count"] = 0
    base["rejected_count"] = 0
    base["total_facts"] = 1
    base["total_facts_unfiltered"] = 1
    base["image_pending"] = 0
    base["image_reviewed"] = 0
    base["image_skipped"] = 0
    base["next_filing_url"] = "#"
    return base


def _cross_filing_template_vars_a_images():
    """Template vars for filing A images tab: one pending image, no pending text facts."""
    base = _shared_template_vars(
        active_tab="images",
        current_fact=None,
        facts=[],
        image_candidates=[MOCK_IMAGE_CANDIDATE_A_LAST],
        all_image_candidates=[MOCK_IMAGE_CANDIDATE_A_LAST],
        current_image=MOCK_IMAGE_CANDIDATE_A_LAST,
    )
    base["filing"] = MOCK_FILING
    base["pending_count"] = 0
    base["accepted_count"] = 0
    base["rejected_count"] = 0
    base["total_facts"] = 0
    base["total_facts_unfiltered"] = 0
    base["image_pending"] = 1
    base["image_reviewed"] = 0
    base["image_skipped"] = 0
    base["next_filing_url"] = "/filing-b-images-pending"
    return base


def _cross_filing_template_vars_b_images():
    """Template vars for filing B images tab with one pending image."""
    base = _shared_template_vars(
        active_tab="images",
        current_fact=None,
        facts=[],
        image_candidates=[MOCK_IMAGE_CANDIDATE_B_PENDING],
        all_image_candidates=[MOCK_IMAGE_CANDIDATE_B_PENDING],
        current_image=MOCK_IMAGE_CANDIDATE_B_PENDING,
    )
    base["filing"] = MOCK_FILING_B
    base["pending_count"] = 0
    base["accepted_count"] = 0
    base["rejected_count"] = 0
    base["total_facts"] = 0
    base["total_facts_unfiltered"] = 0
    base["image_pending"] = 1
    base["image_reviewed"] = 0
    base["image_skipped"] = 0
    base["next_filing_url"] = "#"
    return base


@app.route("/filing-a-last-pending")
def filing_a_last_pending():
    """Filing A: single pending text fact, no pending images. Accepting this fact should
    trigger auto-advance to /filing-b-pending via NEXT_FILING_URL."""
    return render_template("unified_review.html", **_cross_filing_template_vars_a_text())


@app.route("/filing-b-pending")
def filing_b_pending():
    """Filing B: one pending text fact with distinct company name (Acme Corp B)."""
    return render_template("unified_review.html", **_cross_filing_template_vars_b_text())


@app.route("/filing-a-images-last-pending")
def filing_a_images_last_pending():
    """Filing A images tab: last pending image, no pending text facts. Deciding on this
    image should trigger navigateAfterQueueEmpty → advance to /filing-b-images-pending."""
    return render_template("unified_review.html", **_cross_filing_template_vars_a_images())


@app.route("/filing-b-images-pending")
def filing_b_images_pending():
    """Filing B images tab: one pending image with distinct company name (Acme Corp B)."""
    return render_template("unified_review.html", **_cross_filing_template_vars_b_images())


# --- Mock API endpoints ---


@app.route("/api/v2/decisions", methods=["POST"])
def mock_create_decision():
    data = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "success",
            "decision_id": "new-decision-001",
            "fact_id": data.get("fact_id", "fact-001"),
            "next_fact": {
                "fact_id": "fact-002",
                "url": "/?fact_id=fact-002",
            },
        }
    ), 201


@app.route("/api/v2/decisions/<decision_id>", methods=["DELETE"])
def mock_undo_decision(decision_id):
    return jsonify(
        {
            "status": "success",
            "message": "Decision reverted",
            "fact_id": "fact-001",
            "filing_id": 1,
        }
    ), 200


@app.route("/api/v2/image-decisions", methods=["POST"])
def mock_create_image_decision():
    return jsonify(
        {
            "status": "success",
            "decision_id": 100,
            "next_candidate": None,
            "message": "All candidates reviewed for this filing",
        }
    ), 201


@app.route("/api/v2/metrics/list", methods=["GET"])
def mock_metrics_list():
    return jsonify(
        [
            {
                "metric_id": "cm_customer_retention_rate",
                "display_name": "Customer Retention Rate",
                "tier": "tier_1",
            },
            {
                "metric_id": "cm_net_revenue_retention",
                "display_name": "Net Revenue Retention",
                "tier": "tier_1",
            },
            {
                "metric_id": "cm_revenue_by_cohort",
                "display_name": "Revenue by Cohort",
                "tier": "tier_1",
            },
            {"metric_id": "cm_churn_rate", "display_name": "Churn Rate", "tier": "tier_2"},
            {
                "metric_id": "cm_lifetime_value_per_customer",
                "display_name": "Lifetime Value per Customer",
                "tier": "tier_1",
            },
        ]
    ), 200


@app.route("/api/v2/image-metric-confirmations", methods=["POST"])
def mock_create_image_metric_confirmations():
    data = request.get_json(silent=True) or {}
    decisions = data.get("decisions", [])
    img_id = data.get("img_id")
    confirmations = []
    for i, d in enumerate(decisions):
        confirmations.append(
            {
                "confirmation_id": f"c-new-{i}",
                "img_id": img_id,
                "detected_metric_id": d.get("detected_metric_id"),
                "confirmed_metric_id": d.get("confirmed_metric_id"),
                "decision": d.get("decision"),
                "rejection_reason": d.get("rejection_reason"),
                "reviewer_id": data.get("reviewer_id", "anonymous"),
                "created_at": "2026-04-23T00:00:00+00:00",
                "updated_at": "2026-04-23T00:00:00+00:00",
            }
        )
    return jsonify(
        {"ok": True, "upserted": len(confirmations), "confirmations": confirmations}
    ), 200


@app.route("/api/v2/missed-metric", methods=["POST"])
def mock_add_missed_metric():
    return jsonify(
        {
            "status": "success",
            "fact_id": "new-fact-001",
            "filing_id": 1,
        }
    ), 201


# Serve Bootstrap from node_modules if available
BOOTSTRAP_DIR = os.path.join(PROJECT_ROOT, "node_modules", "bootstrap", "dist")


@app.route("/bootstrap/<path:filename>")
def serve_bootstrap(filename):
    return send_from_directory(BOOTSTRAP_DIR, filename)


# Register blueprints
app.register_blueprint(review_unified_bp, url_prefix="/v2/review")
app.register_blueprint(review_images_bp, url_prefix="/review/images")

# Ingest UI blueprint stub — base.html nav references `ingest.ingest_form` as of
# Wave B of the batch-ingest feature. Without this stub every template render
# fails with BuildError and Playwright tests hang on 30s per-page timeouts.
ingest_bp = Blueprint("ingest", __name__)


@ingest_bp.route("/")
def ingest_form():
    return "Ingest Form (stub)"


@ingest_bp.route("/preview", methods=["POST"])
def ingest_preview():
    return "Ingest Preview (stub)"


@ingest_bp.route("/start", methods=["POST"])
def ingest_start():
    return "Ingest Start (stub)"


@ingest_bp.route("/populate", methods=["POST"])
def populate():
    return "Ingest Populate (stub)"


@ingest_bp.route("/batch/<batch_id>")
def ingest_batch(batch_id):
    return "Ingest Batch (stub)"


@ingest_bp.route("/history")
def ingest_history():
    return "Ingest History (stub)"


app.register_blueprint(ingest_bp, url_prefix="/ingest")


if __name__ == "__main__":
    app.run(port=5200, debug=False)
