"""
Flask routes for the human review interface.

Handles page rendering and navigation for reviewing metric extraction candidates.
API endpoints for AJAX decision submission are in api.py.
"""

import logging
from datetime import datetime
from decimal import Decimal

# Import needed for type annotations
from typing import TypedDict

import nh3
from flask import Blueprint, flash, g, redirect, request, url_for
from markupsafe import Markup, escape

from src.web.app import get_db
from src.web.middleware import insert_audit_log_entry, register_timing
from src.web.utils import _validate_positive_int  # noqa: F401 (re-exported for callers)

# Allowed HTML tags and attributes for sanitizing SEC filing HTML before rendering.
# Preserves table structure and formatting while stripping scripts and event handlers.
_SEC_HTML_ALLOWED_TAGS = frozenset(
    {
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        "col",
        "colgroup",
        "caption",
        "div",
        "span",
        "p",
        "br",
        "b",
        "i",
        "em",
        "strong",
        "u",
        "sub",
        "sup",
        "font",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "a",
    }
)
_SEC_HTML_ALLOWED_ATTRS: dict[str, set[str]] = {
    "*": {"class", "style", "id", "colspan", "rowspan", "align", "valign", "width", "height"},
    "a": {"href", "class", "style"},
}

review_bp = Blueprint("review", __name__)
logger = logging.getLogger(__name__)

register_timing(review_bp)


@review_bp.after_request
def _log_request_complete(response):
    """
    Log request details to the audit log table after each review page request.

    Extracts filing_id and candidate_id from URL path parameters or query string.
    """
    filing_id = request.view_args.get("filing_id") if request.view_args else None
    candidate_id = request.view_args.get("candidate_id") if request.view_args else None

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

    return insert_audit_log_entry(
        response,
        filing_id=filing_id,
        candidate_id=candidate_id,
        query_params=dict(request.args) if request.args else None,
    )


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
    extraction_date: datetime  # When candidates were extracted (MIN created_at)


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
    segment_html_table_only: (
        str | None
    )  # Table HTML preserved for dual display when value is truncated
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
    """Redirect root to V2 filing list."""
    return redirect(url_for("review_unified.filing_list"))


@review_bp.route("/filings")
def filing_list():
    """Redirect to unified filing list."""
    return redirect(url_for("review_unified.filing_list"), 301)


@review_bp.route("/review/<int:filing_id>")
def review_filing(filing_id: int):
    """Redirect to unified review (text tab)."""
    return redirect(url_for("review_unified.review_filing", filing_id=filing_id, tab="text"), 301)


@review_bp.route("/stats")
def stats():
    """Redirect to unified stats."""
    return redirect(url_for("review_unified.stats"), 301)


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
            url_for("review.review_filing", filing_id=filing_id, candidate_id=candidate_id)
        )

    except Exception as e:
        logger.error(f"Error jumping to candidate: {e}")
        flash("Error loading candidate.", "danger")
        return redirect(url_for("review.filing_list"))


# =============================================================================
# Helper Functions
# =============================================================================

# _validate_positive_int is imported from src.web.utils (re-exported at module top).


def _paginate(page: int = 1, per_page: int = 50, total_count: int | None = None) -> PaginationData:
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
    candidates: list[CandidateData], requested_id: int | None
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


def _calculate_review_progress(candidates: list[CandidateData]) -> tuple[int, int, int]:
    """
    Calculate review progress from a list of candidates.

    Args:
        candidates: List of candidates with review_status field

    Returns:
        Tuple of (total_candidates, reviewed_count, pending_count)
    """
    total_candidates = len(candidates)
    reviewed_count = sum(1 for c in candidates if c["review_status"] == "reviewed")
    pending_count = sum(1 for c in candidates if c["review_status"] == "pending")

    return total_candidates, reviewed_count, pending_count


def _extract_decision_from_candidate(candidate: CandidateData | None) -> DecisionData | None:
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
    db_status = (
        filter_status
        if filter_status in ("pending", "reviewed", "skipped", "in_progress")
        else None
    )
    db_metric_id = filter_metric if filter_metric != "all" else None
    db_confidence = filter_confidence if filter_confidence in ("high", "medium", "low") else None
    db_sort_by = (
        sort_by
        if sort_by in ("position", "confidence_asc", "confidence_desc", "value_asc", "value_desc")
        else "position"
    )

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

    Ordering is generated dynamically from METRIC_DISPLAY_ORDER dict - the single source
    of truth for dropdown ordering. See _build_metric_order_clause() for SQL generation.

    Returns:
        List[MetricData]: Active metrics with metric_id, display_name, metric_class, primary_concept
    """
    if "metrics" not in g:
        db = get_db()
        # Build ORDER BY clause from METRIC_DISPLAY_ORDER (single source of truth)
        order_clause = _build_metric_order_clause()
        metrics_sql = f"""
            SELECT metric_id, display_name, metric_class, primary_concept
            FROM metrics
            WHERE status = 'active'
            ORDER BY {order_clause}
        """
        g.metrics = db.query(metrics_sql)

    return g.metrics


# Metric ordering for dropdowns - semantic grouping by business category.
# This is the SINGLE SOURCE OF TRUTH for dropdown ordering.
# The SQL CASE statement is generated dynamically from this dict.
#
# ORDERING CONVENTION:
#   - Category 1 (Customer Counts): 1-9
#   - Category 2 (Transactions): 11-19
#   - Category 3 (Revenue): 21-29
#   - Category 4 (Retention/Churn): 31-39
#   - Category 5 (Unit Economics): 41-49
#   Gaps allow inserting new metrics without renumbering existing ones.
#
# SAFETY: These IDs are used in f-string SQL generation. This is safe because
# they are hardcoded constants. Never add user-supplied values to this dict.
METRIC_DISPLAY_ORDER: dict[str, int] = {
    # Category 1: Customer Count Metrics (1-9)
    "cm_customers_period_end": 1,
    "cm_active_customers_total": 2,
    "cm_daily_active_users": 3,
    "cm_monthly_active_users": 4,
    "cm_large_customers_period_end": 5,
    "cm_new_customers_acquired": 6,
    "cm_customers_period_end_by_tenure": 7,
    # Category 2: Transaction & Purchase Behavior (11-19)
    "cm_purchase_transactions_overall": 11,
    "cm_transactions_by_cohort": 12,
    "cm_repeat_purchase_rate": 13,
    "cm_average_order_value": 14,
    # Category 3: Revenue Metrics (21-29)
    "cm_arr": 21,
    "cm_mrr": 22,
    "cm_revenue_per_customer": 23,
    "cm_revenue_by_cohort": 24,
    "cm_gross_margin_by_cohort": 25,
    "cm_expansion_revenue": 26,
    "cm_revenue_concentration": 27,
    # Category 4: Retention, Churn & Attrition (31-39)
    "cm_net_revenue_retention": 31,
    "cm_gross_revenue_retention": 32,
    "cm_customer_churn_rate": 33,
    "cm_customer_retention_rate": 34,
    # Category 5: Unit Economics & CAC (41-49)
    "cm_lifetime_value_per_customer": 41,
    "cm_customer_acquisition_cost": 42,
    "cm_ltv_to_cac_ratio": 43,
    "cm_ltv_to_cac_ratio_by_cohort": 44,
    "cm_cac_payback_period": 45,
}


def _build_metric_order_clause() -> str:
    """
    Build SQL CASE statement for metric ordering from METRIC_DISPLAY_ORDER.

    Returns:
        SQL CASE expression string for ORDER BY clause.

    SAFETY NOTE: This uses f-string SQL building which is safe ONLY because
    metric_ids are hardcoded constants from METRIC_DISPLAY_ORDER, never user input.
    DO NOT copy this pattern for user-supplied values.
    """
    clauses = [
        f"WHEN '{metric_id}' THEN {order}" for metric_id, order in METRIC_DISPLAY_ORDER.items()
    ]
    return "CASE metric_id\n" + "\n".join(clauses) + "\nELSE 99\nEND"


def _get_unique_metrics_for_filing(candidates: list[dict]) -> list[str]:
    """
    Extract unique metric IDs from candidates for filter dropdown.

    Args:
        candidates: List of candidate dicts with suggested_metric_id

    Returns:
        List of unique metric IDs sorted by semantic business grouping
        (same ordering as reclassify dropdown for consistency)
    """
    unique_metrics = set()
    for candidate in candidates:
        metric_id = candidate.get("suggested_metric_id")
        if metric_id:
            unique_metrics.add(metric_id)
    # Sort by semantic grouping order, unknown metrics at end
    return sorted(unique_metrics, key=lambda m: METRIC_DISPLAY_ORDER.get(m, 99))


def _highlight_context(context_text: str, raw_number_text: str, triggering_keyword: str) -> Markup:
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
        number = safe_text[num_idx : num_idx + len(safe_number)]
        after = safe_text[num_idx + len(safe_number) :]
        safe_text = before + f'<mark class="extracted-number">{number}</mark>' + after
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
        actual_keyword = safe_text[kw_idx : kw_idx + len(triggering_keyword)]
        before = safe_text[:kw_idx]
        after = safe_text[kw_idx + len(triggering_keyword) :]
        safe_text = before + f'<u class="triggering-keyword">{actual_keyword}</u>' + after

    return Markup(safe_text)


def _highlight_html(html_content: str, raw_number_text: str, triggering_keyword: str) -> Markup:
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

    # Sanitize SEC HTML to strip scripts and event handlers before rendering.
    # Preserves table structure and text formatting used in SEC filings.
    html_content = nh3.clean(
        html_content,
        tags=_SEC_HTML_ALLOWED_TAGS,
        attributes=_SEC_HTML_ALLOWED_ATTRS,
        strip_comments=True,
    )

    # Parse HTML with BeautifulSoup to fix any truncated/unclosed tags
    # This is critical because segment_html may be cut off mid-tag
    soup = BeautifulSoup(html_content, "html.parser")
    result = str(soup)

    # Highlight the number (case-sensitive exact match)
    # Use word boundary to avoid partial matches
    if raw_number_text:
        escaped_number = re.escape(raw_number_text)
        result = re.sub(
            f"({escaped_number})",
            r'<mark class="extracted-number">\1</mark>',
            result,
            count=1,  # Only highlight first occurrence
        )

    # Highlight the keyword (case-insensitive)
    # Use BeautifulSoup to search text nodes to handle keywords split across HTML tags
    if triggering_keyword:
        soup = BeautifulSoup(result, "html.parser")
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
                    actual_keyword = text[idx : idx + len(triggering_keyword)]

                    # Create highlighted version
                    highlighted_text = (
                        text[:idx]
                        + f'<u class="triggering-keyword">{actual_keyword}</u>'
                        + text[idx + len(triggering_keyword) :]
                    )

                    # Replace the text node with highlighted version
                    # BeautifulSoup will parse the HTML we inject
                    from bs4 import NavigableString

                    if isinstance(element, NavigableString):
                        new_soup = BeautifulSoup(highlighted_text, "html.parser")
                        element.replace_with(new_soup)

                    # Only highlight first occurrence
                    break

        result = str(soup)

    return Markup(result)
