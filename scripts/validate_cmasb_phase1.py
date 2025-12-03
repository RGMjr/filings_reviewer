#!/usr/bin/env python3
"""
Validate CMASB Phase 1 Improvements

This script re-runs extraction on 5 sample filings to measure the impact
of Phase 1 keyword pattern expansion, priority weighting, and prompt updates.

Compares before (Phase 5) vs after (Phase 1) results to verify:
- Increased CMASB priority metric coverage
- New detection of missing metrics (new customers, NRR, gross margin, etc.)
- Maintained breadth (non-priority metrics still captured)
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.extraction.extraction_pipeline import ExtractionPipeline
from src.infra.db import DatabaseAdapter
from src.llm.openai_client import OpenAIClient

# Test Cases: 5 diverse companies with different business types and metric counts
TEST_CASES = [
    {
        "company_name": "Academy Sports & Outdoors, Inc.",
        "cik": "0001817358",
        "business_type": "E-commerce",
        "phase5_metrics": 13,
        "rationale": "Known to have 'new customers' data - tests improved detection"
    },
    {
        "company_name": "agilon health, inc.",
        "cik": "0001831097",
        "business_type": "HealthTech",
        "phase5_metrics": 29,
        "rationale": "Medium metric count - tests retention/churn improvements"
    },
    {
        "company_name": "Savers Value Village, Inc.",
        "cik": "0001883313",
        "business_type": "E-commerce",
        "phase5_metrics": 44,
        "rationale": "High metric count - tests if we maintain breadth"
    },
    {
        "company_name": "Sea Ltd",
        "cik": "0001703399",
        "business_type": "Platform",
        "phase5_metrics": 67,
        "rationale": "Very high metrics - tests cohort table detection improvements"
    },
    {
        "company_name": "American Well Corp",
        "cik": "0001393584",
        "business_type": "Platform",
        "phase5_metrics": 72,
        "rationale": "Highest metrics - comprehensive test of all improvements"
    }
]

# CMASB Priority Metrics (for analysis)
CMASB_CORE_METRICS = {
    'cm_new_customers_acquired',
    'cm_customers_period_end_by_tenure',
    'cm_revenue_by_cohort',
    'cm_transactions_by_cohort',
}

CMASB_EXTENDED_METRICS = {
    'cm_customer_acquisition_cost',
    'cm_active_customers_total',
    'cm_revenue_per_customer',
    'cm_gross_margin_by_cohort',
    'cm_revenue_concentration',
    'cm_customer_churn_rate',
    'cm_customer_retention_rate',
    'cm_net_revenue_retention',
    'cm_expansion_revenue',
}

# Metric name mappings for analysis (Phase 5 used different naming)
METRIC_NAME_PATTERNS = {
    'new_customers': ['new_customer', 'new_user', 'customer_growth', 'customers_acquired', 'acquired'],
    'nrr': ['net_revenue_retention', 'nrr', 'net_retention', 'net_dollar_retention', 'ndr'],
    'gross_margin': ['gross_margin', 'gross_profit'],
    'expansion': ['expansion', 'cross_sell', 'upsell', 'products_per_customer'],
    'revenue_concentration': ['concentration', 'top_customers', 'major_customers'],
    'cac': ['customer_acquisition_cost', 'cac', 'acquisition_cost'],
    'churn': ['churn', 'attrition'],
    'retention': ['retention'],
    'active_customers': ['active_user', 'active_customer', 'mau', 'dau'],
    'revenue_per_customer': ['arpu', 'revenue_per_user', 'revenue_per_customer'],
}


def load_phase5_results() -> Dict[str, List[Dict]]:
    """Load Phase 5 extraction results for comparison."""
    phase5_file = os.path.join(
        os.path.dirname(__file__), '..', 'phase5_extracted_metrics.json'
    )

    if not os.path.exists(phase5_file):
        print(f"WARNING: Phase 5 results file not found: {phase5_file}")
        return {}

    with open(phase5_file, 'r') as f:
        all_metrics = json.load(f)

    # Group by company
    by_company = defaultdict(list)
    for metric in all_metrics:
        company_name = metric.get('company', '')
        by_company[company_name].append(metric)

    return dict(by_company)


def categorize_metric(metric_name: str) -> str:
    """Categorize a metric by its name pattern."""
    metric_lower = metric_name.lower()

    for category, patterns in METRIC_NAME_PATTERNS.items():
        if any(p in metric_lower for p in patterns):
            return category

    return 'other'


def analyze_metrics(metrics: List[Dict]) -> Dict[str, Any]:
    """Analyze a list of metrics and return summary statistics."""
    total = len(metrics)

    # Count by category
    categories = Counter()
    for metric in metrics:
        metric_name = metric.get('metric_name', '')
        category = categorize_metric(metric_name)
        categories[category] += 1

    # Count CMASB priority metrics
    cmasb_core_count = 0
    cmasb_extended_count = 0
    for metric in metrics:
        metric_id = metric.get('candidate_metric_id', '')
        if metric_id in CMASB_CORE_METRICS:
            cmasb_core_count += 1
        elif metric_id in CMASB_EXTENDED_METRICS:
            cmasb_extended_count += 1

    # Extract unique metric names
    unique_metric_names = set(m.get('metric_name', '') for m in metrics)

    return {
        'total': total,
        'categories': dict(categories),
        'cmasb_core_count': cmasb_core_count,
        'cmasb_extended_count': cmasb_extended_count,
        'cmasb_total': cmasb_core_count + cmasb_extended_count,
        'unique_metric_names': sorted(unique_metric_names),
    }


def run_extraction_for_test_case(test_case: Dict, db: DatabaseAdapter, pipeline: ExtractionPipeline) -> List[Dict]:
    """Run extraction for a single test case."""
    company_name = test_case['company_name']
    cik = test_case['cik']

    print(f"\n{'='*80}")
    print(f"Running extraction for: {company_name} (CIK {cik})")
    print(f"Business Type: {test_case['business_type']}")
    print(f"Phase 5 Metrics: {test_case['phase5_metrics']}")
    print(f"Rationale: {test_case['rationale']}")
    print(f"{'='*80}\n")

    # Get company_id from database
    query = "SELECT company_id FROM companies WHERE cik = %s"
    result = db.query(query, (cik,))

    if not result:
        print(f"ERROR: Company not found in database for CIK {cik}")
        return []

    company_id = result[0]['company_id']

    # Get filing_id
    filing_query = """
    SELECT filing_id
    FROM filings
    WHERE company_id = %s
    AND form_type IN ('S-1', 'S-1/A')
    ORDER BY filing_date DESC
    LIMIT 1
    """
    filing_result = db.query(filing_query, (company_id,))

    if not filing_result:
        print(f"ERROR: No S-1 filing found for {company_name}")
        return []

    filing_id = filing_result[0]['filing_id']

    print(f"Found filing_id: {filing_id}")
    print(f"Starting extraction...\n")

    try:
        # Run extraction
        extracted_metrics = pipeline.extract_from_filing(filing_id, company_id)

        print(f"✅ Extraction complete: {len(extracted_metrics)} metrics found")

        return extracted_metrics

    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return []


def compare_results(phase5_metrics: List[Dict], phase1_metrics: List[Dict], test_case: Dict) -> Dict:
    """Compare Phase 5 vs Phase 1 results."""
    phase5_analysis = analyze_metrics(phase5_metrics)
    phase1_analysis = analyze_metrics(phase1_metrics)

    # Calculate improvements
    total_change = phase1_analysis['total'] - phase5_analysis['total']
    total_pct_change = (total_change / phase5_analysis['total'] * 100) if phase5_analysis['total'] > 0 else 0

    cmasb_change = phase1_analysis['cmasb_total'] - phase5_analysis['cmasb_total']
    cmasb_pct_change = (
        (cmasb_change / phase5_analysis['cmasb_total'] * 100)
        if phase5_analysis['cmasb_total'] > 0
        else (100 if cmasb_change > 0 else 0)
    )

    # Find new CMASB metrics
    new_cmasb_categories = set()
    for category in ['new_customers', 'nrr', 'gross_margin', 'expansion', 'revenue_concentration']:
        phase5_count = phase5_analysis['categories'].get(category, 0)
        phase1_count = phase1_analysis['categories'].get(category, 0)
        if phase1_count > phase5_count:
            new_cmasb_categories.add(category)

    return {
        'company_name': test_case['company_name'],
        'business_type': test_case['business_type'],
        'phase5': phase5_analysis,
        'phase1': phase1_analysis,
        'total_change': total_change,
        'total_pct_change': total_pct_change,
        'cmasb_change': cmasb_change,
        'cmasb_pct_change': cmasb_pct_change,
        'new_cmasb_categories': sorted(new_cmasb_categories),
    }


def generate_report(comparisons: List[Dict], output_file: str):
    """Generate validation report."""
    print(f"\n{'='*80}")
    print("CMASB PHASE 1 VALIDATION REPORT")
    print(f"{'='*80}\n")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test Cases: {len(comparisons)}")
    print()

    # Overall statistics
    total_phase5 = sum(c['phase5']['total'] for c in comparisons)
    total_phase1 = sum(c['phase1']['total'] for c in comparisons)
    total_cmasb_phase5 = sum(c['phase5']['cmasb_total'] for c in comparisons)
    total_cmasb_phase1 = sum(c['phase1']['cmasb_total'] for c in comparisons)

    print("OVERALL RESULTS")
    print("-" * 80)
    print(f"Total Metrics Extracted:")
    print(f"  Phase 5 (Baseline): {total_phase5}")
    print(f"  Phase 1 (New):      {total_phase1}")
    print(f"  Change:             {total_phase1 - total_phase5:+d} ({(total_phase1 - total_phase5) / total_phase5 * 100:+.1f}%)")
    print()
    print(f"CMASB Priority Metrics:")
    print(f"  Phase 5 (Baseline): {total_cmasb_phase5}")
    print(f"  Phase 1 (New):      {total_cmasb_phase1}")
    print(f"  Change:             {total_cmasb_phase1 - total_cmasb_phase5:+d} ({(total_cmasb_phase1 - total_cmasb_phase5) / total_cmasb_phase5 * 100:+.1f}%)" if total_cmasb_phase5 > 0 else "  Change:             N/A (no baseline)")
    print()

    # Per-company results
    print("\nPER-COMPANY RESULTS")
    print("-" * 80)
    for comp in comparisons:
        print(f"\n{comp['company_name']} ({comp['business_type']})")
        print(f"  Total Metrics:    {comp['phase5']['total']:3d} → {comp['phase1']['total']:3d}  ({comp['total_change']:+d}, {comp['total_pct_change']:+.1f}%)")
        print(f"  CMASB Metrics:    {comp['phase5']['cmasb_total']:3d} → {comp['phase1']['cmasb_total']:3d}  ({comp['cmasb_change']:+d}, {comp['cmasb_pct_change']:+.1f}%)")

        if comp['new_cmasb_categories']:
            print(f"  ✨ NEW Categories: {', '.join(comp['new_cmasb_categories'])}")

    # Category breakdown
    print("\n\nCATEGORY BREAKDOWN (All Companies Combined)")
    print("-" * 80)

    all_categories = set()
    for comp in comparisons:
        all_categories.update(comp['phase5']['categories'].keys())
        all_categories.update(comp['phase1']['categories'].keys())

    category_totals_phase5 = Counter()
    category_totals_phase1 = Counter()

    for comp in comparisons:
        for cat, count in comp['phase5']['categories'].items():
            category_totals_phase5[cat] += count
        for cat, count in comp['phase1']['categories'].items():
            category_totals_phase1[cat] += count

    print(f"{'Category':<25} {'Phase 5':>10} {'Phase 1':>10} {'Change':>10} {'%':>8}")
    print("-" * 80)

    # Priority categories first
    priority_cats = ['new_customers', 'nrr', 'gross_margin', 'expansion', 'revenue_concentration',
                     'cac', 'churn', 'retention', 'active_customers', 'revenue_per_customer']

    for cat in priority_cats:
        phase5_count = category_totals_phase5[cat]
        phase1_count = category_totals_phase1[cat]
        change = phase1_count - phase5_count
        pct_change = (change / phase5_count * 100) if phase5_count > 0 else (100 if change > 0 else 0)

        marker = "⭐" if change > 0 and cat in ['new_customers', 'nrr', 'gross_margin', 'expansion', 'revenue_concentration'] else ""

        print(f"{cat:<25} {phase5_count:>10d} {phase1_count:>10d} {change:>+10d} {pct_change:>+7.1f}% {marker}")

    # Other categories
    other_cats = sorted(set(all_categories) - set(priority_cats))
    if other_cats:
        print()
        for cat in other_cats:
            phase5_count = category_totals_phase5[cat]
            phase1_count = category_totals_phase1[cat]
            change = phase1_count - phase5_count
            pct_change = (change / phase5_count * 100) if phase5_count > 0 else 0

            print(f"{cat:<25} {phase5_count:>10d} {phase1_count:>10d} {change:>+10d} {pct_change:>+7.1f}%")

    # Success criteria
    print(f"\n\nSUCCESS CRITERIA")
    print("-" * 80)

    criteria_results = []

    # Criterion 1: At least 1 "new customers acquired" found (currently 0)
    new_customers_phase1 = category_totals_phase1.get('new_customers', 0)
    criterion1 = new_customers_phase1 > 0
    criteria_results.append(("At least 1 'new customers acquired' metric found", criterion1))

    # Criterion 2: At least 1 NRR metric found (currently 0)
    nrr_phase1 = category_totals_phase1.get('nrr', 0)
    criterion2 = nrr_phase1 > 0
    criteria_results.append(("At least 1 NRR metric found", criterion2))

    # Criterion 3: CMASB metrics increased by 40%+
    criterion3 = cmasb_pct_change >= 40 if total_cmasb_phase5 > 0 else total_cmasb_phase1 >= 10
    criteria_results.append((f"CMASB coverage increased by 40%+ (actual: {cmasb_pct_change:+.1f}%)", criterion3))

    # Criterion 4: At least 1 new CMASB category detected (gross margin, expansion, or revenue concentration)
    new_critical_cats = {'gross_margin', 'expansion', 'revenue_concentration'} & set(
        cat for comp in comparisons for cat in comp['new_cmasb_categories']
    )
    criterion4 = len(new_critical_cats) > 0
    criteria_results.append((f"At least 1 new critical category detected ({', '.join(new_critical_cats) if new_critical_cats else 'none'})", criterion4))

    for criterion, result in criteria_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {criterion}")

    # Final recommendation
    passed = sum(1 for _, result in criteria_results if result)
    total_criteria = len(criteria_results)

    print(f"\n\nFINAL RECOMMENDATION")
    print("-" * 80)
    print(f"Criteria Passed: {passed}/{total_criteria}")

    if passed >= 3:
        print("\n✅ RECOMMENDATION: **GO** - Phase 1 improvements are effective")
        print("   Proceed with production deployment on 48 validated companies")
    elif passed >= 2:
        print("\n⚠️  RECOMMENDATION: **CONDITIONAL GO** - Moderate improvements")
        print("   Consider minor prompt tuning before production deployment")
    else:
        print("\n❌ RECOMMENDATION: **NO GO** - Insufficient improvement")
        print("   Investigate extraction logs and refine keyword patterns")

    # Save detailed report
    with open(output_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'test_cases': comparisons,
            'overall': {
                'total_phase5': total_phase5,
                'total_phase1': total_phase1,
                'cmasb_phase5': total_cmasb_phase5,
                'cmasb_phase1': total_cmasb_phase1,
            },
            'category_breakdown': {
                'phase5': dict(category_totals_phase5),
                'phase1': dict(category_totals_phase1),
            },
            'criteria_results': {desc: result for desc, result in criteria_results},
            'passed_criteria': passed,
            'total_criteria': total_criteria,
        }, f, indent=2)

    print(f"\n\nDetailed report saved to: {output_file}")


def main():
    """Main validation function."""
    print("CMASB Phase 1 Validation Script")
    print("=" * 80)
    print("\nThis script will:")
    print("1. Load Phase 5 (baseline) extraction results")
    print("2. Re-run extraction on 5 test cases with Phase 1 improvements")
    print("3. Compare before/after CMASB priority metric coverage")
    print("4. Generate validation report with GO/NO-GO recommendation")
    print("\n" + "=" * 80 + "\n")

    # Load Phase 5 baseline
    print("Loading Phase 5 baseline results...")
    phase5_results = load_phase5_results()
    print(f"Loaded results for {len(phase5_results)} companies\n")

    # Initialize components
    print("Initializing extraction pipeline...")
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)
    llm_client = OpenAIClient()
    pipeline = ExtractionPipeline(db, llm_client)
    print("✅ Pipeline ready\n")

    # Run extraction on test cases
    comparisons = []

    for test_case in TEST_CASES:
        # Get Phase 5 baseline
        company_name = test_case['company_name']
        phase5_metrics = phase5_results.get(company_name, [])

        if not phase5_metrics:
            print(f"WARNING: No Phase 5 baseline found for {company_name}, skipping...")
            continue

        # Run Phase 1 extraction
        phase1_metrics = run_extraction_for_test_case(test_case, db, pipeline)

        if not phase1_metrics:
            print(f"WARNING: Phase 1 extraction failed for {company_name}, skipping...")
            continue

        # Compare results
        comparison = compare_results(phase5_metrics, phase1_metrics, test_case)
        comparisons.append(comparison)

        print(f"\n✅ Comparison complete for {company_name}")
        print(f"   Total: {comparison['phase5']['total']} → {comparison['phase1']['total']} ({comparison['total_change']:+d})")
        print(f"   CMASB: {comparison['phase5']['cmasb_total']} → {comparison['phase1']['cmasb_total']} ({comparison['cmasb_change']:+d})")
        if comparison['new_cmasb_categories']:
            print(f"   ✨ NEW: {', '.join(comparison['new_cmasb_categories'])}")

    # Generate report
    if comparisons:
        output_file = os.path.join(
            os.path.dirname(__file__), '..', 'cmasb_phase1_validation_report.json'
        )
        generate_report(comparisons, output_file)
    else:
        print("\n❌ ERROR: No successful comparisons - validation failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
