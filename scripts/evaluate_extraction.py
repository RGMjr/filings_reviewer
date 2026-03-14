#!/usr/bin/env python3
"""
Evaluate extraction accuracy against gold standard labels.

This script reads the human-reviewed CSV files and calculates:
- Precision: What % of extracted items are correct
- Recall: What % of actual items were found
- Accuracy by metric type, extraction method, etc.

Usage:
    python scripts/evaluate_extraction.py
    python scripts/evaluate_extraction.py --input data/gold_standard
    python scripts/evaluate_extraction.py --detailed
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_reviewed_values(csv_path: Path) -> tuple[list, list]:
    """
    Load reviewed values from CSV.

    Returns:
        (reviewed_items, missed_items)
    """
    reviewed = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("review_status"):  # Has been reviewed
                reviewed.append(row)
    return reviewed


def load_missed_items(csv_path: Path) -> list:
    """Load missed items that human identified."""
    if not csv_path.exists():
        return []

    missed = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("metric_id"):  # Has content
                missed.append(row)
    return missed


def calculate_metrics(reviewed: list, missed: list) -> dict:
    """
    Calculate precision, recall, and F1.

    review_status values:
    - correct: Extraction was accurate
    - incorrect: Extraction was wrong (value, metric type, or period)
    - partial: Partially correct
    """
    if not reviewed and not missed:
        return {"error": "No reviewed data"}

    # Count by status
    correct = sum(1 for r in reviewed if r.get("review_status", "").lower() == "correct")
    incorrect = sum(1 for r in reviewed if r.get("review_status", "").lower() == "incorrect")
    partial = sum(1 for r in reviewed if r.get("review_status", "").lower() == "partial")
    total_extracted = len(reviewed)
    total_missed = len(missed)

    # Calculate metrics
    # Precision = correct / (correct + incorrect + partial)
    # Treating partial as 0.5 correct
    if total_extracted > 0:
        precision = (correct + 0.5 * partial) / total_extracted
    else:
        precision = 0

    # Recall = found / (found + missed)
    # "found" includes correct and partial, but not incorrect (which are false positives)
    found = correct + partial
    total_actual = found + total_missed
    if total_actual > 0:
        recall = found / total_actual
    else:
        recall = 0

    # F1 score
    if precision + recall > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0

    return {
        "total_extracted": total_extracted,
        "correct": correct,
        "incorrect": incorrect,
        "partial": partial,
        "missed": total_missed,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1_score": round(f1, 3),
    }


def calculate_by_metric(reviewed: list) -> dict:
    """Calculate accuracy breakdown by metric type."""
    by_metric = defaultdict(lambda: {"correct": 0, "incorrect": 0, "partial": 0, "total": 0})

    for r in reviewed:
        metric = r.get("metric_id", "unknown")
        status = r.get("review_status", "").lower()
        by_metric[metric]["total"] += 1
        if status in ["correct", "incorrect", "partial"]:
            by_metric[metric][status] += 1

    # Calculate accuracy per metric
    result = {}
    for metric, counts in by_metric.items():
        if counts["total"] > 0:
            accuracy = (counts["correct"] + 0.5 * counts["partial"]) / counts["total"]
            result[metric] = {
                "total": counts["total"],
                "correct": counts["correct"],
                "incorrect": counts["incorrect"],
                "partial": counts["partial"],
                "accuracy": round(accuracy, 3),
            }

    return result


def calculate_by_extraction_method(reviewed: list) -> dict:
    """Calculate accuracy breakdown by extraction method."""
    by_method = defaultdict(lambda: {"correct": 0, "incorrect": 0, "partial": 0, "total": 0})

    for r in reviewed:
        method = r.get("extraction_method", "unknown")
        status = r.get("review_status", "").lower()
        by_method[method]["total"] += 1
        if status in ["correct", "incorrect", "partial"]:
            by_method[method][status] += 1

    result = {}
    for method, counts in by_method.items():
        if counts["total"] > 0:
            accuracy = (counts["correct"] + 0.5 * counts["partial"]) / counts["total"]
            result[method] = {
                "total": counts["total"],
                "correct": counts["correct"],
                "incorrect": counts["incorrect"],
                "partial": counts["partial"],
                "accuracy": round(accuracy, 3),
            }

    return result


def evaluate_company(company_dir: Path) -> dict:
    """Evaluate a single company's extraction."""
    values_file = company_dir / "extracted_values.csv"
    defs_file = company_dir / "extracted_definitions.csv"
    missed_file = company_dir / "missed_items_template.csv"

    result = {
        "company": company_dir.name,
        "values": None,
        "definitions": None,
    }

    # Evaluate metric values
    if values_file.exists():
        reviewed = load_reviewed_values(values_file)
        if reviewed:
            missed_values = [
                m for m in load_missed_items(missed_file)
                if m.get("item_type", "").lower() == "value"
            ]
            result["values"] = {
                "overall": calculate_metrics(reviewed, missed_values),
                "by_metric": calculate_by_metric(reviewed),
                "by_method": calculate_by_extraction_method(reviewed),
            }

    # Evaluate definitions
    if defs_file.exists():
        reviewed = load_reviewed_values(defs_file)
        if reviewed:
            missed_defs = [
                m for m in load_missed_items(missed_file)
                if m.get("item_type", "").lower() == "definition"
            ]
            result["definitions"] = {
                "overall": calculate_metrics(reviewed, missed_defs),
                "by_metric": calculate_by_metric(reviewed),
            }

    return result


def aggregate_results(company_results: list) -> dict:
    """Aggregate results across all companies."""
    all_values = {
        "total_extracted": 0,
        "correct": 0,
        "incorrect": 0,
        "partial": 0,
        "missed": 0,
    }
    all_defs = {
        "total_extracted": 0,
        "correct": 0,
        "incorrect": 0,
        "partial": 0,
        "missed": 0,
    }

    reviewed_companies = 0

    for cr in company_results:
        if cr.get("values") and cr["values"].get("overall"):
            v = cr["values"]["overall"]
            if "error" not in v:
                reviewed_companies += 1
                all_values["total_extracted"] += v["total_extracted"]
                all_values["correct"] += v["correct"]
                all_values["incorrect"] += v["incorrect"]
                all_values["partial"] += v["partial"]
                all_values["missed"] += v["missed"]

        if cr.get("definitions") and cr["definitions"].get("overall"):
            d = cr["definitions"]["overall"]
            if "error" not in d:
                all_defs["total_extracted"] += d["total_extracted"]
                all_defs["correct"] += d["correct"]
                all_defs["incorrect"] += d["incorrect"]
                all_defs["partial"] += d["partial"]
                all_defs["missed"] += d["missed"]

    # Calculate aggregate metrics
    def calc_agg_metrics(totals):
        if totals["total_extracted"] == 0:
            return {"note": "No reviewed items"}

        precision = (totals["correct"] + 0.5 * totals["partial"]) / totals["total_extracted"]
        found = totals["correct"] + totals["partial"]
        total_actual = found + totals["missed"]
        recall = found / total_actual if total_actual > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        return {
            **totals,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1_score": round(f1, 3),
        }

    return {
        "companies_reviewed": reviewed_companies,
        "values": calc_agg_metrics(all_values),
        "definitions": calc_agg_metrics(all_defs),
    }


def print_report(results: dict, detailed: bool = False):
    """Print evaluation report."""
    print("\n" + "=" * 70)
    print("EXTRACTION EVALUATION REPORT")
    print("=" * 70)

    agg = results["aggregate"]
    print(f"\nCompanies reviewed: {agg['companies_reviewed']}")

    # Metric Values Summary
    print("\n" + "-" * 40)
    print("METRIC VALUES")
    print("-" * 40)
    v = agg["values"]
    if "note" not in v:
        print(f"Total extracted: {v['total_extracted']}")
        print(f"  Correct:   {v['correct']} ({v['correct']/v['total_extracted']*100:.1f}%)")
        print(f"  Partial:   {v['partial']} ({v['partial']/v['total_extracted']*100:.1f}%)")
        print(f"  Incorrect: {v['incorrect']} ({v['incorrect']/v['total_extracted']*100:.1f}%)")
        print(f"Missed:      {v['missed']}")
        print(f"\nPrecision: {v['precision']:.1%}")
        print(f"Recall:    {v['recall']:.1%}")
        print(f"F1 Score:  {v['f1_score']:.1%}")
    else:
        print("No values have been reviewed yet.")

    # Definitions Summary
    print("\n" + "-" * 40)
    print("DEFINITIONS")
    print("-" * 40)
    d = agg["definitions"]
    if "note" not in d:
        print(f"Total extracted: {d['total_extracted']}")
        print(f"  Correct:   {d['correct']} ({d['correct']/d['total_extracted']*100:.1f}%)")
        print(f"  Partial:   {d['partial']} ({d['partial']/d['total_extracted']*100:.1f}%)")
        print(f"  Incorrect: {d['incorrect']} ({d['incorrect']/d['total_extracted']*100:.1f}%)")
        print(f"Missed:      {d['missed']}")
        print(f"\nPrecision: {d['precision']:.1%}")
        print(f"Recall:    {d['recall']:.1%}")
        print(f"F1 Score:  {d['f1_score']:.1%}")
    else:
        print("No definitions have been reviewed yet.")

    if detailed:
        print("\n" + "=" * 70)
        print("PER-COMPANY BREAKDOWN")
        print("=" * 70)
        for cr in results["companies"]:
            if cr.get("values") and cr["values"].get("overall") and "error" not in cr["values"]["overall"]:
                v = cr["values"]["overall"]
                print(f"\n{cr['company']}:")
                print(f"  Values: {v['correct']}/{v['total_extracted']} correct, "
                      f"precision={v['precision']:.0%}, recall={v['recall']:.0%}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate extraction accuracy against gold standard"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data/gold_standard",
        help="Directory containing gold standard data",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed per-company breakdown",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file for results",
    )
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"Error: Input directory not found: {input_dir}")
        return

    # Find company directories
    company_dirs = [d for d in input_dir.iterdir() if d.is_dir()]

    if not company_dirs:
        print(f"No company directories found in {input_dir}")
        print("Run export_for_evaluation.py first to export data for review.")
        return

    print(f"Found {len(company_dirs)} company directories")

    # Evaluate each company
    company_results = []
    for company_dir in sorted(company_dirs):
        result = evaluate_company(company_dir)
        company_results.append(result)

    # Aggregate results
    aggregate = aggregate_results(company_results)

    results = {
        "aggregate": aggregate,
        "companies": company_results,
    }

    # Print report
    print_report(results, detailed=args.detailed)

    # Save to file if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
