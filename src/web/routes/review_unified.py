"""
Flask routes for the unified V2 review interface.

Combines V2 text fact review and image review into a single tabbed interface.
Takes over the /v2/review URL prefix from review_v2.py.
"""

import io
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from flask import (
    Blueprint,
    Response,
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
from src.web.url_builders import build_sec_directory_url, resolve_sec_filing_url

review_unified_bp = Blueprint("review_unified", __name__, url_prefix="/v2/review")
logger = logging.getLogger(__name__)

# Valid review statuses for V2 facts
V2_REVIEW_STATUSES = ("pending_review", "accepted", "rejected", "corrected", "auto_accepted")

# Valid sort options
V2_SORT_OPTIONS = ("confidence_desc", "confidence_asc", "metric", "period")

# Valid document types for the filing list filter
VALID_DOCUMENT_TYPES = ("sec_filing", "earnings_call", "investor_presentation")

# Valid sort columns for the filing list
VALID_FILING_SORT_COLUMNS = {"company", "date", "text_progress", "image_progress"}


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
            "query_params": dict(request.args) if request.args else None,
            "response_status": response.status_code,
            "response_time_ms": response_time_ms,
        }
        # get_db() returns a per-request adapter tied to Flask g — not safe across threads.
        # Capture DATABASE_URL and pool ref so the thread creates its own adapter.
        database_url = current_app.config["DATABASE_URL"]
        pool = current_app.config.get("_db_pool")
        testing = bool(current_app.config.get("TESTING"))

        def _write():
            try:
                db = DatabaseAdapter(database_url, pool=pool)
                db.insert_audit_log(**audit_kwargs)
            except Exception as exc:
                if testing:
                    logger.debug(f"Async audit log write failed: {exc}")
                else:
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

    raw_sort_by = request.args.get("sort_by", "date")
    sort_by = raw_sort_by if raw_sort_by in VALID_FILING_SORT_COLUMNS else "date"
    raw_sort_dir = request.args.get("sort_dir", "desc")
    sort_dir = "asc" if raw_sort_dir == "asc" else "desc"

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
            sort_by=sort_by,
            sort_dir=sort_dir,
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
        sort_by=sort_by,
        sort_dir=sort_dir,
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

        # Resolve active tab: if caller passed an explicit ?tab=, honor it
        # (unknown values fall back to "text"). Otherwise defer the decision
        # until after pending_count / image_pending are computed so we can
        # land on Images when there's no text work left to do.
        tab_param = request.args.get("tab")
        if tab_param in ("text", "images"):
            active_tab = tab_param
            tab_explicit = True
        else:
            active_tab = "text"
            tab_explicit = False

        # List-page sort context (threaded from Review button for cross-filing navigation)
        list_sort_by = request.args.get("list_sort_by", "date")
        if list_sort_by not in VALID_FILING_SORT_COLUMNS:
            list_sort_by = "date"
        list_sort_dir = request.args.get("list_sort_dir", "desc")
        if list_sort_dir not in ("asc", "desc"):
            list_sort_dir = "desc"
        raw_list_doc_type = request.args.get("list_document_type", "")
        list_document_type = (
            raw_list_doc_type if raw_list_doc_type in VALID_DOCUMENT_TYPES else None
        )
        list_hide_completed = request.args.get("list_hide_completed", "0") == "1"

        next_filing_params: dict[str, Any] = {
            "current_filing_id": filing_id,
            "list_sort_by": list_sort_by,
            "list_sort_dir": list_sort_dir,
            "list_hide_completed": 1 if list_hide_completed else 0,
        }
        if list_document_type:
            next_filing_params["list_document_type"] = list_document_type
        next_filing_url = (
            url_for("review_unified.next_filing") + "?" + urlencode(next_filing_params)
        )

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

        # Resolve source document URL for the "View source" link — always the
        # filing under review, not the company's latest registration. All URL
        # construction goes through src/web/url_builders.py.
        sec_filing_url = resolve_sec_filing_url(filing)

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

        all_image_candidates = db.get_image_review_candidates_for_filing_v2(
            filing_id=filing_id, limit=1000
        )

        image_status = request.args.get("image_status", "all")
        db_image_status = image_status if image_status in IMAGE_REVIEW_STATUSES else None

        image_candidates = db.get_image_review_candidates_for_filing_v2(
            filing_id=filing_id,
            status=db_image_status,
            sort_by="relevance",
            limit=1000,
        )

        # Stable partition: pending first (in existing probability-desc order),
        # then everything else. Matches the order the reviewer will be advanced
        # through via /api/v2/image-decisions -> next_candidate, so the thumbnail
        # strip lets them glance ahead.
        image_candidates = sorted(
            image_candidates,
            key=lambda c: 0 if c["review_status"] == "pending" else 1,
        )

        current_image = _select_current_image(
            image_candidates, request.args.get("img_id")
        )

        # Image progress counts
        image_pending = sum(1 for c in all_image_candidates if c["review_status"] == "pending")
        image_reviewed = sum(1 for c in all_image_candidates if c["review_status"] == "reviewed")
        image_skipped = sum(1 for c in all_image_candidates if c["review_status"] == "skipped")
        image_auto_rejected = sum(
            1 for c in all_image_candidates if c["review_status"] == "auto_rejected"
        )

        # Finalize tab default: if the caller did not pass an explicit ?tab=
        # and text is empty but images have pending work, open the images tab.
        if not tab_explicit and pending_count == 0 and image_pending > 0:
            active_tab = "images"

        # SEC directory URL for image linking — falls back to the resolved
        # source URL when the filing doesn't have a canonical cik/accession
        # pair (e.g. historic presentation rows pre-sql/36 backfill).
        cik_value = filing.get("cik") or ""
        acc_value = filing.get("accession_number") or ""
        if cik_value and acc_value and not acc_value.startswith("presentation:"):
            sec_url = build_sec_directory_url(cik_value, acc_value)
        else:
            sec_url = sec_filing_url or ""

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
            next_filing_url=next_filing_url,
        )

    except Exception as e:
        logger.error(f"Error in unified review for filing_id={filing_id}: {e}")
        flash("Error loading review.", "danger")
        return redirect(url_for("review_unified.filing_list"))


@review_unified_bp.route("/next-filing")
def next_filing():
    """Redirect to the next filing with pending text facts."""
    db = get_db()
    try:
        current_filing_id = request.args.get("current_filing_id", type=int)
        if not current_filing_id:
            flash("No current filing specified.", "warning")
            return redirect(url_for("review_unified.filing_list"))

        raw_sort = request.args.get("list_sort_by", "date")
        sort_by = raw_sort if raw_sort in VALID_FILING_SORT_COLUMNS else "date"
        raw_dir = request.args.get("list_sort_dir", "desc")
        sort_dir = "asc" if raw_dir == "asc" else "desc"
        raw_doc_type = request.args.get("list_document_type", "")
        document_type = raw_doc_type if raw_doc_type in VALID_DOCUMENT_TYPES else None
        hide_completed = request.args.get("list_hide_completed", "0") == "1"

        next_id = db.get_next_filing_with_pending_work(
            current_filing_id=current_filing_id,
            document_type=document_type,
            hide_completed=hide_completed,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

        if next_id:
            # Intentionally omit tab= so review_filing() can pick the tab based
            # on which side actually has pending work (text vs images).
            params = urlencode(
                {
                    "status": "pending_review",
                    "list_sort_by": sort_by,
                    "list_sort_dir": sort_dir,
                    "list_hide_completed": 1 if hide_completed else 0,
                    **({"list_document_type": document_type} if document_type else {}),
                }
            )
            return redirect(f"/v2/review/{next_id}?{params}")

        flash("No more filings with pending facts.", "info")
        list_params = urlencode(
            {
                "sort_by": sort_by,
                "sort_dir": sort_dir,
                **({"document_type": document_type} if document_type else {}),
            }
        )
        return redirect(url_for("review_unified.filing_list") + "?" + list_params)

    except Exception as e:
        logger.error(f"Error in next_filing: {e}")
        flash("Error finding next filing.", "danger")
        return redirect(url_for("review_unified.filing_list"))


@review_unified_bp.route("/image_crop/<img_id>")
def image_crop(img_id: str) -> Response:
    """
    Serve a chart image (full or cropped) stored on disk.

    Query params: x, y, w, h (integers, pixel coordinates). When w or h is
    missing/0, returns the full image instead of cropping — Vision GPT-4o
    does not populate per-DataPoint bbox, so most chart-sourced facts can
    only link back to the whole chart image.

    Security: file_path is validated against the project data/ directory
    before opening to prevent path traversal.
    """
    try:
        from PIL import Image  # type: ignore[import]
    except ImportError:
        abort(500)

    x = request.args.get("x", 0, type=int)
    y = request.args.get("y", 0, type=int)
    w = request.args.get("w", 0, type=int)
    h = request.args.get("h", 0, type=int)

    db = get_db()
    rows = db.query(
        "SELECT file_path FROM v2_image_assets WHERE img_id = %(img_id)s",
        {"img_id": img_id},
    )
    if not rows:
        abort(404)

    file_path = rows[0]["file_path"]
    if not file_path:
        abort(404)

    # Security: resolve the path and confirm it lives under data/
    resolved = Path(file_path).resolve()
    project_root = Path(current_app.root_path).parent.parent.resolve()
    data_dir = project_root / "data"
    try:
        resolved.relative_to(data_dir)
    except ValueError:
        logger.warning("image_crop: path traversal attempt for img_id=%s path=%s", img_id, file_path)
        abort(404)

    if not resolved.exists():
        abort(404)

    try:
        img = Image.open(resolved)
        if w > 0 and h > 0:
            output = img.crop((x, y, x + w, y + h))
        else:
            output = img
        buf = io.BytesIO()
        output.save(buf, format="PNG")
        buf.seek(0)
        return Response(buf.read(), mimetype="image/png")
    except Exception as exc:
        logger.error("image_crop: failed to serve img_id=%s: %s", img_id, exc)
        abort(500)


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


def _select_current_image(candidates: list[dict], requested_img_id: str | None) -> dict | None:
    """Select current image from V2 candidate list by img_id (UUID string)."""
    if not candidates:
        return None
    if requested_img_id:
        current = next(
            (c for c in candidates if str(c["img_id"]) == str(requested_img_id)), None
        )
        if current:
            return current
        flash("Image not found, showing first pending", "warning")
    return next(
        (c for c in candidates if c["review_status"] == "pending"),
        candidates[0] if candidates else None,
    )
