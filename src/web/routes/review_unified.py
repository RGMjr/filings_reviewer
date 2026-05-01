"""
Flask routes for the unified V2 review interface.

Combines V2 text fact review and image review into a single tabbed interface.
Takes over the /v2/review URL prefix from review_v2.py.
"""

import io
import logging
import threading
import time
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

from src.infra.db import DatabaseAdapter, infer_tab_from_filing
from src.review.models import (
    IMAGE_CHART_TYPE_LABELS,
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASON_LABELS,
    IMAGE_REJECTION_REASONS,
    IMAGE_REVIEW_STATUSES,
)
from src.web.app import get_db
from src.web.middleware import require_api_key
from src.web.routes._metrics import get_active_metrics
from src.web.url_builders import build_sec_directory_url, resolve_sec_filing_url

review_unified_bp = Blueprint("review_unified", __name__, url_prefix="/v2/review")
logger = logging.getLogger(__name__)

# Valid review statuses for V2 facts
V2_REVIEW_STATUSES = ("pending_review", "accepted", "rejected", "corrected", "auto_accepted")

# Valid sort options
V2_SORT_OPTIONS = ("confidence_desc", "confidence_asc", "metric", "period")

# Image-tab sort options. The DB function only knows the three legacy values
# ('relevance', 'tier', 'position'); 'model_score' is computed in Python after
# the SELECT (predicted_relevance is NULL in prod since USE_LEARNED_TRIAGE=false).
IMAGE_SORT_OPTIONS = ("relevance", "model_score", "tier", "position")
IMAGE_SORT_DEFAULT = "relevance"

# Valid analytical tab keys for the filing list filter. Stored in the URL under
# ?document_type=<tab> so existing bookmarks keep the same param name; the value
# space changed in the 2026-04 tab rename (was: sec_filing / earnings_call /
# investor_presentation — kept for bookmark compat fall-through to "all").
VALID_TABS = ("ipo", "earnings", "investor_day")

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

    raw_tab = request.args.get("document_type")
    tab = raw_tab if raw_tab in VALID_TABS else None
    hide_completed = request.args.get("hide_completed", "0") == "1"

    raw_sort_by = request.args.get("sort_by", "date")
    sort_by = raw_sort_by if raw_sort_by in VALID_FILING_SORT_COLUMNS else "date"
    raw_sort_dir = request.args.get("sort_dir", "desc")
    sort_dir = "asc" if raw_sort_dir == "asc" else "desc"

    reviewer_ids = [r for r in request.args.getlist("reviewer_id") if r]

    try:
        total = db.get_unified_filings_for_review_count(
            tab=tab,
            hide_completed=hide_completed,
            reviewer_ids=reviewer_ids or None,
        )
        filings = db.get_unified_filings_for_review(
            tab=tab,
            limit=per_page,
            offset=(page - 1) * per_page,
            hide_completed=hide_completed,
            sort_by=sort_by,
            sort_dir=sort_dir,
            reviewer_ids=reviewer_ids or None,
        )
        all_reviewers = db.get_distinct_reviewers()
    except Exception as e:
        logger.error(f"Database error in unified filing list: {e}")
        flash("Error loading filings.", "danger")
        filings = []
        total = 0
        all_reviewers = []

    total_pages = max(1, -(-total // per_page))  # ceiling division

    if not filings and page == 1:
        flash("No filings found.", "info")

    return render_template(
        "unified_filing_list.html",
        filings=filings,
        current_document_type=tab or "all",
        hide_completed=hide_completed,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_dir=sort_dir,
        all_reviewers=all_reviewers,
        selected_reviewers=reviewer_ids,
    )


@review_unified_bp.route("/stats")
def stats():
    """Display aggregate review statistics for both text and image review."""
    from src.web.routes.api_unified import _retrain_thresholds, _text_analysis_threshold

    db = get_db()
    text_data = db.get_v2_review_stats()
    image_overall = db.get_image_decision_overall_v2()
    image_progress = db.get_image_review_progress_v2()
    image_tier = db.get_image_decisions_by_tier_v2()
    image_rejections = db.get_image_rejection_reasons_by_tier_v2()

    # Phase 2: model-update anchor + decision counters + recent activity.
    # The "since" timestamp comes from the most recent succeeded image-classifier
    # retrain. When no run has completed yet, ts=None and the counters become
    # "decisions ever" — informational, not a retrain trigger.
    last_run = db.get_last_training_run("image_relevance")
    since_ts = last_run.get("completed_at") if last_run else None
    image_decisions_since = db.count_image_decisions_since(since_ts)
    text_decisions_since = db.count_text_decisions_since(since_ts)

    recent_text_corrections = db.get_recent_text_corrections(limit=10)
    recent_text_additions = db.get_recent_text_additions(limit=10)
    recent_image_additions = db.get_recent_image_additions(limit=10)
    recent_image_corrections = db.get_recent_image_corrections(limit=10)

    # Phase 4c: rejection-reason rollup. "Why Reviewers Reject" panel groups
    # decisions by category for both sides. Lifetime totals (since=None) so
    # the panel reflects the full reviewer corpus, not just decisions since
    # the last classifier retrain.
    text_rejection_rollup = db.get_rejection_reason_rollup("text", since=None)
    image_rejection_rollup = db.get_rejection_reason_rollup("image", since=None)

    # Phase 3: button activation logic. Active iff thresholds are met AND no
    # retrain is currently running. The endpoint enforces the same gates
    # server-side (this is just UX).
    threshold_total, threshold_positive = _retrain_thresholds()
    running_rows = db.query(
        """
        SELECT id FROM model_training_runs
         WHERE model_type = 'image_relevance' AND status = 'running'
         LIMIT 1
        """
    )
    retrain_running = bool(running_rows)
    running_run_id = str(running_rows[0]["id"]) if running_rows else None
    button_active = (
        not retrain_running
        and image_decisions_since["total"] >= threshold_total
        and image_decisions_since["positive"] >= threshold_positive
    )

    # Text-decision pattern analysis surface (parallel to the image-classifier
    # retrain). Anchor is the most recent succeeded analysis; counter is the
    # number of text decisions accumulated since then. The button enables when
    # the count clears the threshold and no analysis is currently running.
    last_text_analysis_run = db.get_last_text_analysis_run()
    text_analysis_anchor = (
        last_text_analysis_run["completed_at"] if last_text_analysis_run else None
    )
    text_decisions_since_analysis = db.count_text_decisions_since(text_analysis_anchor)
    text_analysis_running, text_analysis_running_run_id = db.is_text_analysis_running()
    text_analysis_threshold = _text_analysis_threshold()
    text_analysis_button_active = (
        not text_analysis_running and text_decisions_since_analysis >= text_analysis_threshold
    )
    if last_text_analysis_run:
        text_metric_summary = db.get_text_decision_metric_summary(str(last_text_analysis_run["id"]))
        text_phrase_findings = db.get_text_decision_phrase_findings(
            str(last_text_analysis_run["id"])
        )
    else:
        text_metric_summary = []
        text_phrase_findings = []

    from src.web.text_pattern_recommendations import compute_recommendations

    text_recommendation_decisions = db.get_recommendation_decisions(
        [s["metric_id"] for s in text_metric_summary] or None
    )
    text_recommendations = compute_recommendations(
        text_metric_summary, text_phrase_findings, text_recommendation_decisions
    )

    return render_template(
        "unified_stats.html",
        per_company=text_data["per_company"],
        totals=text_data["totals"],
        confidence_bands=text_data["confidence_bands"],
        image_overall=image_overall,
        image_progress=image_progress,
        image_tier=image_tier,
        image_rejections=image_rejections,
        rejection_reason_labels=IMAGE_REJECTION_REASON_LABELS,
        last_training_run=last_run,
        image_decisions_since=image_decisions_since,
        text_decisions_since=text_decisions_since,
        recent_text_corrections=recent_text_corrections,
        recent_text_additions=recent_text_additions,
        recent_image_additions=recent_image_additions,
        recent_image_corrections=recent_image_corrections,
        threshold_total=threshold_total,
        threshold_positive=threshold_positive,
        retrain_running=retrain_running,
        running_run_id=running_run_id,
        button_active=button_active,
        text_rejection_rollup=text_rejection_rollup,
        image_rejection_rollup=image_rejection_rollup,
        last_text_analysis_run=last_text_analysis_run,
        text_decisions_since_analysis=text_decisions_since_analysis,
        text_analysis_running=text_analysis_running,
        text_analysis_running_run_id=text_analysis_running_run_id,
        text_analysis_threshold=text_analysis_threshold,
        text_analysis_button_active=text_analysis_button_active,
        text_metric_summary=text_metric_summary,
        text_phrase_findings=text_phrase_findings,
        text_recommendations=text_recommendations,
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
        list_document_type = raw_list_doc_type if raw_list_doc_type in VALID_TABS else None
        list_hide_completed = request.args.get("list_hide_completed", "0") == "1"
        list_reviewer_ids = [r for r in request.args.getlist("list_reviewer_id") if r]

        next_filing_params: list[tuple[str, Any]] = [
            ("current_filing_id", filing_id),
            ("list_sort_by", list_sort_by),
            ("list_sort_dir", list_sort_dir),
            ("list_hide_completed", 1 if list_hide_completed else 0),
        ]
        if list_document_type:
            next_filing_params.append(("list_document_type", list_document_type))
        for rid in list_reviewer_ids:
            next_filing_params.append(("list_reviewer_id", rid))
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

        # Pending-first partition: same idea as image_candidates — display
        # order matches the order /api/v2/decisions advances through.
        # Stable within each partition (preserves user's chosen sort_by).
        facts = sorted(
            facts,
            key=lambda f: 0 if f["review_status"] == "pending_review" else 1,
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

        # Calculate progress. Green/red badges merge text-fact decisions
        # with per-metric image rejections so reviewers see one combined
        # total. Image accepts already promote into v2_metric_facts via
        # _promote_chart_fact, so the green count picks them up through
        # all_facts. Image rejects deliberately do not promote a fact row
        # (CLAUDE.md principle 4), so we count them separately.
        pending_count = sum(1 for f in all_facts if f["review_status"] == "pending_review")
        accepted_count = sum(
            1 for f in all_facts if f["review_status"] in ("accepted", "auto_accepted")
        )
        rejected_count = sum(
            1 for f in all_facts if f["review_status"] in ("rejected", "corrected")
        )
        rejected_count += db.count_image_metric_rejections_for_filing(filing_id)

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

        # Image-OCR segments (text from full-page-image OCR pipeline). Surfaced
        # in the text tab so reviewers can see OCR'd prose even when the
        # extraction pipeline emitted no v2_metric_facts rows for it (e.g.
        # 8-K page-image decks where Tier 1 patterns don't match the issuer's
        # KPI vocabulary). See known-issues fragment legacy-089.
        try:
            image_ocr_segments = db.get_v2_image_ocr_segments_for_filing(filing_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load image_ocr segments for filing_id=%s: %s",
                filing_id,
                exc,
            )
            image_ocr_segments = []

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

        image_sort = request.args.get("image_sort", IMAGE_SORT_DEFAULT)
        if image_sort not in IMAGE_SORT_OPTIONS:
            image_sort = IMAGE_SORT_DEFAULT
        # 'model_score' isn't a SQL sort — fetch in 'relevance' order, then
        # re-sort in Python below.
        db_image_sort = "relevance" if image_sort == "model_score" else image_sort

        image_candidates = db.get_image_review_candidates_for_filing_v2(
            filing_id=filing_id,
            status=db_image_status,
            sort_by=db_image_sort,
            limit=1000,
        )

        # Score-on-render: predicted_relevance is NULL in prod, so the SQL
        # 'relevance' sort silently degrades to relevance_score DESC. Compute
        # model score in Python from row metadata (no R2 fetch — pipeline
        # cached per worker in image_features.py).
        if image_sort == "model_score":
            from src.shared.image_features import predict_relevance, v2_row_to_features_input

            for c in image_candidates:
                # Queue SELECT projects fields under aliases (preceding_text,
                # image_width, image_height, cohort_confidence). Bridge to the
                # native key names v2_row_to_features_input expects.
                native_row = {
                    "nearby_text": c.get("preceding_text"),
                    "width": c.get("image_width"),
                    "height": c.get("image_height"),
                    "relevance_score": c.get("cohort_confidence"),
                    "classification": c.get("classification"),
                    "filename": c.get("filename"),
                }
                c["_model_score"] = predict_relevance(v2_row_to_features_input(native_row))
            image_candidates.sort(
                key=lambda c: (c["_model_score"] is None, -(c["_model_score"] or 0.0))
            )

        # Stable partition: pending first (in existing probability-desc order),
        # then everything else. Note: strip ordering uses raw review_status;
        # post-decision auto-advance in _get_next_image_candidate_info uses the
        # derived image_review_state, so navigation skips per-metric-decided
        # images that are still raw-pending. The strip thumbnail indicator shows
        # the correct derived state (green checkmark / X) alongside this order.
        image_candidates = sorted(
            image_candidates,
            key=lambda c: 0 if c["review_status"] == "pending" else 1,
        )

        current_image = _select_current_image(image_candidates, request.args.get("img_id"))

        # Per-metric confirmations for the currently-focused image
        # (chart-presence pivot, #86 PR 3b). Loaded only for the active image
        # since the full queue does not need prior decisions preloaded.
        current_image_confirmations: list[dict[str, Any]] = []
        if current_image and current_image.get("img_id"):
            try:
                raw = db.get_image_metric_confirmations(current_image["img_id"])
                current_image_confirmations = list(raw) if isinstance(raw, list) else []
                for c in current_image_confirmations:
                    for ts_key in ("created_at", "updated_at"):
                        ts = c.get(ts_key)
                        if ts is not None and hasattr(ts, "isoformat"):
                            c[ts_key] = ts.isoformat()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to load image metric confirmations for img_id=%s: %s",
                    current_image.get("img_id"),
                    exc,
                )
                current_image_confirmations = []

        # Image progress counts
        image_pending = sum(1 for c in all_image_candidates if c["review_status"] == "pending")
        image_reviewed = sum(1 for c in all_image_candidates if c["review_status"] == "reviewed")
        image_skipped = sum(1 for c in all_image_candidates if c["review_status"] == "skipped")
        image_auto_rejected = sum(
            1 for c in all_image_candidates if c["review_status"] == "auto_rejected"
        )
        image_auto_reject_candidates = sum(
            1
            for c in all_image_candidates
            if c.get("auto_reject_candidate") and c["review_status"] == "pending"
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
            image_ocr_segments=image_ocr_segments,
            # Image tab
            image_candidates=image_candidates,
            all_image_candidates=all_image_candidates,
            current_image=current_image,
            current_image_confirmations=current_image_confirmations,
            image_pending=image_pending,
            image_reviewed=image_reviewed,
            image_skipped=image_skipped,
            image_auto_rejected=image_auto_rejected,
            image_auto_reject_candidates=image_auto_reject_candidates,
            image_filters={"status": image_status, "sort": image_sort},
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
        raw_list_tab = request.args.get("list_document_type", "")
        list_tab = raw_list_tab if raw_list_tab in VALID_TABS else None
        hide_completed = request.args.get("list_hide_completed", "0") == "1"
        reviewer_ids = [r for r in request.args.getlist("list_reviewer_id") if r]

        # Tab-scoping fallback: if the reviewer arrived from the "All" view of
        # the filings list (list_tab is None), keep advancement within the
        # current filing's analytical tab so a 10-K reviewer doesn't jump to
        # an investor-day deck. Look up document_type/form_type once.
        effective_tab = list_tab
        if effective_tab is None:
            current_row = db.query(
                """
                SELECT f.form_type, d.document_type
                FROM filings f
                LEFT JOIN v2_documents d ON d.filing_id = f.filing_id
                WHERE f.filing_id = %(filing_id)s
                LIMIT 1
                """,
                {"filing_id": current_filing_id},
            )
            if current_row:
                effective_tab = infer_tab_from_filing(
                    current_row[0].get("document_type"),
                    current_row[0].get("form_type"),
                )

        next_id = db.get_next_filing_with_pending_work(
            current_filing_id=current_filing_id,
            tab=effective_tab,
            hide_completed=hide_completed,
            sort_by=sort_by,
            sort_dir=sort_dir,
            reviewer_ids=reviewer_ids or None,
        )

        if next_id:
            # Smart default: pick tab + status from the target filing's pending
            # counts. Setting them explicitly in the redirect URL prevents the
            # review-page localStorage restore from quietly swapping in a
            # filter saved on a previous filing.
            counts = db.get_filing_pending_counts(next_id)
            params_list: list[tuple[str, Any]] = [
                ("list_sort_by", sort_by),
                ("list_sort_dir", sort_dir),
                ("list_hide_completed", 1 if hide_completed else 0),
            ]
            if counts["facts_pending"] > 0:
                params_list.insert(0, ("status", "pending_review"))
            elif counts["images_pending"] > 0:
                params_list.insert(0, ("tab", "images"))
            else:
                params_list.insert(0, ("status", "all"))
            if list_tab:
                params_list.append(("list_document_type", list_tab))
            for rid in reviewer_ids:
                params_list.append(("list_reviewer_id", rid))
            return redirect(f"/v2/review/{next_id}?{urlencode(params_list)}")

        flash("No more filings with pending facts.", "info")
        list_params_list: list[tuple[str, Any]] = [
            ("sort_by", sort_by),
            ("sort_dir", sort_dir),
        ]
        if list_tab:
            list_params_list.append(("document_type", list_tab))
        for rid in reviewer_ids:
            list_params_list.append(("reviewer_id", rid))
        return redirect(url_for("review_unified.filing_list") + "?" + urlencode(list_params_list))

    except Exception as e:
        logger.error(f"Error in next_filing: {e}")
        flash("Error finding next filing.", "danger")
        return redirect(url_for("review_unified.filing_list"))


@review_unified_bp.route("/image_crop/<img_id>")
@require_api_key
def image_crop(img_id: str) -> Response:
    """
    Serve a chart image (full or cropped) stored on disk.

    Query params: x, y, w, h (integers, pixel coordinates). When w or h is
    missing/0, returns the full image instead of cropping — Vision GPT-4o
    does not populate per-DataPoint bbox, so most chart-sourced facts can
    only link back to the whole chart image.

    Security: `require_api_key` gates external fetches (same-origin browser
    loads from the review UI pass via the Origin/Referer bypass). `file_path`
    is additionally validated by `get_image_storage().get_bytes` to prevent
    path traversal.
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

    from src.infra.image_storage import InvalidStorageKeyError, get_image_storage

    try:
        image_bytes = get_image_storage().get_bytes(file_path)
    except InvalidStorageKeyError:
        logger.warning("image_crop: invalid storage key for img_id=%s key=%s", img_id, file_path)
        abort(404)
    except FileNotFoundError:
        abort(404)

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if w > 0 and h > 0:
            output = img.crop((x, y, x + w, y + h))
        else:
            output = img
        buf = io.BytesIO()
        output.save(buf, format="PNG")
        buf.seek(0)
        resp = Response(buf.read(), mimetype="image/png")
        resp.headers["Cache-Control"] = "private, max-age=3600"
        return resp
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
        current = next((c for c in candidates if str(c["img_id"]) == str(requested_img_id)), None)
        if current:
            return current
        flash("Image not found, showing first pending", "warning")
    return next(
        (c for c in candidates if c["review_status"] == "pending"),
        candidates[0] if candidates else None,
    )
