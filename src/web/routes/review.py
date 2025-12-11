"""
Flask routes for the human review interface.

Handles page rendering and navigation for reviewing metric extraction candidates.
API endpoints for AJAX decision submission are in api.py.
"""

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional, Tuple, TypedDict

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for, session
from markupsafe import Markup, escape

from src.review.models import (
    DECISION_TYPES,
    REJECTION_CATEGORIES,
    REVIEW_STATUSES,
)
from src.web.app import get_db

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
    total_pages: Optional[int]
    html_fetched: bool
    created_at: datetime
    updated_at: datetime


class CandidateData(TypedDict, total=False):
    """Structure of a review candidate with optional decision fields.

    Used by: review.html (in candidates array and current_candidate)

    Note: Uses total=False because decision fields (decision_id, decision, etc.)
    are only present when a candidate has been reviewed.
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
    parsed_unit: Optional[str]
    suggested_metric_id: str
    suggestion_confidence: float
    review_status: str  # 'pending', 'reviewed', 'skipped'
    created_at: datetime

    # Decision fields (present only if reviewed - from LEFT JOIN)
    decision_id: Optional[int]
    decision: Optional[str]  # 'accept', 'reject', 'reclassify'
    assigned_metric_id: Optional[str]
    rejection_category: Optional[str]
    rejection_reason: Optional[str]
    reviewer_notes: Optional[str]
    reviewer_id: Optional[str]
    review_time_seconds: Optional[int]
    decision_created_at: Optional[datetime]


class DecisionData(TypedDict):
    """Existing decision data for a reviewed candidate.

    Used by: review.html (existing_decision)
    """
    decision_id: int
    decision: str  # 'accept', 'reject', 'reclassify'
    assigned_metric_id: Optional[str]
    rejection_category: Optional[str]
    rejection_reason: Optional[str]
    reviewer_notes: Optional[str]
    reviewer_id: Optional[str]
    review_time_seconds: Optional[int]
    created_at: Optional[datetime]


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

        filing = filing_result[0]

        # Get all candidates for this filing WITH their decisions (single query)
        candidates = db.get_review_candidates_with_decisions(
            filing_id=filing_id, limit=None  # Get all
        )

        # Get active metrics for reclassify dropdown
        metrics = _get_active_metrics()

        # Validate and get candidate_id parameter
        candidate_id_raw = request.args.get("candidate_id", type=int)
        candidate_id_param = _validate_positive_int(
            "candidate_id", candidate_id_raw, default=None, min_value=1, flash_errors=False
        )

        # Select current candidate using extracted helper
        current_candidate = _select_current_candidate(candidates, candidate_id_param)

        # Calculate progress using extracted helper
        total_candidates, reviewed_count, pending_count = _calculate_review_progress(candidates)

        # Extract decision from current candidate using extracted helper
        existing_decision = _extract_decision_from_candidate(current_candidate)

        # Render template with documented data contract
        # Template: review.html
        # Data contract:
        #   - filing: FilingData - Filing metadata (company, accession, etc.)
        #   - candidates: List[CandidateData] - All candidates for this filing
        #   - current_candidate: CandidateData | None - Candidate currently being reviewed
        #   - existing_decision: DecisionData | None - Existing decision if already reviewed
        #   - metrics: List[MetricData] - Active metrics for reclassify dropdown
        #   - decision_types: Tuple[str, str, str] - Valid decision types ('accept', 'reject', 'reclassify')
        #   - rejection_categories: Tuple[str, ...] - Valid rejection categories
        #   - total_candidates: int - Total number of candidates for this filing
        #   - pending_count: int - Number of pending candidates
        #   - reviewed_count: int - Number of reviewed candidates
        return render_template(
            "review.html",
            filing=filing,
            candidates=candidates,
            current_candidate=current_candidate,
            existing_decision=existing_decision,
            metrics=metrics,
            decision_types=DECISION_TYPES,
            rejection_categories=REJECTION_CATEGORIES,
            total_candidates=total_candidates,
            pending_count=pending_count,
            reviewed_count=reviewed_count,
        )

    except Exception as e:
        logger.error(f"Error in review_filing for filing_id={filing_id}: {e}")
        flash("Error loading filing. Please try again.", "danger")
        return redirect(url_for("review.filing_list"))


# =============================================================================
# Navigation Routes
# =============================================================================

@review_bp.route("/review/<int:filing_id>/next")
def next_candidate(filing_id: int):
    """Navigate to next pending candidate."""
    db = get_db()
    current_id_raw = request.args.get("current_id", type=int)

    # Validate current_id if provided
    current_id = _validate_positive_int(
        "current_id", current_id_raw, default=None, min_value=1, flash_errors=False
    )

    try:
        # Find next candidate using extracted helper
        next_cand = _find_next_candidate(db, filing_id, current_id)

        if next_cand:
            return redirect(
                url_for(
                    "review.review_filing",
                    filing_id=filing_id,
                    candidate_id=next_cand["candidate_id"],
                )
            )
        else:
            flash("All candidates reviewed for this filing!", "success")
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
    value: Optional[int],
    default: Optional[int],
    min_value: int = 1,
    max_value: Optional[int] = None,
    flash_errors: bool = True,
) -> Optional[int]:
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
    page: int = 1, per_page: int = 50, total_count: Optional[int] = None
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
    candidates: List[CandidateData],
    requested_id: Optional[int]
) -> Optional[CandidateData]:
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
    candidates: List[CandidateData]
) -> Tuple[int, int, int]:
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
    candidate: Optional[CandidateData]
) -> Optional[DecisionData]:
    """
    Extract decision data from a candidate record.

    Candidates from get_review_candidates_with_decisions() include decision fields
    from a LEFT JOIN. This function extracts those fields into a separate dict.

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
    }


def _find_next_candidate(
    db,
    filing_id: int,
    current_id: Optional[int]
) -> Optional[Dict]:
    """
    Find the next pending candidate for a filing.

    Logic:
    - If current_id provided: Find first pending candidate with ID > current_id
    - If no current_id: Use db.get_next_candidate_for_review() to get first pending

    Args:
        db: Database adapter instance
        filing_id: Filing ID to search within
        current_id: Current candidate ID to search after (or None)

    Returns:
        Next candidate dict, or None if no more pending candidates
    """
    if current_id:
        # Get all pending candidates and find first with ID > current_id
        candidates = db.get_review_candidates_for_filing(
            filing_id=filing_id, status="pending"
        )
        return next(
            (c for c in candidates if c["candidate_id"] > current_id),
            None
        )
    else:
        # Use database method to get first pending
        return db.get_next_candidate_for_review(filing_id=filing_id)


def _get_active_metrics() -> List[MetricData]:
    """
    Get list of active metrics for dropdown.

    Cached in Flask g object to avoid repeated queries.
    Returns list sorted by class (core first) then name.

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
                CASE metric_class
                    WHEN 'core' THEN 1
                    WHEN 'extended' THEN 2
                    ELSE 3
                END,
                display_name
        """
        g.metrics = db.query(metrics_sql)

    return g.metrics


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
