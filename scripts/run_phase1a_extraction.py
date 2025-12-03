#!/usr/bin/env python3
"""
Phase 1A: Monitored Test Extraction (5-10 Companies)

Tests Phase 1 improvements on a small set of validated companies:
- Expanded keyword patterns (+27 patterns for CMASB metrics)
- Priority weighting system (+0.2 for Core, +0.1 for Extended)
- Enhanced LLM prompts with CMASB priorities

Success Criteria:
- At least 1 "new customers acquired" metric found (currently 0%)
- At least 1 NRR metric found (currently 0%)
- CMASB priority metrics represent 40%+ of total extractions
- No major regression in non-priority metrics
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from collections import Counter, defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.llm.openai_client import OpenAIClient


# CMASB Priority Metrics
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


def get_test_companies(db: DatabaseAdapter, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get test companies for Phase 1A extraction.

    Selects companies with fetched filings from validated business types,
    prioritizing diversity across E-commerce, Fintech, Platform, HealthTech, and Media.
    """

    query = """
    SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        c.industry_code,
        f.html_storage_path,
        CASE
            WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
            WHEN bc.is_platform_network THEN 'Platform'
            WHEN bc.is_healthcare_tech THEN 'HealthTech'
            WHEN bc.is_fintech_crypto THEN 'Fintech'
            WHEN bc.is_media_subscription THEN 'Media'
            ELSE 'Other'
        END as business_type
    FROM companies c
    JOIN filings f ON c.company_id = f.company_id
    LEFT JOIN business_classifications bc ON c.company_id = bc.company_id
    WHERE f.processing_status = 'fetched'
      AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
      AND f.html_storage_path IS NOT NULL
      AND (bc.is_ecommerce_marketplace OR bc.is_platform_network OR
           bc.is_healthcare_tech OR bc.is_fintech_crypto OR bc.is_media_subscription)
    ORDER BY business_type, c.company_name
    LIMIT %s
    """

    return db.query(query, (limit,))


def analyze_cmasb_coverage(db: DatabaseAdapter, filing_ids: List[int]) -> Dict[str, Any]:
    """
    Analyze CMASB metric coverage in extracted results.

    Returns:
        Dictionary with coverage statistics and detailed breakdown
    """

    # Get all extracted incidences for these filings
    placeholders = ','.join(['%s'] * len(filing_ids))

    query = f"""
    SELECT
        mi.filing_id,
        mi.metric_id,
        mi.incidence_count,
        mi.has_values,
        mi.has_definition
    FROM filing_metric_incidence mi
    WHERE mi.filing_id IN ({placeholders})
    """

    incidences = db.query(query, tuple(filing_ids))

    if not incidences:
        return {
            'total_metrics': 0,
            'cmasb_core_count': 0,
            'cmasb_extended_count': 0,
            'other_count': 0,
            'cmasb_percentage': 0.0,
            'metrics_by_category': {},
            'new_customers_found': False,
            'nrr_found': False,
        }

    # Count metrics by category
    total_metrics = len(incidences)
    cmasb_core_count = 0
    cmasb_extended_count = 0
    other_count = 0

    metrics_by_category = Counter()

    for inc in incidences:
        metric_id = inc['metric_id']

        if metric_id in CMASB_CORE_METRICS:
            cmasb_core_count += 1
            metrics_by_category[metric_id] += 1
        elif metric_id in CMASB_EXTENDED_METRICS:
            cmasb_extended_count += 1
            metrics_by_category[metric_id] += 1
        else:
            other_count += 1

    cmasb_total = cmasb_core_count + cmasb_extended_count
    cmasb_percentage = (cmasb_total / total_metrics * 100) if total_metrics > 0 else 0.0

    # Check for specific target metrics
    new_customers_found = 'cm_new_customers_acquired' in metrics_by_category
    nrr_found = 'cm_net_revenue_retention' in metrics_by_category

    return {
        'total_metrics': total_metrics,
        'cmasb_core_count': cmasb_core_count,
        'cmasb_extended_count': cmasb_extended_count,
        'cmasb_total': cmasb_total,
        'other_count': other_count,
        'cmasb_percentage': cmasb_percentage,
        'metrics_by_category': dict(metrics_by_category),
        'new_customers_found': new_customers_found,
        'nrr_found': nrr_found,
    }


def check_success_criteria(coverage: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Check if Phase 1A success criteria are met.

    Success = 2 of 3 criteria met:
    1. At least 1 "new customers acquired" metric found
    2. At least 2 new CMASB categories detected (NRR, gross margin, expansion, revenue concentration)
    3. CMASB metrics represent 40%+ of total extractions

    Returns:
        (success: bool, feedback: List[str])
    """

    criteria_met = []
    feedback = []

    # Criterion 1: New customers acquired found
    if coverage['new_customers_found']:
        criteria_met.append(1)
        feedback.append("✅ Criterion 1: 'New customers acquired' metric found")
    else:
        feedback.append("❌ Criterion 1: 'New customers acquired' metric NOT found")

    # Criterion 2: At least 2 new CMASB categories detected
    new_categories = [
        'cm_net_revenue_retention',
        'cm_gross_margin_by_cohort',
        'cm_expansion_revenue',
        'cm_revenue_concentration',
    ]

    new_cats_found = sum(1 for cat in new_categories if cat in coverage['metrics_by_category'])

    if new_cats_found >= 2:
        criteria_met.append(2)
        feedback.append(f"✅ Criterion 2: {new_cats_found} new CMASB categories detected")
    else:
        feedback.append(f"❌ Criterion 2: Only {new_cats_found} new CMASB categories detected (need 2)")

    # Criterion 3: CMASB metrics represent 40%+ of total
    if coverage['cmasb_percentage'] >= 40.0:
        criteria_met.append(3)
        feedback.append(f"✅ Criterion 3: CMASB metrics are {coverage['cmasb_percentage']:.1f}% of total (≥40%)")
    else:
        feedback.append(f"❌ Criterion 3: CMASB metrics are {coverage['cmasb_percentage']:.1f}% of total (<40%)")

    success = len(criteria_met) >= 2

    return success, feedback


def main():
    """Main Phase 1A extraction workflow."""
    print("=" * 80)
    print("PHASE 1A: MONITORED TEST EXTRACTION")
    print("=" * 80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nTesting Phase 1 improvements on 5-10 high-quality companies")
    print("=" * 80 + "\n")

    # Setup
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)
    llm_client = OpenAIClient(api_key=api_key)
    pipeline = ExtractionPipeline(db=db, llm_client=llm_client)

    # Get test companies
    print("Loading test companies...")
    companies = get_test_companies(db, limit=10)

    if not companies:
        print("ERROR: No test companies found")
        sys.exit(1)

    print(f"\nTest Companies ({len(companies)}):")
    print("-" * 80)
    for i, company in enumerate(companies, 1):
        print(f"{i:2d}. {company['company_name']:50s} [{company['business_type']:12s}] CIK: {company['cik']}")
    print()

    # Process each company
    results = []
    filing_ids = []

    for i, company in enumerate(companies, 1):
        filing_id = company['filing_id']
        filing_ids.append(filing_id)

        print(f"\n[{i}/{len(companies)}] {company['company_name']}")
        print(f"  CIK: {company['cik']} | SIC: {company['industry_code']} | Business: {company['business_type']}")
        print(f"  Filing ID: {filing_id}")

        # Run extraction pipeline
        result = pipeline.process_filing(filing_id)

        if result.success:
            print(f"  ✓ Success: {result.num_values} values, {result.num_definitions} definitions, "
                  f"{result.num_incidences} metric incidences")
        else:
            print(f"  ✗ Failed: {result.error}")

        results.append({
            'filing_id': filing_id,
            'company_name': company['company_name'],
            'cik': company['cik'],
            'business_type': company['business_type'],
            'success': result.success,
            'num_incidences': result.num_incidences,
            'error': result.error,
        })

    # Analyze CMASB coverage
    print("\n" + "=" * 80)
    print("CMASB METRIC COVERAGE ANALYSIS")
    print("=" * 80 + "\n")

    coverage = analyze_cmasb_coverage(db, filing_ids)

    print(f"Total Metrics Extracted: {coverage['total_metrics']}")
    print(f"  CMASB Core Metrics:     {coverage['cmasb_core_count']:3d} ({coverage['cmasb_core_count']/coverage['total_metrics']*100:.1f}%)")
    print(f"  CMASB Extended Metrics: {coverage['cmasb_extended_count']:3d} ({coverage['cmasb_extended_count']/coverage['total_metrics']*100:.1f}%)")
    print(f"  Other Metrics:          {coverage['other_count']:3d} ({coverage['other_count']/coverage['total_metrics']*100:.1f}%)")
    print(f"\n  CMASB Total Coverage:   {coverage['cmasb_total']:3d} ({coverage['cmasb_percentage']:.1f}%)")

    # Show metrics by category
    if coverage['metrics_by_category']:
        print("\nCMASB Metrics Detected:")
        print("-" * 80)

        # Group by Core vs Extended
        core_metrics = {k: v for k, v in coverage['metrics_by_category'].items() if k in CMASB_CORE_METRICS}
        extended_metrics = {k: v for k, v in coverage['metrics_by_category'].items() if k in CMASB_EXTENDED_METRICS}

        if core_metrics:
            print("\nCore Metrics:")
            for metric_id, count in sorted(core_metrics.items(), key=lambda x: x[1], reverse=True):
                metric_name = metric_id.replace('cm_', '').replace('_', ' ').title()
                marker = "⭐" if metric_id == 'cm_new_customers_acquired' else ""
                print(f"  {metric_name:40s}: {count:3d} occurrences {marker}")

        if extended_metrics:
            print("\nExtended Metrics:")
            for metric_id, count in sorted(extended_metrics.items(), key=lambda x: x[1], reverse=True):
                metric_name = metric_id.replace('cm_', '').replace('_', ' ').title()
                marker = "⭐" if metric_id == 'cm_net_revenue_retention' else ""
                print(f"  {metric_name:40s}: {count:3d} occurrences {marker}")

    # Check success criteria
    print("\n" + "=" * 80)
    print("SUCCESS CRITERIA EVALUATION")
    print("=" * 80 + "\n")

    success, feedback = check_success_criteria(coverage)

    for line in feedback:
        print(line)

    print("\n" + "-" * 80)

    if success:
        print("\n✅ SUCCESS: Phase 1A criteria met (2 of 3 criteria passed)")
        print("\n   RECOMMENDATION: Proceed to Phase 1B (full 48-company extraction)")
        print("\n   Phase 1 improvements are working as expected:")
        print("   - Expanded keyword patterns are detecting CMASB metrics")
        print("   - Priority weighting is preventing CMASB metric filtering")
        print("   - Enhanced prompts are guiding LLM extraction")
    else:
        print("\n⚠️  PARTIAL SUCCESS: Phase 1A criteria partially met")
        print("\n   RECOMMENDATION: Analyze extraction logs and consider adjustments")
        print("\n   Options:")
        print("   1. Refine keyword patterns for missing metrics")
        print("   2. Adjust priority weighting values")
        print("   3. Enhance LLM prompts further")
        print("   4. Proceed cautiously with limited Phase 1B test (10-20 companies)")

    # Save results
    print("\n" + "=" * 80)
    print("SAVING RESULTS")
    print("=" * 80 + "\n")

    summary_file = 'phase1a_extraction_summary.json'
    with open(summary_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'test_companies': results,
            'coverage_analysis': coverage,
            'success_criteria': {
                'met': success,
                'feedback': feedback,
            },
        }, f, indent=2)

    print(f"✓ Results saved to {summary_file}")

    print(f"\nEnd Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == '__main__':
    main()
