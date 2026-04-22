"""
Flask HTML blueprint for batch ingestion UI.

Routes:
  GET  /ingest/             — Criteria form
  POST /ingest/preview      — Resolve criteria, discover candidates, render preview
  POST /ingest/start        — Create batch rows, spawn runner, redirect to progress page
  GET  /ingest/batch/<uuid> — Progress page (server-rendered initial state; Wave C adds polling)
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid as _uuid
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

from src.universe.onboarding import (
    FORM_TYPE_BUNDLES,
    VolumeBand,
    classify_volume,
    count_reviewer_work,
    discover,
    load_industry_map,
    resolve_criteria,
)
from src.web.app import get_db

ingest_bp = Blueprint("ingest", __name__, url_prefix="/ingest")
logger = logging.getLogger(__name__)

# Project root — used for subprocess cwd and log path
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _industry_options() -> list[dict[str, str]]:
    """Return sorted list of industry options from industry_sic_codes.yaml."""
    try:
        ind_map = load_industry_map()
        return sorted(
            [{"key": k, "label": k.replace("_", " ").title()} for k in ind_map["industries"]],
            key=lambda x: x["label"],
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load industry map", exc_info=True)
        return []


def _parse_form_criteria() -> dict[str, Any]:
    """Extract criteria dict from a POST form submission."""
    industries = request.form.getlist("industries")
    sic_codes_raw = request.form.get("sic_codes", "").strip()
    form_types = request.form.getlist("form_types")
    year = request.form.get("year", "").strip()
    reviewer_name = request.form.get("reviewer_name", "").strip()
    company_name_ilike = request.form.get("company_name_ilike", "").strip() or None

    return {
        "industries": industries,
        "sic_codes": sic_codes_raw,
        "form_types": form_types if form_types else ["s1f1"],
        "year": year,
        "company_name_ilike": company_name_ilike,
        "_reviewer_name": reviewer_name,
    }


def _volume_band_alert_class(band: VolumeBand) -> str:
    mapping = {
        VolumeBand.OK: "alert-success",
        VolumeBand.SOFT_WARN: "alert-warning",
        VolumeBand.HARD_WARN: "alert-warning",
        VolumeBand.REFINE: "alert-danger",
        VolumeBand.BLOCK: "alert-danger",
    }
    return mapping.get(band, "alert-secondary")


def _volume_band_message(band: VolumeBand, total: int) -> str:
    messages = {
        VolumeBand.OK: f"{total} filings — proceed when ready.",
        VolumeBand.SOFT_WARN: f"{total} filings — this is a larger batch; review before starting.",
        VolumeBand.HARD_WARN: (
            f"{total} filings — large batch (200–499). Acknowledge below to proceed."
        ),
        VolumeBand.REFINE: (
            f"{total} filings — too many (500–999). Add more criteria to narrow the scope."
        ),
        VolumeBand.BLOCK: (
            f"{total} filings — blocked (1000+). Refine criteria significantly before proceeding."
        ),
    }
    return messages.get(band, f"{total} filings.")


_FORM_TYPES_AVAILABLE = [
    {"key": "s1f1", "label": "S-1 / F-1 (IPO filings)"},
    {"key": "10k", "label": "10-K (Annual reports)"},
    {"key": "8k", "label": "8-K (Current reports)"},
]


def _render_ingest_form(form_state: dict[str, Any] | None = None, status: int = 200):
    """Render the criteria form. When *form_state* is given, the template
    repopulates fields so a validation error doesn't wipe user input.
    """
    state = form_state or {}
    reviewer_name = state.get("_reviewer_name") or request.cookies.get("ingest_reviewer", "")
    return (
        render_template(
            "ingest_form.html",
            reviewer_name=reviewer_name,
            industries=_industry_options(),
            form_types_available=_FORM_TYPES_AVAILABLE,
            form_state=state,
        ),
        status,
    )


# ---------------------------------------------------------------------------
# GET /ingest/
# ---------------------------------------------------------------------------


@ingest_bp.route("/", methods=["GET"])
def ingest_form():
    return _render_ingest_form()


# ---------------------------------------------------------------------------
# POST /ingest/preview
# ---------------------------------------------------------------------------


@ingest_bp.route("/preview", methods=["POST"])
def ingest_preview():
    raw = _parse_form_criteria()

    try:
        query = resolve_criteria(raw)
    except ValueError as exc:
        flash(str(exc), "danger")
        return _render_ingest_form(form_state=raw, status=400)

    reviewer_name = raw.pop("_reviewer_name", "")

    db = get_db()

    result = discover(db, query)
    all_candidates = result.new + result.already_extracted

    # Batch-fetch reviewer work counts for already-extracted candidates
    already_ids = [c.filing_id for c in result.already_extracted]
    reviewer_work = count_reviewer_work(db, already_ids) if already_ids else {}

    # Split already_extracted into reviewed / not-reviewed
    already_no_review = []
    already_reviewed = []
    for c in result.already_extracted:
        decision_count, _ = reviewer_work.get(c.filing_id, (0, 0))
        if decision_count > 0:
            already_reviewed.append((c, decision_count))
        else:
            already_no_review.append(c)

    total = len(all_candidates)
    band = classify_volume(total)
    band_class = _volume_band_alert_class(band)
    band_message = _volume_band_message(band, total)
    submit_disabled = band in (VolumeBand.REFINE, VolumeBand.BLOCK)

    # Serialize query + criteria for hidden fields in the start form
    criteria_json = json.dumps(raw)
    resolved_json = json.dumps(
        {
            "sic_codes": query.sic_codes,
            "form_types": query.form_types,
            "year_min": query.year_min,
            "year_max": query.year_max,
            "include_amendments": query.include_amendments,
            "company_name_ilike": query.company_name_ilike,
        }
    )

    response = make_response(
        render_template(
            "ingest_preview.html",
            new_candidates=result.new,
            already_no_review=already_no_review,
            already_reviewed=already_reviewed,
            gaps=result.gaps,
            total=total,
            band=band,
            band_class=band_class,
            band_message=band_message,
            submit_disabled=submit_disabled,
            reviewer_name=reviewer_name,
            criteria_json=criteria_json,
            resolved_json=resolved_json,
        )
    )
    if reviewer_name:
        response.set_cookie("ingest_reviewer", reviewer_name, max_age=30 * 24 * 3600)
    return response


# ---------------------------------------------------------------------------
# POST /ingest/start
# ---------------------------------------------------------------------------


@ingest_bp.route("/start", methods=["POST"])
def ingest_start():
    reviewer_name = request.form.get("reviewer_name", "").strip()
    hard_warn_ack = request.form.get("hard_warn_ack") == "on"
    reextract_reviewed_ack = request.form.get("reextract_reviewed_ack") == "on"
    filing_ids_raw = request.form.getlist("filing_id")

    if not filing_ids_raw:
        flash("No filings selected.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    try:
        filing_ids = [int(fid) for fid in filing_ids_raw]
    except ValueError:
        flash("Invalid filing ID list.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    if not reviewer_name:
        flash("Reviewer name is required.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    # Server-side volume enforcement — never trust client
    total = len(filing_ids)
    band = classify_volume(total)
    if band in (VolumeBand.REFINE, VolumeBand.BLOCK):
        flash(
            f"Submission rejected: {band.value.upper()} volume ({total} filings). "
            "Add more criteria to narrow the scope.",
            "danger",
        )
        return (
            render_template(
                "ingest_form.html",
                reviewer_name=reviewer_name,
                industries=_industry_options(),
                form_types_available=[
                    {"key": "s1f1", "label": "S-1 / F-1 (IPO filings)"},
                    {"key": "10k", "label": "10-K (Annual reports)"},
                    {"key": "8k", "label": "8-K (Current reports)"},
                ],
            ),
            400,
        )
    if band == VolumeBand.HARD_WARN and not hard_warn_ack:
        flash(
            "Large batch acknowledgement required. Please check the confirmation box.",
            "danger",
        )
        return (
            render_template(
                "ingest_form.html",
                reviewer_name=reviewer_name,
                industries=_industry_options(),
                form_types_available=[
                    {"key": "s1f1", "label": "S-1 / F-1 (IPO filings)"},
                    {"key": "10k", "label": "10-K (Annual reports)"},
                    {"key": "8k", "label": "8-K (Current reports)"},
                ],
            ),
            400,
        )

    # Determine per-filing bucket and reextract flag
    filing_buckets: dict[int, str] = {}
    reextract_decisions: dict[int, bool] = {}
    has_reviewed_reextract = False

    for fid in filing_ids:
        reextract_cb = request.form.get(f"reextract_{fid}") == "on"
        bucket_hidden = request.form.get(f"bucket_{fid}", "new")
        filing_buckets[fid] = bucket_hidden
        if reextract_cb:
            reextract_decisions[fid] = True
            if bucket_hidden == "reextract_reviewed":
                has_reviewed_reextract = True

    # Guard: reviewed-filing re-extraction requires ack
    if has_reviewed_reextract and not reextract_reviewed_ack:
        flash(
            "You must confirm that you understand re-extracting reviewed filings will "
            "delete human review decisions. Check the confirmation checkbox.",
            "danger",
        )
        return redirect(url_for("ingest.ingest_form")), 400

    # Reconstruct criteria/resolved for DB columns from hidden fields
    criteria_json = request.form.get("criteria_json", "{}")
    resolved_json = request.form.get("resolved_json", "{}")

    try:
        criteria_data = json.loads(criteria_json)
        resolved_data = json.loads(resolved_json)
    except json.JSONDecodeError:
        flash("Corrupted form data. Please start over.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    limits_data = {
        "band": band.value,
        "total_filings": total,
        "hard_warn_ack": hard_warn_ack,
    }

    db = get_db()

    # Create batch in a single transaction
    batch_id: str | None = None
    try:
        with db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO v2_ingest_batches
                        (kind, reviewer_id, criteria, resolved_query, limits, total_filings, status)
                    VALUES ('onboard', %(reviewer)s, %(criteria)s::jsonb, %(resolved)s::jsonb,
                            %(limits)s::jsonb, %(total)s, 'queued')
                    RETURNING batch_id
                    """,
                    {
                        "reviewer": reviewer_name,
                        "criteria": json.dumps(criteria_data),
                        "resolved": json.dumps(resolved_data),
                        "limits": json.dumps(limits_data),
                        "total": total,
                    },
                )
                row = cur.fetchone()
                batch_id = str(row["batch_id"])

                for fid in filing_ids:
                    bucket = filing_buckets.get(fid, "new")
                    cur.execute(
                        """
                        INSERT INTO v2_ingest_batch_filings
                            (batch_id, filing_id, initial_bucket, current_status)
                        VALUES (%(batch_id)s, %(filing_id)s, %(bucket)s, 'queued')
                        """,
                        {
                            "batch_id": batch_id,
                            "filing_id": fid,
                            "bucket": bucket,
                        },
                    )
    except Exception as exc:
        logger.error("Failed to create ingest batch: %s", exc, exc_info=True)
        flash("Database error creating batch. Please try again.", "danger")
        return redirect(url_for("ingest.ingest_form")), 500

    # Spawn runner subprocess (guarded by config flag for tests)
    if current_app.config.get("INGEST_SPAWN_SUBPROCESS", True):
        log_dir = _PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"ingest_runner_{batch_id}.log"
        try:
            subprocess.Popen(
                [sys.executable, "-m", "src.universe.onboarding_runner", "--batch-id", batch_id],
                start_new_session=True,
                stdout=open(log_path, "ab"),  # noqa: SIM115
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
            )
            logger.info("Spawned onboarding_runner for batch_id=%s", batch_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to spawn runner for batch %s: %s", batch_id, exc)
            flash(
                "Batch created but runner could not be spawned. "
                "Contact an administrator to start processing.",
                "warning",
            )

    resp = redirect(url_for("ingest.ingest_batch", batch_id=batch_id))
    resp.set_cookie("ingest_reviewer", reviewer_name, max_age=30 * 24 * 3600)
    return resp


# ---------------------------------------------------------------------------
# POST /ingest/populate
# ---------------------------------------------------------------------------

# Year range guard
_POPULATE_YEAR_MIN = 1990
_POPULATE_YEAR_MAX = 2030


@ingest_bp.route("/populate", methods=["POST"])
def populate():
    """Create a kind='populate' batch and redirect to its progress page."""
    reviewer_name = request.form.get("reviewer_name", "").strip()
    year_raw = request.form.get("year", "").strip()
    form_type = request.form.get("form_type", "").strip()

    # Validate reviewer_name
    if not reviewer_name:
        flash("Reviewer name is required.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    # Validate year
    try:
        year = int(year_raw)
    except (ValueError, TypeError):
        flash("Year must be a valid integer.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    if not (_POPULATE_YEAR_MIN <= year <= _POPULATE_YEAR_MAX):
        flash(f"Year must be between {_POPULATE_YEAR_MIN} and {_POPULATE_YEAR_MAX}.", "danger")
        return redirect(url_for("ingest.ingest_form")), 400

    # Validate form_type
    if not form_type or form_type not in FORM_TYPE_BUNDLES:
        flash(
            f"Unknown form type {form_type!r}. Known: {', '.join(sorted(FORM_TYPE_BUNDLES))}.",
            "danger",
        )
        return redirect(url_for("ingest.ingest_form")), 400

    db = get_db()

    # Create populate batch row (no v2_ingest_batch_filings rows)
    batch_id: str | None = None
    try:
        with db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO v2_ingest_batches
                        (kind, reviewer_id, criteria, resolved_query, limits,
                         total_filings, status)
                    VALUES ('populate', %(reviewer)s, %(criteria)s::jsonb,
                            '{}', '{}', NULL, 'queued')
                    RETURNING batch_id
                    """,
                    {
                        "reviewer": reviewer_name,
                        "criteria": json.dumps({"year": year, "form_type": form_type}),
                    },
                )
                row = cur.fetchone()
                batch_id = str(row["batch_id"])
    except Exception as exc:
        logger.error("Failed to create populate batch: %s", exc, exc_info=True)
        flash("Database error creating batch. Please try again.", "danger")
        return redirect(url_for("ingest.ingest_form")), 500

    # Spawn runner subprocess (guarded by config flag for tests)
    if current_app.config.get("INGEST_SPAWN_SUBPROCESS", True):
        log_dir = _PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"ingest_runner_{batch_id}.log"
        try:
            subprocess.Popen(
                [sys.executable, "-m", "src.universe.onboarding_runner", "--batch-id", batch_id],
                start_new_session=True,
                stdout=open(log_path, "ab"),  # noqa: SIM115
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT),
            )
            logger.info("Spawned onboarding_runner for populate batch_id=%s", batch_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to spawn runner for populate batch %s: %s", batch_id, exc)
            flash(
                "Batch created but runner could not be spawned. "
                "Contact an administrator to start processing.",
                "warning",
            )

    resp = redirect(url_for("ingest.ingest_batch", batch_id=batch_id))
    resp.set_cookie("ingest_reviewer", reviewer_name, max_age=30 * 24 * 3600)
    return resp


# ---------------------------------------------------------------------------
# GET /ingest/batch/<uuid>
# ---------------------------------------------------------------------------


@ingest_bp.route("/batch/<batch_id>", methods=["GET"])
def ingest_batch(batch_id: str):
    # Validate UUID format
    try:
        _uuid.UUID(batch_id)
    except ValueError:
        flash("Invalid batch ID.", "danger")
        return redirect(url_for("ingest.ingest_form"))

    db = get_db()

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
    if not batch_rows:
        flash("Batch not found.", "danger")
        return redirect(url_for("ingest.ingest_form"))

    batch = dict(batch_rows[0])
    # Deserialize JSONB fields if returned as strings
    for field in ("criteria", "limits"):
        if isinstance(batch.get(field), str):
            try:
                batch[field] = json.loads(batch[field])
            except (ValueError, TypeError):
                batch[field] = {}
        elif batch.get(field) is None:
            batch[field] = {}

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
    filings = [dict(r) for r in filing_rows]

    # Compute counts for progress bar
    status_counts: dict[str, int] = {
        "queued": 0,
        "fetching": 0,
        "extracting": 0,
        "persisted": 0,
        "failed": 0,
        "skipped": 0,
        "cancelled": 0,
    }
    for f in filings:
        s = f.get("current_status", "queued")
        if s in status_counts:
            status_counts[s] += 1

    total = batch.get("total_filings") or len(filings)
    done = status_counts["persisted"] + status_counts["failed"] + status_counts["skipped"]

    return render_template(
        "ingest_batch.html",
        batch=batch,
        filings=filings,
        status_counts=status_counts,
        total=total,
        done=done,
    )
