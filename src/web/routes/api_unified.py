"""
Unified JSON API endpoints for V2 human review system.

Merges V2 text decision API (api_v2.py) and image decision API (api_images.py)
into a single blueprint under /api/v2. Also provides a new endpoint for
manually adding metric facts that the pipeline missed.
"""

import logging
from typing import Any

import psycopg
from flask import Blueprint, jsonify, request

from src.infra.validation import ValidationError
from src.review.models import (
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASONS,
)
from src.web.app import get_db
from src.web.middleware import insert_audit_log_entry, register_api_auth, register_timing

api_unified_bp = Blueprint("api_unified", __name__, url_prefix="/api/v2")
logger = logging.getLogger(__name__)

register_api_auth(api_unified_bp)
register_timing(api_unified_bp)

# Valid V2 decisions
V2_DECISION_TYPES = ("accept", "reject", "correct")

V2_REJECTION_CATEGORIES = (
    "wrong_metric",
    "not_a_metric",
    "wrong_value",
    "wrong_period",
    "part_of_date",
    "duplicate",
    "other",
)

VALID_UNITS = ("percent", "currency", "count", "ratio", "basis_points", "other")


@api_unified_bp.after_request
def _log_request_complete(response):
    query_params = None

    if request.method == "POST" and request.is_json:
        data = request.get_json(silent=True) or {}
        query_params = {}
        if "fact_id" in data:
            query_params["fact_id"] = data["fact_id"]
        if "decision" in data:
            query_params["decision"] = data["decision"]
        if "rejection_category" in data:
            query_params["rejection_category"] = data["rejection_category"]
        if not query_params:
            query_params = None

    return insert_audit_log_entry(response, query_params=query_params)


# =============================================================================
# Text Decision Recording (from api_v2.py)
# =============================================================================


@api_unified_bp.route("/decisions", methods=["POST"])
def create_decision():
    """
    Record a V2 review decision (accept/reject/correct).

    Request Body:
        {
            "fact_id": str (UUID),
            "decision": "accept" | "reject" | "correct",
            "assigned_metric_id": str (optional, for correct),
            "corrected_value": number (optional, for correct),
            "rejection_category": str (optional, for reject),
            "rejection_reason": str (optional),
            "reviewer_notes": str (optional),
            "review_time_seconds": int (optional)
        }

    Returns:
        201: Decision created
        400: Validation error
        404: Fact not found
        409: Fact already has a decision
    """
    db = get_db()

    try:
        if not request.is_json:
            return jsonify({"status": "error", "message": "Request must be JSON"}), 400

        data = request.get_json()

        # Validate
        errors = _validate_v2_decision(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        fact_id = data["fact_id"]
        decision = data["decision"]

        # Verify fact exists
        fact = db.get_v2_fact_by_id(fact_id)
        if not fact:
            return jsonify({"status": "error", "message": "Fact not found"}), 404

        # Check for existing decision
        if fact.get("decision_id"):
            return jsonify(
                {
                    "status": "error",
                    "message": "Fact already has a decision. Delete it first to re-decide.",
                    "existing_decision_id": str(fact["decision_id"]),
                }
            ), 409

        # Insert decision
        decision_id = db.insert_v2_review_decision(
            fact_id=fact_id,
            decision=decision,
            reviewer_id=data.get("reviewer_id", "web_reviewer"),
            assigned_metric_id=data.get("assigned_metric_id"),
            corrected_value=data.get("corrected_value"),
            rejection_reason=data.get("rejection_reason"),
            rejection_category=data.get("rejection_category"),
            reviewer_notes=data.get("reviewer_notes"),
            review_time_seconds=data.get("review_time_seconds"),
        )

        logger.info(f"V2 decision {decision_id} for fact {fact_id}: {decision}")

        # Find next pending fact in same filing
        filing_id = fact["doc_id"]
        next_fact = _get_next_pending_fact(db, filing_id, fact_id)

        return jsonify(
            {
                "status": "success",
                "decision_id": decision_id,
                "fact_id": fact_id,
                "next_fact": next_fact,
            }
        ), 201

    except psycopg.errors.UniqueViolation:
        return jsonify(
            {
                "status": "error",
                "message": "A decision already exists for this fact",
            }
        ), 409

    except psycopg.errors.ForeignKeyViolation as e:
        return jsonify(
            {
                "status": "error",
                "message": f"Invalid reference: {e}",
            }
        ), 400

    except psycopg.DatabaseError as e:
        logger.error(f"Database error creating V2 decision: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error"}), 500

    except Exception as e:
        logger.error(f"Error creating V2 decision: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_unified_bp.route("/decisions/<decision_id>", methods=["DELETE"])
def undo_decision(decision_id: str):
    """
    Undo (delete) a V2 review decision.

    Resets fact review_status back to pending_review.
    """
    db = get_db()

    try:
        result = db.delete_v2_review_decision(decision_id)
        if not result:
            return jsonify({"status": "error", "message": "Decision not found"}), 404

        logger.info(f"Undid V2 decision {decision_id} for fact {result['fact_id']}")

        return jsonify(
            {
                "status": "success",
                "message": "Decision reverted",
                "fact_id": result["fact_id"],
                "filing_id": result["filing_id"],
            }
        ), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error undoing V2 decision {decision_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error"}), 500

    except Exception as e:
        logger.error(f"Error undoing V2 decision {decision_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# =============================================================================
# Image Decision Recording (from api_images.py)
# =============================================================================


@api_unified_bp.route("/image-decisions", methods=["POST"])
def create_image_decision():
    """
    Record a review decision for an image candidate.

    Request Body:
        {
            "image_candidate_id": int,
            "decision": "relevant" | "not_relevant",
            "chart_type": str (required if decision="relevant"),
            "rejection_reason": str (required if decision="not_relevant"),
            "reviewer_notes": str (optional),
            "review_time_seconds": int (optional)
        }

    Returns:
        201: Decision created successfully
        {
            "status": "success",
            "decision_id": int,
            "next_candidate": {
                "image_candidate_id": int,
                "url": str
            } | null,
            "message": str (if no next candidate)
        }

        400: Validation errors
        {
            "status": "error",
            "message": str
        }

        404: Candidate not found
        {
            "status": "error",
            "message": str
        }

        409: Candidate already has a decision
        {
            "status": "error",
            "message": str
        }

        500: Internal server error
        {
            "status": "error",
            "message": str
        }
    """
    db = get_db()

    try:
        # Parse request JSON
        if not request.is_json:
            return (
                jsonify({"status": "error", "message": "Request must be JSON"}),
                400,
            )

        data = request.get_json()

        # Validate request
        error = _validate_image_decision_request(data)
        if error:
            logger.warning(f"Validation error: {error}")
            return jsonify({"status": "error", "message": error}), 400

        # Extract fields
        image_candidate_id = data["image_candidate_id"]
        decision = data["decision"]
        chart_type = data.get("chart_type")
        rejection_reason = data.get("rejection_reason")
        reviewer_notes = data.get("reviewer_notes")
        review_time_seconds = data.get("review_time_seconds")

        # Validate candidate exists
        candidate = db.get_image_review_candidate(image_candidate_id)
        if not candidate:
            logger.warning(f"Image candidate not found: {image_candidate_id}")
            return (
                jsonify({"status": "error", "message": "Image candidate not found"}),
                404,
            )

        # Check for existing decision
        if candidate.get("decision"):
            logger.warning(
                f"Image candidate {image_candidate_id} already has decision"
            )
            return (
                jsonify(
                    {"status": "error", "message": "Candidate already has a decision"}
                ),
                409,
            )

        # Insert the decision (also updates candidate status atomically)
        decision_id = db.insert_image_review_decision(
            image_candidate_id=image_candidate_id,
            decision=decision,
            chart_type=chart_type,
            rejection_reason=rejection_reason,
            reviewer_notes=reviewer_notes,
            review_time_seconds=review_time_seconds,
        )

        logger.info(
            f"Created image decision {decision_id} for candidate "
            f"{image_candidate_id}: {decision}"
        )

        # Get next candidate for navigation
        filing_id = candidate["filing_id"]
        next_cand = _get_next_image_candidate_info(db, filing_id, image_candidate_id)

        response: dict[str, Any] = {
            "status": "success",
            "decision_id": decision_id,
            "next_candidate": next_cand,
        }

        if not next_cand:
            response["message"] = "All candidates reviewed for this filing"

        return jsonify(response), 201

    except ValidationError as e:
        logger.warning(f"Validation error creating image decision: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

    except psycopg.errors.UniqueViolation:
        logger.warning(
            f"Duplicate decision for image candidate {data.get('image_candidate_id')}"
        )
        return (
            jsonify(
                {"status": "error", "message": "Candidate already has a decision"}
            ),
            409,
        )

    except psycopg.errors.ForeignKeyViolation as e:
        logger.warning(f"Foreign key violation: {e}")
        return (
            jsonify({"status": "error", "message": "Invalid image_candidate_id"}),
            400,
        )

    except psycopg.DatabaseError as e:
        logger.error(f"Database error creating image decision: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": "Database error occurred"}),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error creating image decision: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_unified_bp.route(
    "/image-candidates/<int:image_candidate_id>/skip", methods=["POST"]
)
def skip_image_candidate(image_candidate_id: int):
    """
    Skip an image candidate without making a decision.

    Updates the candidate's status to 'skipped' and returns the next candidate.

    Returns:
        200: Candidate skipped successfully
        {
            "status": "success",
            "next_candidate": {
                "image_candidate_id": int,
                "url": str
            } | null
        }

        404: Candidate not found
        {
            "status": "error",
            "message": str
        }

        500: Internal server error
        {
            "status": "error",
            "message": str
        }
    """
    db = get_db()

    try:
        # Validate candidate exists
        candidate = db.get_image_review_candidate(image_candidate_id)
        if not candidate:
            logger.warning(f"Skip: Image candidate not found: {image_candidate_id}")
            return (
                jsonify({"status": "error", "message": "Image candidate not found"}),
                404,
            )

        # Update status to skipped
        success = db.update_image_candidate_status(image_candidate_id, "skipped")
        if not success:
            logger.error(f"Failed to update status for candidate {image_candidate_id}")
            return (
                jsonify({"status": "error", "message": "Failed to skip candidate"}),
                500,
            )

        logger.info(f"Skipped image candidate {image_candidate_id}")

        # Get next candidate for navigation
        filing_id = candidate["filing_id"]
        next_cand = _get_next_image_candidate_info(db, filing_id, image_candidate_id)

        return jsonify({
            "status": "success",
            "skipped_candidate_id": image_candidate_id,
            "next_candidate": next_cand,
        }), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error skipping image candidate: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": "Database error occurred"}),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error skipping image candidate: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_unified_bp.route(
    "/image-candidates/<int:image_candidate_id>/unskip", methods=["POST"]
)
def unskip_image_candidate(image_candidate_id: int):
    """
    Undo a skip — reset a skipped candidate's status back to 'pending'.

    Returns:
        200: Candidate reset to pending
        {
            "status": "success",
            "candidate_id": int,
            "url": str
        }

        404: Candidate not found or not skipped
        500: Internal server error
    """
    db = get_db()

    try:
        candidate = db.get_image_review_candidate(image_candidate_id)
        if not candidate:
            return jsonify({"status": "error", "message": "Image candidate not found"}), 404

        if candidate.get("review_status") != "skipped":
            return jsonify({"status": "error", "message": "Candidate is not skipped"}), 400

        success = db.update_image_candidate_status(image_candidate_id, "pending")
        if not success:
            return jsonify({"status": "error", "message": "Failed to unskip candidate"}), 500

        filing_id = candidate["filing_id"]
        logger.info(f"Unskipped image candidate {image_candidate_id}")

        return jsonify({
            "status": "success",
            "candidate_id": image_candidate_id,
            "url": f"/review/images/{filing_id}?image_candidate_id={image_candidate_id}",
        }), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error unskipping candidate: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error occurred"}), 500

    except Exception as e:
        logger.error(f"Unexpected error unskipping candidate: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_unified_bp.route("/image-decisions/<int:image_decision_id>", methods=["DELETE"])
def delete_image_decision(image_decision_id: int):
    """
    Delete (undo) an image review decision.

    Resets the candidate's status back to 'pending'.

    Returns:
        200: Decision deleted successfully
        {
            "status": "success",
            "candidate_id": int
        }

        404: Decision not found
        {
            "status": "error",
            "message": str
        }

        500: Internal server error
        {
            "status": "error",
            "message": str
        }
    """
    db = get_db()

    try:
        # Get the candidate_id before deleting (for response)
        decision_info = db.get_image_decision_by_id(image_decision_id)
        if not decision_info:
            logger.warning(f"Image decision not found for undo: {image_decision_id}")
            return (
                jsonify({"status": "error", "message": "Decision not found"}),
                404,
            )

        candidate_id = decision_info["image_candidate_id"]

        # Delete the decision (also resets candidate status)
        success = db.delete_image_review_decision(image_decision_id)
        if not success:
            logger.error(f"Failed to delete image decision {image_decision_id}")
            return (
                jsonify({"status": "error", "message": "Failed to delete decision"}),
                500,
            )

        logger.info(f"Deleted image decision {image_decision_id}")

        return jsonify({"status": "success", "candidate_id": candidate_id}), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error deleting image decision: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": "Database error occurred"}),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error deleting image decision: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# =============================================================================
# Missed Metric (new endpoint)
# =============================================================================


@api_unified_bp.route("/missed-metric", methods=["POST"])
def add_missed_metric():
    """
    Manually add a metric fact that the pipeline missed.

    Request Body:
        {
            "filing_id": int,
            "canonical_metric_id": str,
            "value_raw": str,
            "value": float | null,
            "unit": str,  # percent|currency|count|ratio|basis_points|other
            "period_type": str | null,  # annual|quarterly|trailing|ytd|point_in_time|other
            "period_end": str | null,  # ISO date string e.g. "2024-12-31"
            "scope": str,  # company|segment|geography|product|customer_type|cohort|other (default: company)
            "reviewer_id": str,
            "reviewer_notes": str | null
        }

    Returns:
        201: Fact created with fact_id
        400: Validation error
        500: Database error
    """
    db = get_db()

    try:
        if not request.is_json:
            return jsonify({"status": "error", "message": "Request must be JSON"}), 400

        data = request.get_json()

        # Validate required fields
        errors: dict[str, str] = {}

        filing_id = data.get("filing_id")
        if filing_id is None:
            errors["filing_id"] = "Required field"
        elif not isinstance(filing_id, int):
            errors["filing_id"] = "Must be an integer"

        canonical_metric_id = data.get("canonical_metric_id")
        if not canonical_metric_id:
            errors["canonical_metric_id"] = "Required field"

        value_raw = data.get("value_raw")
        if not value_raw:
            errors["value_raw"] = "Required field"

        unit = data.get("unit")
        if not unit:
            errors["unit"] = "Required field"
        elif unit not in VALID_UNITS:
            errors["unit"] = f"Must be one of: {', '.join(VALID_UNITS)}"

        reviewer_id = data.get("reviewer_id") or "anonymous"
        if not reviewer_id:
            errors["reviewer_id"] = "Required field"

        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        period_end = data.get("period_end") or None
        period_type = data.get("period_type") or None

        fact_id = db.insert_manual_v2_metric_fact(
            filing_id=filing_id,
            canonical_metric_id=canonical_metric_id,
            value_raw=value_raw,
            value=data.get("value"),
            unit=unit,
            period_type=period_type,
            period_end=period_end,
            scope=data.get("scope", "company"),
            reviewer_id=reviewer_id,
            reviewer_notes=data.get("reviewer_notes"),
        )

        logger.info(
            f"Manually added metric fact {fact_id} for filing {filing_id}: "
            f"{canonical_metric_id} = {value_raw}"
        )

        return jsonify({"status": "success", "fact_id": fact_id, "filing_id": filing_id}), 201

    except psycopg.DatabaseError as e:
        logger.error(f"Database error adding missed metric: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error"}), 500

    except Exception as e:
        logger.error(f"Error adding missed metric: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# =============================================================================
# Helper Functions (from api_v2.py)
# =============================================================================


def _validate_v2_decision(data: dict[str, Any]) -> dict[str, str]:
    """Validate V2 decision request."""
    errors: dict[str, str] = {}

    if not data.get("fact_id"):
        errors["fact_id"] = "Required field"

    decision = data.get("decision")
    if not decision:
        errors["decision"] = "Required field"
    elif decision not in V2_DECISION_TYPES:
        errors["decision"] = f"Must be one of: {', '.join(V2_DECISION_TYPES)}"

    if decision == "reject":
        cat = data.get("rejection_category")
        if cat and cat not in V2_REJECTION_CATEGORIES:
            errors["rejection_category"] = f"Must be one of: {', '.join(V2_REJECTION_CATEGORIES)}"

    notes = data.get("reviewer_notes")
    if notes and len(notes) > 1000:
        errors["reviewer_notes"] = "Must be 1000 characters or less"

    review_time = data.get("review_time_seconds")
    if review_time is not None and (not isinstance(review_time, int) or review_time < 0):
        errors["review_time_seconds"] = "Must be a non-negative integer"

    return errors


def _get_next_pending_fact(db, filing_id: int, current_fact_id: str) -> dict | None:
    """Find next pending_review fact in the same filing."""
    facts = db.get_v2_facts_for_filing(filing_id, status="pending_review")
    if not facts:
        return None

    # Find current index
    current_idx = None
    for i, f in enumerate(facts):
        if str(f["fact_id"]) == current_fact_id:
            current_idx = i
            break

    if current_idx is not None and current_idx + 1 < len(facts):
        next_fact = facts[current_idx + 1]
    elif facts:
        # Current not in pending list (just reviewed) or at end — take first
        next_fact = facts[0]
    else:
        return None

    if str(next_fact["fact_id"]) == current_fact_id:
        return None

    return {
        "fact_id": str(next_fact["fact_id"]),
        "url": f"/v2/review/{filing_id}?fact_id={next_fact['fact_id']}",
    }


# =============================================================================
# Helper Functions (from api_images.py)
# =============================================================================


def _validate_image_decision_request(data: dict[str, Any]) -> str | None:
    """
    Validate image decision request data.

    Args:
        data: Request JSON data

    Returns:
        Error message if validation fails, None if valid
    """
    # Validate image_candidate_id
    image_candidate_id = data.get("image_candidate_id")
    if image_candidate_id is None:
        return "image_candidate_id is required"
    if not isinstance(image_candidate_id, int) or image_candidate_id <= 0:
        return "image_candidate_id must be a positive integer"

    # Validate decision
    decision = data.get("decision")
    if not decision:
        return "decision is required"
    if decision not in IMAGE_DECISIONS:
        return f"decision must be one of: {', '.join(IMAGE_DECISIONS)}"

    # Validate chart_type (required for relevant)
    chart_type = data.get("chart_type")
    if decision == "relevant":
        if not chart_type:
            return "chart_type is required when decision is 'relevant'"
        if chart_type not in IMAGE_CHART_TYPES:
            return f"chart_type must be one of: {', '.join(IMAGE_CHART_TYPES)}"
    elif chart_type and chart_type not in IMAGE_CHART_TYPES:
        # Also validate if provided for not_relevant (even though not required)
        return f"chart_type must be one of: {', '.join(IMAGE_CHART_TYPES)}"

    # Validate rejection_reason (required for not_relevant)
    rejection_reason = data.get("rejection_reason")
    if decision == "not_relevant":
        if not rejection_reason:
            return "rejection_reason is required when decision is 'not_relevant'"
        if rejection_reason not in IMAGE_REJECTION_REASONS:
            return f"rejection_reason must be one of: {', '.join(IMAGE_REJECTION_REASONS)}"
    elif rejection_reason and rejection_reason not in IMAGE_REJECTION_REASONS:
        # Also validate if provided for relevant (even though not required)
        return f"rejection_reason must be one of: {', '.join(IMAGE_REJECTION_REASONS)}"

    # Validate optional fields
    reviewer_notes = data.get("reviewer_notes")
    if reviewer_notes and len(reviewer_notes) > 1000:
        return "reviewer_notes must be 1000 characters or less"

    review_time_seconds = data.get("review_time_seconds")
    if review_time_seconds is not None:
        if not isinstance(review_time_seconds, int) or review_time_seconds < 0:
            return "review_time_seconds must be a non-negative integer"

    return None


def _get_next_image_candidate_info(
    db,
    filing_id: int,
    current_candidate_id: int,
) -> dict[str, Any] | None:
    """
    Get the next pending image candidate for navigation.

    Args:
        db: Database adapter
        filing_id: Current filing ID
        current_candidate_id: Current candidate ID

    Returns:
        Dict with image_candidate_id and url, or None if no more candidates
    """
    next_candidate = db.get_next_pending_image_candidate(
        filing_id=filing_id,
        current_candidate_id=current_candidate_id,
    )

    # No more pending candidates — fall back to first skipped (wrap around)
    if not next_candidate:
        next_candidate = db.get_next_pending_image_candidate(
            filing_id=filing_id,
            current_candidate_id=None,
            include_skipped=True,
        )

    if not next_candidate:
        return None

    next_id = next_candidate["image_candidate_id"]

    return {
        "image_candidate_id": next_id,
        "url": f"/v2/review/{filing_id}?image_candidate_id={next_id}&tab=images",
    }
