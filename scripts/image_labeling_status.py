#!/usr/bin/env python3
"""
Report labeling status for presentation image candidates.

Shows which filings have unlabeled image candidates, ranked by labeling priority.
Use this to decide where to focus the next human review session.

Priority factors:
  1. New ticker (not yet represented in any labeled data) — highest value for generalization
  2. Filing type: S-1/F-1/10-K before 8-K (more likely to have charts)
  3. Candidate count (more unlabeled = more value per session)

Usage:
    python3 scripts/image_labeling_status.py
    python3 scripts/image_labeling_status.py --all    # include fully labeled filings too
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLD_STANDARD_DIR = ROOT / "data" / "presentation_gold_standard"
FILE_INDEX = GOLD_STANDARD_DIR / "_file_index.json"
DECISIONS_FILE = GOLD_STANDARD_DIR / "_image_decisions.json"

# Filing types ranked by expected chart density (higher = better)
FILING_TYPE_RANK = {"S-1": 3, "F-1": 3, "10-K": 2, "S-11": 2, "10-Q": 1, "8-K": 0}


def parse_filing_type(key: str) -> str:
    """Extract filing type from a key like TICKER_S-1_DATE or TICKER_DATE."""
    parts = key.split("_")
    if len(parts) >= 3:
        # e.g. ABNB_S-1_2020-12-07 → parts[1] = "S-1"
        candidate = parts[1]
        if any(candidate.startswith(t.replace("-", "")) or candidate == t for t in FILING_TYPE_RANK):
            return candidate
    return "8-K"


def filing_type_rank(key: str) -> int:
    ft = parse_filing_type(key)
    for known, rank in FILING_TYPE_RANK.items():
        if ft == known:
            return rank
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include fully-labeled and empty filings in output",
    )
    args = parser.parse_args()

    # Load decisions
    try:
        decisions: dict[str, dict] = json.loads(DECISIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        decisions = {}

    # Find all candidate files (includes files not yet in the index)
    candidate_files = sorted(GOLD_STANDARD_DIR.glob("*_image_candidates.json"))

    # Load file index to identify which filings have no candidate file
    try:
        file_index: dict[str, object] = json.loads(FILE_INDEX.read_text(encoding="utf-8"))
    except FileNotFoundError:
        file_index = {}

    # Build per-filing stats
    rows: list[dict] = []
    keys_with_candidates: set[str] = set()

    for cand_path in candidate_files:
        key = cand_path.stem.replace("_image_candidates", "")
        keys_with_candidates.add(key)

        try:
            candidates: list[dict] = json.loads(cand_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        total = len(candidates)
        labeled = sum(1 for c in candidates if f"{key}:{c['img_id']}" in decisions)
        relevant = sum(
            1
            for c in candidates
            if decisions.get(f"{key}:{c['img_id']}", {}).get("decision") == "relevant"
        )
        unlabeled = total - labeled

        ticker = key.split("_")[0]
        filing_type = parse_filing_type(key)

        rows.append(
            {
                "key": key,
                "ticker": ticker,
                "filing_type": filing_type,
                "total": total,
                "labeled": labeled,
                "unlabeled": unlabeled,
                "relevant": relevant,
            }
        )

    # Identify tickers already represented in labeled data
    labeled_tickers: set[str] = set()
    for row in rows:
        if row["labeled"] > 0:
            labeled_tickers.add(row["ticker"])

    # Identify filings with no candidate file
    no_candidate_keys = [k for k in file_index if k not in keys_with_candidates]

    # Sort unlabeled rows by priority
    def sort_key(row: dict) -> tuple:
        is_new_ticker = row["ticker"] not in labeled_tickers
        return (
            -int(is_new_ticker),           # new tickers first
            -filing_type_rank(row["key"]), # S-1/F-1 before 8-K
            -row["unlabeled"],             # more unlabeled first
        )

    unlabeled_rows = [r for r in rows if r["unlabeled"] > 0]
    unlabeled_rows.sort(key=sort_key)

    fully_labeled = [r for r in rows if r["unlabeled"] == 0 and r["labeled"] > 0]

    # ── Print summary ──────────────────────────────────────────────────────────
    total_candidates = sum(r["total"] for r in rows)
    total_labeled = sum(r["labeled"] for r in rows)
    total_unlabeled = sum(r["unlabeled"] for r in rows)
    total_relevant = sum(r["relevant"] for r in rows)

    print("=" * 72)
    print("IMAGE LABELING STATUS")
    print("=" * 72)
    print(
        f"  Total presentation candidates : {total_candidates}"
    )
    print(f"  Labeled                       : {total_labeled}")
    print(
        f"  Unlabeled (ready to review)   : {total_unlabeled}"
    )
    if total_labeled > 0:
        pos_rate = total_relevant / total_labeled * 100
        print(f"  Positive rate (labeled)       : {pos_rate:.1f}%  ({total_relevant} relevant)")
    print()

    # ── Unlabeled / priority queue ─────────────────────────────────────────────
    if unlabeled_rows:
        print("LABELING QUEUE (highest value first)")
        print("-" * 72)
        header = f"{'#':<4} {'Filing Key':<30} {'Tkr':<6} {'Type':<6} {'Total':>6} {'Done':>5} {'Left':>5}  New?"
        print(header)
        print("-" * 72)
        for i, row in enumerate(unlabeled_rows, 1):
            is_new = row["ticker"] not in labeled_tickers
            new_flag = "  YES" if is_new else ""
            print(
                f"{i:<4} {row['key']:<30} {row['ticker']:<6} {row['filing_type']:<6}"
                f" {row['total']:>6} {row['labeled']:>5} {row['unlabeled']:>5}{new_flag}"
            )
        print()

    # ── Fully labeled ──────────────────────────────────────────────────────────
    if args.all and fully_labeled:
        fully_labeled.sort(key=lambda r: (-r["labeled"],))
        print("FULLY LABELED")
        print("-" * 72)
        for row in fully_labeled:
            pos_pct = row["relevant"] / row["labeled"] * 100 if row["labeled"] else 0
            print(
                f"  {row['key']:<30} {row['ticker']:<6} {row['filing_type']:<6}"
                f" {row['labeled']:>5} labeled  ({pos_pct:.0f}% relevant)"
            )
        print()

    # ── No candidate file ─────────────────────────────────────────────────────
    if no_candidate_keys:
        print("NO CANDIDATE FILE (filing indexed but no images found)")
        print("-" * 72)
        for k in sorted(no_candidate_keys):
            print(f"  {k}")
        print()
        print(
            "  To generate candidates: python3 scripts/preannotate_presentations.py"
            " --ticker <TICKER> --images-only"
        )
        print()

    if not unlabeled_rows:
        print("All filings with candidate files are fully labeled.")


if __name__ == "__main__":
    main()
