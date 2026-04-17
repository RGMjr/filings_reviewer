#!/usr/bin/env python3
"""
Convert V2 review decisions to SEC gold standard CSV format.

Reads accepted/corrected decisions from v2_review_decisions + v2_metric_facts,
maps them to the gold standard schema, and merges with the existing
golden_set_260408.csv.

Merge strategy (--mode replace, the default):
  - For each company that has V2 review decisions: replace their existing
    gold standard entries with the reviewed V2 results.
  - With --preserve-fn (default): also keep existing gold standard entries
    for metrics that V2 never generated candidates for (i.e., false negatives
    V2 missed entirely), so recall coverage is not lost.
  - For companies without V2 decisions: keep unchanged.

Usage:
    # Dry run — show reconciliation report only
    python3 scripts/convert_v2_to_gold_standard.py --dry-run

    # Write updated gold standard
    python3 scripts/convert_v2_to_gold_standard.py --output data/gold_standard/golden_set_260407.csv

    # Replace without preserving false negatives
    python3 scripts/convert_v2_to_gold_standard.py --no-preserve-fn --dry-run

    # Only export V2 decisions in gold standard format (don't merge)
    python3 scripts/convert_v2_to_gold_standard.py --mode export-only --output /tmp/v2_decisions.csv
"""

import argparse
import csv
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
GOLD_STANDARD_DIR = ROOT / "data" / "gold_standard"
DEFAULT_INPUT_CSV = GOLD_STANDARD_DIR / "golden_set_260408.csv"

# Exact column order matching the existing gold standard CSV
GOLD_STANDARD_COLUMNS = [
    "Document URL",
    "Company",
    "Standard Metric Name",
    "New standard metric?",
    "Name in the text",
    "Raw value",
    "Scaled value",
    "Scale/unit",
    "Period",
    "Definition",
    "Quote/context",
    "segment_type",
    "is_definition_only",
    "value_context",
    "detection_difficulty",
    "period_start",
    "period_end",
    "duplicate_group",
]

# DB company_name → gold standard Company name
COMPANY_NAME_MAP: dict[str, str] = {
    "Snowflake Inc": "Snowflake Inc",
    "Flywire Corp": "Flywire Corp",
    "Robinhood Markets, Inc.": "Robinhood Markets, Inc.",
    "Torrid Holdings Inc.": "Torrid Holdings Inc.",
    "Gitlab Inc.": "Gitlab Inc.",
    "Samsara Inc.": "Samsara Inc.",
    "Samsara Vision Inc.": "SAMSARA VISION INC.",
    # Handle slight variations from DB
    "Snowflake": "Snowflake Inc",
    "Flywire": "Flywire Corp",
    "Robinhood": "Robinhood Markets, Inc.",
    "Torrid": "Torrid Holdings Inc.",
    "GitLab": "Gitlab Inc.",
    "Samsara": "Samsara Inc.",
    "Samsara Vision": "SAMSARA VISION INC.",
}

# V2 unit → Scale/unit column
UNIT_MAP: dict[str, str] = {
    "percent": "%",
    "currency": "$",
    "count": "count",
    "ratio": "ratio",
    "basis_points": "basis_points",
    "other": "other",
    "unknown": "",
}

# V2 source_type → segment_type
SOURCE_TYPE_MAP: dict[str, str] = {
    "html_table": "table",
    "text": "text",
    "chart": "chart",
    "ocr_table": "table",
    "pdf_table": "table",
}


def _format_period(
    period_start: str | None,
    period_end: str | None,
    period_type: str | None,
) -> str:
    """Format a human-readable period string from V2 period fields."""
    if not period_end and not period_start:
        return ""
    if not period_start and period_end:
        return period_end
    if period_start and period_end and period_start != period_end:
        return f"{period_start} to {period_end}"
    return period_end or period_start or ""


def _map_unit(unit: str | None, currency: str | None) -> str:
    """Map V2 unit enum to gold standard Scale/unit string."""
    if not unit:
        return ""
    u = str(unit).lower()
    if u == "currency" and currency and currency.upper() != "USD":
        return currency.upper()
    return UNIT_MAP.get(u, u)


def _extract_source_quote(evidence_pack: Any) -> str:
    """Extract source quote from evidence_pack JSON field."""
    if not evidence_pack:
        return ""
    if isinstance(evidence_pack, str):
        try:
            evidence_pack = json.loads(evidence_pack)
        except Exception:
            return ""
    if not isinstance(evidence_pack, dict):
        return ""
    return evidence_pack.get("snippet_html") or evidence_pack.get("context_before", "") or ""


def convert_decision_to_gold_row(
    decision: dict[str, Any],
    metric_defs: dict[str, str],
) -> dict[str, str] | None:
    """
    Convert a single V2 decision dict (from get_v2_decisions) to a gold standard row.

    Returns None for rejected decisions (they should not appear in the gold standard).
    """
    d = decision.get("decision", "")
    if d == "reject":
        return None

    db_company = decision.get("company", "")
    company = COMPANY_NAME_MAP.get(db_company)
    if company is None:
        logger.warning(f"No name mapping for company: {db_company!r} — using as-is")
        company = db_company

    # Metric ID: use correction if provided, else canonical
    metric_id = decision.get("assigned_metric_id") or decision.get("metric_id") or ""

    # Value: use corrected_value for corrections, else raw value from V2
    corrected_value = decision.get("corrected_value")
    scaled_value = (
        str(corrected_value)
        if corrected_value is not None
        else str(decision.get("value", "") or "")
    )
    raw_value = str(decision.get("value_raw", "") or "")

    unit = _map_unit(decision.get("unit"), decision.get("currency"))
    period_start = str(decision.get("period_start", "") or "")
    period_end = str(decision.get("period_end", "") or "")
    period_type = str(decision.get("period_type", "") or "")
    period = _format_period(period_start, period_end, period_type)

    source_type = str(decision.get("source_type", "") or "")
    segment_type = SOURCE_TYPE_MAP.get(source_type, source_type)

    source_quote = _extract_source_quote(
        decision.get("evidence_pack") or decision.get("source_quote")
    )

    definition = metric_defs.get(metric_id, "")

    return {
        "Document URL": decision.get("document_url", ""),
        "Company": company,
        "Standard Metric Name": metric_id,
        "New standard metric?": "",
        "Name in the text": "",
        "Raw value": raw_value,
        "Scaled value": scaled_value,
        "Scale/unit": unit,
        "Period": period,
        "Definition": definition,
        "Quote/context": source_quote,
        "segment_type": segment_type,
        "is_definition_only": "",
        "value_context": "",
        "detection_difficulty": "",
        "period_start": period_start,
        "period_end": period_end,
        "duplicate_group": "",
    }


def load_gold_standard(path: Path) -> list[dict[str, str]]:
    """Load the existing gold standard CSV as a list of row dicts."""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_metric_definitions(db: Any) -> dict[str, str]:
    """Load metric_id → description mapping from the metrics table."""
    try:
        rows = db.query("SELECT metric_id, description FROM metrics")
        return {r["metric_id"]: r.get("description", "") for r in rows}
    except Exception:
        logger.debug("Could not load metric definitions from DB — definitions will be empty")
        return {}


def get_v2_decisions(db: Any) -> list[dict[str, Any]]:
    """Pull V2 review decisions with full fact context."""
    rows = db.query("""
        SELECT
            rd.decision,
            rd.assigned_metric_id,
            rd.corrected_value,
            rd.rejection_reason,
            rd.reviewer_notes,
            mf.canonical_metric_id   AS metric_id,
            mf.value,
            mf.value_raw,
            mf.unit,
            mf.currency,
            mf.period_type,
            mf.period_start::text    AS period_start,
            mf.period_end::text      AS period_end,
            mf.source_type,
            mf.confidence,
            mf.evidence_pack,
            f.sec_html_url           AS document_url,
            c.company_name           AS company
        FROM v2_review_decisions rd
        JOIN v2_metric_facts mf ON rd.fact_id = mf.fact_id
        JOIN filings f ON mf.doc_id = f.filing_id
        JOIN companies c ON f.company_id = c.company_id
        ORDER BY c.company_name, rd.created_at
    """)
    return rows


def reconcile(
    existing: list[dict[str, str]],
    v2_rows: list[dict[str, str]],
    mode: str,
    preserve_fn: bool,
) -> tuple[list[dict[str, str]], dict[str, dict]]:
    """
    Merge V2 rows into existing gold standard.

    Returns (merged_rows, stats_by_company).
    stats keys: old, new, fn_kept, fn_lost
    """
    # Companies covered by V2 decisions
    v2_companies = {r["Company"] for r in v2_rows}

    # Group existing by company
    existing_by_company: dict[str, list[dict]] = defaultdict(list)
    for row in existing:
        existing_by_company[row["Company"]].append(row)

    # Group V2 rows by company
    v2_by_company: dict[str, list[dict]] = defaultdict(list)
    for row in v2_rows:
        v2_by_company[row["Company"]].append(row)

    stats: dict[str, dict] = {}
    merged: list[dict[str, str]] = []

    if mode == "export-only":
        return v2_rows, {}

    all_companies = set(existing_by_company.keys()) | v2_companies

    for company in sorted(all_companies):
        old_rows = existing_by_company.get(company, [])
        new_rows = v2_by_company.get(company, [])

        if company not in v2_companies:
            # Not reviewed — keep as-is
            merged.extend(old_rows)
            stats[company] = {
                "old": len(old_rows),
                "new": len(old_rows),
                "fn_kept": 0,
                "fn_lost": 0,
            }
            continue

        if mode == "replace":
            if preserve_fn:
                # Find existing entries for metrics V2 never touched (FNs)
                # "V2 touched" = V2 had any decision (accept OR reject) for this metric
                v2_metric_ids = {
                    r["Standard Metric Name"] for r in v2_rows if r["Company"] == company
                }
                fn_rows = [
                    r for r in old_rows if r.get("Standard Metric Name", "") not in v2_metric_ids
                ]
                out_rows = new_rows + fn_rows
                stats[company] = {
                    "old": len(old_rows),
                    "new": len(new_rows),
                    "fn_kept": len(fn_rows),
                    "fn_lost": 0,
                }
            else:
                out_rows = new_rows
                fn_lost = sum(
                    1
                    for r in old_rows
                    if r.get("Standard Metric Name", "")
                    not in {x["Standard Metric Name"] for x in new_rows}
                )
                stats[company] = {
                    "old": len(old_rows),
                    "new": len(new_rows),
                    "fn_kept": 0,
                    "fn_lost": fn_lost,
                }
            merged.extend(out_rows)

        elif mode == "add":
            # Add V2 rows that don't already exist (match on company+metric+period_end)
            existing_keys = {
                (r["Company"], r.get("Standard Metric Name", ""), r.get("period_end", ""))
                for r in old_rows
            }
            added = [
                r
                for r in new_rows
                if (r["Company"], r.get("Standard Metric Name", ""), r.get("period_end", ""))
                not in existing_keys
            ]
            out_rows = old_rows + added
            merged.extend(out_rows)
            stats[company] = {
                "old": len(old_rows),
                "new": len(out_rows),
                "fn_kept": 0,
                "fn_lost": 0,
            }

    return merged, stats


def print_report(stats: dict[str, dict], v2_raw_counts: dict[str, dict]) -> None:
    """Print per-company reconciliation report."""
    print("\n=== Reconciliation Report ===\n")
    print(
        f"{'Company':<35} {'Old':>5} {'Accept':>7} {'Reject':>7} {'Correct':>8} {'New':>5} {'FN kept':>8} {'FN lost':>8}"
    )
    print("-" * 95)

    total_old = total_new = total_fn_kept = total_fn_lost = 0
    for company in sorted(stats.keys()):
        s = stats[company]
        v2 = v2_raw_counts.get(company, {})
        print(
            f"{company:<35} {s['old']:>5} {v2.get('accept', 0):>7} {v2.get('reject', 0):>7}"
            f" {v2.get('correct', 0):>8} {s['new']:>5} {s['fn_kept']:>8} {s['fn_lost']:>8}"
        )
        total_old += s["old"]
        total_new += s["new"]
        total_fn_kept += s["fn_kept"]
        total_fn_lost += s["fn_lost"]

    print("-" * 95)
    print(
        f"{'TOTAL':<35} {total_old:>5} {'':<7} {'':<7} {'':<8} {total_new:>5} {total_fn_kept:>8} {total_fn_lost:>8}"
    )

    if total_fn_lost:
        print(
            f"\nWARNING: {total_fn_lost} existing FN entries will be removed (use --preserve-fn to keep them)"
        )


def write_gold_standard(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write gold standard rows to CSV with exact column order."""
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=GOLD_STANDARD_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows to {output_path}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Convert V2 review decisions to gold standard CSV format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["replace", "add", "export-only"],
        default="replace",
        help="Merge strategy (default: replace)",
    )
    parser.add_argument(
        "--preserve-fn",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="In replace mode, keep existing GS entries for metrics V2 never reviewed (default: True)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help=f"Existing gold standard CSV (default: {DEFAULT_INPUT_CSV})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for updated gold standard CSV (required unless --dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print reconciliation report without writing any files",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string (default: $DATABASE_URL)",
    )
    args = parser.parse_args()

    if not args.dry_run and args.output is None:
        parser.error("--output is required unless --dry-run is set")

    if not args.database_url:
        parser.error("DATABASE_URL not set and --database-url not provided")

    from src.infra.db import DatabaseAdapter

    db = DatabaseAdapter(args.database_url)

    try:
        print("Loading V2 review decisions from DB...")
        raw_decisions = get_v2_decisions(db)
        print(f"  {len(raw_decisions)} total decisions (accept + reject + correct)")

        metric_defs = load_metric_definitions(db)
    finally:
        db.close()

    # Count raw decisions by company and type
    v2_raw_counts: dict[str, dict] = defaultdict(lambda: {"accept": 0, "reject": 0, "correct": 0})
    for d in raw_decisions:
        db_company = d.get("company", "")
        company = COMPANY_NAME_MAP.get(db_company, db_company)
        decision_type = d.get("decision", "")
        if decision_type in v2_raw_counts[company]:
            v2_raw_counts[company][decision_type] += 1

    # Convert decisions to gold standard rows (skip rejects)
    v2_gs_rows: list[dict[str, str]] = []
    for d in raw_decisions:
        row = convert_decision_to_gold_row(d, metric_defs)
        if row is not None:
            v2_gs_rows.append(row)
    print(f"  {len(v2_gs_rows)} accepted/corrected decisions → gold standard rows")

    # Load existing gold standard
    print(f"Loading existing gold standard: {args.input}")
    existing = load_gold_standard(args.input)
    print(f"  {len(existing)} existing rows")

    # Reconcile
    merged, stats = reconcile(existing, v2_gs_rows, args.mode, args.preserve_fn)

    # Print report
    print_report(stats, v2_raw_counts)

    if args.dry_run:
        print("\nDry run — no files written.")
        return

    # Write output
    write_gold_standard(merged, args.output)


if __name__ == "__main__":
    main()
