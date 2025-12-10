"""
JSON API endpoints for human review system.

Handles AJAX requests from the review interface for recording decisions
and fetching candidate data. All endpoints return JSON responses.
"""

import logging
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from src.review.models import (
    DECISION_TYPES,
    REJECTION_CATEGORIES,
)
from src.web.app import get_db

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


# =============================================================================
# Decision Recording
# =============================================================================


@api_bp.route("/decisions", methods=["POST"])
def create_decision():
    """
    Record a review decision (accept/reject/reclassify).

    Request Body:
        {
            "candidate_id": int,
            "decision": "accept" | "reject" | "reclassify",
            "assigned_metric_id": str (required for accept/reclassify),
            "rejection_category": str (required for reject),
            "rejection_reason": str (optional),
            "reviewer_notes": str (optional),
            "review_time_seconds": int (optional)
        }

    Returns:
        201: Decision created successfully
        {
            "status": "success",
            "decision_id": int,
            "candidate_id": int,
            "next_candidate": {
                "candidate_id": int,
                "url": str
            } | null
        }

        400: Validation errors
        {
            "status": "error",
            "errors": {
                "field_name": "Error message"
            }
        }

        404: Candidate not found
        {
            "status": "error",
            "message": "Candidate not found"
        }

        409: Candidate already has a decision
        {
            "status": "error",
            "message": "Candidate already has a decision",
            "existing_decision_id": int
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Parse request JSON
        if not request.is_json:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Request must be JSON",
                    }
                ),
                400,
            )

        data = request.get_json()

        # Validate request
        errors = _validate_decision_request(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # Extract fields
        candidate_id = data["candidate_id"]
        decision = data["decision"]
        assigned_metric_id = data.get("assigned_metric_id")
        rejection_category = data.get("rejection_category")
        rejection_reason = data.get("rejection_reason")
        reviewer_notes = data.get("reviewer_notes")
        review_time_seconds = data.get("review_time_seconds")

        # Validate candidate exists
        candidate = db.get_review_candidate(candidate_id)
        if not candidate:
            logger.warning(f"Candidate not found: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate not found",
                    }
                ),
                404,
            )

        # Check for existing decision
        existing = db.get_decision_for_candidate(candidate_id)
        if existing:
            logger.warning(
                f"Candidate {candidate_id} already has decision {existing['decision_id']}"
            )
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate already has a decision",
                        "existing_decision_id": existing["decision_id"],
                    }
                ),
                409,
            )

        # Begin transaction (implicit - will commit on success, rollback on exception)
        # Note: Metric ID validity will be checked by foreign key constraint
        # Insert decision (this also updates candidate status atomically in same transaction)
        decision_id = db.insert_review_decision(
            candidate_id=candidate_id,
            decision=decision,
            assigned_metric_id=assigned_metric_id,
            rejection_category=rejection_category,
            rejection_reason=rejection_reason,
            reviewer_notes=reviewer_notes,
            review_time_seconds=review_time_seconds,
        )

        # Status update happens atomically inside insert_review_decision()
        # No need for separate update call - this ensures true atomicity

        # Transaction commits automatically if no exceptions

        logger.info(
            f"Created decision {decision_id} for candidate {candidate_id}: {decision}"
        )

        # Get next candidate (outside transaction - read-only)
        filing_id = candidate["filing_id"]
        next_cand = _get_next_candidate_info(db, filing_id, candidate_id)

        return (
            jsonify(
                {
                    "status": "success",
                    "decision_id": decision_id,
                    "candidate_id": candidate_id,
                    "next_candidate": next_cand,
                }
            ),
            201,
        )

    except Exception as e:
        logger.error(f"Error creating decision: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                }
            ),
            500,
        )


# =============================================================================
# Candidate Retrieval (Future Enhancement)
# =============================================================================


@api_bp.route("/candidates/<int:candidate_id>", methods=["GET"])
def get_candidate(candidate_id: int):
    """
    Get candidate details.

    Future enhancement for dynamic loading.

    Args:
        candidate_id: Candidate ID

    Returns:
        200: Candidate details
        404: Candidate not found
    """
    # Future enhancement
    return (
        jsonify(
            {
                "status": "error",
                "message": "Not implemented",
            }
        ),
        501,
    )


# =============================================================================
# Progress Tracking (Future Enhancement)
# =============================================================================


@api_bp.route("/filings/<int:filing_id>/progress", methods=["GET"])
def get_filing_progress(filing_id: int):
    """
    Get review progress for a filing.

    Future enhancement for live progress updates.

    Args:
        filing_id: Filing ID

    Returns:
        200: Progress statistics
        404: Filing not found
    """
    # Future enhancement
    return (
        jsonify(
            {
                "status": "error",
                "message": "Not implemented",
            }
        ),
        501,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _validate_decision_request(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate decision request data.

    Args:
        data: Request JSON data

    Returns:
        Dict of field_name -> error message
        Empty dict if validation passes
    """
    errors: Dict[str, str] = {}

    # Required: candidate_id
    candidate_id = data.get("candidate_id")
    if candidate_id is None:
        errors["candidate_id"] = "Required field"
    elif not isinstance(candidate_id, int) or candidate_id <= 0:
        errors["candidate_id"] = "Must be a positive integer"

    # Required: decision
    decision = data.get("decision")
    if not decision:
        errors["decision"] = "Required field"
    elif decision not in DECISION_TYPES:
        errors["decision"] = (
            f"Must be one of: {', '.join(DECISION_TYPES)}. Got: {decision}"
        )
    else:
        # Decision-specific validation
        if decision in ("accept", "reclassify"):
            # Require assigned_metric_id
            assigned_metric_id = data.get("assigned_metric_id")
            if not assigned_metric_id:
                errors["assigned_metric_id"] = (
                    f"Required for {decision} decision"
                )
            elif not isinstance(assigned_metric_id, str):
                errors["assigned_metric_id"] = "Must be a string"

        elif decision == "reject":
            # Require rejection_category
            rejection_category = data.get("rejection_category")
            if not rejection_category:
                errors["rejection_category"] = "Required for reject decision"
            elif rejection_category not in REJECTION_CATEGORIES:
                errors["rejection_category"] = (
                    f"Must be one of: {', '.join(REJECTION_CATEGORIES)}. "
                    f"Got: {rejection_category}"
                )

            # Optional: rejection_reason (max 500 chars)
            rejection_reason = data.get("rejection_reason")
            if rejection_reason and len(rejection_reason) > 500:
                errors["rejection_reason"] = "Must be 500 characters or less"

    # Optional: reviewer_notes (max 1000 chars)
    reviewer_notes = data.get("reviewer_notes")
    if reviewer_notes and len(reviewer_notes) > 1000:
        errors["reviewer_notes"] = "Must be 1000 characters or less"

    # Optional: review_time_seconds
    review_time_seconds = data.get("review_time_seconds")
    if review_time_seconds is not None:
        if not isinstance(review_time_seconds, int) or review_time_seconds < 0:
            errors["review_time_seconds"] = "Must be a non-negative integer"

    return errors


def _get_next_candidate_info(
    db, filing_id: int, current_candidate_id: int
) -> Optional[Dict[str, Any]]:
    """
    Get next pending candidate for the same filing.

    Args:
        db: Database adapter
        filing_id: Filing ID
        current_candidate_id: Current candidate ID

    Returns:
        Dict with candidate_id and url, or None if no more pending
    """
    # Query for next pending candidate
    sql = """
        SELECT candidate_id
        FROM review_candidates
        WHERE filing_id = %(filing_id)s
          AND review_status = 'pending'
          AND candidate_id > %(current_candidate_id)s
        ORDER BY candidate_id ASC
        LIMIT 1
    """

    result = db.query(
        sql,
        {
            "filing_id": filing_id,
            "current_candidate_id": current_candidate_id,
        },
    )

    if not result:
        return None

    next_candidate_id = result[0]["candidate_id"]
    return {
        "candidate_id": next_candidate_id,
        "url": f"/review/{filing_id}/candidate/{next_candidate_id}",
    }
