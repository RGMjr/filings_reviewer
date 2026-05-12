"""
Admin review tool endpoints.

All routes are protected by @admin_required (flag-independent, always active).
Provides endpoints for auditing suppressed images, reviewing decisions by
reviewer, inspecting an image in context, and writing / undoing admin
override rows on v2_image_metric_confirmations.

Endpoints:
  GET  /admin/review                            — composite UI
  GET  /admin/review/suppressed                 — JSON: paginated suppressed images
  GET  /admin/review/by-reviewer                — JSON: paginated decisions for one reviewer
  GET  /admin/review/image-detail/<img_id>      — JSON: read-only image context
  POST /api/admin/image-decision-override       — write an admin override row
  DELETE /api/admin/image-decision-override/<id> — undo an admin override row
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

import psycopg
from flask import Blueprint, g, jsonify, render_template, request, url_for

from src.auth.admin import admin_required
from src.web.app import get_db
from src.web.url_builders import build_image_cache_url

admin_review_bp = Blueprint("admin_review", __name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SUPPRESSION_REASONS = frozenset(
    {"skipped", "hidden_classification", "low_score", "sentinel_reject"}
)
_VALID_DECISIONS = frozenset({"accept", "reject", "correct", "add"})


def _parse_int_param(value: str | None, default: int, max_val: int) -> int:
    """Parse a query-param integer with a default and ceiling."""
    if not value:
        return default
    try:
        parsed = int(value)
        return min(max(parsed, 0), max_val)
    except (ValueError, TypeError):
        return default


def _parse_bool_param(value: str | None) -> bool | None:
    """Parse 'true'/'false' string to bool, or None if absent."""
    if value is None:
        return None
    return value.lower() in ("1", "true", "yes")


def _get_list_param(args, key: str) -> list[str]:
    """Return all values for a multi-value query param as a list."""
    return args.getlist(key)


def _audit(
    *,
    action_type: str,
    actor_user_id: str,
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any] | None,
) -> None:
    """Write a row to admin_audit_log. Errors are logged but never raised."""
    try:
        db = get_db()
        db.execute(
            """
            INSERT INTO admin_audit_log (
                actor_user_id,
                action_type,
                before_state,
                after_state,
                success
            ) VALUES (
                %(actor_user_id)s,
                %(action_type)s,
                %(before_state)s::jsonb,
                %(after_state)s::jsonb,
                true
            )
            """,
            {
                "actor_user_id": actor_user_id,
                "action_type": action_type,
                "before_state": json.dumps(before_state) if before_state else None,
                "after_state": json.dumps(after_state) if after_state else None,
            },
        )
    except Exception:
        logger.exception("Failed to write admin_audit_log row (action=%s)", action_type)


# ---------------------------------------------------------------------------
# GET /admin/review — placeholder HTML
# ---------------------------------------------------------------------------


@admin_review_bp.route("/admin/review", methods=["GET"])
@admin_required
def admin_review_index():
    """Composite admin review tool — Suppressed Images + Reviewer Audit tabs."""
    db = get_db()
    try:
        recent_reviewers = db.query(
            """
            SELECT reviewer_id, MAX(created_at) AS last_seen
            FROM v2_image_metric_confirmations
            WHERE reviewer_id IS NOT NULL AND reviewer_id != ''
            GROUP BY reviewer_id
            ORDER BY MAX(created_at) DESC
            LIMIT 10
            """,
            {},
        )
    except psycopg.DatabaseError:
        logger.exception("Failed to fetch recent reviewers for admin page")
        recent_reviewers = []
    return render_template("admin_review.html", recent_reviewers=recent_reviewers)


# ---------------------------------------------------------------------------
# GET /admin/review/suppressed
# ---------------------------------------------------------------------------


@admin_review_bp.route("/admin/review/suppressed", methods=["GET"])
@admin_required
def admin_review_suppressed():
    """Return paginated list of suppressed images matching the given filters.

    Query params:
      suppression_reason  — multi-select: skipped / hidden_classification /
                            low_score / sentinel_reject
      classification      — multi-select
      score_min, score_max
      company             — substring match on company_name
      filing_date_from, filing_date_to  — ISO date
      limit (default 20, max 100), offset (default 0)
    """
    db = get_db()

    limit = _parse_int_param(request.args.get("limit"), default=20, max_val=100)
    offset = _parse_int_param(request.args.get("offset"), default=0, max_val=10_000_000)

    raw_reasons = _get_list_param(request.args, "suppression_reason")
    invalid = [r for r in raw_reasons if r not in _VALID_SUPPRESSION_REASONS]
    if invalid:
        return (
            jsonify(
                {
                    "error": f"Invalid suppression_reason value(s): {invalid}. "
                    f"Must be one of: {sorted(_VALID_SUPPRESSION_REASONS)}"
                }
            ),
            400,
        )

    filters: dict[str, Any] = {}
    if raw_reasons:
        filters["suppression_reason"] = raw_reasons

    raw_classifications = _get_list_param(request.args, "classification")
    if raw_classifications:
        filters["classification"] = raw_classifications

    score_min = request.args.get("score_min")
    if score_min is not None:
        try:
            filters["score_min"] = float(score_min)
        except ValueError:
            return jsonify({"error": "score_min must be a number"}), 400

    score_max = request.args.get("score_max")
    if score_max is not None:
        try:
            filters["score_max"] = float(score_max)
        except ValueError:
            return jsonify({"error": "score_max must be a number"}), 400

    company = request.args.get("company")
    if company:
        filters["company"] = company

    filing_date_from = request.args.get("filing_date_from")
    if filing_date_from:
        filters["filing_date_from"] = filing_date_from

    filing_date_to = request.args.get("filing_date_to")
    if filing_date_to:
        filters["filing_date_to"] = filing_date_to

    try:
        images, total = db.get_admin_suppressed_images(filters, limit=limit, offset=offset)
    except psycopg.DatabaseError as exc:
        logger.error("DB error in admin_review_suppressed: %s", exc, exc_info=True)
        return jsonify({"error": "database error"}), 500

    # Serialize datetime objects for JSON
    for img in images:
        for k, v in img.items():
            if hasattr(v, "isoformat"):
                img[k] = v.isoformat()

    return jsonify({"images": images, "total": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# GET /admin/review/by-reviewer
# ---------------------------------------------------------------------------


@admin_review_bp.route("/admin/review/by-reviewer", methods=["GET"])
@admin_required
def admin_review_by_reviewer():
    """Return paginated decisions for a specific reviewer.

    Query params:
      reviewer_id (required)
      decision        — multi-select: accept/reject/correct/add/skip
      metric_id       — multi-select
      date_from, date_to
      rejection_reason — multi-select
      has_admin_override — true/false
      limit, offset
    """
    db = get_db()

    reviewer_id = request.args.get("reviewer_id")
    if not reviewer_id:
        return jsonify({"error": "reviewer_id is required"}), 400

    limit = _parse_int_param(request.args.get("limit"), default=20, max_val=100)
    offset = _parse_int_param(request.args.get("offset"), default=0, max_val=10_000_000)

    filters: dict[str, Any] = {}

    raw_decisions = _get_list_param(request.args, "decision")
    if raw_decisions:
        filters["decision"] = raw_decisions

    raw_metrics = _get_list_param(request.args, "metric_id")
    if raw_metrics:
        filters["metric_id"] = raw_metrics

    date_from = request.args.get("date_from")
    if date_from:
        filters["date_from"] = date_from

    date_to = request.args.get("date_to")
    if date_to:
        filters["date_to"] = date_to

    raw_rr = _get_list_param(request.args, "rejection_reason")
    if raw_rr:
        filters["rejection_reason"] = raw_rr

    has_override_param = request.args.get("has_admin_override")
    has_override = _parse_bool_param(has_override_param)
    if has_override is not None:
        filters["has_admin_override"] = has_override

    try:
        decisions, total = db.get_decisions_by_reviewer(
            reviewer_id, filters, limit=limit, offset=offset
        )
    except psycopg.DatabaseError as exc:
        logger.error("DB error in admin_review_by_reviewer: %s", exc, exc_info=True)
        return jsonify({"error": "database error"}), 500

    # Serialize datetime objects
    for dec in decisions:
        for k, v in dec.items():
            if hasattr(v, "isoformat"):
                dec[k] = v.isoformat()

    return jsonify({"decisions": decisions, "total": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# GET /admin/review/image-detail/<img_id>
# ---------------------------------------------------------------------------


@admin_review_bp.route("/admin/review/image-detail/<uuid:img_id>", methods=["GET"])
@admin_required
def admin_review_image_detail(img_id):
    """Return read-only context for a single image in the admin tool.

    Response shape:
      {
        "image": {...image cols + image_url for <img src>...},
        "filing": {...filing + company cols...},
        "confirmations": [...per-metric rows, ASC by created_at, up to 50...],
        "deep_link_url": "/v2/review/<filing_id>?img_id=<uuid>&tab=images"
      }

    Read-only: does NOT write to admin_audit_log.
    """
    db = get_db()
    try:
        detail = db.get_image_detail_for_admin(str(img_id))
    except psycopg.DatabaseError as exc:
        logger.error("DB error in admin_review_image_detail: %s", exc, exc_info=True)
        return jsonify({"error": "database error"}), 500

    if detail is None:
        return jsonify({"error": "image not found"}), 404

    filing = detail["filing"]
    image = detail["image"]

    image["image_url"] = build_image_cache_url(
        filing.get("cik"),
        filing.get("accession_number"),
        image["filename"],
    )

    deep_link_path = url_for("review_unified.review_filing", filing_id=filing["filing_id"])
    detail["deep_link_url"] = f"{deep_link_path}?img_id={image['img_id']}&tab=images"

    for section in (image, filing):
        for k, v in list(section.items()):
            if hasattr(v, "isoformat"):
                section[k] = v.isoformat()
    for conf in detail["confirmations"]:
        for k, v in list(conf.items()):
            if hasattr(v, "isoformat"):
                conf[k] = v.isoformat()

    return jsonify(detail)


# ---------------------------------------------------------------------------
# POST /api/admin/image-decision-override
# ---------------------------------------------------------------------------


@admin_review_bp.route("/api/admin/image-decision-override", methods=["POST"])
@admin_required
def create_admin_image_decision_override():
    """Write an admin override row (one per decision entry).

    Body JSON:
      {
        "img_id": "<uuid>",
        "decisions": [{"decision": "...", "detected_metric_id": "...", ...}],
        "override_reason": "<string, min 5 chars>",
        "supersedes_confirmation_id": "<uuid or null>"
      }

    Returns {"ok": true, "confirmation_ids": [<uuid>, ...]}
    """
    db = get_db()

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    # Validate img_id
    img_id_raw = data.get("img_id")
    if not img_id_raw:
        return jsonify({"error": "img_id is required"}), 400
    try:
        img_id = str(_uuid.UUID(str(img_id_raw)))
    except (ValueError, AttributeError):
        return jsonify({"error": "img_id must be a valid UUID"}), 400

    # Validate override_reason
    override_reason: str = data.get("override_reason") or ""
    override_reason = override_reason.strip()
    if len(override_reason) < 5:
        return jsonify({"error": "override_reason is required (min 5 characters)"}), 400

    # Validate decisions list
    decisions_raw = data.get("decisions")
    if decisions_raw is None:
        return jsonify({"error": "decisions is required"}), 400
    if not isinstance(decisions_raw, list) or len(decisions_raw) == 0:
        return jsonify({"error": "decisions must be a non-empty list"}), 400

    validated_decisions: list[dict[str, Any]] = []
    for i, d in enumerate(decisions_raw):
        prefix = f"decisions[{i}]"
        if not isinstance(d, dict):
            return jsonify({"error": f"{prefix}: must be an object"}), 400

        decision = d.get("decision")
        if decision not in _VALID_DECISIONS:
            return jsonify(
                {
                    "error": f"{prefix}.decision must be one of: "
                    f"{', '.join(sorted(_VALID_DECISIONS))}"
                }
            ), 400

        validated_decisions.append(
            {
                "decision": decision,
                "detected_metric_id": d.get("detected_metric_id") or None,
                "confirmed_metric_id": d.get("confirmed_metric_id") or None,
                "rejection_reason": d.get("rejection_reason") or None,
            }
        )

    # Validate optional supersedes_confirmation_id
    supersedes_raw = data.get("supersedes_confirmation_id")
    supersedes_id: str | None = None
    if supersedes_raw:
        try:
            supersedes_id = str(_uuid.UUID(str(supersedes_raw)))
        except (ValueError, AttributeError):
            return jsonify({"error": "supersedes_confirmation_id must be a valid UUID"}), 400

    admin_user_id = g.user.id

    try:
        # Snapshot the superseded row for audit log
        before_state: dict[str, Any] | None = None
        if supersedes_id:
            rows = db.query(
                """
                SELECT
                    id::text AS id,
                    img_id::text AS img_id,
                    reviewer_id,
                    decision,
                    detected_metric_id,
                    confirmed_metric_id,
                    rejection_reason,
                    created_at::text AS created_at
                FROM v2_image_metric_confirmations
                WHERE id = %(sid)s
                """,
                {"sid": supersedes_id},
            )
            if rows:
                before_state = dict(rows[0])

        new_ids = db.insert_admin_override(
            img_id=img_id,
            decisions=validated_decisions,
            override_reason=override_reason,
            supersedes_id=supersedes_id,
            admin_user_id=admin_user_id,
        )

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except psycopg.DatabaseError as exc:
        logger.error("DB error in create_admin_image_decision_override: %s", exc, exc_info=True)
        return jsonify({"error": "database error"}), 500

    after_state: dict[str, Any] = {
        "img_id": img_id,
        "decisions": validated_decisions,
        "override_reason": override_reason,
        "confirmation_ids": new_ids,
    }

    action_type = (
        "image.admin_override_create" if supersedes_id else "image.admin_review_suppressed"
    )
    _audit(
        action_type=action_type,
        actor_user_id=admin_user_id,
        before_state=before_state,
        after_state=after_state,
    )

    return jsonify({"ok": True, "confirmation_ids": new_ids})


# ---------------------------------------------------------------------------
# DELETE /api/admin/image-decision-override/<override_id>
# ---------------------------------------------------------------------------


@admin_review_bp.route("/api/admin/image-decision-override/<uuid:override_id>", methods=["DELETE"])
@admin_required
def delete_admin_image_decision_override(override_id):
    """Undo an admin override row.

    Returns 404 if not found; 400 if the row is not an admin row.
    Logs to admin_audit_log with action_type 'image.admin_override_undo'.
    """
    db = get_db()
    admin_user_id = g.user.id

    # First check whether the row exists at all (to distinguish 404 vs 400)
    existing_rows = db.query(
        """
        SELECT
            id::text AS id,
            reviewer_id,
            override_reason IS NOT NULL AS is_admin_row
        FROM v2_image_metric_confirmations
        WHERE id = %(override_id)s
        """,
        {"override_id": str(override_id)},
    )
    if not existing_rows:
        return jsonify({"error": "override not found"}), 404
    if not existing_rows[0]["is_admin_row"]:
        return jsonify({"error": "row is not an admin override (override_reason is null)"}), 400

    try:
        deleted = db.delete_admin_override(
            override_id=str(override_id),
            admin_user_id=admin_user_id,
        )
    except psycopg.DatabaseError as exc:
        logger.error("DB error in delete_admin_image_decision_override: %s", exc, exc_info=True)
        return jsonify({"error": "database error"}), 500

    if deleted is None:
        # Row exists but does not belong to this admin — 400 not 404
        return jsonify({"error": "override not found or not owned by this admin"}), 400

    _audit(
        action_type="image.admin_override_undo",
        actor_user_id=admin_user_id,
        before_state=deleted,
        after_state=None,
    )

    return jsonify({"ok": True, "deleted": deleted})
