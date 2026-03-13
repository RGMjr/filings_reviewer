#!/usr/bin/env python3
"""
Compare V1 and V2 extraction results for one or more filings.

Usage:
    # Compare all filings
    python3 scripts/compare_v1_v2_results.py

    # Compare a specific filing
    python3 scripts/compare_v1_v2_results.py --filing-id 42

    # JSON output
    python3 scripts/compare_v1_v2_results.py --output json

    # Adjust confidence threshold
    python3 scripts/compare_v1_v2_results.py --min-confidence 0.7
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def _get_filing_ids(conn, filing_id: int | None) -> list[int]:
    """Return the list of filing IDs to compare."""
    if filing_id is not None:
        return [filing_id]
    rows = conn.execute("SELECT DISTINCT filing_id FROM filings ORDER BY filing_id").fetchall()
    return [r[0] for r in rows]


def _query_v1(conn, filing_ids: list[int]) -> list[dict]:
    """Query V1 metric_values table."""
    sql = """
        SELECT filing_id, metric_name, value, period_start, period_end, unit
        FROM metric_values
        WHERE filing_id = ANY(%s)
    """
    rows = conn.execute(sql, (filing_ids,)).fetchall()
    cols = ["filing_id", "metric_name", "value", "period_start", "period_end", "unit"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _query_v2(conn, filing_ids: list[int], min_confidence: float) -> list[dict]:
    """Query V2 metric_facts table."""
    sql = """
        SELECT filing_id, canonical_metric_id, value, period_start, period_end, unit, confidence
        FROM v2_metric_facts
        WHERE filing_id = ANY(%s) AND confidence >= %s
    """
    rows = conn.execute(sql, (filing_ids, min_confidence)).fetchall()
    cols = ["filing_id", "canonical_metric_id", "value", "period_start", "period_end", "unit", "confidence"]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _periods_overlap(start1, end1, start2, end2) -> bool:
    """Return True if two date ranges overlap (inclusive)."""
    if None in (start1, end1, start2, end2):
        # If either period is missing, treat as a match by date
        return True
    return start1 <= end2 and start2 <= end1


def _values_match(v1, v2) -> bool:
    """Return True if two numeric values are within 1% of each other."""
    try:
        f1 = float(v1)
        f2 = float(v2)
        if f1 == 0 and f2 == 0:
            return True
        if f1 == 0 or f2 == 0:
            return False
        return abs(f1 - f2) / max(abs(f1), abs(f2)) <= 0.01
    except (TypeError, ValueError):
        return str(v1) == str(v2)


def _compare_filing(
    filing_id: int,
    v1_rows: list[dict],
    v2_rows: list[dict],
    resolve_fn,
) -> dict:
    """Compare V1 and V2 results for a single filing."""

    # Resolve V1 metric names to canonical IDs
    v1_resolved = [
        {**r, "canonical": resolve_fn(r["metric_name"])}
        for r in v1_rows
        if r["filing_id"] == filing_id
    ]
    v2_filing = [r for r in v2_rows if r["filing_id"] == filing_id]

    matches = []
    v1_only = []
    matched_v2_indices: set[int] = set()

    for v1 in v1_resolved:
        found = False
        for i, v2 in enumerate(v2_filing):
            if i in matched_v2_indices:
                continue
            if v1["canonical"] != v2["canonical_metric_id"]:
                continue
            if not _values_match(v1["value"], v2["value"]):
                continue
            if not _periods_overlap(
                v1["period_start"], v1["period_end"],
                v2["period_start"], v2["period_end"],
            ):
                continue
            matches.append({
                "metric": v1["canonical"],
                "value": v1["value"],
                "period_start": str(v1["period_start"]) if v1["period_start"] else None,
                "period_end": str(v1["period_end"]) if v1["period_end"] else None,
            })
            matched_v2_indices.add(i)
            found = True
            break
        if not found:
            v1_only.append({
                "metric": v1["canonical"],
                "value": v1["value"],
                "period_start": str(v1["period_start"]) if v1["period_start"] else None,
                "period_end": str(v1["period_end"]) if v1["period_end"] else None,
            })

    v2_only = [
        {
            "metric": v2["canonical_metric_id"],
            "value": v2["value"],
            "confidence": v2["confidence"],
            "period_start": str(v2["period_start"]) if v2["period_start"] else None,
            "period_end": str(v2["period_end"]) if v2["period_end"] else None,
        }
        for i, v2 in enumerate(v2_filing)
        if i not in matched_v2_indices
    ]

    total = len(matches) + len(v1_only) + len(v2_only)
    precision = len(matches) / (len(matches) + len(v2_only)) if (len(matches) + len(v2_only)) > 0 else 0.0
    recall = len(matches) / (len(matches) + len(v1_only)) if (len(matches) + len(v1_only)) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "filing_id": filing_id,
        "matches": len(matches),
        "v1_only": len(v1_only),
        "v2_only": len(v2_only),
        "total": total,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "match_details": matches,
        "v1_only_details": v1_only,
        "v2_only_details": v2_only,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare V1 and V2 extraction results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--filing-id", type=int, help="Compare a single filing by ID")
    parser.add_argument(
        "--output", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--min-confidence", type=float, default=0.5,
        help="Minimum V2 confidence threshold (default: 0.5)",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg3 not installed (pip install psycopg[binary])", file=sys.stderr)
        sys.exit(1)

    from src.shared.keyword_config import resolve_to_canonical

    try:
        conn = psycopg.connect(db_url, autocommit=True)
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        filing_ids = _get_filing_ids(conn, args.filing_id)
    except Exception as e:
        print(f"ERROR: Could not query filings: {e}", file=sys.stderr)
        sys.exit(1)

    if not filing_ids:
        print("No filings found.")
        sys.exit(0)

    try:
        v1_rows = _query_v1(conn, filing_ids)
    except Exception as e:
        # Table may not exist
        if "does not exist" in str(e) or "undefined" in str(e):
            print(f"WARNING: V1 table not found: {e}", file=sys.stderr)
            v1_rows = []
        else:
            print(f"ERROR: V1 query failed: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        v2_rows = _query_v2(conn, filing_ids, args.min_confidence)
    except Exception as e:
        if "does not exist" in str(e) or "undefined" in str(e):
            print(f"WARNING: V2 table not found: {e}", file=sys.stderr)
            v2_rows = []
        else:
            print(f"ERROR: V2 query failed: {e}", file=sys.stderr)
            sys.exit(1)

    conn.close()

    results = [
        _compare_filing(fid, v1_rows, v2_rows, resolve_to_canonical)
        for fid in filing_ids
    ]

    if args.output == "json":
        print(json.dumps(results, indent=2))
        return

    # Text report
    total_matches = sum(r["matches"] for r in results)
    total_v1_only = sum(r["v1_only"] for r in results)
    total_v2_only = sum(r["v2_only"] for r in results)
    overall_precision = total_matches / (total_matches + total_v2_only) if (total_matches + total_v2_only) > 0 else 0.0
    overall_recall = total_matches / (total_matches + total_v1_only) if (total_matches + total_v1_only) > 0 else 0.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0 else 0.0
    )

    print("\nV1/V2 Comparison Report")
    print(f"{'=' * 60}")
    print(f"Filings compared:  {len(results)}")
    print(f"Min V2 confidence: {args.min_confidence}")
    print(f"{'=' * 60}")
    print(f"{'Filing':>10}  {'Match':>6}  {'V1-only':>7}  {'V2-only':>7}  {'P':>6}  {'R':>6}  {'F1':>6}")
    print(f"{'-' * 60}")
    for r in results:
        print(
            f"{r['filing_id']:>10}  {r['matches']:>6}  {r['v1_only']:>7}  "
            f"{r['v2_only']:>7}  {r['precision']:>6.1%}  {r['recall']:>6.1%}  {r['f1']:>6.1%}"
        )
    print(f"{'-' * 60}")
    print(
        f"{'TOTAL':>10}  {total_matches:>6}  {total_v1_only:>7}  "
        f"{total_v2_only:>7}  {overall_precision:>6.1%}  {overall_recall:>6.1%}  {overall_f1:>6.1%}"
    )
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
