"""
Flask routes for presentation image review.

File-based (no database required). Reads image candidates from
data/presentation_gold_standard/{key}_image_candidates.json.
"""

import logging

from flask import Blueprint, abort, jsonify, render_template, request

from src.web.pres_image_store import (
    get_edgar_url,
    get_filing_keys,
    get_progress,
    load_candidates,
    load_decisions,
    save_decision,
    undo_decision,
)

review_pres_images_bp = Blueprint("review_pres_images", __name__, url_prefix="/review/pres-images")
logger = logging.getLogger(__name__)

CHART_TYPES = [
    ("cohort_table", "Cohort Table"),
    ("cohort_parfait", "Cohort Parfait"),
    ("line_chart", "Line Chart"),
    ("bar_chart", "Bar Chart"),
    ("stacked_bar", "Stacked Bar"),
    ("other_chart", "Other Chart"),
]

REJECTION_REASONS = [
    ("decorative", "Decorative / Logo"),
    ("not_a_chart", "Not a Chart"),
    ("wrong_subject", "Wrong Subject"),
    ("duplicate", "Duplicate"),
    ("unreadable", "Unreadable"),
    ("other", "Other"),
]


@review_pres_images_bp.route("/")
def index():
    """List all filings with image candidates."""
    keys = get_filing_keys()
    filings = []
    for key in keys:
        progress = get_progress(key)
        parts = key.split("_")
        ticker = parts[0] if parts else key
        filings.append({"key": key, "ticker": ticker, **progress})
    return render_template("pres_image_filing_list.html", filings=filings)


@review_pres_images_bp.route("/<key>")
def review_filing(key: str):
    """Image review interface for one filing."""
    candidates = load_candidates(key)
    if not candidates:
        abort(404)

    decisions = load_decisions()
    # Annotate candidates with decision data
    for c in candidates:
        d = decisions.get(f"{key}:{c['img_id']}")
        c["decision"] = d["decision"] if d else None
        c["chart_type"] = d.get("chart_type", "") if d else ""
        c["rejection_reason"] = d.get("rejection_reason", "") if d else ""
        c["notes"] = d.get("notes", "") if d else ""
        c["status"] = d["decision"] if d else "pending"

    # Select current candidate
    img_id_param = request.args.get("img_id")
    current = None
    if img_id_param:
        current = next((c for c in candidates if c["img_id"] == img_id_param), None)
    if not current:
        # First pending
        current = next(
            (c for c in candidates if c["status"] == "pending"),
            candidates[0] if candidates else None,
        )

    if not current:
        abort(404)

    progress = get_progress(key)
    parts = key.split("_")
    ticker = parts[0] if parts else key

    return render_template(
        "review_pres_images.html",
        key=key,
        ticker=ticker,
        edgar_url=get_edgar_url(key),
        candidates=candidates,
        current=current,
        progress=progress,
        chart_types=CHART_TYPES,
        rejection_reasons=REJECTION_REASONS,
    )


@review_pres_images_bp.route("/<key>/<img_id>/decide", methods=["POST"])
def decide(key: str, img_id: str):
    """Save a review decision."""
    data = request.get_json(force=True)
    decision = data.get("decision", "")
    if decision not in ("relevant", "not_relevant", "skip"):
        return jsonify({"error": "Invalid decision"}), 400

    save_decision(
        key=key,
        img_id=img_id,
        decision=decision,
        chart_type=data.get("chart_type", ""),
        rejection_reason=data.get("rejection_reason", ""),
        notes=data.get("notes", ""),
    )
    return jsonify({"ok": True})


@review_pres_images_bp.route("/<key>/<img_id>/decide", methods=["DELETE"])
def undo(key: str, img_id: str):
    """Undo a review decision."""
    undo_decision(key, img_id)
    return jsonify({"ok": True})
