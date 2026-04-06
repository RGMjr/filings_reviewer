"""
JSON API endpoints for human review system.

Handles AJAX requests from the review interface for recording decisions
and fetching candidate data. All endpoints return JSON responses.
"""

import logging
from typing import Any

import psycopg
from flask import Blueprint, jsonify, request

from src.infra.validation import ValidationError
from src.review.models import (
    DECISION_TYPES,
    REJECTION_CATEGORIES,
)
from src.web.app import get_db
from src.web.middleware import insert_audit_log_entry, register_api_auth, register_timing

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)

register_api_auth(api_bp)
register_timing(api_bp)


@api_bp.after_request
def _log_request_complete(response):
    """
    Log request details to the audit log table after each API request.

    Extracts candidate_id and decision fields from request body for POST /decisions.
    """
    candidate_id = None
    filing_id = None
    query_params = None

    if request.view_args:
        candidate_id = request.view_args.get("candidate_id")
        filing_id = request.view_args.get("filing_id")

    if request.method == "POST" and request.is_json:
        data = request.get_json(silent=True) or {}
        if "candidate_id" in data:
            candidate_id = data.get("candidate_id")
        query_params = {}
        if "decision" in data:
            query_params["decision"] = data["decision"]
        if "assigned_metric_id" in data:
            query_params["assigned_metric_id"] = data["assigned_metric_id"]
        if "rejection_category" in data:
            query_params["rejection_category"] = data["rejection_category"]
        if not query_params:
            query_params = None

    return insert_audit_log_entry(
        response,
        candidate_id=candidate_id,
        filing_id=filing_id,
        query_params=query_params,
    )


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
            # Allow overriding automated decisions (reviewer_id = 'hrv5_script')
            if existing.get("reviewer_id") == "hrv5_script":
                logger.info(
                    f"Overriding automated decision {existing['decision_id']} for candidate {candidate_id}"
                )
                # Delete the automated decision so we can create a new human decision
                db.execute(
                    "DELETE FROM review_decisions WHERE decision_id = %(decision_id)s",
                    {"decision_id": existing["decision_id"]},
                )
            else:
                # Human decision already exists - don't allow override
                logger.warning(
                    f"Candidate {candidate_id} already has human decision {existing['decision_id']}"
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Candidate already has a decision",
                            "existing_decision_id": existing["decision_id"],
                            "error_type": "duplicate_decision",
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
            reviewer_id=data.get("reviewer_id"),
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
        # Extract filter parameters from request to maintain navigation consistency
        filing_id = candidate["filing_id"]
        filters = {
            "status": data.get("filter_status", "all"),
            "metric": data.get("filter_metric", "all"),
            "confidence": data.get("filter_confidence", "all"),
            "sort": data.get("filter_sort", "position"),
        }
        next_cand = _get_next_candidate_info(db, filing_id, candidate_id, filters)

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

    except psycopg.errors.ForeignKeyViolation as e:
        # Invalid assigned_metric_id - client provided non-existent metric
        logger.warning(
            f"Foreign key violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        # Extract metric_id from request for better error message
        metric_id = data.get("assigned_metric_id", "unknown")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Invalid metric_id: '{metric_id}' does not exist",
                    "error_type": "foreign_key_violation",
                }
            ),
            400,
        )

    except psycopg.errors.UniqueViolation as e:
        # Duplicate decision (race condition bypassing our check at line 129)
        logger.warning(
            f"Unique constraint violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "A decision already exists for this candidate",
                    "error_type": "duplicate_decision",
                }
            ),
            409,
        )

    except psycopg.errors.NotNullViolation as e:
        # NOT NULL constraint violation - missing required field
        logger.warning(
            f"NOT NULL violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing required field in database operation",
                    "error_type": "not_null_violation",
                }
            ),
            400,
        )

    except psycopg.errors.CheckViolation as e:
        # CHECK constraint violation - invalid enum value, etc.
        logger.warning(
            f"CHECK constraint violation creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        # Try to get detailed message from diag, fallback to generic message
        try:
            detail_msg = e.diag.message_primary if e.diag else str(e)
        except AttributeError:
            detail_msg = str(e)

        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Data validation failed: {detail_msg}",
                    "error_type": "check_violation",
                }
            ),
            400,
        )

    except psycopg.IntegrityError as e:
        # Other integrity constraint violations not caught above
        logger.warning(
            f"Integrity error creating decision for candidate {data.get('candidate_id')}: {e}"
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Data integrity constraint violated",
                    "error_type": "integrity_error",
                }
            ),
            400,
        )

    except psycopg.OperationalError as e:
        # Database connection/operational issues - temporary problem
        logger.error(
            f"Database operational error creating decision for candidate {data.get('candidate_id')}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database temporarily unavailable, please retry",
                    "error_type": "database_unavailable",
                }
            ),
            503,
        )

    except psycopg.DatabaseError as e:
        # Other database errors - unexpected database issues
        logger.error(
            f"Database error creating decision for candidate {data.get('candidate_id')}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        # Unexpected application errors - bugs
        logger.error(
            f"Unexpected error creating decision for candidate {data.get('candidate_id')}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


@api_bp.route("/candidates/<int:candidate_id>/skip", methods=["POST"])
def skip_candidate(candidate_id: int):
    """
    Skip a candidate without making a decision.

    Sets the candidate status to 'skipped' and returns the next candidate URL.
    Skip is a status change, NOT a decision - no decision record is created.

    Request Body (optional):
        {
            "filter_status": str (optional, default: "all"),
            "filter_metric": str (optional, default: "all"),
            "filter_confidence": str (optional, default: "all"),
            "filter_sort": str (optional, default: "position")
        }

    Returns:
        200: Candidate skipped successfully
        {
            "status": "success",
            "candidate_id": int,
            "next_candidate": {
                "candidate_id": int,
                "url": str
            } | null
        }

        400: Cannot skip a reviewed candidate
        {
            "status": "error",
            "message": "Cannot skip a reviewed candidate"
        }

        404: Candidate not found
        {
            "status": "error",
            "message": "Candidate not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Validate candidate exists
        candidate = db.get_review_candidate(candidate_id)
        if not candidate:
            logger.warning(f"Skip: Candidate not found: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate not found",
                    }
                ),
                404,
            )

        # Block skipping reviewed candidates (would lose decision data)
        if candidate.get("review_status") == "reviewed":
            logger.warning(f"Skip: Cannot skip reviewed candidate: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Cannot skip a reviewed candidate",
                    }
                ),
                400,
            )

        # Update candidate status to 'skipped'
        db.update_candidate_status(candidate_id, "skipped")

        logger.info(f"Skipped candidate {candidate_id}")

        # Get next candidate (respecting filters)
        data = request.get_json() if request.is_json else {}
        filing_id = candidate["filing_id"]
        filters = {
            "status": data.get("filter_status", "all"),
            "metric": data.get("filter_metric", "all"),
            "confidence": data.get("filter_confidence", "all"),
            "sort": data.get("filter_sort", "position"),
        }
        next_cand = _get_next_candidate_info(db, filing_id, candidate_id, filters)

        return (
            jsonify(
                {
                    "status": "success",
                    "candidate_id": candidate_id,
                    "next_candidate": next_cand,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error skipping candidate {candidate_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                }
            ),
            500,
        )


@api_bp.route("/decisions/<int:decision_id>", methods=["DELETE"])
def undo_decision(decision_id: int):
    """
    Undo (delete) a review decision.

    Resets the candidate status back to 'pending'.
    Only the most recent decision should be undone (enforced client-side).

    Args:
        decision_id: Decision ID to undo

    Returns:
        200: Decision undone successfully
        {
            "status": "success",
            "message": "Decision reverted",
            "candidate_id": int,
            "candidate_url": str
        }

        404: Decision not found
        {
            "status": "error",
            "message": "Decision not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Get decision details
        decision = db.get_decision_by_id(decision_id)
        if not decision:
            logger.warning(f"Decision not found for undo: {decision_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Decision not found"
                    }
                ),
                404,
            )

        candidate_id = decision["candidate_id"]
        filing_id = decision["filing_id"]

        # Delete decision and reset candidate status
        success = db.delete_review_decision(decision_id)

        if not success:
            logger.error(f"Failed to delete decision {decision_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Failed to undo decision"
                    }
                ),
                500,
            )

        logger.info(f"Undid decision {decision_id} for candidate {candidate_id}")

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Decision reverted",
                    "candidate_id": candidate_id,
                    "candidate_url": f"/review/{filing_id}/candidate/{candidate_id}"
                }
            ),
            200,
        )

    except psycopg.DatabaseError as e:
        logger.error(
            f"Database error undoing decision {decision_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error undoing decision {decision_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


@api_bp.route("/bulk-decisions", methods=["POST"])
def create_bulk_decisions():
    """
    Record multiple review decisions in one request (bulk accept or reject).

    Only 'accept' and 'reject' are allowed - 'reclassify' requires individual review.
    Maximum 50 candidates per request for safety.

    Request Body:
        {
            "candidate_ids": [int, ...],    # Required: 1-50 candidate IDs
            "decision": "accept" | "reject", # Required: only accept/reject allowed
            "assigned_metric_id": str,       # Required for accept
            "rejection_category": str,       # Required for reject
            "rejection_reason": str          # Optional for reject
        }

    Returns:
        200: Bulk operation completed (partial success possible)
        {
            "status": "success",
            "processed_count": int,
            "decision_ids": [int, ...],
            "failed_candidates": [
                {"candidate_id": int, "error": str}
            ],
            "message": "Processed N of M candidates"
        }

        400: Validation errors
        {
            "status": "error",
            "errors": {
                "field_name": "Error message"
            }
        }

        403: Safety limit exceeded
        {
            "status": "error",
            "message": "Maximum 20 candidates per bulk action"
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
        errors = _validate_bulk_decision_request(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # Extract and deduplicate candidate IDs
        candidate_ids = list(set(data["candidate_ids"]))
        decision = data["decision"]

        # Safety limit - maximum 50 candidates per bulk action
        if len(candidate_ids) > 50:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Maximum 50 candidates per bulk action",
                    }
                ),
                403,
            )

        # Verify all candidates are from same filing
        candidates = []
        for cid in candidate_ids:
            cand = db.get_review_candidate(cid)
            if cand:
                candidates.append(cand)

        if not candidates:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "No valid candidates found",
                    }
                ),
                400,
            )

        filing_ids = set(c["filing_id"] for c in candidates)
        if len(filing_ids) > 1:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "All candidates must be from same filing",
                    }
                ),
                400,
            )

        # Process bulk decision
        decision_ids, failed = db.insert_bulk_review_decisions(
            candidate_ids=candidate_ids,
            decision=decision,
            assigned_metric_id=data.get("assigned_metric_id"),
            rejection_category=data.get("rejection_category"),
            rejection_reason=data.get("rejection_reason"),
        )

        logger.info(
            f"Bulk {decision}: processed {len(decision_ids)} of {len(candidate_ids)} candidates"
        )

        return (
            jsonify(
                {
                    "status": "success",
                    "processed_count": len(decision_ids),
                    "decision_ids": decision_ids,
                    "failed_candidates": failed,
                    "message": f"Processed {len(decision_ids)} of {len(candidate_ids)} candidates",
                }
            ),
            200,
        )

    except ValidationError as e:
        logger.warning(f"Validation error in bulk decision: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": str(e),
                    "error_type": "validation_error",
                }
            ),
            400,
        )

    except psycopg.errors.ForeignKeyViolation as e:
        logger.warning(f"Foreign key violation in bulk decision: {e}")
        metric_id = data.get("assigned_metric_id", "unknown")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Invalid metric_id: '{metric_id}' does not exist",
                    "error_type": "foreign_key_violation",
                }
            ),
            400,
        )

    except psycopg.DatabaseError as e:
        logger.error(f"Database error in bulk decision: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error in bulk decision: {e}", exc_info=True)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
                }
            ),
            500,
        )


# =============================================================================
# Context Expansion
# =============================================================================


@api_bp.route("/candidates/<int:candidate_id>/expanded-context", methods=["GET"])
def get_expanded_context(candidate_id: int):
    """
    Get expanded context for a candidate.

    Fetches adjacent segments to provide broader context beyond the default
    ~50 word window shown in the review interface.

    Args:
        candidate_id: Candidate ID

    Returns:
        200: Expanded context
        {
            "status": "success",
            "expanded_context": str,
            "segment_count": int,
            "can_expand": bool
        }

        404: Candidate not found
        {
            "status": "error",
            "message": "Candidate not found"
        }

        500: Internal server error
        {
            "status": "error",
            "message": "Internal server error"
        }
    """
    db = get_db()

    try:
        # Get expanded context from database
        result = db.get_expanded_context_for_candidate(candidate_id)

        if result is None:
            logger.warning(f"Candidate not found for context expansion: {candidate_id}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Candidate not found"
                    }
                ),
                404,
            )

        return (
            jsonify(
                {
                    "status": "success",
                    "expanded_context": result["expanded_context"],
                    "segment_count": result["segment_count"],
                    "can_expand": result["can_expand"],
                }
            ),
            200,
        )

    except psycopg.DatabaseError as e:
        logger.error(
            f"Database error fetching expanded context for candidate {candidate_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Database error occurred",
                    "error_type": "database_error",
                }
            ),
            500,
        )

    except Exception as e:
        logger.error(
            f"Unexpected error fetching expanded context for candidate {candidate_id}: {e}",
            exc_info=True,
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Internal server error",
                    "error_type": "internal_error",
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


def _validate_decision_request(data: dict[str, Any]) -> dict[str, str]:
    """
    Validate decision request data.

    Orchestrates field-level and decision-specific validators.

    Args:
        data: Request JSON data

    Returns:
        Dict of field_name -> error message
        Empty dict if validation passes
    """
    errors: dict[str, str] = {}

    # Validate required fields
    if error := _validate_candidate_id(data.get("candidate_id")):
        errors["candidate_id"] = error

    if error := _validate_decision_type(data.get("decision")):
        errors["decision"] = error
    else:
        # Decision-specific validation (only if decision type is valid)
        decision = data["decision"]
        decision_errors = _validate_decision_specific_fields(decision, data)
        errors.update(decision_errors)

    # Validate optional fields
    if error := _validate_text_field(
        data.get("reviewer_notes"), "reviewer_notes", max_length=1000
    ):
        errors["reviewer_notes"] = error

    if error := _validate_review_time(data.get("review_time_seconds")):
        errors["review_time_seconds"] = error

    return errors


def _validate_bulk_decision_request(data: dict[str, Any]) -> dict[str, str]:
    """
    Validate bulk decision request data.

    Args:
        data: Request JSON data

    Returns:
        Dict of field_name -> error message
        Empty dict if validation passes
    """
    errors: dict[str, str] = {}

    # Validate candidate_ids
    candidate_ids = data.get("candidate_ids")
    if not candidate_ids:
        errors["candidate_ids"] = "Required field"
    elif not isinstance(candidate_ids, list):
        errors["candidate_ids"] = "Must be an array"
    elif not all(isinstance(id, int) and id > 0 for id in candidate_ids):
        errors["candidate_ids"] = "All IDs must be positive integers"
    elif len(candidate_ids) < 1:
        errors["candidate_ids"] = "Must select at least 1 candidate"

    # Validate decision type - only accept/reject allowed for bulk
    decision = data.get("decision")
    if not decision:
        errors["decision"] = "Required field"
    elif decision not in ("accept", "reject"):
        errors["decision"] = "Bulk actions only support 'accept' or 'reject'"

    # Decision-specific validation
    if decision == "accept":
        if not data.get("assigned_metric_id"):
            errors["assigned_metric_id"] = "Required for bulk accept"
    elif decision == "reject":
        if not data.get("rejection_category"):
            errors["rejection_category"] = "Required for bulk reject"
        elif data["rejection_category"] not in REJECTION_CATEGORIES:
            errors["rejection_category"] = (
                f"Must be one of: {', '.join(REJECTION_CATEGORIES)}"
            )

    # Validate optional rejection_reason
    if error := _validate_text_field(
        data.get("rejection_reason"), "rejection_reason", max_length=500
    ):
        errors["rejection_reason"] = error

    return errors


def _validate_candidate_id(value: Any) -> str | None:
    """
    Validate candidate_id field.

    Args:
        value: The candidate_id value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if value is None:
        return "Required field"
    if not isinstance(value, int) or value <= 0:
        return "Must be a positive integer"
    return None


def _validate_decision_type(value: Any) -> str | None:
    """
    Validate decision type field.

    Args:
        value: The decision type value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if not value:
        return "Required field"
    if value not in DECISION_TYPES:
        return f"Must be one of: {', '.join(DECISION_TYPES)}. Got: {value}"
    return None


def _validate_decision_specific_fields(
    decision: str, data: dict[str, Any]
) -> dict[str, str]:
    """
    Validate fields specific to the decision type.

    Args:
        decision: The decision type (accept, reject, reclassify)
        data: Full request data

    Returns:
        Dict of field_name -> error message for decision-specific fields
    """
    if decision in ("accept", "reclassify"):
        return _validate_accept_or_reclassify_decision(decision, data)
    elif decision == "reject":
        return _validate_reject_decision(data)
    return {}


def _validate_accept_or_reclassify_decision(
    decision: str, data: dict[str, Any]
) -> dict[str, str]:
    """
    Validate fields required for accept or reclassify decisions.

    Args:
        decision: The decision type (accept or reclassify)
        data: Full request data

    Returns:
        Dict of field_name -> error message
    """
    errors: dict[str, str] = {}

    if error := _validate_assigned_metric_id(
        data.get("assigned_metric_id"), decision
    ):
        errors["assigned_metric_id"] = error

    return errors


def _validate_reject_decision(data: dict[str, Any]) -> dict[str, str]:
    """
    Validate fields required for reject decisions.

    Args:
        data: Full request data

    Returns:
        Dict of field_name -> error message
    """
    errors: dict[str, str] = {}

    if error := _validate_rejection_category(data.get("rejection_category")):
        errors["rejection_category"] = error

    if error := _validate_text_field(
        data.get("rejection_reason"), "rejection_reason", max_length=500
    ):
        errors["rejection_reason"] = error

    return errors


def _validate_assigned_metric_id(value: Any, decision: str) -> str | None:
    """
    Validate assigned_metric_id field.

    Args:
        value: The assigned_metric_id value to validate
        decision: The decision type (for error message context)

    Returns:
        Error message if invalid, None if valid
    """
    if not value:
        return f"Required for {decision} decision"
    if not isinstance(value, str):
        return "Must be a string"
    return None


def _validate_rejection_category(value: Any) -> str | None:
    """
    Validate rejection_category field.

    Args:
        value: The rejection_category value to validate

    Returns:
        Error message if invalid, None if valid
    """
    if not value:
        return "Required for reject decision"
    if value not in REJECTION_CATEGORIES:
        return (
            f"Must be one of: {', '.join(REJECTION_CATEGORIES)}. Got: {value}"
        )
    return None


def _validate_text_field(
    value: Any, field_name: str, max_length: int
) -> str | None:
    """
    Validate optional text field with maximum length.

    Args:
        value: The text value to validate
        field_name: Name of the field (for error messages)
        max_length: Maximum allowed length

    Returns:
        Error message if invalid, None if valid or None
    """
    if value and len(value) > max_length:
        return f"Must be {max_length} characters or less"
    return None


def _validate_review_time(value: Any) -> str | None:
    """
    Validate review_time_seconds field.

    Args:
        value: The review_time_seconds value to validate

    Returns:
        Error message if invalid, None if valid or None
    """
    if value is not None:
        if not isinstance(value, int) or value < 0:
            return "Must be a non-negative integer"
    return None


def _get_next_candidate_info(
    db,
    filing_id: int,
    current_candidate_id: int,
    filters: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Get next pending candidate for the same filing, respecting active filters.

    Navigation order: Advances through the filtered, sorted candidate list.
    When reaching the end, wraps around to the beginning of the filtered list.

    Args:
        db: Database adapter
        filing_id: Filing ID
        current_candidate_id: Current candidate ID
        filters: Optional dict with filter/sort settings:
            - status: 'pending', 'reviewed', 'all' (default: navigates to pending only)
            - metric: metric_id or 'all'
            - confidence: 'high', 'medium', 'low', 'all'
            - sort: 'position', 'confidence_asc', 'confidence_desc', 'value_asc', 'value_desc'

    Returns:
        Dict with candidate_id and url (with filter params preserved), or None if no more candidates
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

    # Get next candidate ID using lightweight query (IDs only, no HTML)
    next_candidate_id = db.get_next_pending_candidate_id(
        filing_id=filing_id,
        current_candidate_id=current_candidate_id,
        status=db_status,
        metric_id=db_metric_id,
        confidence_level=db_confidence,
        sort_by=db_sort_by,
    )

    if next_candidate_id is None:
        return None

    # Build URL with filter parameters preserved
    url = f"/review/{filing_id}?candidate_id={next_candidate_id}"
    if filter_status != "all":
        url += f"&status={filter_status}"
    if filter_metric != "all":
        url += f"&metric={filter_metric}"
    if filter_confidence != "all":
        url += f"&confidence={filter_confidence}"
    if sort_by != "position":
        url += f"&sort={sort_by}"

    return {
        "candidate_id": next_candidate_id,
        "url": url,
    }
