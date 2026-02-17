#!/usr/bin/env python3
"""
Transcript Extraction Validator — Measure V2 pipeline performance on transcripts.

Runs the V2 pipeline (with transcript config) on sample transcripts,
compares against manual annotations, and reports recall/precision/F1.

Supports baseline comparison for regression detection.

Usage:
    # Run validation and print results
    python3 scripts/validate_transcript_extraction.py

    # Save current results as baseline
    python3 scripts/validate_transcript_extraction.py --save-baseline

    # Compare against saved baseline
    python3 scripts/validate_transcript_extraction.py --baseline

    # Verbose: show per-fact details and missed metrics
    python3 scripts/validate_transcript_extraction.py --verbose

    # Filter to specific tickers
    python3 scripts/validate_transcript_extraction.py --ticker CRM META
"""

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction_v2.pipeline import PipelineConfig, PipelineResult, V2Pipeline

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("transcript_validator")

# Paths
HTML_DIR = ROOT / "data" / "spike_samples" / "transcripts_html"
ANNOTATIONS_PATH = ROOT / "data" / "spike_samples" / "manual_annotations.csv"
RESULTS_DIR = ROOT / "data" / "spike_results"
BASELINE_PATH = RESULTS_DIR / "transcript_baseline.json"

# Tolerance for value matching (5%)
VALUE_TOLERANCE = 0.05


def load_annotations(path: Path) -> dict[str, list[dict]]:
    """Load manual annotations, grouped by 'TICKER_DATE' key."""
    annotations: dict[str, list[dict]] = {}
    if not path.exists():
        logger.warning("Annotations file not found: %s", path)
        return annotations

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = f"{row['ticker']}_{row['date']}"
            annotations.setdefault(key, []).append(row)

    return annotations


def match_facts_to_annotations(
    facts: list,
    annotations: list[dict],
    tolerance: float = VALUE_TOLERANCE,
) -> dict:
    """
    Match extracted facts against manual annotations.

    Returns dict with matched, unmatched_annotations (FN), unmatched_facts (FP).
    """
    matched = []
    used_annotations: set[int] = set()
    used_facts: set[int] = set()

    for i, fact in enumerate(facts):
        for j, ann in enumerate(annotations):
            if j in used_annotations:
                continue

            if fact.canonical_metric_id != ann["metric_id"]:
                continue

            try:
                ann_value = float(ann["value"])
                if fact.value is not None and ann_value != 0:
                    if abs(fact.value - ann_value) / abs(ann_value) <= tolerance:
                        matched.append((fact, ann))
                        used_annotations.add(j)
                        used_facts.add(i)
                        break
                elif fact.value is not None and ann_value == 0 and fact.value == 0:
                    matched.append((fact, ann))
                    used_annotations.add(j)
                    used_facts.add(i)
                    break
            except (ValueError, TypeError):
                matched.append((fact, ann))
                used_annotations.add(j)
                used_facts.add(i)
                break

    return {
        "matched": matched,
        "unmatched_annotations": [
            ann for j, ann in enumerate(annotations) if j not in used_annotations
        ],
        "unmatched_facts": [
            fact for i, fact in enumerate(facts) if i not in used_facts
        ],
    }


def compute_scores(match_result: dict) -> dict:
    """Compute recall, precision, F1 from match results."""
    tp = len(match_result["matched"])
    fn = len(match_result["unmatched_annotations"])
    fp = len(match_result["unmatched_facts"])

    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1 = (
        2 * recall * precision / (recall + precision)
        if (recall + precision) > 0
        else 0.0
    )

    return {
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def run_validation(
    html_files: list[Path],
    annotations: dict[str, list[dict]],
    verbose: bool = False,
) -> list[dict]:
    """Run pipeline on all files and collect per-file results."""
    config = PipelineConfig.for_transcript()
    pipeline = V2Pipeline(config=config)
    results = []

    for html_file in html_files:
        stem = html_file.stem
        parts = stem.split("_", 1)
        ticker = parts[0] if parts else stem
        date_str = parts[1] if len(parts) > 1 else ""
        ann_key = f"{ticker}_{date_str}"

        try:
            result = pipeline.process(html_path=html_file, filing_id=-1)
        except Exception as e:
            logger.error("Pipeline failed for %s: %s", html_file.name, e)
            results.append({
                "file": html_file.name,
                "ticker": ticker,
                "date": date_str,
                "pipeline_success": False,
                "error": str(e),
            })
            continue

        file_annotations = annotations.get(ann_key, [])
        metrics: dict = {}

        if file_annotations:
            match_result = match_facts_to_annotations(result.facts, file_annotations)
            metrics = compute_scores(match_result)

            if verbose and match_result["unmatched_annotations"]:
                print(f"\n  {ticker} {date_str} — Missed metrics:")
                for ann in match_result["unmatched_annotations"]:
                    print(
                        f"    {ann['metric_id']}: {ann['value']} "
                        f'— "{ann.get("raw_text", "")[:80]}"'
                    )

            if verbose and match_result["unmatched_facts"]:
                print(f"  {ticker} {date_str} — Extra facts (FP):")
                for fact in match_result["unmatched_facts"]:
                    print(
                        f"    {fact.canonical_metric_id}: {fact.value} "
                        f"[{fact.confidence:.2f}]"
                    )

        results.append({
            "file": html_file.name,
            "ticker": ticker,
            "date": date_str,
            "pipeline_success": result.success,
            "duration_ms": result.total_duration_ms,
            "segments": len(result.segments),
            "facts_extracted": result.fact_count,
            "annotations_count": len(file_annotations),
            "true_positives": metrics.get("true_positives", 0),
            "false_negatives": metrics.get("false_negatives", 0),
            "false_positives": metrics.get("false_positives", 0),
            "recall": metrics.get("recall", 0),
            "precision": metrics.get("precision", 0),
            "f1": metrics.get("f1", 0),
        })

    return results


def aggregate_scores(results: list[dict]) -> dict:
    """Compute aggregate recall/precision/F1 across all annotated files."""
    with_ann = [r for r in results if r.get("annotations_count", 0) > 0]
    if not with_ann:
        return {"recall": 0, "precision": 0, "f1": 0, "total_annotations": 0}

    total_tp = sum(r["true_positives"] for r in with_ann)
    total_fn = sum(r["false_negatives"] for r in with_ann)
    total_fp = sum(r["false_positives"] for r in with_ann)

    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    f1 = (
        2 * recall * precision / (recall + precision)
        if (recall + precision) > 0
        else 0
    )

    return {
        "total_annotations": total_tp + total_fn,
        "true_positives": total_tp,
        "false_negatives": total_fn,
        "false_positives": total_fp,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def per_company_scores(results: list[dict]) -> dict[str, dict]:
    """Compute per-company aggregate scores."""
    by_company: dict[str, list[dict]] = {}
    for r in results:
        ticker = r.get("ticker", "UNKNOWN")
        by_company.setdefault(ticker, []).append(r)

    scores = {}
    for ticker, company_results in sorted(by_company.items()):
        agg = aggregate_scores(company_results)
        if agg["total_annotations"] > 0:
            scores[ticker] = agg
    return scores


def save_baseline(results: list[dict], agg: dict, per_company: dict) -> Path:
    """Save current results as baseline JSON."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    baseline = {
        "timestamp": datetime.now().isoformat(),
        "aggregate": agg,
        "per_company": per_company,
        "per_file": [
            {k: v for k, v in r.items() if k != "stage_stats"}
            for r in results
        ],
    }
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2))
    return BASELINE_PATH


def load_baseline() -> dict | None:
    """Load baseline JSON if it exists."""
    if not BASELINE_PATH.exists():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupted baseline file: %s", BASELINE_PATH)
        return None


def print_comparison(current_agg: dict, baseline: dict) -> bool:
    """Print comparison between current and baseline results. Returns True if no regression."""
    base_agg = baseline["aggregate"]
    print("\n" + "=" * 70)
    print("BASELINE COMPARISON")
    print(f"  Baseline from: {baseline['timestamp']}")
    print("=" * 70)

    no_regression = True

    for metric in ("recall", "precision", "f1"):
        curr = current_agg.get(metric, 0)
        base = base_agg.get(metric, 0)
        delta = curr - base
        direction = "+" if delta >= 0 else ""
        status = "OK" if delta >= -0.01 else "REGRESSION"
        if status == "REGRESSION":
            no_regression = False
        print(f"  {metric.upper():12s}: {curr:.1%} (was {base:.1%}, {direction}{delta:.1%}) [{status}]")

    # Per-company diff
    base_per_company = baseline.get("per_company", {})
    curr_per_company = per_company_scores(
        baseline.get("_current_results", [])
    ) if "_current_results" in baseline else {}

    return no_regression


def print_results(results: list[dict], agg: dict, company_scores: dict, verbose: bool) -> None:
    """Print formatted results table."""
    print("\n" + "=" * 70)
    print("TRANSCRIPT EXTRACTION VALIDATION")
    print("=" * 70)

    successful = [r for r in results if r.get("pipeline_success")]
    with_ann = [r for r in successful if r.get("annotations_count", 0) > 0]

    print(f"  Files processed:    {len(results)}")
    print(f"  Pipeline successes: {len(successful)}")
    print(f"  With annotations:   {len(with_ann)}")

    # Aggregate scores
    print(f"\n  AGGREGATE SCORES:")
    print(f"    Recall:    {agg['recall']:.1%} ({agg.get('true_positives', 0)}/{agg.get('total_annotations', 0)})")
    print(f"    Precision: {agg['precision']:.1%}")
    print(f"    F1:        {agg['f1']:.1%}")

    # Per-company table
    if company_scores:
        print(f"\n  PER-COMPANY BREAKDOWN:")
        print(f"  {'Ticker':<8} {'R':>6} {'P':>6} {'F1':>6} {'TP':>4} {'FN':>4} {'FP':>4}")
        print(f"  {'-'*42}")
        for ticker, scores in sorted(company_scores.items()):
            print(
                f"  {ticker:<8} "
                f"{scores['recall']:>5.0%} "
                f"{scores['precision']:>5.0%} "
                f"{scores['f1']:>5.0%} "
                f"{scores['true_positives']:>4} "
                f"{scores['false_negatives']:>4} "
                f"{scores['false_positives']:>4}"
            )

    total_facts = sum(r.get("facts_extracted", 0) for r in successful)
    avg_duration = (
        sum(r.get("duration_ms", 0) for r in successful) / max(len(successful), 1)
    )
    print(f"\n  Total facts extracted: {total_facts}")
    print(f"  Average duration:     {avg_duration:.0f}ms")


def main():
    parser = argparse.ArgumentParser(
        description="Validate V2 pipeline transcript extraction against annotations."
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Compare against saved baseline and flag regressions",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Save current results as the new baseline",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-fact details and missed metrics",
    )
    parser.add_argument(
        "--ticker",
        nargs="+",
        help="Filter to specific tickers (e.g., --ticker CRM META)",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=HTML_DIR,
        help="Directory containing transcript HTML files",
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=ANNOTATIONS_PATH,
        help="Path to manual annotations CSV",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    # Load inputs
    html_files = sorted(args.html_dir.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {args.html_dir}")
        sys.exit(1)

    # Filter by ticker if specified
    if args.ticker:
        tickers = {t.upper() for t in args.ticker}
        html_files = [
            f for f in html_files if f.stem.split("_", 1)[0].upper() in tickers
        ]
        if not html_files:
            print(f"No files found for tickers: {', '.join(args.ticker)}")
            sys.exit(1)

    annotations = load_annotations(args.annotations)
    if not annotations:
        print(f"WARNING: No annotations loaded from {args.annotations}")

    # Run validation
    print(f"Processing {len(html_files)} transcript files...")
    results = run_validation(html_files, annotations, verbose=args.verbose)

    # Compute scores
    agg = aggregate_scores(results)
    company_scores = per_company_scores(results)

    # Print results
    print_results(results, agg, company_scores, args.verbose)

    # Baseline comparison
    if args.baseline:
        baseline = load_baseline()
        if baseline:
            no_regression = print_comparison(agg, baseline)
            if not no_regression:
                print("\n  ** REGRESSION DETECTED — review changes before merging **")
                sys.exit(1)
        else:
            print(f"\n  No baseline found at {BASELINE_PATH}")
            print("  Run with --save-baseline first.")

    # Save baseline
    if args.save_baseline:
        path = save_baseline(results, agg, company_scores)
        print(f"\n  Baseline saved to: {path}")

    # Write detailed CSV
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_csv = RESULTS_DIR / "transcripts_results.csv"
    fieldnames = [
        "file", "ticker", "date", "pipeline_success", "duration_ms",
        "segments", "facts_extracted", "annotations_count",
        "true_positives", "false_negatives", "false_positives",
        "recall", "precision", "f1",
    ]
    with open(results_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\n  Results CSV: {results_csv}")


if __name__ == "__main__":
    main()
