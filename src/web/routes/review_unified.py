"""
Flask routes for the unified V2 review interface.

Combines V2 text fact review and image review into a single tabbed interface.
Takes over the /v2/review URL prefix from review_v2.py.
"""

import logging
import threading
import time
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import SECClient
from src.review.models import (
    IMAGE_CHART_TYPE_LABELS,
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASON_LABELS,
    IMAGE_REJECTION_REASONS,
    IMAGE_REVIEW_STATUSES,
)
from src.web.app import get_db
from src.web.routes._metrics import get_active_metrics

review_unified_bp = Blueprint("review_unified", __name__, url_prefix="/v2/review")
logger = logging.getLogger(__name__)

# Valid review statuses for V2 facts
V2_REVIEW_STATUSES = ("pending_review", "accepted", "rejected", "corrected", "auto_accepted")

# Valid sort options
V2_SORT_OPTIONS = ("confidence_desc", "confidence_asc", "metric", "period")

# Valid document types for the filing list filter
VALID_DOCUMENT_TYPES = ("sec_filing", "earnings_call", "investor_presentation")


# =============================================================================
# Audit Logging Hooks
# =============================================================================


@review_unified_bp.before_request
def _log_request_start():
    """Capture request start time for response time calculation."""
    g.request_start_time = time.time()


@review_unified_bp.after_request
def _log_request_complete(response):
    """Log request details to audit table asynchronously (fire-and-forget)."""
    try:
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        # Capture all request context into a plain dict BEFORE spawning thread.
        # Flask's request/session proxies are not usable across threads.
        audit_kwargs = {
            "session_id": session.get("_id"),
            "ip_address": request.remote_addr,
            "user_agent": request.headers.get("User-Agent"),
            "route_name": request.endpoint or "unknown",
            "http_method": request.method,
            "url_path": request.path,
            "filing_id": request.view_args.get("filing_id") if request.view_args else None,
            "candidate_id": None,
            "query_params": dict(request.args) if request.args else None,
            "response_status": response.status_code,
            "response_time_ms": response_time_ms,
        }
        # get_db() returns a per-request adapter tied to Flask g — not safe across threads.
        # Capture DATABASE_URL and pool ref so the thread creates its own adapter.
        database_url = current_app.config["DATABASE_URL"]
        pool = current_app.config.get("_db_pool")

        def _write():
            try:
                db = DatabaseAdapter(database_url, pool=pool)
                db.insert_audit_log(**audit_kwargs)
            except Exception as exc:
                logger.error(f"Async audit log write failed: {exc}")

        t = threading.Thread(target=_write, daemon=True)
        t.start()
    except Exception as e:
        logger.error(f"Failed to prepare audit log: {e}")

    return response


# =============================================================================
# Page Routes
# =============================================================================


@review_unified_bp.route("/")
def index():
    """Redirect /v2/review/ to filing list."""
    return redirect(url_for("review_unified.filing_list"))


@review_unified_bp.route("/filings")
def filing_list():
    """Display unified filing list."""
    db = get_db()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(200, max(1, request.args.get("per_page", 50, type=int)))

    raw_type = request.args.get("document_type")
    document_type = raw_type if raw_type in VALID_DOCUMENT_TYPES else None
    hide_completed = request.args.get("hide_completed", "0") == "1"

    try:
        total = db.get_unified_filings_for_review_count(
            document_type=document_type,
            hide_completed=hide_completed,
        )
        filings = db.get_unified_filings_for_review(
            document_type=document_type,
            limit=per_page,
            offset=(page - 1) * per_page,
            hide_completed=hide_completed,
        )
    except Exception as e:
        logger.error(f"Database error in unified filing list: {e}")
        flash("Error loading filings.", "danger")
        filings = []
        total = 0

    total_pages = max(1, -(-total // per_page))  # ceiling division

    if not filings and page == 1:
        flash("No filings found.", "info")

    return render_template(
        "unified_filing_list.html",
        filings=filings,
        current_document_type=document_type or "all",
        hide_completed=hide_completed,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@review_unified_bp.route("/stats")
def stats():
    """Display aggregate review statistics for both text and image review."""
    db = get_db()
    try:
        text_data = db.get_v2_review_stats()
        image_overall = db.get_image_overall_decision_statistics()
        image_tier = db.get_image_decision_statistics()
        image_progress = db.get_image_review_progress()
        image_chart_types = db.get_image_chart_type_distribution()
        image_rejections = db.get_image_rejection_reason_stats()
    except Exception as e:
        logger.error(f"Error loading unified stats: {e}")
        flash("Error loading statistics.", "danger")
        return redirect(url_for("review_unified.filing_list"))

    return render_template(
        "unified_stats.html",
        per_company=text_data["per_company"],
        totals=text_data["totals"],
        confidence_bands=text_data["confidence_bands"],
        image_overall=image_overall,
        image_tier=image_tier,
        image_progress=image_progress,
        image_chart_types=image_chart_types,
        image_rejections=image_rejections,
        chart_type_labels=IMAGE_CHART_TYPE_LABELS,
        rejection_reason_labels=IMAGE_REJECTION_REASON_LABELS,
    )


@review_unified_bp.route("/<int:filing_id>")
def review_filing(filing_id: int):
    """Combined text + image review interface for a filing."""
    db = get_db()

    try:
        # Get filing metadata (include document_type from v2_documents)
        filing_sql = """
            SELECT f.*, c.company_name, c.cik, c.ticker,
                   d.document_type
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            LEFT JOIN v2_documents d ON d.filing_id = f.filing_id
            WHERE f.filing_id = %(filing_id)s
            LIMIT 1
        """
        filing_result = db.query(filing_sql, {"filing_id": filing_id})
        if not filing_result:
            abort(404)
        filing = dict(filing_result[0])
        document_type = filing.get("document_type") or "sec_filing"

        # Validate active tab
        active_tab = request.args.get("tab", "text")
        if active_tab not in ("text", "images"):
            active_tab = "text"

        # ---------------------------------------------------------------
        # Text tab data (always loaded — needed for progress counts)
        # ---------------------------------------------------------------

        # Parse filter parameters
        filter_status = request.args.get("status", "all")
        filter_metric = request.args.get("metric", "all")
        sort_by = request.args.get("sort", "confidence_desc")

        # Convert to DB params
        db_status = filter_status if filter_status in V2_REVIEW_STATUSES else None
        db_metric = filter_metric if filter_metric != "all" else None
        db_sort = sort_by if sort_by in V2_SORT_OPTIONS else "confidence_desc"

        # Get all facts (unfiltered) for progress counts and metrics dropdown
        all_facts = db.get_v2_facts_for_filing(filing_id)
        total_facts_unfiltered = len(all_facts)

        # Pagination for filtered facts
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(500, max(1, request.args.get("per_page", 100, type=int)))

        total_filtered = db.count_v2_facts_for_filing(
            filing_id, status=db_status, metric_id=db_metric
        )
        facts = db.get_v2_facts_for_filing(
            filing_id,
            status=db_status,
            metric_id=db_metric,
            sort_by=db_sort,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total_pages = max(1, -(-total_filtered // per_page))  # ceiling division

        # Get unique metrics for filter dropdown (filing-scoped)
        available_metrics = sorted(
            set(f["canonical_metric_id"] for f in all_facts if f.get("canonical_metric_id"))
        )

        # Get all active metrics for correction/missed-metric dropdowns
        all_metrics = get_active_metrics()

        # Select current fact
        fact_id_param = request.args.get("fact_id")
        current_fact = _select_current_fact(facts, fact_id_param)

        # Enrich sparse evidence with live segment/table context
        if current_fact:
            current_fact = _enrich_sparse_evidence(db, filing_id, current_fact)

        # Calculate progress
        pending_count = sum(1 for f in all_facts if f["review_status"] == "pending_review")
        accepted_count = sum(
            1 for f in all_facts if f["review_status"] in ("accepted", "auto_accepted")
        )
        rejected_count = sum(
            1 for f in all_facts if f["review_status"] in ("rejected", "corrected")
        )

        # Extract existing decision from current fact
        existing_decision = None
        if current_fact and current_fact.get("decision_id"):
            existing_decision = {
                "decision_id": current_fact["decision_id"],
                "decision": current_fact["decision"],
                "assigned_metric_id": current_fact.get("decision_metric_id"),
                "corrected_value": current_fact.get("corrected_value"),
                "rejection_reason": current_fact.get("rejection_reason"),
                "rejection_category": current_fact.get("rejection_category"),
                "reviewer_notes": current_fact.get("reviewer_notes"),
                "reviewer_id": current_fact.get("reviewer_id"),
            }

        # Resolve source document URL for the "View source" link.
        sec_filing_url = None
        if document_type == "sec_filing" and filing.get("cik"):
            # SEC filings: use the latest S-1/S-1/A for the company so the
            # link always points to the most current registration statement.
            try:
                sec_client = SECClient()
                latest = sec_client.get_latest_registration_filing(filing["cik"])
                if latest:
                    sec_filing_url = latest.primary_doc_url
            except Exception:
                pass  # Non-fatal — link just won't appear
        elif document_type == "investor_presentation":
            # Presentations: use sec_html_url (8-K filing page) if available,
            # otherwise fall back to the EDGAR filing directory.
            sec_filing_url = filing.get("sec_html_url")
            if not sec_filing_url and filing.get("cik") and filing.get("accession_number"):
                sec_filing_url = _build_sec_directory_url(
                    filing["cik"], filing["accession_number"]
                )

        # Current filter state
        current_filters = {
            "status": filter_status,
            "metric": filter_metric,
            "sort": sort_by,
            "has_active_filters": filter_status != "all"
            or filter_metric != "all"
            or sort_by != "confidence_desc",
        }

        # ---------------------------------------------------------------
        # Image tab data (always loaded — needed for progress counts)
        # ---------------------------------------------------------------

        all_image_candidates = db.get_image_review_candidates_for_filing(
            filing_id=filing_id, limit=1000
        )

        image_status = request.args.get("image_status", "all")
        db_image_status = image_status if image_status in IMAGE_REVIEW_STATUSES else None

        image_candidates = db.get_image_review_candidates_for_filing(
            filing_id=filing_id,
            status=db_image_status,
            sort_by="relevance",
            limit=1000,
        )

        current_image = _select_current_image(
            image_candidates, request.args.get("image_candidate_id", type=int)
        )

        # Image progress counts
        image_pending = sum(1 for c in all_image_candidates if c["review_status"] == "pending")
        image_reviewed = sum(1 for c in all_image_candidates if c["review_status"] == "reviewed")
        image_skipped = sum(1 for c in all_image_candidates if c["review_status"] == "skipped")
        image_auto_rejected = sum(1 for c in all_image_candidates if c["review_status"] == "auto_rejected")

        # SEC directory URL for image linking
        sec_url = _build_sec_directory_url(
            filing.get("cik", ""), filing.get("accession_number", "")
        )

        chart_types = [(ct, IMAGE_CHART_TYPE_LABELS[ct]) for ct in IMAGE_CHART_TYPES]
        rejection_reasons = [
            (rr, IMAGE_REJECTION_REASON_LABELS[rr]) for rr in IMAGE_REJECTION_REASONS
        ]

        return render_template(
            "unified_review.html",
            filing=filing,
            document_type=document_type,
            active_tab=active_tab,
            # Text tab
            facts=facts,
            current_fact=current_fact,
            existing_decision=existing_decision,
            available_metrics=available_metrics,
            all_metrics=all_metrics,
            current_filters=current_filters,
            total_facts=total_filtered,
            total_facts_unfiltered=total_facts_unfiltered,
            pending_count=pending_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            review_statuses=V2_REVIEW_STATUSES,
            sort_options=V2_SORT_OPTIONS,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            sec_filing_url=sec_filing_url,
            # Image tab
            image_candidates=image_candidates,
            all_image_candidates=all_image_candidates,
            current_image=current_image,
            image_pending=image_pending,
            image_reviewed=image_reviewed,
            image_skipped=image_skipped,
            image_auto_rejected=image_auto_rejected,
            image_filters={"status": image_status},
            chart_types=chart_types,
            rejection_reasons=rejection_reasons,
            image_decisions=IMAGE_DECISIONS,
            review_statuses_images=IMAGE_REVIEW_STATUSES,
            sec_url=sec_url,
        )

    except Exception as e:
        logger.error(f"Error in unified review for filing_id={filing_id}: {e}")
        flash("Error loading review.", "danger")
        return redirect(url_for("review_unified.filing_list"))


# =============================================================================
# Helpers
# =============================================================================


def _enrich_sparse_evidence(db: Any, filing_id: int, fact: dict) -> dict:
    """
    When evidence_pack lacks context (table facts, or text facts with failed
    span detection), fetch the full segment or table from the DB and attach
    it to the fact dict for the template to render.
    """
    ep = fact.get("evidence_pack") or {}
    if not isinstance(ep, dict):
        ep = {}

    # Sparse = no surrounding text context stored
    is_sparse = not ep.get("context_before") and not ep.get("context_after")
    if not is_sparse:
        return fact

    loc = fact.get("source_locator") or {}
    if not isinstance(loc, dict):
        return fact

    # Make fact a mutable copy so we don't mutate shared list entries
    fact = dict(fact)

    table_id = loc.get("table_id")
    segment_id = loc.get("segment_id")

    if table_id:
        try:
            fact["_table_context"] = db.get_table_context(filing_id, str(table_id))
        except Exception:
            pass
    elif segment_id:
        try:
            fact["_segment_context"] = db.get_segment_context(filing_id, str(segment_id))
        except Exception:
            pass

    return fact


def _select_current_fact(facts: list[dict], requested_id: str | None) -> dict | None:
    """Select the current fact to display."""
    if not facts:
        return None

    if requested_id:
        current = next((f for f in facts if str(f["fact_id"]) == requested_id), None)
        if current:
            return current
        flash("Fact not found, showing first pending.", "warning")

    # First pending_review fact, or first fact
    return next(
        (f for f in facts if f["review_status"] == "pending_review"),
        facts[0],
    )


def _build_sec_directory_url(cik: str, accession_number: str) -> str:
    """Build URL to SEC EDGAR filing directory for image linking."""
    acc_no_dashes = accession_number.replace("-", "")
    cik_stripped = cik.lstrip("0") or "0"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_no_dashes}/"


def _select_current_image(candidates: list[dict], requested_id: int | None) -> dict | None:
    """Select current image candidate. Same logic as _select_current_candidate in review_images.py."""
    if not candidates:
        return None
    if requested_id:
        current = next((c for c in candidates if c["image_candidate_id"] == requested_id), None)
        if current:
            return current
        flash("Candidate not found, showing first pending", "warning")
    return next(
        (c for c in candidates if c["review_status"] == "pending"),
        candidates[0] if candidates else None,
    )
