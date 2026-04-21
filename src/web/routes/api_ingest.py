"""
JSON API endpoints for batch ingestion.

Routes:
  GET  /api/v2/ingest/batches/<uuid>/status  — JSON status + filings list
  POST /api/v2/ingest/batches/<uuid>/cancel  — Soft-cancel a batch
"""

from __future__ import annotations

import logging
import uuid as _uuid

import psycopg
from flask import Blueprint, jsonify

from src.web.app import get_db
from src.web.middleware import register_api_auth

api_ingest_bp = Blueprint("api_ingest", __name__, url_prefix="/api/v2/ingest")
logger = logging.getLogger(__name__)

register_api_auth(api_ingest_bp)

# All 7 valid filing statuses — always present in counts output
_FILING_STATUSES = ("queued", "fetching", "extracting", "persisted", "failed", "skipped", "cancelled")


def _format_ts(ts) -> str | None:
    """Format a datetime to ISO 8601 with Z suffix, or return None."""
    if ts is None:
        return None
    # psycopg returns aware datetimes; isoformat gives +00:00, swap to Z
    s = ts.isoformat()
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


# ---------------------------------------------------------------------------
# GET /api/v2/ingest/batches/<uuid>/status
# ---------------------------------------------------------------------------


@api_ingest_bp.route("/batches/<batch_id>/status", methods=["GET"])
def batch_status(batch_id: str):
    try:
        _uuid.UUID(batch_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid batch ID"}), 400

    db = get_db()

    try:
        batch_rows = db.query(
            """
            SELECT batch_id, kind, status, reviewer_id, total_filings,
                   created_at, started_at, finished_at, cancelled_at, error
            FROM v2_ingest_batches
            WHERE batch_id = %(batch_id)s
            """,
            {"batch_id": batch_id},
        )
    except psycopg.DatabaseError as exc:
        logger.error("DB error fetching batch %s: %s", batch_id, exc)
        return jsonify({"status": "error", "message": "Database error"}), 500

    if not batch_rows:
        return jsonify({"status": "error", "message": "Batch not found"}), 404

    batch = batch_rows[0]

    # Fetch all filings with JOIN to get ticker, company_name, form_type, filing_date
    try:
        filing_rows = db.query(
            """
            SELECT ibf.filing_id, ibf.initial_bucket, ibf.current_status,
                   ibf.fact_count, ibf.error, ibf.started_at, ibf.finished_at,
                   f.form_type, f.filing_date,
                   c.company_name, c.ticker
            FROM v2_ingest_batch_filings ibf
            JOIN filings f ON f.filing_id = ibf.filing_id
            JOIN companies c ON c.company_id = f.company_id
            WHERE ibf.batch_id = %(batch_id)s
            ORDER BY f.filing_date, c.company_name
            """,
            {"batch_id": batch_id},
        )
    except psycopg.DatabaseError as exc:
        logger.error("DB error fetching filings for batch %s: %s", batch_id, exc)
        return jsonify({"status": "error", "message": "Database error"}), 500

    # Build counts — always include all 7 statuses
    counts: dict[str, int] = {s: 0 for s in _FILING_STATUSES}
    filings_out = []
    for row in filing_rows:
        s = row["current_status"]
        if s in counts:
            counts[s] += 1
        filing_date = row["filing_date"]
        filings_out.append(
            {
                "filing_id": row["filing_id"],
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "form_type": row["form_type"],
                "filing_date": str(filing_date) if filing_date else None,
                "initial_bucket": row["initial_bucket"],
                "current_status": row["current_status"],
                "fact_count": row["fact_count"],
                "error": row["error"],
                "started_at": _format_ts(row["started_at"]),
                "finished_at": _format_ts(row["finished_at"]),
            }
        )

    payload = {
        "batch_id": str(batch["batch_id"]),
        "kind": batch["kind"],
        "status": batch["status"],
        "reviewer_id": batch["reviewer_id"],
        "total_filings": batch["total_filings"],
        "counts": counts,
        "created_at": _format_ts(batch["created_at"]),
        "started_at": _format_ts(batch["started_at"]),
        "finished_at": _format_ts(batch["finished_at"]),
        "cancelled_at": _format_ts(batch["cancelled_at"]),
        "error": batch["error"],
        "filings": filings_out,
    }
    return jsonify(payload), 200


# ---------------------------------------------------------------------------
# POST /api/v2/ingest/batches/<uuid>/cancel
# ---------------------------------------------------------------------------


@api_ingest_bp.route("/batches/<batch_id>/cancel", methods=["POST"])
def batch_cancel(batch_id: str):
    try:
        _uuid.UUID(batch_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid batch ID"}), 400

    db = get_db()

    try:
        rows = db.query(
            """
            UPDATE v2_ingest_batches
            SET status = 'cancelled', cancelled_at = NOW()
            WHERE batch_id = %(batch_id)s
              AND status IN ('queued', 'running')
            RETURNING batch_id
            """,
            {"batch_id": batch_id},
        )
    except psycopg.DatabaseError as exc:
        logger.error("DB error cancelling batch %s: %s", batch_id, exc)
        return jsonify({"status": "error", "message": "Database error"}), 500

    if not rows:
        # Idempotent: batch already cancelled/complete, or not found
        return jsonify({"status": "ok", "message": "no-op"}), 200

    return jsonify({"status": "ok"}), 200
