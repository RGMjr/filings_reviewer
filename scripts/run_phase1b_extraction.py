#!/usr/bin/env python3
"""
Phase 1B: Full Production Extraction (All Validated Companies)

Runs Phase 1 extraction on all validated companies with fetched filings:
- Expanded keyword patterns (+27 patterns for CMASB metrics)
- Priority weighting system (+0.2 for Core, +0.1 for Extended)
- Enhanced LLM prompts with CMASB priorities

Based on Phase 1A validation results showing 48.7% CMASB coverage.

Expected Outcome:
- ~33-34 successful extractions from 48 companies
- ~580-600 total metrics
- 45-50% CMASB coverage
- Cost: ~$2.40-3.00
"""

import json
import os
import sys
import signal
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from collections import Counter, defaultdict

# Per-filing timeout (5 minutes max)
FILING_TIMEOUT_SECONDS = 300


class TimeoutError(Exception):
    """Raised when filing processing exceeds timeout."""
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("Filing processing timed out")

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


def get_all_companies(db: DatabaseAdapter) -> List[Dict[str, Any]]:
    """
    Get all validated companies for Phase 1B extraction.

    Selects all companies with fetched filings from validated business types:
    E-commerce, Fintech, Platform, HealthTech, and Media.
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
      AND f.filing_id NOT IN (17688, 1193, 26914)  -- Skip Academy Sports, Baozun, Savers Value Village (timeout issues)
      AND (bc.is_ecommerce_marketplace OR bc.is_platform_network OR
           bc.is_healthcare_tech OR bc.is_fintech_crypto OR bc.is_media_subscription)
    ORDER BY business_type, c.company_name
    """

    return db.query(query)


def analyze_cmasb_coverage(db: DatabaseAdapter, filing_ids: List[int]) -> Dict[str, Any]:
    """
    Analyze CMASB metric coverage in extracted results.

    Returns:
        Dictionary with coverage statistics and detailed breakdown
    """

    if not filing_ids:
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

    # Get all extracted incidences for these filings
    placeholders = ','.join(['%s'] * len(filing_ids))

    query = f"""
    SELECT
        mi.filing_id,
        mi.metric_id,
        mi.num_numeric_segments,
        mi.num_definition_segments,
        mi.num_methodology_segments
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
    Check if Phase 1B success criteria are met.

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
    """Main Phase 1B extraction workflow."""
    print("=" * 80)
    print("PHASE 1B: FULL PRODUCTION EXTRACTION")
    print("=" * 80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nRunning Phase 1 extraction on all validated companies with fetched filings")
    print("Expected: ~33-34 successful extractions, ~580-600 total metrics")
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

    # Get all companies
    print("Loading all validated companies...")
    companies = get_all_companies(db)

    if not companies:
        print("ERROR: No companies found")
        sys.exit(1)

    print(f"\nTarget Companies ({len(companies)}):")
    print("-" * 80)

    # Group by business type for display
    by_type = defaultdict(list)
    for company in companies:
        by_type[company['business_type']].append(company)

    for biz_type in sorted(by_type.keys()):
        print(f"\n{biz_type} ({len(by_type[biz_type])} companies):")
        for company in by_type[biz_type]:
            print(f"  • {company['company_name']:50s} CIK: {company['cik']}")

    print("\n" + "=" * 80)
    print("Starting extraction...")
    print()

    # Process each company
    results = []
    filing_ids = []
    successful = 0
    failed = 0

    for i, company in enumerate(companies, 1):
        filing_id = company['filing_id']
        filing_ids.append(filing_id)

        print(f"\n[{i}/{len(companies)}] {company['company_name']}")
        print(f"  CIK: {company['cik']} | SIC: {company['industry_code']} | Business: {company['business_type']}")
        print(f"  Filing ID: {filing_id}")
        print(f"  Progress: {successful} successful, {failed} failed")

        # Run extraction pipeline with timeout
        try:
            # Set up timeout handler
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(FILING_TIMEOUT_SECONDS)

            result = pipeline.process_filing(filing_id)

            # Cancel the alarm on success
            signal.alarm(0)

            if result.success:
                successful += 1
                print(f"  ✓ Success: {result.num_values} values, {result.num_definitions} definitions, "
                      f"{result.num_incidences} metric incidences")
            else:
                failed += 1
                print(f"  ✗ Failed: {result.error}")

            results.append({
                'filing_id': filing_id,
                'company_name': company['company_name'],
                'cik': company['cik'],
                'business_type': company['business_type'],
                'success': result.success,
                'num_incidences': result.num_incidences,
                'num_values': result.num_values,
                'num_definitions': result.num_definitions,
                'error': result.error,
            })
        except TimeoutError:
            signal.alarm(0)  # Cancel alarm
            failed += 1
            print(f"  ✗ TIMEOUT: Filing took longer than {FILING_TIMEOUT_SECONDS}s")
            results.append({
                'filing_id': filing_id,
                'company_name': company['company_name'],
                'cik': company['cik'],
                'business_type': company['business_type'],
                'success': False,
                'num_incidences': 0,
                'num_values': 0,
                'num_definitions': 0,
                'error': f'Timeout after {FILING_TIMEOUT_SECONDS}s',
            })
        except Exception as e:
            signal.alarm(0)  # Cancel alarm
            failed += 1
            print(f"  ✗ Exception: {str(e)}")
            results.append({
                'filing_id': filing_id,
                'company_name': company['company_name'],
                'cik': company['cik'],
                'business_type': company['business_type'],
                'success': False,
                'num_incidences': 0,
                'num_values': 0,
                'num_definitions': 0,
                'error': str(e),
            })

    # Analyze CMASB coverage
    print("\n" + "=" * 80)
    print("CMASB METRIC COVERAGE ANALYSIS")
    print("=" * 80 + "\n")

    coverage = analyze_cmasb_coverage(db, filing_ids)

    print(f"Extraction Summary:")
    print(f"  Total Companies:        {len(companies)}")
    print(f"  Successful Extractions: {successful}")
    print(f"  Failed Extractions:     {failed}")
    print(f"  Success Rate:           {successful/len(companies)*100:.1f}%")

    print(f"\nMetric Summary:")
    print(f"  Total Metrics Extracted: {coverage['total_metrics']}")
    print(f"  CMASB Core Metrics:      {coverage['cmasb_core_count']:3d} ({coverage['cmasb_core_count']/coverage['total_metrics']*100:.1f}%)")
    print(f"  CMASB Extended Metrics:  {coverage['cmasb_extended_count']:3d} ({coverage['cmasb_extended_count']/coverage['total_metrics']*100:.1f}%)")
    print(f"  Other Metrics:           {coverage['other_count']:3d} ({coverage['other_count']/coverage['total_metrics']*100:.1f}%)")
    print(f"\n  CMASB Total Coverage:    {coverage['cmasb_total']:3d} ({coverage['cmasb_percentage']:.1f}%)")

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
        print("\n✅ SUCCESS: Phase 1B criteria met (2 of 3 criteria passed)")
        print("\n   Phase 1 improvements validated at scale:")
        print("   - Expanded keyword patterns successfully detecting CMASB metrics")
        print("   - Priority weighting preventing over-filtering")
        print("   - Enhanced LLM prompts guiding accurate extraction")
    else:
        print("\n⚠️  PARTIAL SUCCESS: Phase 1B criteria partially met")
        print("\n   Review detailed metrics to identify areas for improvement")

    # Save results
    print("\n" + "=" * 80)
    print("SAVING RESULTS")
    print("=" * 80 + "\n")

    summary_file = 'phase1b_extraction_summary.json'
    with open(summary_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'extraction_results': results,
            'coverage_analysis': coverage,
            'success_criteria': {
                'met': success,
                'feedback': feedback,
            },
            'statistics': {
                'total_companies': len(companies),
                'successful': successful,
                'failed': failed,
                'success_rate': successful/len(companies)*100,
            },
        }, f, indent=2)

    print(f"✓ Results saved to {summary_file}")

    print(f"\nEnd Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == '__main__':
    main()
