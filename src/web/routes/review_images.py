"""
Flask routes for the image review interface.

Handles page rendering and navigation for reviewing image candidates
(charts, cohort tables, etc.) detected in SEC filings.

API endpoints for AJAX decision submission are in api_images.py.
"""

import logging
from typing import TypedDict

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

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

review_images_bp = Blueprint("review_images", __name__, url_prefix="/review/images")
logger = logging.getLogger(__name__)


# =============================================================================
# Template Data Contracts (TypedDict)
# =============================================================================


class ImageFilingListItem(TypedDict):
    """Structure of a filing item in the image filing list."""

    filing_id: int
    accession_number: str
    form_type: str
    filing_date: str
    company_name: str
    cik: str
    total_candidates: int
    pending_count: int
    reviewed_count: int
    skipped_count: int
    first_candidate_date: str


class ImagePaginationData(TypedDict, total=False):
    """Pagination metadata for image filing list."""

    page: int
    per_page: int
    offset: int
    limit: int
    total_count: int
    total_pages: int
    has_prev: bool
    has_next: bool


class ImageReviewProgress(TypedDict, total=False):
    """Overall image review progress statistics."""

    total_candidates: int
    pending_count: int
    reviewed_count: int
    skipped_count: int
    review_pct: float
    total_filings: int
    filings_with_pending: int
    by_tier: dict


# =============================================================================
# Page Routes
# =============================================================================


@review_images_bp.route("/")
def index():
    """Redirect root to filing list."""
    return redirect(url_for("review_images.filing_list"))


@review_images_bp.route("/filings")
def filing_list():
    """Display list of filings with image candidates."""
    db = get_db()

    # Get pagination parameters
    page_raw = request.args.get("page", type=int)
    per_page_raw = request.args.get("per_page", type=int)

    # Validate pagination
    page = _validate_positive_int("page", page_raw, default=1, min_value=1)
    per_page = _validate_positive_int(
        "per_page", per_page_raw, default=50, min_value=1, max_value=100
    )

    # Get status filter
    status = request.args.get("status")
    if status and status not in IMAGE_REVIEW_STATUSES:
        flash(f"Invalid status filter: {status}", "warning")
        status = None

    try:
        # Get total count for pagination
        total_count = db.get_filings_with_image_candidates_count(status=status)

        # Calculate pagination
        pagination = _paginate(page=page, per_page=per_page, total_count=total_count)

        # Validate page doesn't exceed total_pages
        if total_count > 0 and page > pagination["total_pages"]:
            flash(
                f"Page {page} does not exist. Showing page 1 of {pagination['total_pages']}.",
                "warning",
            )
            return redirect(
                url_for("review_images.filing_list", status=status, per_page=per_page)
            )

        # Get filings for current page
        filings = db.get_filings_with_image_candidates(
            status=status, limit=pagination["limit"], offset=pagination["offset"]
        )

        # Get overall progress
        progress = db.get_image_review_progress()

    except Exception as e:
        logger.error(f"Database error in image filing_list: {e}")
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
            "by_tier": {},
        }
        pagination = _paginate(page=1, per_page=50, total_count=0)

    # Handle empty results
    if not filings and page == 1:
        flash(
            "No filings with image candidates found. Generate candidates first.", "info"
        )

    return render_template(
        "image_filing_list.html",
        filings=filings,
        progress=progress,
        current_status_filter=status,
        review_statuses=IMAGE_REVIEW_STATUSES,
        pagination=pagination,
    )


@review_images_bp.route("/<int:filing_id>")
def review_filing(filing_id: int):
    """Main image review interface for a filing."""
    db = get_db()

    # Get filing metadata (outside try block to let 404 propagate)
    filing = _get_filing_data(db, filing_id)
    if not filing:
        abort(404)

    try:

        # Get filter and sort parameters
        filter_status = request.args.get("status", "all")
        sort_by = request.args.get("sort", "tier")

        # Validate filter values
        db_status = filter_status if filter_status in IMAGE_REVIEW_STATUSES else None
        db_sort = sort_by if sort_by in ("tier", "confidence", "position") else "tier"

        # Get all candidates (unfiltered) for progress calculation
        all_candidates = db.get_image_review_candidates_for_filing(
            filing_id=filing_id, limit=1000
        )

        if not all_candidates:
            flash("This filing has no image candidates.", "info")
            return redirect(url_for("review_images.filing_list"))

        # Get filtered candidates for sidebar
        candidates = db.get_image_review_candidates_for_filing(
            filing_id=filing_id,
            status=db_status,
            sort_by=db_sort,
            limit=1000,
        )

        # Get requested candidate_id
        candidate_id_param = _validate_positive_int(
            "image_candidate_id",
            request.args.get("image_candidate_id", type=int),
            default=None,
            min_value=1,
            flash_errors=False,
        )

        # Select current candidate
        current_candidate = _select_current_candidate(candidates, candidate_id_param)

        if not current_candidate:
            # No candidates match filters
            flash("No candidates match your filters.", "warning")
            return redirect(url_for("review_images.review_filing", filing_id=filing_id))

        # Calculate progress from all candidates
        progress = _calculate_progress(all_candidates)

        # Build current_filters dict
        has_active_filters = filter_status != "all" or sort_by != "tier"
        current_filters = {
            "status": filter_status,
            "sort": sort_by,
            "has_active_filters": has_active_filters,
        }

        # Build chart_types and rejection_reasons for dropdowns from models.py
        chart_types = [
            (ct, IMAGE_CHART_TYPE_LABELS[ct]) for ct in IMAGE_CHART_TYPES
        ]
        rejection_reasons = [
            (rr, IMAGE_REJECTION_REASON_LABELS[rr]) for rr in IMAGE_REJECTION_REASONS
        ]

        return render_template(
            "review_images.html",
            filing=filing,
            current_candidate=current_candidate,
            candidates=candidates,
            all_candidates=all_candidates,
            progress=progress,
            current_filters=current_filters,
            chart_types=chart_types,
            rejection_reasons=rejection_reasons,
            image_decisions=IMAGE_DECISIONS,
            review_statuses=IMAGE_REVIEW_STATUSES,
        )

    except Exception as e:
        logger.error(f"Error in review_filing for filing_id={filing_id}: {e}")
        flash("Error loading filing. Please try again.", "danger")
        return redirect(url_for("review_images.filing_list"))


@review_images_bp.route("/<int:filing_id>/next")
def next_candidate(filing_id: int):
    """Navigate to next pending candidate."""
    db = get_db()

    current_id_raw = request.args.get("current", type=int)
    current_id = _validate_positive_int(
        "current", current_id_raw, default=None, min_value=1, flash_errors=False
    )

    try:
        # Get next pending candidate
        next_cand = db.get_next_pending_image_candidate(
            filing_id=filing_id, current_candidate_id=current_id
        )

        if next_cand:
            return redirect(
                url_for(
                    "review_images.review_filing",
                    filing_id=filing_id,
                    image_candidate_id=next_cand["image_candidate_id"],
                )
            )
        else:
            flash("All image candidates for this filing have been reviewed!", "success")
            return redirect(url_for("review_images.filing_list"))

    except Exception as e:
        logger.error(f"Error navigating to next image candidate: {e}")
        flash("Error loading next candidate.", "danger")
        return redirect(url_for("review_images.filing_list"))


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
        value: The value to validate
        default: Default value on validation failure
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        flash_errors: Whether to flash validation errors

    Returns:
        Validated integer or default
    """
    if value is None:
        return default

    if value < min_value:
        if flash_errors:
            flash(
                f"Invalid {param_name}: must be at least {min_value}. Using default: {default}",
                "warning",
            )
        return default

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
) -> ImagePaginationData:
    """
    Calculate pagination metadata.

    Args:
        page: Current page number (1-indexed)
        per_page: Items per page
        total_count: Total number of items

    Returns:
        Pagination dict with offset, limit, total_pages, etc.
    """
    page = max(1, page)
    per_page = max(1, min(100, per_page))
    offset = (page - 1) * per_page

    result: ImagePaginationData = {
        "page": page,
        "per_page": per_page,
        "offset": offset,
        "limit": per_page,
    }

    if total_count is not None:
        result["total_count"] = total_count
        result["total_pages"] = (total_count + per_page - 1) // per_page if total_count > 0 else 1
        result["has_prev"] = page > 1
        result["has_next"] = page < result["total_pages"]

    return result


def _get_filing_data(db: DatabaseAdapter, filing_id: int) -> dict | None:
    """
    Get filing metadata with company info.

    Args:
        db: Database adapter
        filing_id: Filing to retrieve

    Returns:
        Filing dict with sec_url added, or None if not found
    """
    sql = """
        SELECT f.*, c.company_name, c.cik
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.filing_id = %(filing_id)s
    """
    results = db.query(sql, {"filing_id": filing_id})

    if not results:
        return None

    filing = dict(results[0])

    # Build SEC directory URL for image links
    filing["sec_url"] = _build_sec_filing_url(
        cik=filing.get("cik", ""),
        accession_number=filing.get("accession_number", ""),
    )

    return filing


def _build_sec_filing_url(cik: str, accession_number: str) -> str:
    """
    Build URL to SEC EDGAR filing directory.

    For image review, we only need the directory URL since we're
    linking to images, not the primary document.

    Args:
        cik: Company CIK (will be normalized)
        accession_number: SEC accession number (with dashes)

    Returns:
        URL to SEC EDGAR filing directory
    """
    acc_no_dashes = accession_number.replace("-", "")
    cik_stripped = cik.lstrip("0") or "0"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_no_dashes}/"


def _select_current_candidate(
    candidates: list[dict], requested_id: int | None
) -> dict | None:
    """
    Select the current candidate to display.

    Logic:
    1. If requested_id provided and found → return that candidate
    2. If requested_id not found → flash warning, return first pending
    3. If no requested_id → return first pending
    4. If no pending → return first candidate

    Args:
        candidates: List of candidates for the filing
        requested_id: Candidate ID from query parameter

    Returns:
        Selected candidate, or None if list is empty
    """
    if not candidates:
        return None

    if requested_id:
        current = next(
            (c for c in candidates if c["image_candidate_id"] == requested_id),
            None,
        )
        if current:
            return current
        flash("Candidate not found, showing first pending", "warning")

    # Return first pending, or first candidate if none pending
    return next(
        (c for c in candidates if c["review_status"] == "pending"),
        candidates[0],
    )


def _calculate_progress(candidates: list[dict]) -> dict:
    """
    Calculate review progress from candidate list.

    Args:
        candidates: List of candidates with review_status

    Returns:
        Progress dict with total, pending, reviewed, skipped counts
    """
    total = len(candidates)
    pending = sum(1 for c in candidates if c["review_status"] == "pending")
    reviewed = sum(1 for c in candidates if c["review_status"] == "reviewed")
    skipped = sum(1 for c in candidates if c["review_status"] == "skipped")

    return {
        "total": total,
        "pending": pending,
        "reviewed": reviewed,
        "skipped": skipped,
    }
