#!/usr/bin/env python3
"""
POC Runner: Execute V2 pipeline on transcript samples and measure results.

For each transcript HTML file:
1. Run V2 pipeline
2. Capture all extracted facts
3. Compare against manual annotations
4. Compute recall and precision
5. Log per-stage behavior

Output: data/spike_results/transcripts_results.csv

This is a spike script — not production code.
"""

import csv
import json
import logging
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig, PipelineResult


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("poc_runner")


def load_annotations(annotations_path: Path) -> dict[str, list[dict]]:
    """
    Load manual annotations, grouped by (ticker, date).

    Returns:
        Dict mapping "TICKER_DATE" to list of annotation dicts
    """
    annotations: dict[str, list[dict]] = {}
    if not annotations_path.exists():
        logger.warning(f"Annotations file not found: {annotations_path}")
        return annotations

    with open(annotations_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = f"{row['ticker']}_{row['date']}"
            if key not in annotations:
                annotations[key] = []
            annotations[key].append(row)

    return annotations


def run_pipeline_on_file(pipeline: V2Pipeline, html_path: Path) -> PipelineResult:
    """Run V2 pipeline on a single HTML file."""
    logger.info(f"Processing: {html_path.name}")
    result = pipeline.process(
        html_path=html_path,
        filing_id=-1,  # Dummy ID for spike
    )
    return result


def match_facts_to_annotations(
    facts: list,
    annotations: list[dict],
    tolerance: float = 0.05,
) -> dict:
    """
    Match extracted facts against manual annotations.

    Returns dict with:
    - matched: list of (fact, annotation) pairs
    - unmatched_annotations: annotations with no matching fact (missed = low recall)
    - unmatched_facts: facts with no matching annotation (false positives)
    """
    matched = []
    used_annotations = set()
    used_facts = set()

    for i, fact in enumerate(facts):
        for j, ann in enumerate(annotations):
            if j in used_annotations:
                continue

            # Match by metric ID
            if fact.canonical_metric_id != ann["metric_id"]:
                continue

            # Match by value (with tolerance)
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
                # If value can't be parsed, match on metric ID alone
                matched.append((fact, ann))
                used_annotations.add(j)
                used_facts.add(i)
                break

    unmatched_annotations = [
        ann for j, ann in enumerate(annotations) if j not in used_annotations
    ]
    unmatched_facts = [
        fact for i, fact in enumerate(facts) if i not in used_facts
    ]

    return {
        "matched": matched,
        "unmatched_annotations": unmatched_annotations,
        "unmatched_facts": unmatched_facts,
    }


def compute_metrics(match_result: dict) -> dict:
    """Compute recall and precision from match results."""
    tp = len(match_result["matched"])
    fn = len(match_result["unmatched_annotations"])
    fp = len(match_result["unmatched_facts"])

    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0

    return {
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "recall": recall,
        "precision": precision,
        "f1": f1,
    }


def extract_stage_stats(result: PipelineResult) -> dict:
    """Extract per-stage statistics from pipeline result."""
    stats = {}
    for sr in result.stage_results:
        stats[sr.stage.value] = {
            "success": sr.success,
            "items_in": sr.items_processed,
            "items_out": sr.items_output,
            "duration_ms": sr.duration_ms,
            "errors": len(sr.errors),
            "warnings": len(sr.warnings),
        }
    return stats


def main():
    html_dir = ROOT / "data" / "spike_samples" / "transcripts_html"
    annotations_path = ROOT / "data" / "spike_samples" / "manual_annotations.csv"
    results_dir = ROOT / "data" / "spike_results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Check inputs
    html_files = sorted(html_dir.glob("*.html"))
    if not html_files:
        print(f"No HTML files found in {html_dir}")
        print("Run scripts/spike/convert_transcript_to_html.py first.")
        sys.exit(1)

    annotations = load_annotations(annotations_path)
    if not annotations:
        print(f"WARNING: No annotations loaded from {annotations_path}")
        print("Results will show extraction output but cannot compute recall/precision.")

    # Configure pipeline for transcript processing
    config = PipelineConfig.for_transcript()
    pipeline = V2Pipeline(config=config)

    # Results storage
    all_results = []

    print("=" * 70)
    print("V2 PIPELINE POC — EARNINGS CALL TRANSCRIPTS")
    print("=" * 70)

    for html_file in html_files:
        # Derive key from filename (e.g., CRM_2025-02-26.html -> CRM_2025-02-26)
        stem = html_file.stem
        parts = stem.split("_", 1)
        ticker = parts[0] if parts else stem
        date_str = parts[1] if len(parts) > 1 else ""
        ann_key = f"{ticker}_{date_str}"

        print(f"\n{'—' * 50}")
        print(f"File: {html_file.name}")
        print(f"Ticker: {ticker}, Date: {date_str}")

        # Run pipeline
        try:
            result = run_pipeline_on_file(pipeline, html_file)
        except Exception as e:
            logger.error(f"Pipeline failed for {html_file.name}: {e}")
            all_results.append({
                "file": html_file.name,
                "ticker": ticker,
                "date": date_str,
                "pipeline_success": False,
                "error": str(e),
            })
            continue

        # Pipeline stats
        stage_stats = extract_stage_stats(result)
        print(f"  Pipeline: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"  Duration: {result.total_duration_ms}ms")
        print(f"  Segments: {len(result.segments)}")
        print(f"  Tables: {len(result.tables)}")
        print(f"  Facts extracted: {result.fact_count}")

        # Print extracted facts
        if result.facts:
            print(f"\n  Extracted facts:")
            for fact in result.facts:
                print(f"    {fact.canonical_metric_id}: {fact.value} "
                      f"({fact.unit.value}) [{fact.confidence:.2f}]")
                if fact.evidence_pack.raw_value_text:
                    print(f"      raw: \"{fact.evidence_pack.raw_value_text}\"")

        # Compare against annotations
        file_annotations = annotations.get(ann_key, [])
        match_result = None
        metrics = {}

        if file_annotations:
            match_result = match_facts_to_annotations(result.facts, file_annotations)
            metrics = compute_metrics(match_result)

            print(f"\n  Annotations: {len(file_annotations)} manual metrics")
            print(f"  Matched: {metrics['true_positives']}")
            print(f"  Missed (FN): {metrics['false_negatives']}")
            print(f"  Extra (FP): {metrics['false_positives']}")
            print(f"  Recall: {metrics['recall']:.1%}")
            print(f"  Precision: {metrics['precision']:.1%}")
            print(f"  F1: {metrics['f1']:.1%}")

            if match_result["unmatched_annotations"]:
                print(f"\n  Missed metrics:")
                for ann in match_result["unmatched_annotations"]:
                    print(f"    {ann['metric_id']}: {ann['value']} "
                          f"- \"{ann.get('raw_text', '')[:80]}\"")
        else:
            print(f"\n  No annotations available for {ann_key}")

        # Stage-by-stage stats
        print(f"\n  Stage stats:")
        for stage_name, stats in stage_stats.items():
            print(f"    {stage_name}: in={stats['items_in']} out={stats['items_out']} "
                  f"ok={stats['success']} {stats['duration_ms']}ms")

        all_results.append({
            "file": html_file.name,
            "ticker": ticker,
            "date": date_str,
            "pipeline_success": result.success,
            "duration_ms": result.total_duration_ms,
            "segments": len(result.segments),
            "tables": len(result.tables),
            "facts_extracted": result.fact_count,
            "annotations_count": len(file_annotations),
            "true_positives": metrics.get("true_positives", 0),
            "false_negatives": metrics.get("false_negatives", 0),
            "false_positives": metrics.get("false_positives", 0),
            "recall": metrics.get("recall", 0),
            "precision": metrics.get("precision", 0),
            "f1": metrics.get("f1", 0),
            "stage_stats": json.dumps(stage_stats),
        })

    # Write results CSV
    results_path = results_dir / "transcripts_results.csv"
    fieldnames = [
        "file", "ticker", "date", "pipeline_success", "duration_ms",
        "segments", "tables", "facts_extracted", "annotations_count",
        "true_positives", "false_negatives", "false_positives",
        "recall", "precision", "f1", "stage_stats",
    ]

    with open(results_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_results:
            writer.writerow(r)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    successful = [r for r in all_results if r.get("pipeline_success")]
    with_annotations = [r for r in successful if r.get("annotations_count", 0) > 0]

    print(f"Files processed: {len(all_results)}")
    print(f"Pipeline successes: {len(successful)}")
    print(f"With annotations: {len(with_annotations)}")

    if with_annotations:
        total_tp = sum(r["true_positives"] for r in with_annotations)
        total_fn = sum(r["false_negatives"] for r in with_annotations)
        total_fp = sum(r["false_positives"] for r in with_annotations)

        agg_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        agg_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        agg_f1 = 2 * agg_recall * agg_precision / (agg_recall + agg_precision) if (agg_recall + agg_precision) > 0 else 0

        print(f"\nAggregate metrics (across annotated files):")
        print(f"  Total annotations: {total_tp + total_fn}")
        print(f"  True positives: {total_tp}")
        print(f"  False negatives: {total_fn}")
        print(f"  False positives: {total_fp}")
        print(f"  Recall: {agg_recall:.1%}")
        print(f"  Precision: {agg_precision:.1%}")
        print(f"  F1: {agg_f1:.1%}")

    total_facts = sum(r.get("facts_extracted", 0) for r in successful)
    avg_duration = sum(r.get("duration_ms", 0) for r in successful) / max(len(successful), 1)
    print(f"\nTotal facts extracted: {total_facts}")
    print(f"Average duration: {avg_duration:.0f}ms")
    print(f"\nResults written to: {results_path}")


if __name__ == "__main__":
    main()
