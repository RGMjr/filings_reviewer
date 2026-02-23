"""
JSON API endpoints for image review decisions.

Handles AJAX requests from the image review interface for recording
decisions (relevant/not_relevant), skipping, and undoing decisions.
All endpoints return JSON responses.

Response format follows existing api.py patterns for consistency.
"""

import hmac
import logging
import time
from typing import Any

import psycopg
from flask import Blueprint, current_app, g, jsonify, request, session

from src.infra.validation import ValidationError
from src.review.models import (
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASONS,
)
from src.web.app import get_db

api_images_bp = Blueprint("api_images", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


# =============================================================================
# Authentication
# =============================================================================


@api_images_bp.before_request
def _check_api_key():
    """
    Verify API key for all requests to this blueprint.

    Checks X-API-Key header or api_key query parameter.
    Skips authentication if API_KEY_REQUIRED is False (development mode).
    """
    if not current_app.config.get("API_KEY_REQUIRED", True):
        return None  # Auth not required

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    expected_key = current_app.config.get("API_KEY")

    if not expected_key:
        logger.error("API_KEY_REQUIRED is True but API_KEY is not configured")
        return jsonify({"status": "error", "message": "Server misconfigured"}), 500

    if not api_key:
        logger.warning(
            f"Missing API key for {request.method} {request.path} from {request.remote_addr}"
        )
        return jsonify({"status": "error", "message": "API key required"}), 401

    if not hmac.compare_digest(api_key, expected_key):
        logger.warning(
            f"Invalid API key for {request.method} {request.path} from {request.remote_addr}"
        )
        return jsonify({"status": "error", "message": "Invalid API key"}), 401

    return None  # Auth passed


# =============================================================================
# Audit Logging Hooks
# =============================================================================
# These hooks automatically log all API requests for audit trail and analytics.
# Logs are stored in review_audit_log table.


@api_images_bp.before_request
def _log_request_start():
    """
    Hook that runs before each request to image API routes.

    Captures request start time for response time calculation.
    Stored in Flask g object for access in after_request hook.
    """
    g.request_start_time = time.time()


@api_images_bp.after_request
def _log_request_complete(response):
    """
    Hook that runs after each request to image API routes.

    Logs request details to audit_log table including:
    - Session ID, IP address, user agent
    - Route name, HTTP method, URL path
    - Image candidate ID if present in request body
    - Decision details (chart_type, rejection_reason) for POST /image-decisions
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

        # Extract IDs and decision info from request
        candidate_id = None
        filing_id = None
        query_params = None

        # Check URL path parameters first (for skip/delete endpoints)
        if request.view_args:
            candidate_id = request.view_args.get("image_candidate_id")
            if request.view_args.get("image_decision_id"):
                # For delete endpoint, store decision_id in query_params
                query_params = {"image_decision_id": request.view_args["image_decision_id"]}

        # For POST requests with JSON body, extract decision details
        if request.method == "POST" and request.is_json:
            data = request.get_json(silent=True) or {}
            # Extract image_candidate_id from body (overrides URL param if present)
            if "image_candidate_id" in data:
                candidate_id = data.get("image_candidate_id")
            # Capture decision-specific fields in query_params
            query_params = query_params or {}
            if "decision" in data:
                query_params["decision"] = data["decision"]
            if "chart_type" in data:
                query_params["chart_type"] = data["chart_type"]
            if "rejection_reason" in data:
                query_params["rejection_reason"] = data["rejection_reason"]
            # Only store non-empty query_params
            if not query_params:
                query_params = None

        # Get database connection and insert audit log
        db = get_db()
        db.insert_audit_log(
            session_id=session.get("_id"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            filing_id=filing_id,
            candidate_id=candidate_id,
            query_params=query_params,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        # Log error but don't break the response
        logger.error(f"Failed to insert audit log: {e}")

    return response


# =============================================================================
# Decision Recording
# =============================================================================


@api_images_bp.route("/image-decisions", methods=["POST"])
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
            logger.warning(f"Image candidate {image_candidate_id} already has decision")
            return (
                jsonify({"status": "error", "message": "Candidate already has a decision"}),
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
            f"Created image decision {decision_id} for candidate {image_candidate_id}: {decision}"
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
        logger.warning(f"Duplicate decision for image candidate {data.get('image_candidate_id')}")
        return (
            jsonify({"status": "error", "message": "Candidate already has a decision"}),
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


# =============================================================================
# Skip Candidate
# =============================================================================


@api_images_bp.route("/image-candidates/<int:image_candidate_id>/skip", methods=["POST"])
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

        return jsonify({"status": "success", "next_candidate": next_cand}), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error skipping image candidate: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": "Database error occurred"}),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error skipping image candidate: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# =============================================================================
# Undo Decision
# =============================================================================


@api_images_bp.route("/image-decisions/<int:image_decision_id>", methods=["DELETE"])
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
# Helper Functions
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

    if not next_candidate:
        return None

    next_id = next_candidate["image_candidate_id"]

    return {
        "image_candidate_id": next_id,
        "url": f"/review/images/{filing_id}?image_candidate_id={next_id}",
    }
