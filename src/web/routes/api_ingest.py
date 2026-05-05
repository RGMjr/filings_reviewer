"""
JSON API endpoints for batch ingestion.

Routes:
  GET  /api/v2/ingest/batches/<uuid>/status  — JSON status + filings list
  POST /api/v2/ingest/batches/<uuid>/cancel  — Soft-cancel a batch
  GET  /api/v2/ingest/filter-options         — Year ↔ industry facet counts
"""

from __future__ import annotations

import json
import logging
import uuid as _uuid

import psycopg
from flask import Blueprint, jsonify, request

from src.auth.middleware import require
from src.auth.permissions import (
    INGEST_RUN,
    PROTECTED_READ,
)
from src.universe.onboarding import (
    FORM_TYPE_BUNDLES,
    OTHER_INDUSTRY_KEY,
    load_industry_map,
    query_universe_form_type_counts,
    query_universe_industry_counts,
    query_universe_other_count,
    query_universe_year_counts,
    resolve_industry,
)
from src.web.app import get_db

api_ingest_bp = Blueprint("api_ingest", __name__, url_prefix="/api/v2/ingest")
logger = logging.getLogger(__name__)

# register_api_auth removed (PR-C1): per-route @require() decorators below
# replace the blueprint-wide API-key gate. Browser traffic authenticates via
# session cookie; non-browser callers continue to use X-API-Key /
# Authorization: ApiKey on routes that still accept the header path.

# All 7 valid filing statuses — always present in counts output
_FILING_STATUSES = (
    "queued",
    "fetching",
    "extracting",
    "persisted",
    "failed",
    "skipped",
    "cancelled",
)


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
@require(PROTECTED_READ)
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
                   criteria, limits,
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
            ORDER BY f.filing_date DESC, c.company_name ASC
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

    # criteria + limits arrive as dict (psycopg JSONB) or str (fallback) — normalise.
    criteria = batch.get("criteria") or {}
    if isinstance(criteria, str):
        try:
            criteria = json.loads(criteria)
        except (json.JSONDecodeError, TypeError):
            criteria = {}

    limits = batch.get("limits") or {}
    if isinstance(limits, str):
        try:
            limits = json.loads(limits)
        except (json.JSONDecodeError, TypeError):
            limits = {}

    populate_progress = limits.get("populate_progress") if isinstance(limits, dict) else None

    payload = {
        "batch_id": str(batch["batch_id"]),
        "kind": batch["kind"],
        "status": batch["status"],
        "reviewer_id": batch["reviewer_id"],
        "total_filings": batch["total_filings"],
        "counts": counts,
        "criteria": criteria,
        "populate_progress": populate_progress,
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
@require(INGEST_RUN)
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


# ---------------------------------------------------------------------------
# GET /api/v2/ingest/filter-options
#
# Year ↔ industry ↔ form-type facet counts for the /ingest/ form. Each axis
# ignores its own selections (standard facet behaviour) so the user always
# sees the full set of options for that axis given the OTHER two axes'
# filters.
# ---------------------------------------------------------------------------


@api_ingest_bp.route("/filter-options", methods=["GET"])
@require(PROTECTED_READ)
def filter_options():
    raw_years = request.args.getlist("year")
    raw_industries = request.args.getlist("industry")
    raw_form_types = request.args.getlist("form_type")

    selected_years: list[int] = []
    for raw in raw_years:
        try:
            selected_years.append(int(raw))
        except (TypeError, ValueError):
            continue  # ignore malformed input rather than 400 — facet is best-effort

    industry_map = load_industry_map()

    # Detect whether the user selected the "Other" pseudo-industry sentinel.
    # The sentinel is stripped before SIC resolution so it never reaches
    # resolve_industry(); the include_other flag carries the signal instead.
    include_other = OTHER_INDUSTRY_KEY in raw_industries
    named_industries = [ind for ind in raw_industries if ind != OTHER_INDUSTRY_KEY]

    selected_sic_codes: list[str] = []
    for ind_name in named_industries:
        try:
            _, codes = resolve_industry(ind_name, industry_map)
        except ValueError:
            continue  # unknown industry → ignored
        selected_sic_codes.extend(codes)
    # Dedupe SIC codes while preserving order
    seen: set[str] = set()
    selected_sic_codes = [s for s in selected_sic_codes if not (s in seen or seen.add(s))]

    # Compute the union of every YAML-mapped SIC code (needed for the
    # Other-partition negation predicate when include_other is True).
    mapped_sic_codes: list[str] = []
    if include_other:
        all_mapped: set[str] = set()
        for entry in (industry_map.get("industries") or {}).values():
            all_mapped.update(entry.get("sic_codes") or [])
        mapped_sic_codes = sorted(all_mapped)

    # Resolve form-type bundle keys (s1f1, 10k, 8k) to canonical form-type
    # strings (S-1, S-1/A, 10-K, ...). Unknown bundle keys are ignored.
    selected_form_types: list[str] = []
    seen_ft: set[str] = set()
    for ft_key in raw_form_types:
        if ft_key in FORM_TYPE_BUNDLES:
            for ft in FORM_TYPE_BUNDLES[ft_key]:
                if ft not in seen_ft:
                    selected_form_types.append(ft)
                    seen_ft.add(ft)

    db = get_db()

    try:
        # Each axis is filtered by the OTHER two axes' selections, ignoring its own.
        # When include_other is True the year/form-type axes restrict to the
        # Other partition (complement of every named-bucket SIC) instead of
        # dropping the SIC predicate entirely.
        year_rows = query_universe_year_counts(
            db,
            sic_codes=selected_sic_codes or None,
            form_types=selected_form_types or None,
            include_other=include_other,
            mapped_sic_codes=mapped_sic_codes if include_other else None,
        )
        industry_rows = query_universe_industry_counts(
            db,
            industry_map,
            years=selected_years or None,
            form_types=selected_form_types or None,
        )
        other_row = query_universe_other_count(
            db,
            industry_map,
            years=selected_years or None,
            form_types=selected_form_types or None,
        )
        form_type_rows = query_universe_form_type_counts(
            db,
            years=selected_years or None,
            sic_codes=selected_sic_codes or None,
            include_other=include_other,
            mapped_sic_codes=mapped_sic_codes if include_other else None,
        )
    except psycopg.DatabaseError as exc:
        logger.error("DB error in filter-options: %s", exc)
        return jsonify({"status": "error", "message": "Database error"}), 500

    payload = {
        "years": [{"year": yc.year, "total": yc.total, "pending": yc.pending} for yc in year_rows],
        "industries": [
            {"key": ic.key, "label": ic.label, "total": ic.total, "pending": ic.pending}
            for ic in industry_rows
        ]
        + [
            {
                "key": other_row.key,
                "label": other_row.label,
                "total": other_row.total,
                "pending": other_row.pending,
            }
        ],
        "form_types": [
            {"key": ftc.key, "label": ftc.label, "total": ftc.total, "pending": ftc.pending}
            for ftc in form_type_rows
        ],
    }
    return jsonify(payload), 200
