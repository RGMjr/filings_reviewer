#!/usr/bin/env python3
"""
Export image training data for relevance model development.

Unifies human review decisions from two sources:
  - SEC filing image decisions (PostgreSQL DB via image_review_decisions)
  - Presentation image decisions (file-based, data/presentation_gold_standard/)

Outputs a single CSV with a normalized feature schema ready for model training.

Usage:
    python3 scripts/export_image_training_data.py
    python3 scripts/export_image_training_data.py --output data/image_model/training_data.csv
    python3 scripts/export_image_training_data.py --source sec
    python3 scripts/export_image_training_data.py --source pres
"""

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "image_model" / "training_data.csv"
PRES_DIR = ROOT / "data" / "presentation_gold_standard"

# Keywords used for cohort/retention signal detection in nearby text.
# Shared between SEC and presentation export paths so both sources produce
# comparable keyword_count / detected_keywords features.
COHORT_KEYWORDS = {"cohort", "retention", "vintage", "ltv", "cac", "arr", "mrr", "nrr"}

# Normalized output schema — features useful for relevance modelling
OUTPUT_COLUMNS = [
    # Identifiers
    "image_id",
    "source",  # 'sec' or 'pres'
    "company",
    "filing_key",  # accession number (SEC) or TICKER_FORM_DATE key (pres)
    "filename",
    "image_url",
    # Dimensions
    "width",
    "height",
    "has_dimensions",  # derived: width and height both known
    "image_area",  # derived: width * height (0 if unknown)
    "aspect_ratio",  # derived: width / height (0 if unknown or height=0)
    # Text signals
    "cohort_keyword_nearby",  # bool: cohort keyword within ~1500 chars
    "keyword_count",  # derived: number of distinct detected keywords
    "detected_keywords",  # raw: comma-separated keyword list
    "preceding_text",  # ~50-500 chars of text before the image
    "text_length",  # derived: len(preceding_text)
    # Scoring signals
    "cohort_confidence",  # 0.0-1.0 heuristic score (SEC) or relevance_score (pres)
    "detection_tier",  # tier_1_cohort, tier_2_large, tier_3_all, seed_list (SEC)
    # or inferred from classification (pres)
    "classification",  # V2 image classification: chart, unknown, decorative, etc.
    "section_type",  # SEC section: MD&A, BUSINESS, etc. (pres only)
    "image_index",  # 1-indexed position in filing (SEC only)
    # Labels
    "decision",  # 'relevant' or 'not_relevant'
    "chart_type",  # if relevant: bar_chart, line_chart, cohort_table, etc.
    "rejection_reason",  # if not_relevant: decorative, not_a_chart, wrong_subject, etc.
]


# ---------------------------------------------------------------------------
# SEC export (database-backed)
# ---------------------------------------------------------------------------

_IMAGE_URL_FRAGMENT = (
    "'https://www.sec.gov/Archives/edgar/data/'\n"
    "        || COALESCE(NULLIF(REGEXP_REPLACE(c.cik, '^0+', ''), ''), '0')\n"
    "        || '/' || REPLACE(f.accession_number, '-', '')\n"
    "        || '/' || v.filename AS image_url"
)

# Legacy reviewer decisions (image-level relevant / not_relevant).
# Stops accumulating new rows after PR #192 (per-metric confirmations
# took over the reviewer surface), but historical rows remain valid
# training data.
LEGACY_SEC_QUERY = f"""
    SELECT
        v.img_id,
        d.decision,
        d.chart_type,
        d.rejection_reason,
        v.filename,
        v.width,
        v.height,
        v.nearby_text,
        v.classification,
        v.section_type,
        v.relevance_score,
        f.accession_number,
        c.company_name,
        {_IMAGE_URL_FRAGMENT}
    FROM v2_image_review_decisions d
    JOIN v2_image_assets v ON v.img_id = d.img_id
    JOIN filings f ON v.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    ORDER BY c.company_name, v.img_id
"""

# Per-metric confirmations aggregated to image-level relevant / not_relevant.
# Mapping (sql/47):
#   relevant     — any confirmation in {accept, correct, add}
#   not_relevant — at least one confirmation, all rejects (no accept/correct/add)
#   excluded     — only skips, or zero confirmations (filtered by HAVING)
# `chart_type` is read from v2_image_assets.reviewer_chart_type (nullable;
# backfilled from legacy v2_image_review_decisions in migration 202604291500).
# Confirmation-derived rows that have never had a legacy decision will still
# emit NULL — downstream training treats it as a missing feature.
# `rejection_reason` is taken from any reject confirmation deterministically
# (earliest by created_at).
CONFIRMATIONS_SEC_QUERY = f"""
    SELECT
        v.img_id,
        CASE
            WHEN bool_or(imc.decision IN ('accept','correct','add'))
                 THEN 'relevant'
            ELSE 'not_relevant'
        END                                          AS decision,
        v.reviewer_chart_type                        AS chart_type,
        (
            SELECT imc2.rejection_reason
              FROM v2_image_metric_confirmations imc2
             WHERE imc2.img_id = v.img_id
               AND imc2.decision = 'reject'
               AND imc2.rejection_reason IS NOT NULL
             ORDER BY imc2.created_at
             LIMIT 1
        )                                            AS rejection_reason,
        v.filename,
        v.width,
        v.height,
        v.nearby_text,
        v.classification,
        v.section_type,
        v.relevance_score,
        f.accession_number,
        c.company_name,
        {_IMAGE_URL_FRAGMENT}
    FROM v2_image_metric_confirmations imc
    JOIN v2_image_assets v ON v.img_id = imc.img_id
    JOIN filings f ON v.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    GROUP BY v.img_id, v.filename, v.width, v.height, v.nearby_text,
             v.classification, v.section_type, v.relevance_score,
             v.reviewer_chart_type,
             f.accession_number, c.company_name, c.cik
    HAVING bool_or(imc.decision IN ('accept','correct','add','reject'))
    ORDER BY c.company_name, v.img_id
"""


def export_sec_rows(db) -> list[dict]:
    """
    Export V2 SEC image decisions for training.

    Pulls from both reviewer surfaces:
      - v2_image_review_decisions (legacy, image-level relevant/not_relevant)
      - v2_image_metric_confirmations (per-metric A/R/C/Add/Skip, sql/47),
        aggregated to image-level using the mapping in
        ``CONFIRMATIONS_SEC_QUERY``

    Legacy rows take precedence when the same `img_id` appears in both
    surfaces — historical reviewer intent on existing rows is authoritative.

    V2 does not persist V1's `detected_keywords[]` or `cohort_keyword_nearby`.
    Synthesize both from nearby_text using the same COHORT_KEYWORDS set used by
    the presentation export path:
      - detected_keywords: COHORT_KEYWORDS members found in nearby_text (sorted)
      - keyword_count: len(detected_keywords)
      - cohort_keyword_nearby: 1 if any keyword detected OR relevance_score >= 0.6
    """
    from src.shared.image_features import derive_detection_tier

    legacy_rows = db.query(LEGACY_SEC_QUERY)
    confirmation_rows = db.query(CONFIRMATIONS_SEC_QUERY)
    legacy_img_ids = {str(r["img_id"]) for r in legacy_rows}
    rows = list(legacy_rows) + [
        r for r in confirmation_rows if str(r["img_id"]) not in legacy_img_ids
    ]
    out = []
    for r in rows:
        w = r.get("width")
        h = r.get("height")
        has_dim = w is not None and h is not None
        area = (w * h) if has_dim else 0
        aspect = (w / h) if (has_dim and h > 0) else 0.0

        nearby = r.get("nearby_text") or ""
        relevance = float(r.get("relevance_score") or 0.0)

        nearby_lower = nearby.lower()
        detected = [kw for kw in COHORT_KEYWORDS if kw in nearby_lower]

        out.append(
            {
                "image_id": f"sec:{r['img_id']}",
                "source": "sec",
                "company": r.get("company_name", ""),
                "filing_key": r.get("accession_number", ""),
                "filename": r.get("filename", ""),
                "image_url": r.get("image_url", ""),
                "width": w if w is not None else "",
                "height": h if h is not None else "",
                "has_dimensions": int(has_dim),
                "image_area": area,
                "aspect_ratio": round(aspect, 4),
                "cohort_keyword_nearby": int(bool(detected) or relevance >= 0.6),
                "keyword_count": len(detected),
                "detected_keywords": ",".join(sorted(detected)),
                "preceding_text": nearby,
                "text_length": len(nearby),
                "cohort_confidence": relevance,
                "detection_tier": derive_detection_tier(r.get("classification"), relevance, w, h),
                "classification": (r.get("classification") or "").lower(),
                "section_type": r.get("section_type", "") or "",
                "image_index": "",  # V2 does not store image_index
                "decision": r.get("decision", ""),
                "chart_type": r.get("chart_type") or "",
                "rejection_reason": r.get("rejection_reason") or "",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Presentation export (file-based)
# ---------------------------------------------------------------------------

# Map presentation classification to a detection_tier proxy so the two
# sources share a common tier vocabulary for modelling.
CLASSIFICATION_TO_TIER = {
    "chart": "tier_1_cohort",
    "table_image": "tier_2_large",
    "unknown": "tier_3_all",
    "decorative": "tier_3_all",
    "logo": "tier_3_all",
    "signature": "tier_3_all",
}


def export_pres_rows() -> list[dict]:
    decisions_file = PRES_DIR / "_image_decisions.json"
    if not decisions_file.exists():
        logger.warning("No presentation decisions file found at %s", decisions_file)
        return []

    decisions: dict[str, dict] = json.loads(decisions_file.read_text(encoding="utf-8"))
    # Skip 'skip' decisions — these are not labelled
    decisions = {k: v for k, v in decisions.items() if v.get("decision") not in ("skip", "", None)}

    # Build candidate lookup: "{key}:{img_id}" -> candidate dict
    candidate_lookup: dict[str, dict] = {}
    for cand_file in sorted(PRES_DIR.glob("*_image_candidates.json")):
        key = cand_file.stem.replace("_image_candidates", "")
        for cand in json.loads(cand_file.read_text(encoding="utf-8")):
            candidate_lookup[f"{key}:{cand['img_id']}"] = {**cand, "filing_key": key}

    out = []
    for decision_key, dec in decisions.items():
        cand = candidate_lookup.get(decision_key)
        if cand is None:
            logger.warning("No candidate found for decision key %s — skipping", decision_key)
            continue

        filing_key = cand.get("filing_key", "")
        # Derive company from filing key (TICKER_FORM_DATE -> TICKER)
        company = filing_key.split("_")[0] if filing_key else ""

        w = cand.get("width")
        h = cand.get("height")
        has_dim = w is not None and h is not None
        area = (w * h) if has_dim else 0
        aspect = (w / h) if (has_dim and h > 0) else 0.0

        nearby = cand.get("nearby_text") or ""
        classification = (cand.get("classification") or "").lower()
        relevance_score = cand.get("relevance_score") or 0.0

        # Presence of cohort-adjacent keywords in nearby text
        nearby_lower = nearby.lower()
        detected = [kw for kw in COHORT_KEYWORDS if kw in nearby_lower]
        cohort_nearby = int(bool(detected))

        out.append(
            {
                "image_id": f"pres:{decision_key}",
                "source": "pres",
                "company": company,
                "filing_key": filing_key,
                "filename": cand.get("filename", ""),
                "image_url": cand.get("image_url", ""),
                "width": w if w is not None else "",
                "height": h if h is not None else "",
                "has_dimensions": int(has_dim),
                "image_area": area,
                "aspect_ratio": round(aspect, 4),
                "cohort_keyword_nearby": cohort_nearby,
                "keyword_count": len(detected),
                "detected_keywords": ",".join(detected),
                "preceding_text": nearby[:500],
                "text_length": len(nearby),
                "cohort_confidence": relevance_score,
                "detection_tier": CLASSIFICATION_TO_TIER.get(classification, "tier_3_all"),
                "classification": classification,
                "section_type": cand.get("section_type", ""),
                "image_index": "",
                "decision": dec.get("decision", ""),
                "chart_type": dec.get("chart_type") or "",
                "rejection_reason": dec.get("rejection_reason") or "",
            }
        )
    skipped = len(decisions) - len(out)
    if skipped > 0:
        logger.warning(
            "%d presentation decision(s) had no matching candidate JSON — "
            "run: preannotate_presentations.py --images-only for affected tickers",
            skipped,
        )
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export unified image training data for relevance model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help=f"Output CSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--source",
        choices=["sec", "pres", "all"],
        default="all",
        help="Which source to export (default: all)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()

    rows: list[dict] = []

    if args.source in ("sec", "all"):
        db_url = args.database_url or os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL not set — cannot export SEC decisions")
            sys.exit(1)
        from src.infra.db import DatabaseAdapter

        db = DatabaseAdapter(db_url)
        sec_rows = export_sec_rows(db)
        logger.info("SEC: %d decisions exported", len(sec_rows))
        rows.extend(sec_rows)

    if args.source in ("pres", "all"):
        pres_rows = export_pres_rows()
        logger.info("Presentations: %d decisions exported", len(pres_rows))
        rows.extend(pres_rows)

    if not rows:
        logger.warning("No rows to export")
        sys.exit(0)

    # Summary
    relevant = sum(1 for r in rows if r["decision"] == "relevant")
    not_relevant = sum(1 for r in rows if r["decision"] == "not_relevant")
    logger.info(
        "Total: %d rows | relevant=%d (%.1f%%) | not_relevant=%d (%.1f%%)",
        len(rows),
        relevant,
        100 * relevant / len(rows),
        not_relevant,
        100 * not_relevant / len(rows),
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Written to %s", output_path)

    # Per-source breakdown
    sources: dict[str, dict] = {}
    for r in rows:
        s = r["source"]
        if s not in sources:
            sources[s] = {"total": 0, "relevant": 0}
        sources[s]["total"] += 1
        if r["decision"] == "relevant":
            sources[s]["relevant"] += 1
    for s, counts in sources.items():
        logger.info(
            "  %s: %d total, %d relevant (%.1f%%)",
            s,
            counts["total"],
            counts["relevant"],
            100 * counts["relevant"] / counts["total"],
        )


if __name__ == "__main__":
    main()
