"""
Minimal Flask server for Playwright UI tests of the unified review interface.
Renders unified_review.html with mock data and stub API endpoints.
Port 5200.
"""

import os

from flask import Blueprint, Flask, jsonify, render_template, request, send_from_directory

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
    return {"app_name": "Filings Review", "app_version": "0.1.0"}


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
    "source_locator": {"segment_id": "42"},
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
    "source_locator": {"segment_id": "43"},
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
    "source_locator": {},
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
}

MOCK_IMAGE_CANDIDATE_REVIEWED = {
    "image_candidate_id": 11,
    "img_id": "img-reviewed-11",
    "filing_id": 1,
    "image_url": "https://via.placeholder.com/400x300?text=Chart2",
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
        page=1,
        per_page=100,
        total_pages=1,
        sec_filing_url=None,
        # Image tab
        image_candidates=image_candidates,
        all_image_candidates=all_image_candidates,
        current_image=current_image,
        image_pending=1,
        image_reviewed=1,
        image_skipped=0,
        image_filters={"status": "all"},
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


app.register_blueprint(ingest_bp, url_prefix="/ingest")


if __name__ == "__main__":
    app.run(port=5200, debug=False)
