"""
Flask routes for the image review interface.

Handles page rendering and navigation for reviewing image candidates
(charts, cohort tables, etc.) detected in SEC filings.

API endpoints for AJAX decision submission are in api_images.py.
"""

import logging
from typing import TypedDict

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src.infra.db import DatabaseAdapter
from src.review.models import (
    IMAGE_CHART_TYPE_LABELS,
    IMAGE_REJECTION_REASON_LABELS,
)
from src.web.app import get_db
from src.web.utils import _validate_positive_int  # noqa: F401 (re-exported for callers)

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
    """Redirect to unified filing list."""
    return redirect(url_for("review_unified.filing_list"), 301)


@review_images_bp.route("/filings")
def filing_list():
    """Redirect to unified filing list."""
    return redirect(url_for("review_unified.filing_list"), 301)


@review_images_bp.route("/<int:filing_id>")
def review_filing(filing_id: int):
    """Redirect to unified review (images tab)."""
    return redirect(
        url_for("review_unified.review_filing", filing_id=filing_id, tab="images"), 301
    )


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


@review_images_bp.route("/stats")
def image_stats():
    """Display statistics dashboard for image review progress."""
    db = get_db()

    try:
        overall_stats = db.get_image_overall_decision_statistics()
        tier_stats = db.get_image_decision_statistics()
        daily_counts = db.get_image_daily_decision_counts(days=7)
        progress = db.get_image_review_progress()
        chart_type_stats = db.get_image_chart_type_distribution()
        rejection_stats = db.get_image_rejection_reason_stats()

        return render_template(
            "image_stats.html",
            overall_stats=overall_stats,
            tier_stats=tier_stats,
            daily_counts=daily_counts,
            progress=progress,
            chart_type_stats=chart_type_stats,
            rejection_stats=rejection_stats,
            chart_type_labels=IMAGE_CHART_TYPE_LABELS,
            rejection_reason_labels=IMAGE_REJECTION_REASON_LABELS,
        )

    except Exception as e:
        logger.error(f"Error loading image statistics dashboard: {e}")
        flash("Error loading statistics. Please try again.", "danger")
        return redirect(url_for("review_images.filing_list"))


# =============================================================================
# Helper Functions
# =============================================================================


# _validate_positive_int is imported from src.web.utils (re-exported at module top).

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
