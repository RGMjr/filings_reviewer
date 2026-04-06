"""
Flask routes for V2 human review interface.

Parallel to V1 review.py — queries V2 tables (v2_metric_facts, v2_review_decisions).
V1 review is untouched.
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
from src.web.app import get_db

review_v2_bp = Blueprint("review_v2", __name__, url_prefix="/v2/review")
logger = logging.getLogger(__name__)

# Valid review statuses for V2 facts
V2_REVIEW_STATUSES = ("pending_review", "accepted", "rejected", "corrected", "auto_accepted")

# Valid sort options
V2_SORT_OPTIONS = ("confidence_desc", "confidence_asc", "metric", "period")


# =============================================================================
# Audit Logging Hooks
# =============================================================================


@review_v2_bp.before_request
def _log_request_start():
    """Capture request start time for response time calculation."""
    g.request_start_time = time.time()


@review_v2_bp.after_request
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


VALID_DOCUMENT_TYPES = ("sec_filing", "earnings_call", "investor_presentation")


@review_v2_bp.route("/")
def index():
    """Redirect /v2/review/ to filing list."""
    return redirect(url_for("review_v2.filing_list"))


@review_v2_bp.route("/filings")
def filing_list():
    """Display list of filings with V2 extraction results."""
    db = get_db()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(200, max(1, request.args.get("per_page", 50, type=int)))

    raw_type = request.args.get("document_type")
    document_type = raw_type if raw_type in VALID_DOCUMENT_TYPES else None

    try:
        total = db.count_v2_filings_with_facts()
        filings = db.get_v2_filings_with_facts(
            document_type=document_type,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
    except Exception as e:
        logger.error(f"Database error in V2 filing list: {e}")
        flash("Error loading V2 filings.", "danger")
        filings = []
        total = 0

    total_pages = max(1, -(-total // per_page))  # ceiling division

    if not filings and page == 1:
        flash("No V2 extractions found. Run scripts/run_v2_extraction.py first.", "info")

    return render_template(
        "v2_filing_list.html",
        filings=filings,
        current_document_type=document_type or "all",
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


@review_v2_bp.route("/stats")
def stats():
    """Display aggregate V2 review statistics."""
    db = get_db()
    try:
        data = db.get_v2_review_stats()
    except Exception as e:
        logger.error(f"Error loading V2 stats: {e}")
        flash("Error loading V2 statistics.", "danger")
        return redirect(url_for("review_v2.filing_list"))

    return render_template(
        "v2_stats.html",
        per_company=data["per_company"],
        totals=data["totals"],
        confidence_bands=data["confidence_bands"],
    )


@review_v2_bp.route("/<int:filing_id>")
def review_filing(filing_id: int):
    """V2 fact-by-fact review interface for a filing."""
    db = get_db()

    try:
        # Get filing metadata (include document_type from v2_documents)
        filing_sql = """
            SELECT f.*, c.company_name, c.cik,
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

        # Get unique metrics for filter dropdown
        available_metrics = sorted(
            set(f["canonical_metric_id"] for f in all_facts if f.get("canonical_metric_id"))
        )

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

        # Resolve primary document URL for source filing link
        sec_filing_url = None
        if document_type == "sec_filing" and filing.get("cik") and filing.get("accession_number"):
            try:
                sec_client = SECClient()
                sec_filing_url = sec_client.resolve_primary_document_url(
                    filing["cik"], filing["accession_number"]
                )
            except Exception:
                pass  # Non-fatal — link just won't appear

        # Current filter state
        current_filters = {
            "status": filter_status,
            "metric": filter_metric,
            "sort": sort_by,
            "has_active_filters": filter_status != "all"
            or filter_metric != "all"
            or sort_by != "confidence_desc",
        }

        template = (
            "v2_review_transcript.html" if document_type == "earnings_call" else "v2_review.html"
        )
        return render_template(
            template,
            filing=filing,
            facts=facts,
            current_fact=current_fact,
            existing_decision=existing_decision,
            available_metrics=available_metrics,
            current_filters=current_filters,
            total_facts=total_filtered,
            total_facts_unfiltered=total_facts_unfiltered,
            pending_count=pending_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            review_statuses=V2_REVIEW_STATUSES,
            sort_options=V2_SORT_OPTIONS,
            document_type=document_type,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            sec_filing_url=sec_filing_url,
        )

    except Exception as e:
        logger.error(f"Error in V2 review for filing_id={filing_id}: {e}")
        flash("Error loading V2 review.", "danger")
        return redirect(url_for("review_v2.filing_list"))


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
