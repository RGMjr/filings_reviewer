"""
Flask routes for the human review interface.

Handles page rendering and navigation for reviewing metric extraction candidates.
API endpoints for AJAX decision submission are in api.py.
"""

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape

from src.review.models import (
    DECISION_TYPES,
    REJECTION_CATEGORIES,
    REVIEW_STATUSES,
)
from src.web.app import get_db

# Import needed for type annotations
from typing import Any

review_bp = Blueprint("review", __name__)
logger = logging.getLogger(__name__)


# =============================================================================
# Audit Logging Hooks
# =============================================================================
# These hooks automatically log all requests to review routes for audit trail
# and analytics. Logs are stored in review_audit_log table.


@review_bp.before_request
def _log_request_start():
    """
    Hook that runs before each request to review routes.

    Captures request start time for response time calculation.
    Stored in Flask g object for access in after_request hook.
    """
    g.request_start_time = time.time()


@review_bp.after_request
def _log_request_complete(response):
    """
    Hook that runs after each request to review routes.

    Logs request details to audit_log table including:
    - Session ID, IP address, user agent
    - Route name, HTTP method, URL path
    - Filing/candidate IDs if present in URL or query params
    - Response status and time

    Args:
        response: Flask response object

    Returns:
        Unmodified response object
    """
    try:
        # Calculate response time
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        # Extract filing_id and candidate_id from URL path or query params
        filing_id = request.view_args.get("filing_id") if request.view_args else None
        candidate_id = request.view_args.get("candidate_id") if request.view_args else None

        # If not in URL path, check query params
        if filing_id is None and "filing_id" in request.args:
            try:
                filing_id = int(request.args["filing_id"])
            except (ValueError, TypeError):
                pass

        if candidate_id is None and "candidate_id" in request.args:
            try:
                candidate_id = int(request.args["candidate_id"])
            except (ValueError, TypeError):
                pass

        # Get database connection
        db = get_db()

        # Insert audit log entry
        db.insert_audit_log(
            session_id=session.get("_id"),  # Flask session ID
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            filing_id=filing_id,
            candidate_id=candidate_id,
            query_params=dict(request.args) if request.args else None,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        # Log error but don't break the request
        logger.error(f"Failed to insert audit log: {e}")

    return response


# =============================================================================
# Template Data Contracts (TypedDict)
# =============================================================================
# These TypedDict classes document the structure of data passed to templates.
# They serve as both documentation and enable type checking.


class PaginationData(TypedDict, total=False):
    """Pagination metadata passed to templates.

    Used by: filing_list.html

    Note: Uses total=False because total_count, total_pages, has_prev, has_next
    are only included when total_count is known.
    """
    # Always present
    page: int  # Current page number (1-indexed)
    per_page: int  # Items per page
    offset: int  # Database query offset
    limit: int  # Database query limit (same as per_page)

    # Present only when total_count is known
    total_count: int  # Total number of items
    total_pages: int  # Total number of pages
    has_prev: bool  # Whether there is a previous page
    has_next: bool  # Whether there is a next page


class ReviewProgress(TypedDict):
    """Overall review progress across all filings.

    Used by: filing_list.html
    """
    total_candidates: int  # Total candidates across all filings
    pending_count: int  # Number of pending candidates
    reviewed_count: int  # Number of reviewed candidates
    skipped_count: int  # Number of skipped candidates
    review_pct: float  # Percentage reviewed (0-100)
    total_filings: int  # Total filings with candidates
    filings_with_pending: int  # Filings that still have pending candidates


class FilingListItem(TypedDict):
    """Structure of a filing item in the filing list.

    Used by: filing_list.html (in filings array)
    """
    filing_id: int
    company_id: int
    company_name: str
    cik: str
    accession_number: str
    form_type: str
    filing_date: datetime
    total_candidates: int  # Total candidates for this filing
    pending_count: int  # Pending candidates for this filing
    reviewed_count: int  # Reviewed candidates for this filing
    review_status: str  # Overall status: 'pending' or 'reviewed'


class FilingData(TypedDict):
    """Filing metadata passed to review interface.

    Used by: review.html
    """
    filing_id: int
    company_id: int
    company_name: str
    cik: str
    accession_number: str
    form_type: str
    filing_date: datetime
    file_path: str
    status: str
    total_pages: int | None
    html_fetched: bool
    sec_html_url: str | None  # Direct URL to primary HTML document on SEC EDGAR
    created_at: datetime
    updated_at: datetime


class CandidateData(TypedDict, total=False):
    """Structure of a review candidate with optional segment and decision fields.

    Used by: review.html (in candidates array and current_candidate)

    Note: Uses total=False because segment fields (segment_type, segment_html)
    and decision fields (decision_id, decision, etc.) may be NULL depending on
    whether the candidate has a source_segment_id or has been reviewed.
    """
    # Core candidate fields (always present)
    candidate_id: int
    filing_id: int
    company_id: int
    char_position: int
    context_text: str
    raw_number_text: str
    triggering_keyword: str
    keyword_distance: int
    keyword_position: str
    parsed_value: Decimal
    parsed_unit: str | None
    suggested_metric_id: str
    suggestion_confidence: float
    review_status: str  # 'pending', 'reviewed', 'skipped'
    created_at: datetime

    # Segment fields (from LEFT JOIN to source_segments)
    segment_type: str | None  # 'table', 'paragraph', etc. - NULL if no source_segment_id
    segment_html: str | None  # Raw HTML of segment - NULL if no source_segment_id
    segment_html_table_only: str | None  # Table HTML preserved for dual display when value is truncated
    features: dict | None  # JSONB features for ML pattern analysis

    # Decision fields (present only if reviewed - from LEFT JOIN)
    decision_id: int | None
    decision: str | None  # 'accept', 'reject', 'reclassify'
    assigned_metric_id: str | None
    rejection_category: str | None
    rejection_reason: str | None
    reviewer_notes: str | None
    reviewer_id: str | None
    review_time_seconds: int | None
    decision_created_at: datetime | None


class DecisionData(TypedDict):
    """Existing decision data for a reviewed candidate.

    Used by: review.html (existing_decision)
    """
    decision_id: int
    decision: str  # 'accept', 'reject', 'reclassify'
    assigned_metric_id: str | None
    rejection_category: str | None
    rejection_reason: str | None
    reviewer_notes: str | None
    reviewer_id: str | None
    review_time_seconds: int | None
    created_at: datetime | None


class MetricData(TypedDict):
    """Active metric data for reclassify dropdown.

    Used by: review.html (in metrics array)
    """
    metric_id: str
    display_name: str
    metric_class: str  # 'core', 'extended', etc.
    primary_concept: str


# =============================================================================
# Page Routes
# =============================================================================

@review_bp.route("/")
def index():
    """Redirect root to filing list."""
    return redirect(url_for("review.filing_list"))


@review_bp.route("/filings")
def filing_list():
    """Display list of filings with review candidates."""
    db = get_db()
    status = request.args.get("status")

    # Get pagination parameters from query string
    page_raw = request.args.get("page", type=int)
    per_page_raw = request.args.get("per_page", type=int)

    # Validate pagination parameters
    page = _validate_positive_int("page", page_raw, default=1, min_value=1)
    per_page = _validate_positive_int(
        "per_page", per_page_raw, default=50, min_value=1, max_value=100
    )

    # Validate status filter
    if status and status not in REVIEW_STATUSES:
        flash(f"Invalid status filter: {status}", "warning")
        status = None

    try:
        # Get total count for pagination
        total_count = db.get_filings_with_candidates_count(status=status)

        # Calculate pagination
        pagination = _paginate(page=page, per_page=per_page, total_count=total_count)

        # Improvement #1: Validate page doesn't exceed total_pages
        if total_count > 0 and page > pagination["total_pages"]:
            flash(
                f"Page {page} does not exist. Showing page 1 of {pagination['total_pages']}.",
                "warning",
            )
            # Redirect to page 1 with same filters
            return redirect(
                url_for("review.filing_list", status=status, per_page=per_page)
            )

        # Get filings for current page
        filings = db.get_filings_with_candidates(
            status=status, limit=pagination["limit"], offset=pagination["offset"]
        )

        # Get overall progress
        progress = db.get_review_progress()
    except Exception as e:
        logger.error(f"Database error in filing_list: {e}")
        flash("Error loading filings. Please try again.", "danger")
        filings = []
        progress = {
            "total_candidates": 0,
            "pending_count": 0,
            "reviewed_count": 0,
            "skipped_count": 0,
            "review_pct": 0,
            "total_filings": 0,
            "filings_with_pending": 0,
        }
        pagination = _paginate(page=1, per_page=50, total_count=0)

    # Improvement #2: Handle empty results on page 1
    if not filings and page == 1:
        flash("No filings with candidates found. Generate candidates first.", "info")

    # Render template with documented data contract
    # Template: filing_list.html
    # Data contract:
    #   - filings: List[FilingListItem] - Filings with candidate counts
    #   - progress: ReviewProgress - Overall review progress
    #   - current_status_filter: str | None - Active status filter
    #   - review_statuses: Tuple[str, str] - Valid status values ('pending', 'reviewed')
    #   - pagination: PaginationData - Pagination metadata
    return render_template(
        "filing_list.html",
        filings=filings,
        progress=progress,
        current_status_filter=status,
        review_statuses=REVIEW_STATUSES,
        pagination=pagination,
    )


@review_bp.route("/review/<int:filing_id>")
def review_filing(filing_id: int):
    """Main review interface for a filing."""
    db = get_db()

    try:
        # Get filing metadata
        filing_sql = """
            SELECT f.*, c.company_name, c.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.filing_id = %(filing_id)s
        """
        filing_result = db.query(filing_sql, {"filing_id": filing_id})

        if not filing_result:
            abort(404)

        filing = dict(filing_result[0])  # Make mutable copy

        # Resolve the correct SEC filing URL (database may have incorrect primary.htm URL)
        filing["sec_html_url"] = _resolve_sec_filing_url(
            cik=filing.get("cik", ""),
            accession_number=filing.get("accession_number", ""),
            stored_url=filing.get("sec_html_url"),
        )

        # Parse filter and sort URL parameters
        filter_status = request.args.get("status", "all")
        filter_metric = request.args.get("metric", "all")
        filter_confidence = request.args.get("confidence", "all")
        sort_by = request.args.get("sort", "position")

        # Validate and convert filter values for database query
        # Invalid values fall back to defaults (no filter)
        db_status = filter_status if filter_status in REVIEW_STATUSES else None
        db_metric_id = filter_metric if filter_metric != "all" else None
        db_confidence = filter_confidence if filter_confidence in ("high", "medium", "low") else None
        db_sort_by = sort_by if sort_by in ("position", "confidence_asc", "confidence_desc", "value_asc", "value_desc") else "position"

        # Get total candidate count (unfiltered) for "Showing X of Y" display
        all_candidates = db.get_review_candidates_with_decisions(
            filing_id=filing_id, limit=None
        )
        total_candidates_unfiltered = len(all_candidates)

        # Get filtered candidates for this filing WITH their decisions
        candidates = db.get_review_candidates_with_decisions(
            filing_id=filing_id,
            status=db_status,
            metric_id=db_metric_id,
            confidence_level=db_confidence,
            sort_by=db_sort_by,
            limit=None  # Get all matching candidates
        )

        # Get active metrics for reclassify dropdown
        metrics = _get_active_metrics()

        # Get unique metrics in this filing for filter dropdown
        available_metrics = _get_unique_metrics_for_filing(all_candidates)

        # Validate and get candidate_id parameter
        candidate_id_raw = request.args.get("candidate_id", type=int)
        candidate_id_param = _validate_positive_int(
            "candidate_id", candidate_id_raw, default=None, min_value=1, flash_errors=False
        )

        # Select current candidate using extracted helper
        current_candidate = _select_current_candidate(candidates, candidate_id_param)

        # Calculate progress using extracted helper (on filtered candidates)
        total_candidates, reviewed_count, pending_count = _calculate_review_progress(candidates)

        # Extract decision from current candidate using extracted helper
        existing_decision = _extract_decision_from_candidate(current_candidate)

        # Build current_filters dict for template
        has_active_filters = (filter_status != "all" or filter_metric != "all" or
                             filter_confidence != "all" or sort_by != "position")
        current_filters = {
            "status": filter_status,
            "metric": filter_metric,
            "confidence": filter_confidence,
            "sort": sort_by,
            "has_active_filters": has_active_filters,
        }

        # Render template with documented data contract
        # Template: review.html
        # Data contract:
        #   - filing: FilingData - Filing metadata (company, accession, etc.)
        #   - candidates: List[CandidateData] - Filtered candidates for this filing
        #   - current_candidate: CandidateData | None - Candidate currently being reviewed
        #   - existing_decision: DecisionData | None - Existing decision if already reviewed
        #   - metrics: List[MetricData] - Active metrics for reclassify dropdown
        #   - available_metrics: List[str] - Unique metrics in this filing for filter dropdown
        #   - current_filters: Dict - Current filter state
        #   - decision_types: Tuple[str, str, str] - Valid decision types ('accept', 'reject', 'reclassify')
        #   - rejection_categories: Tuple[str, ...] - Valid rejection categories
        #   - total_candidates: int - Number of candidates matching filters
        #   - total_candidates_unfiltered: int - Total number of candidates (unfiltered)
        #   - pending_count: int - Number of pending candidates (in filtered set)
        #   - reviewed_count: int - Number of reviewed candidates (in filtered set)
        return render_template(
            "review.html",
            filing=filing,
            candidates=candidates,
            current_candidate=current_candidate,
            existing_decision=existing_decision,
            metrics=metrics,
            available_metrics=available_metrics,
            current_filters=current_filters,
            decision_types=DECISION_TYPES,
            rejection_categories=REJECTION_CATEGORIES,
            total_candidates=total_candidates,
            total_candidates_unfiltered=total_candidates_unfiltered,
            pending_count=pending_count,
            reviewed_count=reviewed_count,
        )

    except Exception as e:
        logger.error(f"Error in review_filing for filing_id={filing_id}: {e}")
        flash("Error loading filing. Please try again.", "danger")
        return redirect(url_for("review.filing_list"))


@review_bp.route("/stats")
def stats():
    """Display statistics dashboard for review progress."""
    db = get_db()

    try:
        # Get overall decision statistics
        overall_stats = db.get_decision_statistics()

        # Get decision breakdown by metric
        metric_stats = db.get_decision_stats_by_metric()

        # Get daily decision counts for trend chart
        daily_counts = db.get_daily_decision_counts(days=7)

        # Get overall review progress (reviewed vs total candidates)
        progress = db.get_review_progress()

        # Render template with documented data contract
        # Template: stats.html
        # Data contract:
        #   - overall_stats: Dict - Total decisions, accept/reject/reclassify counts & percentages
        #   - metric_stats: List[Dict] - Decision breakdown by metric type
        #   - daily_counts: List[Dict] - Daily decision counts for last 7 days
        #   - progress: Dict - Overall review progress (reviewed/total candidates)
        return render_template(
            "stats.html",
            overall_stats=overall_stats,
            metric_stats=metric_stats,
            daily_counts=daily_counts,
            progress=progress,
        )

    except Exception as e:
        logger.error(f"Error loading statistics dashboard: {e}")
        flash("Error loading statistics. Please try again.", "danger")
        return redirect(url_for("review.filing_list"))


# =============================================================================
# Navigation Routes
# =============================================================================

@review_bp.route("/review/<int:filing_id>/next")
def next_candidate(filing_id: int):
    """Navigate to next pending candidate, respecting active filters."""
    db = get_db()
    current_id_raw = request.args.get("current_id", type=int)

    # Validate current_id if provided
    current_id = _validate_positive_int(
        "current_id", current_id_raw, default=None, min_value=1, flash_errors=False
    )

    # Extract filter parameters to maintain navigation consistency
    filter_status = request.args.get("status", "all")
    filter_metric = request.args.get("metric", "all")
    filter_confidence = request.args.get("confidence", "all")
    sort_by = request.args.get("sort", "position")

    filters = {
        "status": filter_status,
        "metric": filter_metric,
        "confidence": filter_confidence,
        "sort": sort_by,
    }

    try:
        # Find next candidate using filter-aware helper
        next_cand = _find_next_candidate(db, filing_id, current_id, filters)

        if next_cand:
            # Build redirect URL with filter parameters preserved
            redirect_params = {"filing_id": filing_id, "candidate_id": next_cand["candidate_id"]}
            if filter_status != "all":
                redirect_params["status"] = filter_status
            if filter_metric != "all":
                redirect_params["metric"] = filter_metric
            if filter_confidence != "all":
                redirect_params["confidence"] = filter_confidence
            if sort_by != "position":
                redirect_params["sort"] = sort_by

            return redirect(url_for("review.review_filing", **redirect_params))
        else:
            flash("All candidates matching your filters have been reviewed!", "success")
            return redirect(url_for("review.filing_list"))

    except Exception as e:
        logger.error(f"Error navigating to next candidate: {e}")
        flash("Error loading next candidate.", "danger")
        return redirect(url_for("review.filing_list"))


@review_bp.route("/review/<int:filing_id>/candidate/<int:candidate_id>")
def jump_to_candidate(filing_id: int, candidate_id: int):
    """Jump to specific candidate (canonical URL)."""
    db = get_db()

    try:
        # Verify candidate exists
        candidate = db.get_review_candidate(candidate_id)

        if not candidate:
            flash("Candidate not found", "danger")
            return redirect(url_for("review.filing_list"))

        # Verify candidate belongs to this filing
        if candidate["filing_id"] != filing_id:
            flash("Candidate does not belong to this filing", "danger")
            return redirect(url_for("review.filing_list"))

        # Redirect to review interface with query param
        return redirect(
            url_for(
                "review.review_filing", filing_id=filing_id, candidate_id=candidate_id
            )
        )

    except Exception as e:
        logger.error(f"Error jumping to candidate: {e}")
        flash("Error loading candidate.", "danger")
        return redirect(url_for("review.filing_list"))


# =============================================================================
# Helper Functions
# =============================================================================

def _validate_positive_int(
    param_name: str,
    value: int | None,
    default: int | None,
    min_value: int = 1,
    max_value: int | None = None,
    flash_errors: bool = True,
) -> int | None:
    """
    Validate and sanitize a positive integer query parameter.

    Args:
        param_name: Name of the parameter (for error messages)
        value: The value to validate (from request.args.get)
        default: Default value to return on validation failure (can be None)
        min_value: Minimum allowed value (default: 1)
        max_value: Maximum allowed value (default: None = no max)
        flash_errors: Whether to flash validation errors (default: True)

    Returns:
        Validated integer value or default (which may be None)

    Examples:
        >>> _validate_positive_int("page", 5, 1)
        5
        >>> _validate_positive_int("page", -1, 1)  # Returns 1 (default), flashes error
        1
        >>> _validate_positive_int("per_page", 200, 50, max_value=100)  # Returns 100 (max), flashes error
        100
        >>> _validate_positive_int("candidate_id", None, None)  # Returns None
        None
    """
    # Handle None (conversion failed or not provided)
    if value is None:
        return default

    # Validate minimum
    if value < min_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at least {min_value}. Using default: {default}",
                "warning",
            )
        return default

    # Validate maximum
    if max_value is not None and value > max_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at most {max_value}. Using {max_value}.",
                "warning",
            )
        return max_value

    return value


def _paginate(
    page: int = 1, per_page: int = 50, total_count: int | None = None
) -> PaginationData:
    """
    Calculate pagination metadata.

    Args:
        page: Current page number (1-indexed)
        per_page: Items per page
        total_count: Total number of items (if known)

    Returns:
        PaginationData with offset, limit, page, per_page, total_pages (if total_count provided)
    """
    page = max(1, page)  # Ensure page >= 1
    per_page = max(1, min(100, per_page))  # Clamp between 1 and 100

    offset = (page - 1) * per_page

    result = {
        "page": page,
        "per_page": per_page,
        "offset": offset,
        "limit": per_page,
    }

    if total_count is not None:
        result["total_count"] = total_count
        result["total_pages"] = (total_count + per_page - 1) // per_page
        result["has_prev"] = page > 1
        result["has_next"] = page < result["total_pages"]

    return result


def _select_current_candidate(
    candidates: list[CandidateData],
    requested_id: int | None
) -> CandidateData | None:
    """
    Select the current candidate to display from a list of candidates.

    Logic:
    1. If requested_id provided and found → return that candidate
    2. If requested_id provided but not found → flash warning, return first pending
    3. If no requested_id → return first pending
    4. If no pending candidates → return first candidate (or None if empty)

    Args:
        candidates: List of all candidates for the filing
        requested_id: Candidate ID requested via query parameter (or None)

    Returns:
        The candidate to display, or None if candidates list is empty
    """
    if not candidates:
        return None

    if requested_id:
        # Try to find the requested candidate
        current = next(
            (c for c in candidates if c["candidate_id"] == requested_id),
            None,
        )
        if current:
            return current

        # Requested candidate not found, show warning and fall back
        flash("Candidate not found, showing first pending", "warning")

    # Return first pending candidate, or first candidate if none pending
    return next(
        (c for c in candidates if c["review_status"] == "pending"),
        candidates[0],
    )


def _calculate_review_progress(
    candidates: list[CandidateData]
) -> tuple[int, int, int]:
    """
    Calculate review progress from a list of candidates.

    Args:
        candidates: List of candidates with review_status field

    Returns:
        Tuple of (total_candidates, reviewed_count, pending_count)
    """
    total_candidates = len(candidates)
    reviewed_count = sum(
        1 for c in candidates if c["review_status"] == "reviewed"
    )
    pending_count = sum(
        1 for c in candidates if c["review_status"] == "pending"
    )

    return total_candidates, reviewed_count, pending_count


def _extract_decision_from_candidate(
    candidate: CandidateData | None
) -> DecisionData | None:
    """
    Extract decision data from a candidate record.

    Candidates from get_review_candidates_with_decisions() include decision fields
    from a LEFT JOIN. This function extracts those fields into a separate dict.

    **IMPORTANT**: Automated decisions (reviewer_id='hrv5_script') are treated as
    suggestions that can be overridden by humans. They are returned so the UI can
    display them, but the template should allow human reviewers to override them.

    Args:
        candidate: Candidate record with optional decision fields

    Returns:
        DecisionData dict if candidate has a decision, None otherwise
    """
    if not candidate or not candidate.get("decision_id"):
        return None

    return {
        "decision_id": candidate["decision_id"],
        "decision": candidate["decision"],
        "assigned_metric_id": candidate.get("assigned_metric_id"),
        "rejection_category": candidate.get("rejection_category"),
        "rejection_reason": candidate.get("rejection_reason"),
        "reviewer_notes": candidate.get("reviewer_notes"),
        "reviewer_id": candidate.get("reviewer_id"),
        "review_time_seconds": candidate.get("review_time_seconds"),
        "created_at": candidate.get("decision_created_at"),
        "is_automated": candidate.get("reviewer_id") == "hrv5_script",  # Flag automated decisions
    }


def _find_next_candidate(
    db,
    filing_id: int,
    current_id: int | None,
    filters: dict[str, str] | None = None,
) -> dict | None:
    """
    Find the next pending candidate for a filing, respecting active filters.

    Navigation advances through the filtered, sorted candidate list.
    When reaching the end, wraps around to the beginning of the filtered list.

    Args:
        db: Database adapter instance
        filing_id: Filing ID to search within
        current_id: Current candidate ID to search after (or None)
        filters: Optional dict with filter/sort settings:
            - status: 'pending', 'reviewed', 'all' (default: navigates to pending only)
            - metric: metric_id or 'all'
            - confidence: 'high', 'medium', 'low', 'all'
            - sort: 'position', 'confidence_asc', 'confidence_desc', 'value_asc', 'value_desc'

    Returns:
        Next candidate dict, or None if no more candidates matching filters
    """
    filters = filters or {}

    # Extract filter parameters
    filter_status = filters.get("status", "all")
    filter_metric = filters.get("metric", "all")
    filter_confidence = filters.get("confidence", "all")
    sort_by = filters.get("sort", "position")

    # Convert to database query parameters
    db_status = filter_status if filter_status in ("pending", "reviewed", "skipped", "in_progress") else None
    db_metric_id = filter_metric if filter_metric != "all" else None
    db_confidence = filter_confidence if filter_confidence in ("high", "medium", "low") else None
    db_sort_by = sort_by if sort_by in ("position", "confidence_asc", "confidence_desc", "value_asc", "value_desc") else "position"

    # When navigating "next", we always look for pending candidates (unless status filter is set)
    # This ensures we skip reviewed candidates during normal review flow
    if db_status is None:
        db_status = "pending"

    # Get filtered, sorted candidates
    candidates = db.get_review_candidates_with_decisions(
        filing_id=filing_id,
        status=db_status,
        metric_id=db_metric_id,
        confidence_level=db_confidence,
        sort_by=db_sort_by,
        limit=None,
    )

    if not candidates:
        return None

    # Find current candidate index in the sorted list
    current_index = None
    if current_id:
        for i, c in enumerate(candidates):
            if c["candidate_id"] == current_id:
                current_index = i
                break

    # If current candidate is in the list, get the next one
    if current_index is not None:
        # Next candidate is the one after current in sorted order
        next_index = current_index + 1
        if next_index < len(candidates):
            next_candidate = candidates[next_index]
        else:
            # Wrap around to beginning
            next_candidate = candidates[0]

        # Don't return the same candidate we're on
        if next_candidate["candidate_id"] == current_id:
            return None

        return next_candidate
    else:
        # Current candidate not in filtered list (e.g., just reviewed it, or no current_id)
        # Return the first candidate in the filtered list
        return candidates[0]


def _resolve_sec_filing_url(cik: str, accession_number: str, stored_url: str | None = None) -> str:
    """
    Resolve the correct SEC filing URL for the primary document.

    The stored sec_html_url in the database sometimes uses a hardcoded filename
    like 'primary.htm' which may not exist. This function resolves the actual
    primary document URL by querying the SEC EDGAR index.

    Args:
        cik: Company CIK (can be any format, will be normalized)
        accession_number: SEC accession number (with dashes)
        stored_url: Optional stored URL from database (used as fallback)

    Returns:
        URL to the primary HTML document, or fallback to directory URL
    """
    import os

    from src.infra.sec_client import SECClient

    try:
        # Create SEC client with user agent from env
        user_agent = os.environ.get("SEC_USER_AGENT", "filings-reviewer info@example.com")
        client = SECClient(user_agent=user_agent)

        # Normalize CIK (remove leading zeros for API call, but keep for URL)
        cik_normalized = cik.lstrip("0") or "0"

        # Resolve the actual primary document URL
        resolved_url = client.resolve_primary_document_url(cik_normalized, accession_number)

        if resolved_url:
            logger.debug(f"Resolved SEC URL: {resolved_url}")
            return resolved_url

    except Exception as e:
        logger.warning(f"Failed to resolve SEC URL for {cik}/{accession_number}: {e}")

    # Fallback: if stored URL exists and doesn't look like hardcoded primary.htm, use it
    if stored_url and "primary.htm" not in stored_url.lower():
        return stored_url

    # Final fallback: directory URL
    accession_no_dashes = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_no_dashes}/"


def _get_active_metrics() -> list[MetricData]:
    """
    Get list of active metrics for dropdown.

    Cached in Flask g object to avoid repeated queries.
    Returns list sorted by logical grouping (customer count, transactions, revenue, etc.).

    Returns:
        List[MetricData]: Active metrics with metric_id, display_name, metric_class, primary_concept
    """
    if "metrics" not in g:
        db = get_db()
        metrics_sql = """
            SELECT metric_id, display_name, metric_class, primary_concept
            FROM metrics
            WHERE status = 'active'
            ORDER BY
                CASE metric_id
                    -- 1. Customer Count Metrics
                    WHEN 'cm_new_customers_acquired' THEN 1
                    WHEN 'cm_active_customers_total' THEN 2
                    WHEN 'cm_customers_period_end_by_tenure' THEN 3
                    WHEN 'cm_monthly_active_users' THEN 4
                    WHEN 'cm_daily_active_users' THEN 5

                    -- 2. Transaction & Purchase Behavior
                    WHEN 'cm_transactions_by_cohort' THEN 10
                    WHEN 'cm_repeat_purchase_rate' THEN 11
                    WHEN 'cm_average_order_value' THEN 12

                    -- 3. Revenue Metrics
                    WHEN 'cm_revenue_by_cohort' THEN 20
                    WHEN 'cm_revenue_per_customer' THEN 21
                    WHEN 'cm_arr' THEN 22
                    WHEN 'cm_mrr' THEN 23
                    WHEN 'cm_expansion_revenue' THEN 24
                    WHEN 'cm_gmv' THEN 25
                    WHEN 'cm_take_rate' THEN 26

                    -- 4. Revenue Predictability & Contracting
                    WHEN 'cm_bookings' THEN 30
                    WHEN 'cm_billings' THEN 31
                    WHEN 'cm_deferred_revenue' THEN 32
                    WHEN 'cm_acv' THEN 33
                    WHEN 'cm_tcv' THEN 34

                    -- 5. Revenue Concentration
                    WHEN 'cm_revenue_concentration' THEN 40

                    -- 6. Gross Margin
                    WHEN 'cm_gross_margin_overall' THEN 50
                    WHEN 'cm_gross_margin_by_cohort' THEN 51

                    -- 7. Retention, Churn & Attrition
                    WHEN 'cm_customer_retention_rate' THEN 60
                    WHEN 'cm_customer_churn_rate' THEN 61
                    WHEN 'cm_net_revenue_retention' THEN 62
                    WHEN 'cm_gross_revenue_retention' THEN 63

                    -- 8. Unit Economics & CAC
                    WHEN 'cm_customer_acquisition_cost' THEN 70
                    WHEN 'cm_cac_payback_period' THEN 71

                    -- Future metrics (if any become active)
                    ELSE 99
                END
        """
        g.metrics = db.query(metrics_sql)

    return g.metrics


def _get_unique_metrics_for_filing(candidates: list[dict]) -> list[str]:
    """
    Extract unique metric IDs from candidates for filter dropdown.

    Args:
        candidates: List of candidate dicts with suggested_metric_id

    Returns:
        Sorted list of unique metric IDs present in candidates
    """
    unique_metrics = set()
    for candidate in candidates:
        metric_id = candidate.get("suggested_metric_id")
        if metric_id:
            unique_metrics.add(metric_id)
    return sorted(unique_metrics)


def _highlight_context(
    context_text: str,
    raw_number_text: str,
    triggering_keyword: str
) -> Markup:
    """
    Highlight number and keyword in context text for review display.

    This function prepares context text for display in the review interface by:
    1. HTML-escaping the context for XSS safety
    2. Wrapping the raw number with <mark class="extracted-number"> for yellow highlighting
    3. Wrapping the triggering keyword with <u class="triggering-keyword"> for blue underlining
    4. Returning as Markup for safe template rendering

    Args:
        context_text: The surrounding text context (30-50 words each direction from number)
        raw_number_text: Exact number text to highlight (e.g., "1,234", "$493M")
        triggering_keyword: Metric keyword to underline (e.g., "customers", "revenue")

    Returns:
        Markup: HTML-safe string with highlighting markup

    Edge Cases:
        - Number not found: Logs warning, returns context with only keyword highlighted
        - Keyword not found: Highlights only the number
        - Number matching: Case-sensitive exact match
        - Keyword matching: Case-insensitive search
        - XSS protection: All user input is HTML-escaped before markup is added

    Example:
        >>> context = "We had 1,234 active customers in Q1 2023."
        >>> result = _highlight_context(context, "1,234", "customers")
        >>> # Returns: "We had <mark class='extracted-number'>1,234</mark> active
        >>> #           <u class='triggering-keyword'>customers</u> in Q1 2023."
    """
    # HTML-escape context_text first for XSS protection
    safe_text = str(escape(context_text))
    safe_number = str(escape(raw_number_text))

    # Find and highlight number (case-sensitive exact match)
    num_idx = safe_text.find(safe_number)
    if num_idx != -1:
        before = safe_text[:num_idx]
        number = safe_text[num_idx:num_idx + len(safe_number)]
        after = safe_text[num_idx + len(safe_number):]
        safe_text = (
            before +
            f'<mark class="extracted-number">{number}</mark>' +
            after
        )
    else:
        logger.warning(
            f"Number '{raw_number_text}' not found in context text. "
            f"Context length: {len(context_text)} chars"
        )

    # Find and highlight keyword (case-insensitive)
    # Need to search in the safe_text which may now contain markup
    # So we search case-insensitively and extract the actual case from text
    lower_text = safe_text.lower()
    kw_lower = triggering_keyword.lower()
    kw_idx = lower_text.find(kw_lower)

    if kw_idx != -1:
        # Extract actual keyword with original case from safe_text
        actual_keyword = safe_text[kw_idx:kw_idx + len(triggering_keyword)]
        before = safe_text[:kw_idx]
        after = safe_text[kw_idx + len(triggering_keyword):]
        safe_text = (
            before +
            f'<u class="triggering-keyword">{actual_keyword}</u>' +
            after
        )

    return Markup(safe_text)


def _highlight_html(
    html_content: str,
    raw_number_text: str,
    triggering_keyword: str
) -> Markup:
    """
    Highlight number and keyword in HTML content (like tables) for review display.

    Unlike _highlight_context, this function preserves existing HTML structure
    and only adds highlighting to text content. Use this for segment_html
    which already contains safe table markup.

    IMPORTANT: This function uses BeautifulSoup to parse and re-serialize the HTML,
    which auto-closes any truncated/broken tags. This is necessary because segment_html
    may be truncated at max_length characters, leaving unclosed tags that would break
    the page layout.

    Args:
        html_content: HTML content (e.g., table) - may be truncated/have unclosed tags
        raw_number_text: Exact number text to highlight
        triggering_keyword: Metric keyword to underline

    Returns:
        Markup: HTML string with highlighting added and broken tags fixed
    """
    import re

    from bs4 import BeautifulSoup

    # Parse HTML with BeautifulSoup to fix any truncated/unclosed tags
    # This is critical because segment_html may be cut off mid-tag
    soup = BeautifulSoup(html_content, 'html.parser')
    result = str(soup)

    # Highlight the number (case-sensitive exact match)
    # Use word boundary to avoid partial matches
    if raw_number_text:
        escaped_number = re.escape(raw_number_text)
        result = re.sub(
            f'({escaped_number})',
            r'<mark class="extracted-number">\1</mark>',
            result,
            count=1  # Only highlight first occurrence
        )

    # Highlight the keyword (case-insensitive)
    # Use BeautifulSoup to search text nodes to handle keywords split across HTML tags
    if triggering_keyword:
        soup = BeautifulSoup(result, 'html.parser')
        keyword_lower = triggering_keyword.lower()

        # Search through all text nodes to find the keyword
        # This handles cases where keyword is split across tags or has whitespace
        for element in soup.find_all(text=True):
            text = str(element)
            text_lower = text.lower()

            # Check if keyword appears in this text node
            if keyword_lower in text_lower:
                # Find the actual position (case-insensitive)
                idx = text_lower.find(keyword_lower)
                if idx != -1:
                    # Extract the actual keyword with original case from the text
                    actual_keyword = text[idx:idx + len(triggering_keyword)]

                    # Create highlighted version
                    highlighted_text = (
                        text[:idx] +
                        f'<u class="triggering-keyword">{actual_keyword}</u>' +
                        text[idx + len(triggering_keyword):]
                    )

                    # Replace the text node with highlighted version
                    # BeautifulSoup will parse the HTML we inject
                    from bs4 import NavigableString
                    if isinstance(element, NavigableString):
                        new_soup = BeautifulSoup(highlighted_text, 'html.parser')
                        element.replace_with(new_soup)

                    # Only highlight first occurrence
                    break

        result = str(soup)

    return Markup(result)
