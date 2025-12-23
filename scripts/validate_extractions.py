#!/usr/bin/env python3
"""
Validate extraction accuracy with automated sanity checks and sampling.

This script:
1. Loads extracted values from gold standard CSVs
2. Runs automated sanity checks to flag likely errors
3. Samples extractions for manual review
4. Outputs validation report

Usage:
    python3 scripts/validate_extractions.py
    python3 scripts/validate_extractions.py --company "Samsara Inc."
    python3 scripts/validate_extractions.py --sample 50
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

# Sanity check rules: expected unit types per metric
METRIC_UNIT_RULES = {
    "cm_customer_acquisition_cost": ["dollars", "usd", "$", None],  # Should be currency
    "cm_revenue_per_customer": ["dollars", "usd", "$", None],
    "cm_active_customers_total": ["count", None],  # Should be count
    "cm_new_customers_acquired": ["count", None],
    "cm_customer_retention_rate": ["percent", "%", None],  # Should be percentage
    "cm_net_revenue_retention": ["percent", "%", None],
    "cm_gross_margin_by_cohort": ["percent", "%", None],
    "cm_expansion_revenue": ["dollars", "usd", "$", "percent", "%", None],
    "cm_revenue_concentration": ["percent", "%", None],
}

# Value range sanity checks
METRIC_VALUE_RANGES = {
    "cm_customer_retention_rate": (0, 200),  # Percentage, should be 0-100 typically
    "cm_net_revenue_retention": (0, 500),  # NRR can exceed 100%
    "cm_gross_margin_by_cohort": (-100, 100),  # Gross margin percentage
    "cm_revenue_concentration": (0, 100),  # Percentage
}


def load_extractions(data_dir: Path) -> dict:
    """Load all extracted values from gold standard directory."""
    extractions = {}

    for company_dir in data_dir.iterdir():
        if not company_dir.is_dir():
            continue

        values_file = company_dir / "extracted_values.csv"
        if not values_file.exists():
            continue

        metadata_file = company_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
                company_name = metadata.get("company_name", company_dir.name)
        else:
            company_name = company_dir.name

        values = []
        with open(values_file, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                values.append(row)

        extractions[company_name] = {
            "dir": company_dir,
            "values": values,
            "metadata": metadata if metadata_file.exists() else {},
        }

    return extractions


def run_sanity_checks(extractions: dict) -> list:
    """Run automated sanity checks on extractions."""
    issues = []

    for company_name, data in extractions.items():
        for row in data["values"]:
            metric_id = row.get("metric_id", "")
            unit = row.get("unit", "").lower() if row.get("unit") else None
            value = row.get("value_numeric", "")
            source_preview = row.get("source_text_preview", "")[:200]

            # Check unit appropriateness
            if metric_id in METRIC_UNIT_RULES:
                expected_units = METRIC_UNIT_RULES[metric_id]
                if unit and unit.lower() not in [u.lower() if u else None for u in expected_units]:
                    issues.append({
                        "company": company_name,
                        "type": "wrong_unit",
                        "metric": metric_id,
                        "value": value,
                        "unit": unit,
                        "expected": expected_units,
                        "source_preview": source_preview,
                        "severity": "high",
                    })

            # Check value ranges
            if metric_id in METRIC_VALUE_RANGES and value:
                try:
                    val = float(value)
                    min_val, max_val = METRIC_VALUE_RANGES[metric_id]
                    if val < min_val or val > max_val:
                        issues.append({
                            "company": company_name,
                            "type": "out_of_range",
                            "metric": metric_id,
                            "value": val,
                            "expected_range": f"{min_val}-{max_val}",
                            "source_preview": source_preview,
                            "severity": "medium",
                        })
                except (ValueError, TypeError):
                    pass

            # Check for mismatched metric names in source text
            metric_keywords = {
                "cm_customer_acquisition_cost": ["cac", "acquisition cost", "cost to acquire"],
                "cm_new_customers_acquired": ["new customer", "customer growth", "added"],
                "cm_net_revenue_retention": ["nrr", "net revenue retention", "dollar-based"],
                "cm_gross_margin_by_cohort": ["gross margin", "gross profit"],
            }

            if metric_id in metric_keywords:
                keywords = metric_keywords[metric_id]
                source_lower = source_preview.lower()
                has_keyword = any(kw in source_lower for kw in keywords)
                if not has_keyword and source_preview:
                    issues.append({
                        "company": company_name,
                        "type": "missing_keyword",
                        "metric": metric_id,
                        "value": value,
                        "expected_keywords": keywords,
                        "source_preview": source_preview,
                        "severity": "low",
                    })

    return issues


def sample_for_review(extractions: dict, sample_size: int = 50) -> list:
    """Sample extractions for manual review."""
    import random

    all_values = []
    for company_name, data in extractions.items():
        for row in data["values"]:
            all_values.append({
                "company": company_name,
                **row,
            })

    if len(all_values) <= sample_size:
        return all_values

    return random.sample(all_values, sample_size)


def generate_report(extractions: dict, issues: list, sample: list = None) -> str:
    """Generate validation report."""
    lines = []
    lines.append("# Extraction Validation Report\n")

    # Summary
    total_values = sum(len(data["values"]) for data in extractions.values())
    total_companies = len(extractions)

    lines.append("## Summary\n")
    lines.append(f"- Companies analyzed: {total_companies}")
    lines.append(f"- Total extractions: {total_values}")
    lines.append(f"- Issues found: {len(issues)}")
    lines.append(f"- Issue rate: {len(issues)/total_values*100:.1f}%\n" if total_values > 0 else "")

    # Issues by type
    lines.append("## Issues by Type\n")
    issue_counts = defaultdict(int)
    for issue in issues:
        issue_counts[issue["type"]] += 1

    for issue_type, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {issue_type}: {count}")

    # High severity issues
    high_severity = [i for i in issues if i.get("severity") == "high"]
    if high_severity:
        lines.append(f"\n## High Severity Issues ({len(high_severity)})\n")
        for issue in high_severity[:20]:  # Limit output
            lines.append(f"### {issue['company']} - {issue['metric']}")
            lines.append(f"- Type: {issue['type']}")
            lines.append(f"- Value: {issue.get('value')} {issue.get('unit', '')}")
            if issue.get("expected"):
                lines.append(f"- Expected units: {issue['expected']}")
            lines.append(f"- Source: {issue.get('source_preview', '')[:100]}...")
            lines.append("")

    # Sample for manual review
    if sample:
        lines.append(f"\n## Sample for Manual Review ({len(sample)} items)\n")
        lines.append("| Company | Metric | Value | Unit | Source Preview |")
        lines.append("|---------|--------|-------|------|----------------|")
        for item in sample[:20]:
            source = item.get("source_text_preview", "")[:50].replace("|", "\\|")
            lines.append(f"| {item['company'][:20]} | {item.get('metric_name', '')[:25]} | {item.get('value_numeric', '')} | {item.get('unit', '')} | {source}... |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Validate extraction accuracy")
    parser.add_argument("--input", default="data/gold_standard", help="Gold standard directory")
    parser.add_argument("--company", help="Filter to specific company")
    parser.add_argument("--sample", type=int, default=50, help="Sample size for manual review")
    parser.add_argument("--output", help="Output report file")
    args = parser.parse_args()

    data_dir = Path(args.input)
    if not data_dir.exists():
        print(f"Error: Directory {data_dir} not found")
        return

    print(f"Loading extractions from {data_dir}...")
    extractions = load_extractions(data_dir)

    if args.company:
        extractions = {k: v for k, v in extractions.items() if args.company.lower() in k.lower()}

    if not extractions:
        print("No extractions found")
        return

    print(f"Loaded {sum(len(d['values']) for d in extractions.values())} extractions from {len(extractions)} companies")

    print("Running sanity checks...")
    issues = run_sanity_checks(extractions)
    print(f"Found {len(issues)} potential issues")

    print(f"Sampling {args.sample} items for manual review...")
    sample = sample_for_review(extractions, args.sample)

    report = generate_report(extractions, issues, sample)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print("\n" + "="*60)
        print(report)


if __name__ == "__main__":
    main()
