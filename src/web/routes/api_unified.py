"""
Unified JSON API endpoints for V2 human review system.

Merges V2 text decision API (api_v2.py) and image decision API (api_images.py)
into a single blueprint under /api/v2. Also provides a new endpoint for
manually adding metric facts that the pipeline missed.
"""

import logging
import uuid as _uuid
from typing import Any

import psycopg
from flask import Blueprint, jsonify, request

from src.shared.keyword_config import _load_config
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

# Reviewer-id gate: decision-writing endpoints must carry a real reviewer name.
# Empty / NULL / fallback sentinels / historical bulk prefixes are all rejected
# with 403 so the client is forced to open the "Who are you?" modal in base.html.
# See .claude/rules/web.md "Reviewer identity invariant".
_BLOCKED_REVIEWER_IDS = frozenset({"", "anonymous", "web_reviewer", "test", "test_user"})


def _require_reviewer_id(data: dict[str, Any]) -> tuple[str | None, tuple[Any, int] | None]:
    """Validate the reviewer_id in a decision payload.

    Returns (reviewer_id, None) when the caller can proceed, or
    (None, (json_response, status_code)) when the request must be rejected.
    """
    raw = data.get("reviewer_id")
    rid = (raw or "").strip() if isinstance(raw, str) else ""
    if not rid or rid in _BLOCKED_REVIEWER_IDS or rid.startswith("bulk:"):
        return None, (
            jsonify(
                {
                    "status": "error",
                    "error": "reviewer_name_required",
                    "message": (
                        "Set your reviewer name before making decisions. "
                        "The UI will open a prompt — enter a name, then retry."
                    ),
                }
            ),
            403,
        )
    return rid, None


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

        reviewer_id, gate_reject = _require_reviewer_id(data)
        if gate_reject is not None:
            return gate_reject

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
            reviewer_id=reviewer_id,
            assigned_metric_id=data.get("assigned_metric_id"),
            corrected_value=data.get("corrected_value"),
            rejection_reason=data.get("rejection_reason"),
            rejection_category=data.get("rejection_category"),
            reviewer_notes=data.get("reviewer_notes"),
            review_time_seconds=data.get("review_time_seconds"),
        )

        logger.info(f"V2 decision {decision_id} for fact {fact_id}: {decision}")

        # Find next fact in the reviewer's current filtered view
        filing_id = fact["filing_id"]
        view_filters = (
            data.get("view_filters") if isinstance(data.get("view_filters"), dict) else None
        )
        anchor_raw = data.get("anchor_index")
        anchor_index = anchor_raw if isinstance(anchor_raw, int) else None
        next_fact = _get_next_pending_fact(
            db,
            filing_id,
            fact_id,
            view_filters=view_filters,
            anchor_index=anchor_index,
        )

        pending_counts = _get_filing_pending_counts(db, filing_id)

        return jsonify(
            {
                "status": "success",
                "decision_id": decision_id,
                "fact_id": fact_id,
                "next_fact": next_fact,
                **pending_counts,
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
# Image Bulk Actions (must be before any <uuid:img_id> routes)
# =============================================================================


@api_unified_bp.route("/image-candidates/bulk-reject", methods=["POST"])
def bulk_reject_image_candidates():
    """
    Bulk "Reject all (no relevant metrics)" across multiple images.

    For each image:
    - If it has keyword-detected metrics: rejects all unreviewed detected metrics
      (skipping any already accepted/corrected) with rejection_reason='not_present',
      then skips the image.
    - If it has no detected metrics: writes the sentinel no_relevant_metrics rejection
      row, then skips.

    Request body: {image_ids: [...str], reviewer_id: str, image_status: str|null}
    Response: {ok: true, processed: int, results: [...], next_candidate, ...pending_counts}
    """
    db = get_db()
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    reviewer_id, gate_reject = _require_reviewer_id(data)
    if gate_reject is not None:
        return gate_reject

    image_ids = data.get("image_ids")
    if not image_ids or not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a non-empty list"}), 400
    if len(image_ids) > 50:
        return jsonify({"error": "bulk-reject limited to 50 images per request"}), 400

    image_status = data.get("image_status") or None
    view_filters = {"status": image_status} if image_status else None

    results = []
    last_filing_id = None
    last_img_id = None

    for raw_id in image_ids:
        try:
            img_id = str(_uuid.UUID(str(raw_id)))
        except (ValueError, AttributeError):
            results.append({"img_id": raw_id, "status": "error", "reason": "invalid uuid"})
            continue

        try:
            candidate = db.get_image_review_candidate_v2(img_id)
            if not candidate:
                results.append({"img_id": img_id, "status": "error", "reason": "not found"})
                continue

            detected = candidate.get("detected_metrics") or []

            if not detected:
                decisions = [
                    {
                        "detected_metric_id": None,
                        "confirmed_metric_id": None,
                        "decision": "reject",
                        "rejection_reason": "no_relevant_metrics",
                    }
                ]
            else:
                existing = db.get_image_metric_confirmations(img_id)
                kept = {
                    c["detected_metric_id"]
                    for c in existing
                    if c["decision"] in ("accept", "correct")
                }
                targets = [m for m in detected if m.get("metric_id") not in kept]
                if not targets:
                    results.append(
                        {"img_id": img_id, "status": "skipped", "reason": "already fully decided"}
                    )
                    continue
                decisions = [
                    {
                        "detected_metric_id": m["metric_id"],
                        "confirmed_metric_id": None,
                        "decision": "reject",
                        "rejection_reason": "not_present",
                    }
                    for m in targets
                ]

            db.insert_image_metric_confirmations(img_id, decisions, reviewer_id)
            db.skip_image_candidate_v2(img_id)

            last_filing_id = candidate["filing_id"]
            last_img_id = img_id
            results.append({"img_id": img_id, "status": "rejected"})

        except Exception as exc:
            logger.error("bulk-reject error for img_id=%s: %s", img_id, exc, exc_info=True)
            results.append({"img_id": img_id, "status": "error", "reason": "internal error"})

    next_cand = None
    pending_counts: dict[str, Any] = {}
    if last_filing_id and last_img_id:
        try:
            next_cand = _get_next_image_candidate_info(
                db, last_filing_id, last_img_id, view_filters=view_filters
            )
            pending_counts = _get_filing_pending_counts(db, last_filing_id)
        except Exception as exc:
            logger.warning("bulk-reject next_candidate lookup failed: %s", exc)

    return jsonify(
        {
            "ok": True,
            "processed": len(results),
            "results": results,
            "next_candidate": next_cand,
            **pending_counts,
        }
    ), 200


@api_unified_bp.route("/image-candidates/bulk-undo", methods=["POST"])
def bulk_undo_image_candidates():
    """
    Bulk undo — reverts the most recent reviewer action on each selected image:
    - If skipped: unskip (return to pending).
    - If reviewed: delete all per-metric confirmations for this reviewer (rolling back
      any promoted chart facts) and flip v2_image_assets.review_status='pending' via
      db.reopen_image_candidate_v2, mirroring the single-image /reopen flow so the
      center-pane status alert and top-right badge update on reload.
    - If pending (partial confirmations): delete the reviewer's confirmations only;
      raw review_status stays 'pending'.

    Request body: {image_ids: [...str], reviewer_id: str, image_status: str|null}
    Response: {ok: true, processed: int, results: [...], next_candidate, ...pending_counts}
    """
    db = get_db()
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json() or {}
    reviewer_id, gate_reject = _require_reviewer_id(data)
    if gate_reject is not None:
        return gate_reject

    image_ids = data.get("image_ids")
    if not image_ids or not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a non-empty list"}), 400
    if len(image_ids) > 50:
        return jsonify({"error": "bulk-undo limited to 50 images per request"}), 400

    image_status = data.get("image_status") or None
    view_filters = {"status": image_status} if image_status else None

    results = []
    last_filing_id = None
    last_img_id = None

    for raw_id in image_ids:
        try:
            img_id = str(_uuid.UUID(str(raw_id)))
        except (ValueError, AttributeError):
            results.append({"img_id": raw_id, "status": "error", "reason": "invalid uuid"})
            continue

        try:
            candidate = db.get_image_review_candidate_v2(img_id)
            if not candidate:
                results.append({"img_id": img_id, "status": "error", "reason": "not found"})
                continue

            status = candidate.get("review_status")

            if status == "skipped":
                db.unskip_image_candidate_v2(img_id)
                results.append({"img_id": img_id, "status": "unskipped"})
            else:
                confirmations = db.get_image_metric_confirmations(img_id)
                mine = [c for c in confirmations if c.get("reviewer_id") == reviewer_id]
                deleted = 0
                for conf in mine:
                    result = db.delete_image_metric_confirmation(
                        conf["confirmation_id"], reviewer_id
                    )
                    if result is not None:
                        deleted += 1

                if status == "reviewed":
                    db.reopen_image_candidate_v2(img_id)
                    results.append(
                        {
                            "img_id": img_id,
                            "status": "reopened",
                            "deleted_confirmations": deleted,
                        }
                    )
                else:
                    results.append(
                        {
                            "img_id": img_id,
                            "status": "undone",
                            "deleted_confirmations": deleted,
                        }
                    )

            last_filing_id = candidate["filing_id"]
            last_img_id = img_id

        except Exception as exc:
            logger.error("bulk-undo error for img_id=%s: %s", img_id, exc, exc_info=True)
            results.append({"img_id": img_id, "status": "error", "reason": "internal error"})

    next_cand = None
    pending_counts: dict[str, Any] = {}
    if last_filing_id and last_img_id:
        try:
            next_cand = _get_next_image_candidate_info(
                db, last_filing_id, last_img_id, view_filters=view_filters
            )
            pending_counts = _get_filing_pending_counts(db, last_filing_id)
        except Exception as exc:
            logger.warning("bulk-undo next_candidate lookup failed: %s", exc)

    return jsonify(
        {
            "ok": True,
            "processed": len(results),
            "results": results,
            "next_candidate": next_cand,
            **pending_counts,
        }
    ), 200


# =============================================================================
# Image Skip / Unskip (image-grain "defer the whole image" actions)
# =============================================================================


@api_unified_bp.route("/image-candidates/<uuid:img_id>/skip", methods=["POST"])
def skip_image_candidate(img_id):
    """
    Skip a V2 image without making a decision.

    Returns:
        200: Skipped — returns next_candidate for navigation (or null when queue empty).
        404: Image not found.
        500: Internal server error.
    """
    img_id_str = str(img_id)
    db = get_db()

    try:
        candidate = db.get_image_review_candidate_v2(img_id_str)
        if not candidate:
            logger.warning(f"Skip: v2 image not found: {img_id_str}")
            return (
                jsonify({"status": "error", "message": "Image candidate not found"}),
                404,
            )

        success = db.skip_image_candidate_v2(img_id_str)
        if not success:
            logger.error(f"Failed to skip v2 image {img_id_str}")
            return (
                jsonify({"status": "error", "message": "Failed to skip candidate"}),
                500,
            )

        logger.info(f"Skipped v2 image {img_id_str}")

        filing_id = candidate["filing_id"]
        # Skip is fire-and-forget for the image; the body is empty for GET-style
        # callers, so accept view_filters from query string OR JSON body.
        view_filters: dict[str, Any] | None = None
        if request.is_json:
            data = request.get_json(silent=True) or {}
            if isinstance(data.get("view_filters"), dict):
                view_filters = data["view_filters"]
        if view_filters is None:
            qs_status = request.args.get("image_status")
            if qs_status:
                view_filters = {"status": qs_status}
        next_cand = _get_next_image_candidate_info(
            db, filing_id, img_id_str, view_filters=view_filters
        )
        pending_counts: dict[str, int] = {}
        try:
            pending_counts = _get_filing_pending_counts(db, filing_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pending_counts lookup failed for filing_id=%s: %s", filing_id, exc)

        return jsonify(
            {
                "status": "success",
                "skipped_img_id": img_id_str,
                "next_candidate": next_cand,
                **pending_counts,
            }
        ), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error skipping v2 image: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": "Database error occurred"}),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error skipping v2 image: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_unified_bp.route("/image-candidates/<uuid:img_id>/unskip", methods=["POST"])
def unskip_image_candidate(img_id):
    """
    Undo a skip — revert v2_image_assets.review_status back to 'pending'.

    Returns:
        200: Reverted to pending.
        400: Image is not in 'skipped' status.
        404: Image not found.
    """
    img_id_str = str(img_id)
    db = get_db()

    try:
        candidate = db.get_image_review_candidate_v2(img_id_str)
        if not candidate:
            return jsonify({"status": "error", "message": "Image candidate not found"}), 404

        if candidate.get("review_status") != "skipped":
            return jsonify({"status": "error", "message": "Candidate is not skipped"}), 400

        success = db.unskip_image_candidate_v2(img_id_str)
        if not success:
            return jsonify({"status": "error", "message": "Failed to unskip candidate"}), 500

        filing_id = candidate["filing_id"]
        logger.info(f"Unskipped v2 image {img_id_str}")

        qs = f"img_id={img_id_str}&tab=images"
        image_status = request.args.get("image_status")
        if image_status:
            qs += f"&image_status={image_status}"
        return jsonify(
            {
                "status": "success",
                "img_id": img_id_str,
                "url": f"/v2/review/{filing_id}?{qs}",
            }
        ), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error unskipping v2 image: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Database error occurred"}), 500

    except Exception as e:
        logger.error(f"Unexpected error unskipping v2 image: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@api_unified_bp.route("/image-candidates/<uuid:img_id>/reopen", methods=["POST"])
def reopen_image_candidate(img_id):
    """
    Re-open a reviewed image — flip review_status='reviewed' back to 'pending'.

    Requires X-Reviewer-Id header to identify who is reopening the image.
    Preserves all v2_image_review_decisions and v2_image_metric_confirmations
    rows (ML training signal).

    Returns:
        200: Reopened — returns img_id and new review_status.
        400: Missing X-Reviewer-Id header.
        404: Image not found or not in 'reviewed' status.
        500: Internal server error.
    """
    reviewer_id = (request.headers.get("X-Reviewer-Id") or "").strip()
    if not reviewer_id:
        return (
            jsonify({"status": "error", "message": "X-Reviewer-Id header is required"}),
            400,
        )

    image_status = request.args.get("image_status")
    img_id_str = str(img_id)
    db = get_db()

    try:
        success = db.reopen_image_candidate_v2(img_id_str)
        if not success:
            logger.warning(f"Reopen: v2 image not found or not reviewed: {img_id_str}")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Image not found or not in 'reviewed' status",
                    }
                ),
                404,
            )

        logger.info(f"Reopened v2 image {img_id_str} by reviewer {reviewer_id}")

        return jsonify(
            {
                "img_id": img_id_str,
                "review_status": "pending",
                "image_status": image_status,
            }
        ), 200

    except psycopg.DatabaseError as e:
        logger.error(f"Database error reopening v2 image: {e}", exc_info=True)
        return (
            jsonify({"status": "error", "message": "Database error occurred"}),
            500,
        )

    except Exception as e:
        logger.error(f"Unexpected error reopening v2 image: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# =============================================================================
# Missed Metric (new endpoint)
# =============================================================================


@api_unified_bp.route("/missed-metric", methods=["POST"])
def add_missed_metric():
    """
    Manually add a metric fact (the manual value-entry path).

    Under the chart-presence pivot (#86, 2026-04-23) the pipeline does not
    auto-emit per-value chart facts; this endpoint is the primary path by
    which CMASB-required values enter ``v2_metric_facts`` for chart-native
    metrics. It is also used to capture text-fact values that the pipeline
    missed entirely. The resulting fact carries ``extraction_method='manual'``
    and propagates through ``MetricPresenceStage`` on the next re-extraction
    via ``advisory_fact_ids``. See
    ``docs/operations/text-pipeline-presence-pivot-plan.md``.

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

        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        reviewer_id, gate_reject = _require_reviewer_id(data)
        if gate_reject is not None:
            return gate_reject

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
# Metric List (for metric-picker autocomplete)
# =============================================================================

# Tier-1 metric IDs per CLAUDE.md; used as fallback when YAML has no tier field.
_TIER_1_METRICS = frozenset(
    {
        "cm_customer_retention_rate",
        "cm_net_revenue_retention",
        "cm_gross_revenue_retention",
        "cm_revenue_by_cohort",
        "cm_transactions_by_cohort",
        "cm_balance_by_cohort",
        "cm_gross_margin_by_cohort",
        "cm_revenue_concentration",
        "cm_lifetime_value_per_customer",
        "cm_customer_acquisition_cost",
        "cm_ltv_to_cac_ratio",
        "cm_ltv_to_cac_ratio_by_cohort",
        "cm_large_customers_period_end",
        "cm_new_customers_acquired",
        "cm_customers_period_end_by_tenure",
    }
)


@api_unified_bp.route("/metrics/list", methods=["GET"])
def list_metrics():
    """
    Return the full list of active metrics for the metric-picker autocomplete.

    Response: JSON array of {metric_id, display_name, tier} objects.
    Sourced from config/metric_keywords.yaml via the shared keyword_config loader.
    """
    try:
        config = _load_config()
        result = []
        for metric_id, metric_cfg in config.items():
            if metric_id.startswith("_"):
                continue
            if metric_cfg.get("status") == "deprecated":
                continue
            yaml_tier = metric_cfg.get("tier")
            if yaml_tier is not None:
                tier = f"tier_{yaml_tier}"
            else:
                tier = "tier_1" if metric_id in _TIER_1_METRICS else "tier_2"
            result.append(
                {
                    "metric_id": metric_id,
                    "display_name": metric_cfg.get("display_name") or metric_id,
                    "tier": tier,
                }
            )
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error loading metrics list: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to load metrics"}), 500


# =============================================================================
# Image Metric Confirmations
# =============================================================================

_VALID_IMAGE_METRIC_DECISIONS = ("accept", "reject", "correct", "add", "skip")


@api_unified_bp.route("/image-metric-confirmations", methods=["POST"])
def create_image_metric_confirmations():
    """
    Record per-metric confirmation decisions for a chart image.

    Request Body:
        {
            "img_id": "<uuid>",
            "reviewer_id": "<string>",   (optional — defaults to "anonymous")
            "decisions": [
                {"detected_metric_id": "...", "decision": "accept"},
                {"detected_metric_id": "...", "decision": "reject",
                 "rejection_reason": "not_present"},
                {"detected_metric_id": "...", "decision": "correct",
                 "confirmed_metric_id": "..."},
                {"detected_metric_id": null, "decision": "add",
                 "confirmed_metric_id": "..."}
            ],
            "mark_complete": false       (optional — when true, also flips
                                          v2_image_assets.review_status to
                                          'reviewed' so the image leaves the
                                          pending queue)
        }

    Returns:
        200: {"ok": true, "upserted": <int>, "confirmations": [...]}
        400: {"error": "<reason>"}
        500: {"error": "database error"}
    """
    db = get_db()

    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400

        data = request.get_json()

        # Validate img_id
        img_id_raw = data.get("img_id")
        if not img_id_raw:
            return jsonify({"error": "img_id is required"}), 400
        try:
            img_id = str(_uuid.UUID(str(img_id_raw)))
        except (ValueError, AttributeError):
            return jsonify({"error": "img_id must be a valid UUID"}), 400

        reviewer_id, gate_reject = _require_reviewer_id(data)
        if gate_reject is not None:
            return gate_reject

        decisions_raw = data.get("decisions")
        if decisions_raw is None:
            return jsonify({"error": "decisions is required"}), 400
        if not isinstance(decisions_raw, list):
            return jsonify({"error": "decisions must be a list"}), 400

        validated: list[dict[str, Any]] = []
        for i, d in enumerate(decisions_raw):
            prefix = f"decisions[{i}]"
            if not isinstance(d, dict):
                return jsonify({"error": f"{prefix}: must be an object"}), 400

            decision = d.get("decision")
            if decision not in _VALID_IMAGE_METRIC_DECISIONS:
                return jsonify(
                    {
                        "error": f"{prefix}.decision must be one of: {', '.join(_VALID_IMAGE_METRIC_DECISIONS)}"
                    }
                ), 400

            detected_metric_id = d.get("detected_metric_id") or None
            confirmed_metric_id = d.get("confirmed_metric_id") or None
            rejection_reason = d.get("rejection_reason") or None

            if decision == "accept":
                if not detected_metric_id:
                    return jsonify({"error": f"{prefix}: accept requires detected_metric_id"}), 400
                if rejection_reason:
                    return jsonify(
                        {"error": f"{prefix}: accept must not have rejection_reason"}
                    ), 400
                confirmed_metric_id = confirmed_metric_id or detected_metric_id

            elif decision == "reject":
                if not rejection_reason:
                    return jsonify({"error": f"{prefix}: reject requires rejection_reason"}), 400
                if not detected_metric_id and rejection_reason != "no_relevant_metrics":
                    return jsonify({"error": f"{prefix}: reject requires detected_metric_id"}), 400
                confirmed_metric_id = None

            elif decision == "correct":
                if not detected_metric_id:
                    return jsonify({"error": f"{prefix}: correct requires detected_metric_id"}), 400
                if not confirmed_metric_id:
                    return jsonify(
                        {"error": f"{prefix}: correct requires confirmed_metric_id"}
                    ), 400
                if detected_metric_id == confirmed_metric_id:
                    return jsonify(
                        {
                            "error": f"{prefix}: correct requires detected_metric_id != confirmed_metric_id"
                        }
                    ), 400

            elif decision == "add":
                if detected_metric_id:
                    return jsonify(
                        {"error": f"{prefix}: add must have null detected_metric_id"}
                    ), 400
                if not confirmed_metric_id:
                    return jsonify({"error": f"{prefix}: add requires confirmed_metric_id"}), 400
                if rejection_reason:
                    return jsonify({"error": f"{prefix}: add must not have rejection_reason"}), 400

            elif decision == "skip":
                if not detected_metric_id:
                    return jsonify({"error": f"{prefix}: skip requires detected_metric_id"}), 400
                if rejection_reason:
                    return jsonify({"error": f"{prefix}: skip must not have rejection_reason"}), 400
                confirmed_metric_id = None

            validated.append(
                {
                    "detected_metric_id": detected_metric_id,
                    "confirmed_metric_id": confirmed_metric_id,
                    "decision": decision,
                    "rejection_reason": rejection_reason,
                }
            )

        mark_complete = bool(data.get("mark_complete", False))

        upserted = db.insert_image_metric_confirmations(img_id, validated, reviewer_id)
        if mark_complete:
            db.mark_image_reviewed_v2(img_id)
        confirmations = db.get_image_metric_confirmations(img_id)

        # Convert datetime objects to ISO strings for JSON serialisation
        serialised = []
        for row in confirmations:
            r = dict(row)
            for k in ("created_at", "updated_at"):
                if r.get(k) is not None and hasattr(r[k], "isoformat"):
                    r[k] = r[k].isoformat()
            serialised.append(r)

        # Compute next image candidate in the reviewer's filtered view so the
        # client can advance after a per-metric submission. The N-decision
        # batch maps to a single next_candidate (the image is the unit, not
        # the metric). null fires the cross-tab / cross-doc cascade.
        view_filters = (
            data.get("view_filters") if isinstance(data.get("view_filters"), dict) else None
        )
        next_cand: dict[str, Any] | None = None
        pending_counts: dict[str, int] = {}
        try:
            candidate_row = db.get_image_review_candidate_v2(img_id)
            if candidate_row:
                filing_id_for_nav = candidate_row["filing_id"]
                next_cand = _get_next_image_candidate_info(
                    db,
                    filing_id_for_nav,
                    img_id,
                    view_filters=view_filters,
                )
                pending_counts = _get_filing_pending_counts(db, filing_id_for_nav)
        except Exception as exc:  # noqa: BLE001
            # Advancement is a best-effort UX hint; never block decision write.
            logger.warning("next_candidate lookup failed for img_id=%s: %s", img_id, exc)

        return jsonify(
            {
                "ok": True,
                "upserted": upserted,
                "confirmations": serialised,
                "next_candidate": next_cand,
                **pending_counts,
            }
        ), 200

    except psycopg.errors.ForeignKeyViolation:
        return jsonify({"error": "img_id not found in v2_image_assets"}), 400

    except psycopg.DatabaseError as e:
        logger.error(f"Database error in image-metric-confirmations: {e}", exc_info=True)
        return jsonify({"error": "database error"}), 500

    except Exception as e:
        logger.error(f"Error in image-metric-confirmations: {e}", exc_info=True)
        return jsonify({"error": "internal server error"}), 500


@api_unified_bp.route("/image-metric-confirmations/<uuid:confirmation_id>", methods=["DELETE"])
def delete_image_metric_confirmation(confirmation_id):
    """
    Undo a single per-metric confirmation. Deletes the confirmation row
    and rolls back any promoted chart fact in v2_metric_facts.

    Reviewer identity must be forwarded via the `X-Reviewer-Id` header or
    the `reviewer_id` query parameter — same gate as the POST side.
    """
    db = get_db()

    data: dict[str, Any] = {}
    header_reviewer = request.headers.get("X-Reviewer-Id")
    if header_reviewer:
        data["reviewer_id"] = header_reviewer
    if "reviewer_id" in request.args:
        data["reviewer_id"] = request.args["reviewer_id"]
    if request.is_json:
        try:
            body = request.get_json(silent=True) or {}
            if isinstance(body, dict) and body.get("reviewer_id"):
                data["reviewer_id"] = body["reviewer_id"]
        except Exception:
            pass

    reviewer_id, gate_reject = _require_reviewer_id(data)
    if gate_reject is not None:
        return gate_reject

    try:
        deleted = db.delete_image_metric_confirmation(str(confirmation_id), reviewer_id)
        if deleted is None:
            return jsonify({"error": "confirmation not found or not owned by this reviewer"}), 404

        return jsonify({"ok": True, "deleted": deleted}), 200

    except psycopg.DatabaseError as e:
        logger.error(
            f"Database error deleting image-metric-confirmation {confirmation_id}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "database error"}), 500

    except Exception as e:
        logger.error(
            f"Error deleting image-metric-confirmation {confirmation_id}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "internal server error"}), 500


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


_VALID_TEXT_SORTS = ("confidence_desc", "confidence_asc", "metric", "period")
_VALID_TEXT_STATUSES = (
    "pending_review",
    "accepted",
    "rejected",
    "corrected",
    "auto_accepted",
)


def _get_next_pending_fact(
    db,
    filing_id: int,
    current_fact_id: str,
    view_filters: dict[str, Any] | None = None,
    anchor_index: int | None = None,
) -> dict | None:
    """Return the next fact to advance to, scoped to the reviewer's active view.

    `view_filters` mirrors the URL params the review page is rendering with
    (`status`, `metric`, `sort`). When provided, advancement walks the same
    filtered+sorted list the user is looking at — so the next-fact pointer is
    synchronized with the rendered thumbnail strip.

    `anchor_index` is the position of the just-reviewed fact in the filtered
    FACTS array at decision time. If the just-reviewed fact dropped out of the
    filter (e.g. reject under `status=pending_review`), we fall back to that
    index in the freshly-queried list — which now points at the *next* fact in
    the user's view because the list shrunk by one.

    Returns None when there is no further fact in the current view (the
    cross-tab / cross-document cascade fires client-side).
    """
    view_filters = view_filters or {}
    raw_status = view_filters.get("status")
    raw_metric = view_filters.get("metric")
    raw_sort = view_filters.get("sort")

    db_status = raw_status if raw_status in _VALID_TEXT_STATUSES else None
    db_metric = raw_metric if raw_metric and raw_metric != "all" else None
    db_sort = raw_sort if raw_sort in _VALID_TEXT_SORTS else "confidence_desc"

    facts = db.get_v2_facts_for_filing(
        filing_id,
        status=db_status,
        metric_id=db_metric,
        sort_by=db_sort,
    )
    if not facts:
        return None

    next_fact = None

    current_idx = None
    for i, f in enumerate(facts):
        if str(f["fact_id"]) == current_fact_id:
            current_idx = i
            break

    if current_idx is not None and current_idx + 1 < len(facts):
        next_fact = facts[current_idx + 1]
    elif current_idx is None and isinstance(anchor_index, int) and anchor_index >= 0:
        # The reviewed fact dropped out of the filter — the list shrank by
        # one, so the same anchor_index now points at what was previously
        # anchor_index+1. If the anchor was past the end, the user is done.
        if anchor_index < len(facts):
            candidate = facts[anchor_index]
            if str(candidate["fact_id"]) != current_fact_id:
                next_fact = candidate

    if next_fact is None:
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


_VALID_IMAGE_STATUSES = ("pending", "reviewed", "skipped", "auto_rejected")


_AUDIT_IMAGE_STATUSES = frozenset(("reviewed", "skipped", "auto_rejected"))


def _get_next_image_candidate_info(
    db,
    filing_id: int,
    current_img_id: str,
    view_filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the next image candidate to advance to, scoped to the reviewer's view.

    `view_filters['status']` mirrors `?image_status=` on the review page.

    For the default review intent ('pending', None, or 'all'), advancement
    scans forward in relevance order and returns the first candidate whose
    derived `image_review_state` is 'pending'. This correctly skips images that
    have been fully decided via per-metric confirmations even though their raw
    `v2_image_assets.review_status` column remains 'pending' by design.

    For explicit audit filters ('reviewed', 'skipped', 'auto_rejected'),
    advancement walks linearly within the filtered set.

    Returns None when no suitable next candidate exists; the cross-tab /
    cross-document cascade then fires client-side.
    """
    view_filters = view_filters or {}
    raw_status = view_filters.get("status")
    db_status = raw_status if raw_status in _VALID_IMAGE_STATUSES else None

    candidates = db.get_image_review_candidates_for_filing_v2(
        filing_id=filing_id,
        status=db_status,
        sort_by="relevance",
        limit=1000,
    )
    if not candidates:
        return None

    current_idx = None
    for i, c in enumerate(candidates):
        if str(c["img_id"]) == current_img_id:
            current_idx = i
            break

    if current_idx is None:
        # Image was removed from the filtered set (e.g. just skipped out of
        # the status=pending view). Scan from the top for the first genuinely
        # pending image rather than falsely signalling queue-empty.
        if db_status not in _AUDIT_IMAGE_STATUSES:
            for c in candidates:
                if c.get("image_review_state") == "pending":
                    next_id = str(c["img_id"])
                    qs = f"img_id={next_id}&tab=images"
                    if db_status:
                        qs += f"&image_status={db_status}"
                    return {"img_id": next_id, "url": f"/v2/review/{filing_id}?{qs}"}
        return None

    if db_status in _AUDIT_IMAGE_STATUSES:
        # Audit mode: walk linearly within the explicitly filtered set.
        next_idx = current_idx + 1
        if next_idx >= len(candidates):
            return None
        next_candidate = candidates[next_idx]
    else:
        # Default review mode: advance to the next image that still needs a
        # decision. `image_review_state` is the derived per-metric rollup field
        # (see DatabaseAdapter._derive_image_review_state); `review_status` is
        # the raw column which stays 'pending' through per-metric decisions by
        # design, so we must not use it here.
        next_candidate = None
        for c in candidates[current_idx + 1 :]:
            if c.get("image_review_state") == "pending":
                next_candidate = c
                break
        if next_candidate is None:
            # Wrap: images before current position (e.g. user navigated
            # directly to a low-relevance thumbnail, skipping earlier ones).
            for c in candidates[:current_idx]:
                if c.get("image_review_state") == "pending":
                    next_candidate = c
                    break
        if next_candidate is None:
            return None

    next_id = str(next_candidate["img_id"])
    if next_id == current_img_id:
        return None

    # Preserve the active image_status filter on the next URL so the strip
    # the reviewer lands on shows the same scope.
    qs = f"img_id={next_id}&tab=images"
    if db_status:
        qs += f"&image_status={db_status}"
    return {
        "img_id": next_id,
        "url": f"/v2/review/{filing_id}?{qs}",
    }


def _get_filing_pending_counts(db, filing_id: int) -> dict[str, int]:
    """Return current pending counts for a filing (post-decision cascade hints).

    Called after a decision write so the client has fresh numbers without
    needing an extra round-trip to decide which tab to navigate to next.
    """
    text_facts = db.get_v2_facts_for_filing(filing_id, status="pending_review")
    text_pending = len(text_facts) if text_facts else 0

    all_images = db.get_image_review_candidates_for_filing_v2(
        filing_id=filing_id, status=None, sort_by="relevance", limit=1000
    )
    image_pending = sum(1 for img in all_images if img.get("image_review_state") == "pending")
    return {"text_pending_count": text_pending, "image_pending_count": image_pending}
