"""
JSON API endpoints for V2 human review system.

Handles AJAX requests for recording V2 review decisions (accept/reject/correct).
Parallel to V1 api.py — queries V2 tables.
"""

import hmac
import logging
import time
from typing import Any

import psycopg
from flask import Blueprint, current_app, g, jsonify, request, session

from src.web.app import get_db

api_v2_bp = Blueprint("api_v2", __name__, url_prefix="/api/v2")
logger = logging.getLogger(__name__)

# Valid V2 decisions
V2_DECISION_TYPES = ("accept", "reject", "correct")

V2_REJECTION_CATEGORIES = (
    "wrong_metric",
    "not_a_metric",
    "wrong_value",
    "wrong_period",
    "duplicate",
    "other",
)


# =============================================================================
# Authentication
# =============================================================================


@api_v2_bp.before_request
def _check_api_key():
    """Verify API key (skipped in development mode)."""
    if not current_app.config.get("API_KEY_REQUIRED", True):
        return None

    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    expected_key = current_app.config.get("API_KEY")

    if not expected_key:
        return jsonify({"status": "error", "message": "Server misconfigured"}), 500
    if not api_key:
        return jsonify({"status": "error", "message": "API key required"}), 401
    if not hmac.compare_digest(api_key, expected_key):
        return jsonify({"status": "error", "message": "Invalid API key"}), 401

    return None


# =============================================================================
# Audit Logging
# =============================================================================


@api_v2_bp.before_request
def _log_request_start():
    g.request_start_time = time.time()


@api_v2_bp.after_request
def _log_request_complete(response):
    try:
        response_time_ms = None
        if hasattr(g, "request_start_time"):
            response_time_ms = int((time.time() - g.request_start_time) * 1000)

        db = get_db()
        db.insert_audit_log(
            session_id=session.get("_id"),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
            route_name=request.endpoint or "unknown",
            http_method=request.method,
            url_path=request.path,
            filing_id=None,
            candidate_id=None,
            query_params=None,
            response_status=response.status_code,
            response_time_ms=response_time_ms,
        )
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")

    return response


# =============================================================================
# Decision Recording
# =============================================================================


@api_v2_bp.route("/decisions", methods=["POST"])
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


@api_v2_bp.route("/decisions/<decision_id>", methods=["DELETE"])
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
# Extraction Jobs
# =============================================================================


@api_v2_bp.route("/jobs", methods=["POST"])
def enqueue_job():
    """
    Enqueue a V2 extraction job for a filing.

    Request Body:
        {"filing_id": int}

    Returns:
        201: Job created with job id
        400: Validation error
        404: Filing not found
    """
    db = get_db()

    if not request.is_json:
        return jsonify({"status": "error", "message": "Request must be JSON"}), 400

    data = request.get_json()
    filing_id = data.get("filing_id")

    if not filing_id or not isinstance(filing_id, int):
        return jsonify({"status": "error", "message": "filing_id (integer) is required"}), 400

    try:
        # Verify filing exists
        rows = db.query(
            "SELECT filing_id FROM filings WHERE filing_id = %(filing_id)s",
            {"filing_id": filing_id},
        )
        if not rows:
            return jsonify({"status": "error", "message": "Filing not found"}), 404

        # Insert job
        result = db.query(
            """
            INSERT INTO extraction_jobs (filing_id, status)
            VALUES (%(filing_id)s, 'pending')
            RETURNING id, filing_id, status, created_at
            """,
            {"filing_id": filing_id},
        )
        job = result[0]

        logger.info(f"Enqueued extraction job {job['id']} for filing_id={filing_id}")

        return jsonify(
            {
                "status": "success",
                "job": {
                    "id": job["id"],
                    "filing_id": job["filing_id"],
                    "status": job["status"],
                    "created_at": job["created_at"].isoformat(),
                },
            }
        ), 201

    except psycopg.DatabaseError as e:
        logger.error(f"Database error enqueuing job for filing {filing_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error"}), 500

    except Exception as e:
        logger.error(f"Error enqueuing job for filing {filing_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_v2_bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id: int):
    """
    Get extraction job status.

    Returns:
        200: Job status
        404: Job not found
    """
    db = get_db()

    try:
        rows = db.query(
            """
            SELECT id, filing_id, status, created_at, started_at, completed_at, error
            FROM extraction_jobs
            WHERE id = %(job_id)s
            """,
            {"job_id": job_id},
        )
        if not rows:
            return jsonify({"status": "error", "message": "Job not found"}), 404

        job = rows[0]

        return jsonify(
            {
                "status": "success",
                "job": {
                    "id": job["id"],
                    "filing_id": job["filing_id"],
                    "status": job["status"],
                    "created_at": job["created_at"].isoformat() if job["created_at"] else None,
                    "started_at": job["started_at"].isoformat() if job["started_at"] else None,
                    "completed_at": job["completed_at"].isoformat() if job["completed_at"] else None,
                    "error": job["error"],
                },
            }
        ), 200

    except Exception as e:
        logger.error(f"Error fetching job {job_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# =============================================================================
# Helpers
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
