"""
Flask routes for the human review interface.

Handles page rendering and navigation for reviewing metric extraction candidates.
API endpoints for AJAX decision submission are in api.py.
"""

import logging

import nh3
from flask import Blueprint, flash, redirect, request, url_for
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
# Page Routes
# =============================================================================


@review_bp.route("/")
# DEPRECATED: V1 redirect, remove after 2026-07
def index():
    """Redirect root to V2 filing list."""
    return redirect(url_for("review_unified.filing_list"))


@review_bp.route("/filings")
# DEPRECATED: V1 redirect, remove after 2026-07
def filing_list():
    """Redirect to unified filing list."""
    return redirect(url_for("review_unified.filing_list"), 301)


@review_bp.route("/review/<int:filing_id>")
# DEPRECATED: V1 redirect, remove after 2026-07
def review_filing(filing_id: int):
    """Redirect to unified review (text tab)."""
    return redirect(url_for("review_unified.review_filing", filing_id=filing_id, tab="text"), 301)


@review_bp.route("/stats")
# DEPRECATED: V1 redirect, remove after 2026-07
def stats():
    """Redirect to unified stats."""
    return redirect(url_for("review_unified.stats"), 301)


# =============================================================================
# Navigation Routes
# =============================================================================


@review_bp.route("/review/<int:filing_id>/next")
def next_candidate(filing_id: int):
    """Navigate to next pending candidate, respecting active filters."""
    logger.warning(
        "V1 nav route '%s' accessed — should be unreachable post-V1-cutover", request.path
    )
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
    logger.warning(
        "V1 nav route '%s' accessed — should be unreachable post-V1-cutover", request.path
    )
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
    "cm_revenue_per_customer": 23,
    "cm_revenue_by_cohort": 24,
    "cm_gross_margin_by_cohort": 25,
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
