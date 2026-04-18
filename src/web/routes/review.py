"""
Thin redirect shim for legacy V1 review URLs.

All V1 review pages have been retired. These handlers 301-redirect to the
V2 unified interface (`src/web/routes/review_unified.py`) so existing
bookmarks continue to work.
"""

import logging

from flask import Blueprint, redirect, request, url_for

from src.web.middleware import insert_audit_log_entry, register_timing

review_bp = Blueprint("review", __name__)
logger = logging.getLogger(__name__)

register_timing(review_bp)


@review_bp.after_request
def _log_request_complete(response):
    """Log redirect requests to the audit log table."""
    filing_id = request.view_args.get("filing_id") if request.view_args else None

    if filing_id is None and "filing_id" in request.args:
        try:
            filing_id = int(request.args["filing_id"])
        except (ValueError, TypeError):
            pass

    return insert_audit_log_entry(
        response,
        filing_id=filing_id,
        query_params=dict(request.args) if request.args else None,
    )


@review_bp.route("/")
def index():
    """Redirect root to V2 filing list."""
    return redirect(url_for("review_unified.filing_list"), 301)


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
