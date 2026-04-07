#!/usr/bin/env python3
"""
Terminal-Based Presentation Annotation Review Tool.

Presents each pipeline-extracted candidate one at a time with raw text context.
Reviewer assigns a disposition code to each candidate, then has the option to
add any metrics the pipeline missed.

Disposition codes:
  ACCEPT  — Annotation is correct as-is
  EDIT    — Real metric but details need correction (reviewer fixes fields)
  REJECT  — False positive; reviewer enters a brief reason
  SKIP    — Defer to next review pass (not counted in statistics)

After all candidates, reviewer is prompted to ADD any missed metrics.

Trap detection: synthetic false positives may be injected by preannotate_presentations.py.
If a trap is ACCEPTED rather than REJECTED, a warning is shown. Trap detection rate
is tracked per session; a warning is shown if detection rate < 80%.

Output:
  data/presentation_gold_standard/{TICKER}_{DATE}_reviewed.csv

Usage:
    python3 scripts/review_presentation_annotations.py \\
        data/presentation_gold_standard/CRM_2025-02-26_preannotated.csv

    # Review multiple files back-to-back
    python3 scripts/review_presentation_annotations.py \\
        data/presentation_gold_standard/CRM_2025-02-26_preannotated.csv \\
        data/presentation_gold_standard/META_2025-04-30_preannotated.csv

    # Resume a partial review session
    python3 scripts/review_presentation_annotations.py \\
        data/presentation_gold_standard/CRM_2025-02-26_preannotated.csv --resume
"""

import argparse
import csv
import json
import sys
import textwrap
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.gold_standard.transcript_metrics import ACTIVE_METRICS  # noqa: E402

OUTPUT_DIR = ROOT / "data" / "presentation_gold_standard"
_URL_INDEX_PATH = OUTPUT_DIR / "_url_index.json"


def _load_url_index() -> dict[str, str]:
    try:
        return json.loads(_URL_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


OUTPUT_FIELDNAMES = [
    "company",
    "ticker",
    "date",
    "metric_id",
    "value",
    "unit",
    "period",
    "source_type",
    "raw_text",
    "context_before",
    "context_after",
    "header_path",
    "stub_path",
    "confidence",
    "section",
    "is_trap",
    "disposition",
    "disposition_reason",
]

TRAP_ALERT_THRESHOLD = 0.80  # Warn if trap detection rate < 80%
ACCEPT_RATE_WARNING = 0.85  # Warn if ACCEPT rate > 85% (possible rubber-stamping)


# ---------------------------------------------------------------------------
# Terminal UI helpers
# ---------------------------------------------------------------------------


def clear_screen():
    print("\033[2J\033[H", end="")


def bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m"


def prompt(message: str, valid_options: list[str] | None = None) -> str:
    """
    Display a prompt and read input. Optionally validates against valid_options
    (case-insensitive). Strips leading/trailing whitespace.
    """
    while True:
        try:
            raw = input(message).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nReview interrupted. Progress saved.")
            sys.exit(0)

        if valid_options is None:
            return raw

        upper = raw.upper()
        if upper in [v.upper() for v in valid_options]:
            return upper

        print(f"  Invalid input. Choose from: {', '.join(valid_options)}")


def prompt_optional(message: str, default: str = "") -> str:
    """Prompt with an optional default (press Enter to accept)."""
    try:
        raw = input(message).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nReview interrupted. Progress saved.")
        sys.exit(0)
    return raw if raw else default


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------


def load_candidates(path: Path) -> list[dict]:
    """Load pre-annotated candidates CSV."""
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_reviewed(path: Path) -> list[dict]:
    """Load already-reviewed annotations (for resume mode)."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_reviewed(path: Path, rows: list[dict]) -> None:
    """Write reviewed annotations to output CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Review logic — single annotation
# ---------------------------------------------------------------------------


def review_candidate(
    candidate: dict,
    index: int,
    total: int,
) -> dict:
    """
    Present a single candidate to the reviewer and collect their disposition.
    Returns the candidate with disposition fields added, or None if undo was requested.
    """
    is_trap = candidate.get("is_trap", "false").lower() == "true"
    confidence = candidate.get("confidence", "MEDIUM")
    metric_id = candidate.get("metric_id", "")
    value = candidate.get("value", "")
    unit = candidate.get("unit", "")
    period = candidate.get("period", "")
    section = candidate.get("section", "")
    raw_text = candidate.get("raw_text", "")

    clear_screen()
    print(bold(f"\n{'='*65}"))
    print(bold(f"  PRESENTATION ANNOTATION REVIEW  [{index}/{total}]"))
    print(bold(f"{'='*65}"))
    print(
        f"  Company:    {candidate.get('company', '')} ({candidate.get('ticker', '')}) — {candidate.get('date', '')}"
    )
    print(f"  Progress:   {'#' * index}{'.' * (total - index)} {index}/{total}")
    print()

    if is_trap:
        print(red("  *** POTENTIAL TRAP — review carefully ***"))
        print()

    source_type = candidate.get("source_type", "")
    context_before = candidate.get("context_before", "") or ""
    context_after = candidate.get("context_after", "") or ""
    header_path = candidate.get("header_path", "") or ""
    stub_path = candidate.get("stub_path", "") or ""

    conf_color = {"HIGH": green, "MEDIUM": yellow, "LOW": red}.get(confidence, str)
    print(f"  Metric:     {bold(metric_id)}")
    print(f"  Value:      {value or '(none)'}")
    print(f"  Unit:       {unit}")
    print(f"  Period:     {period}")
    print(f"  Section:    {section}")
    print(f"  Source:     {source_type}")
    print(f"  Confidence: {conf_color(confidence)}")
    print()
    print(cyan("  Raw text from slide:"))
    wrapped = textwrap.fill(raw_text, width=62, initial_indent="    ", subsequent_indent="    ")
    print(wrapped)
    print()

    if context_before or context_after:
        print(cyan("  Context:"))
        context_snippet = f"{context_before} [{value}] {context_after}".strip()
        wrapped_ctx = textwrap.fill(
            context_snippet, width=62, initial_indent="    ", subsequent_indent="    "
        )
        print(wrapped_ctx)
        print()
    if header_path:
        print(cyan("  Table column:"))
        print(f"    {header_path}")
        print()
    if stub_path:
        print(cyan("  Table row:"))
        print(f"    {stub_path}")
        print()

    print(f"  {'─'*55}")
    print(f"  Dispositions: {green('ACCEPT')}  {yellow('EDIT')}  {red('REJECT')}  SKIP")
    print()

    disposition = prompt("  Your decision [A/E/R/S/U=undo prior]: ", ["A", "E", "R", "S", "U"])
    if disposition == "U":
        return None  # sentinel: caller will step back
    disposition_map = {"A": "ACCEPT", "E": "EDIT", "R": "REJECT", "S": "SKIP"}
    disposition_full = disposition_map[disposition]

    result = deepcopy(candidate)
    result["disposition"] = disposition_full
    result["disposition_reason"] = ""

    if disposition_full == "ACCEPT":
        if is_trap:
            print(red("\n  WARNING: This is a TRAP annotation — you accepted a false positive!"))
            print(red("  Traps should always be REJECTED. Changing to REJECT."))
            result["disposition"] = "REJECT"
            result["disposition_reason"] = "TRAP_ACCEPTED_AUTO_CORRECTED"
            prompt("  Press Enter to continue...", None)
        return result

    elif disposition_full == "REJECT":
        reason = prompt_optional(
            "  Brief reason for rejection (or Enter to skip): ",
            default="",
        )
        result["disposition_reason"] = reason

    elif disposition_full == "EDIT":
        result = _collect_edits(result)

    elif disposition_full == "SKIP":
        pass  # deferred

    return result


def _collect_edits(candidate: dict) -> dict:
    """
    Prompt reviewer to correct specific fields.
    Press Enter to keep the existing value.
    """
    print()
    print(cyan("  EDIT MODE — press Enter to keep existing value"))
    print()

    # metric_id
    current_id = candidate.get("metric_id", "")
    new_id = prompt_optional(
        f"  metric_id [{current_id}]: ",
        default=current_id,
    )
    if new_id and new_id not in ACTIVE_METRICS:
        print(yellow(f"  WARNING: '{new_id}' is not in the active metric set — keeping original"))
        new_id = current_id
    candidate["metric_id"] = new_id

    # value
    current_val = candidate.get("value", "")
    candidate["value"] = prompt_optional(
        f"  value [{current_val or '(empty)'}]: ",
        default=current_val,
    )

    # unit
    current_unit = candidate.get("unit", "")
    new_unit = prompt_optional(f"  unit [{current_unit}]: ", default=current_unit)
    if new_unit and new_unit not in ("currency", "count", "percent", "ratio", ""):
        print(yellow(f"  WARNING: non-standard unit '{new_unit}' — keeping"))
        new_unit = current_unit
    candidate["unit"] = new_unit

    # period
    current_period = candidate.get("period", "")
    candidate["period"] = prompt_optional(
        f"  period [{current_period}]: ",
        default=current_period,
    )

    # source_type
    current_st = candidate.get("source_type", "presentation")
    candidate["source_type"] = prompt_optional(
        f"  source_type [{current_st}]: ",
        default=current_st,
    )

    # Edit reason
    candidate["disposition_reason"] = prompt_optional(
        "  Edit reason (what was wrong): ",
        default="",
    )

    return candidate


# ---------------------------------------------------------------------------
# ADD mode — manual entry of missed metrics
# ---------------------------------------------------------------------------


def collect_add_annotations(ticker: str, date: str, company: str) -> list[dict]:
    """
    After all pipeline candidates are reviewed, prompt reviewer to add any missed items.
    """
    added = []
    print()
    print(bold(f"{'='*65}"))
    print(bold("  ADD MISSED METRICS"))
    print(bold(f"{'='*65}"))
    print("  Enter any metrics the pipeline missed. Type 'done' to finish.")
    print()

    while True:
        metric_id = prompt_optional("  metric_id (or 'done'): ").strip()
        if metric_id.lower() in ("done", ""):
            break

        if metric_id not in ACTIVE_METRICS:
            print(red(f"  Unknown metric: '{metric_id}'"))
            print("  Valid options:", ", ".join(sorted(ACTIVE_METRICS)))
            confirm = prompt_optional("  Add anyway? [y/N]: ", default="N")
            if confirm.upper() != "Y":
                continue

        value = prompt_optional("  value (numeric, or Enter for none): ")
        unit = prompt_optional("  unit [currency/count/percent/ratio]: ", default="count")
        period = prompt_optional("  period (e.g. Q4 FY2025): ")
        source_type = prompt_optional("  source_type [presentation]: ", default="presentation")
        raw_text = prompt_optional("  raw_text (verbatim from slide): ")
        section = prompt_optional(
            "  section [KEY_METRICS/FINANCIAL_OVERVIEW/GUIDANCE/APPENDIX/TITLE_SLIDE]: ",
            default="KEY_METRICS",
        )

        row = {
            "company": company,
            "ticker": ticker,
            "date": date,
            "metric_id": metric_id,
            "value": value,
            "unit": unit,
            "period": period,
            "source_type": source_type,
            "raw_text": raw_text,
            "confidence": "HIGH",  # Human-added annotations are HIGH confidence
            "section": section,
            "is_trap": "false",
            "disposition": "ACCEPT",
            "disposition_reason": "Added by reviewer (pipeline missed)",
        }
        added.append(row)
        print(green(f"  Added: {metric_id} = {value}"))
        print()

    return added


# ---------------------------------------------------------------------------
# Session statistics
# ---------------------------------------------------------------------------


def compute_session_stats(reviewed: list[dict]) -> dict:
    """Compute trap detection rate and disposition distribution."""
    traps = [r for r in reviewed if r.get("is_trap", "false").lower() == "true"]
    non_traps = [r for r in reviewed if r.get("is_trap", "false").lower() == "false"]
    added = [r for r in non_traps if "Added by reviewer" in r.get("disposition_reason", "")]

    trap_rejected = sum(1 for t in traps if t.get("disposition") == "REJECT")
    trap_detection_rate = trap_rejected / max(len(traps), 1)

    non_trap_decided = [r for r in non_traps if r.get("disposition") not in ("SKIP", None)]
    accept_count = sum(1 for r in non_trap_decided if r.get("disposition") == "ACCEPT")
    accept_rate = accept_count / max(len(non_trap_decided), 1)

    return {
        "total_candidates": len(reviewed),
        "traps_total": len(traps),
        "traps_detected": trap_rejected,
        "trap_detection_rate": trap_detection_rate,
        "disposition_accept": accept_count,
        "disposition_edit": sum(1 for r in non_trap_decided if r.get("disposition") == "EDIT"),
        "disposition_reject": sum(1 for r in non_trap_decided if r.get("disposition") == "REJECT"),
        "disposition_skip": sum(1 for r in non_traps if r.get("disposition") == "SKIP"),
        "manually_added": len(added),
        "accept_rate": accept_rate,
    }


def print_session_stats(stats: dict) -> None:
    """Print session statistics with warnings."""
    print()
    print(bold(f"{'='*65}"))
    print(bold("  SESSION STATISTICS"))
    print(bold(f"{'='*65}"))
    print(f"  Total candidates reviewed: {stats['total_candidates']}")
    print()

    # Trap detection
    tdr = stats["trap_detection_rate"]
    tdr_str = f"{tdr:.0%}"
    if tdr < TRAP_ALERT_THRESHOLD:
        print(
            red(
                f"  Trap detection rate:  {tdr_str}  *** BELOW {TRAP_ALERT_THRESHOLD:.0%} — POSSIBLE RUBBER-STAMPING ***"
            )
        )
    else:
        print(
            green(
                f"  Trap detection rate:  {tdr_str}  ({stats['traps_detected']}/{stats['traps_total']})"
            )
        )

    # Disposition distribution
    print()
    print("  Disposition breakdown (non-trap annotations):")
    print(f"    ACCEPT:  {stats['disposition_accept']}")
    print(f"    EDIT:    {stats['disposition_edit']}")
    print(f"    REJECT:  {stats['disposition_reject']}")
    print(f"    SKIP:    {stats['disposition_skip']}")
    print(f"    Added:   {stats['manually_added']}")

    ar = stats["accept_rate"]
    ar_str = f"{ar:.0%}"
    if ar > ACCEPT_RATE_WARNING:
        print()
        print(
            yellow(
                f"  Accept rate: {ar_str}  *** ABOVE {ACCEPT_RATE_WARNING:.0%} — review for rubber-stamping ***"
            )
        )
    else:
        print(f"\n  Accept rate: {ar_str}")

    if stats["manually_added"] == 0:
        print(yellow("\n  NOTE: No annotations were manually added (ADD = 0)."))
        print(yellow("  Consider whether the pipeline missed any metrics."))


# ---------------------------------------------------------------------------
# Main review loop
# ---------------------------------------------------------------------------


def _parse_key_from_filename(stem: str) -> tuple[str, str, str]:
    """Extract (ticker, date, company) from a preannotated filename stem.

    Handles two formats:
      {TICKER}_{DATE}_preannotated      e.g. ADBE_2019-01-24_preannotated
      {TICKER}_{FORM}_{DATE}_preannotated  e.g. NETS_F-1_2017-03-21_preannotated
    Returns (ticker, date, company) where company defaults to ticker.
    """
    import re
    clean = stem.replace("_preannotated", "")
    match = re.search(r"(\d{4}-\d{2}-\d{2})", clean)
    if not match:
        return clean, "", clean
    date = match.group(1)
    prefix = clean[: match.start()].rstrip("_")
    ticker = prefix.split("_")[0]
    return ticker, date, ticker


def review_file(input_path: Path, resume: bool) -> None:
    """
    Run the review loop for a single pre-annotated CSV file.
    """
    # Determine output path
    stem = input_path.stem.replace("_preannotated", "")
    out_path = OUTPUT_DIR / f"{stem}_reviewed.csv"

    # Load candidates
    candidates = load_candidates(input_path)
    zero_candidate_file = not candidates

    if candidates:
        first = candidates[0]
        company = first.get("company", "")
        ticker = first.get("ticker", "")
        date = first.get("date", "")
    else:
        ticker, date, company = _parse_key_from_filename(input_path.stem)
        if not ticker or not date:
            print(f"No candidates found and cannot parse ticker/date from {input_path.name}")
            return
        print(f"No pipeline candidates for {ticker} {date} — entering add-only mode.")

    # Resume: skip already-reviewed candidates
    already_reviewed: list[dict] = []
    reviewed_keys: set[tuple] = set()

    if resume and out_path.exists():
        already_reviewed = load_reviewed(out_path)
        # Key on raw_text (never modified by edits) so resume works correctly
        # even after EDIT dispositions that change metric_id, value, or period.
        # SKIP rows are excluded so they get re-presented on resume.
        reviewed_keys = {
            (r.get("raw_text", ""), r.get("is_trap", ""))
            for r in already_reviewed
            if r.get("disposition") not in ("SKIP", None, "")
        }
        print(f"Resuming: {len(already_reviewed)} already reviewed, skipping those.")

    # Filter to pending candidates
    pending = []
    for c in candidates:
        key = (c.get("raw_text", ""), c.get("is_trap", ""))
        if key not in reviewed_keys:
            pending.append(c)

    total = len(pending)
    if total == 0 and not zero_candidate_file:
        print(green(f"All {len(candidates)} candidates already reviewed."))
        print(f"Output: {out_path}")
        return

    url_index = _load_url_index()
    index_key = input_path.stem.replace("_preannotated", "")
    doc_url = url_index.get(index_key)

    print(f"\nStarting review: {total} pending candidates for {company} ({ticker}) {date}")
    print(f"Output: {out_path}")
    if doc_url:
        print(f"Document: {doc_url}")
    print()
    prompt("Press Enter to begin...", None)

    reviewed_this_session: list[dict] = []

    idx = 0
    while idx < total:
        candidate = pending[idx]
        result = review_candidate(candidate, idx + 1, total)

        if result is None:  # undo requested
            if reviewed_this_session:
                reviewed_this_session.pop()
                idx -= 1
                print(yellow("\n  Undone — re-reviewing previous candidate."))
                prompt("  Press Enter to continue...", None)
            else:
                print(yellow("\n  Nothing to undo."))
                prompt("  Press Enter to continue...", None)
            continue

        reviewed_this_session.append(result)
        idx += 1

        # Save after each annotation (so progress is not lost on interruption)
        all_reviewed = already_reviewed + reviewed_this_session
        write_reviewed(out_path, all_reviewed)

    # Add missed metrics
    added = collect_add_annotations(ticker, date, company)
    reviewed_this_session.extend(added)

    # Final save
    all_reviewed = already_reviewed + reviewed_this_session
    write_reviewed(out_path, all_reviewed)

    # Print session stats (only for this session's decisions)
    stats = compute_session_stats(reviewed_this_session)
    print_session_stats(stats)

    print(bold(f"\n  Output saved: {out_path}"))
    print(f"  Total annotations: {len(all_reviewed)} (incl. previously reviewed)")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Terminal-based presentation annotation review tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              %(prog)s data/presentation_gold_standard/CRM_2025-02-26_preannotated.csv
              %(prog)s data/presentation_gold_standard/*.csv --resume
        """
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Pre-annotated CSV file(s) to review",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a partially completed review session",
    )
    args = parser.parse_args()

    for input_path in args.inputs:
        if not input_path.exists():
            print(f"ERROR: File not found: {input_path}", file=sys.stderr)
            sys.exit(1)

        review_file(input_path, resume=args.resume)

        if len(args.inputs) > 1:
            cont = prompt_optional(
                "\nMove to next file? [Y/n]: ",
                default="Y",
            )
            if cont.upper() == "N":
                print("Review session ended.")
                break


if __name__ == "__main__":
    main()
