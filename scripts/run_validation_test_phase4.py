#!/usr/bin/env python3
"""
Phase 4 Validation Testing Script

Tests enhanced extraction prompts with business-type-specific optimizations
on a 30-filing sample across 3 tiers:
- Tier 1: Known-good filings (5 filings)
- Tier 2: High-yield business types (21 filings)
- Tier 3: Control group (10 filings)

Compares results against baseline extraction to measure improvement.
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from openai import OpenAI
from src.infra.db import DatabaseAdapter


# Business-type-specific metric keywords (expanded from Phase 2)
BUSINESS_TYPE_METRICS = {
    'saas': [
        'arr', 'annual recurring revenue', 'mrr', 'monthly recurring revenue',
        'nrr', 'net revenue retention', 'net dollar retention', 'dollar-based net retention',
        'logo retention', 'customer retention rate', 'gross retention',
        'expansion revenue', 'upsell', 'cross-sell', 'seat expansion',
        'contraction', 'downsell', 'churn', 'churn rate', 'cancellation rate',
        'acv', 'average contract value', 'tcv', 'total contract value',
        'booking', 'bookings', 'renewal rate',
        'paying subscribers', 'paid users', 'active users', 'dau', 'mau',
        'arpu', 'average revenue per user', 'arppu',
        'ltv', 'lifetime value', 'cac', 'customer acquisition cost',
        'magic number', 'payback period'
    ],
    'ecommerce': [
        'gmv', 'gross merchandise value', 'gross order value', 'gov',
        'take rate', 'commission rate', 'monetization rate',
        'orders', 'transactions', 'transaction volume',
        'active buyers', 'active customers', 'paying customers',
        'basket size', 'average order value', 'aov',
        'conversion rate', 'checkout rate', 'cart abandonment',
        'reorder rate', 'repeat purchase rate', 'customer frequency',
        'purchase frequency', 'orders per customer',
        'new customers', 'returning customers', 'customer cohorts'
    ],
    'fintech': [
        'transaction volume', 'payment volume', 'tpv', 'total payment volume',
        'transactions', 'payment transactions',
        'active accounts', 'funded accounts', 'verified accounts',
        'wallet users', 'platform users', 'registered users',
        'take rate', 'monetization rate', 'interchange',
        'arpu', 'average revenue per user', 'revenue per account',
        'deposits', 'aum', 'assets under management',
        'loan volume', 'loan originations', 'credit volume'
    ],
    'platform': [
        'gmv', 'gross merchandise value', 'marketplace volume',
        'network effects', 'network density', 'liquidity',
        'supply side', 'demand side', 'marketplace participants',
        'active buyers', 'active sellers', 'active hosts', 'active drivers',
        'two-sided', 'cross-side effects', 'same-side effects',
        'take rate', 'commission', 'monetization rate',
        'utilization rate', 'fill rate', 'matching rate',
        'transactions', 'bookings', 'completed orders'
    ],
    'healthtech': [
        'patients', 'active patients', 'registered patients',
        'providers', 'physicians', 'clinicians',
        'visits', 'consultations', 'appointments', 'sessions',
        'telemedicine', 'telehealth', 'virtual visits',
        'patient engagement', 'patient retention',
        'revenue per patient', 'revenue per visit',
        'claims processed', 'members', 'covered lives'
    ],
    'media': [
        'subscribers', 'paying subscribers', 'premium subscribers',
        'viewers', 'listeners', 'users', 'active users',
        'dau', 'daily active users', 'mau', 'monthly active users',
        'engagement', 'time spent', 'viewing hours', 'listening hours',
        'content hours', 'video views', 'streams',
        'arpu', 'average revenue per user', 'arppu',
        'subscriber retention', 'churn', 'cancellation rate',
        'free users', 'freemium conversion'
    ],
    'telecom': [
        'subscribers', 'postpaid subscribers', 'prepaid subscribers',
        'connections', 'lines', 'wireless lines',
        'arpu', 'average revenue per user', 'arpu', 'revenue per line',
        'churn', 'churn rate', 'subscriber churn',
        'net adds', 'gross adds', 'subscriber additions',
        'market share', 'coverage', 'network quality',
        'data usage', 'voice minutes', 'sms volume'
    ]
}

# Enhanced customer synonyms (68 terms from Phase 2)
CUSTOMER_SYNONYMS = [
    "customer", "customers", "user", "users", "client", "clients",
    "subscriber", "subscribers", "member", "members", "account", "accounts",
    "buyer", "buyers", "consumer", "consumers", "organization", "organizations",
    "merchant", "merchants", "host", "hosts", "driver", "drivers",
    "partner", "partners", "vendor", "vendors", "tenant", "tenants",
    "seller", "sellers", "creator", "creators",
    "rider", "riders", "guest", "guests", "viewer", "viewers",
    "listener", "listeners", "player", "players", "attendee", "attendees",
    "participant", "participants", "enrollee", "enrollees",
    "patient", "patients", "student", "students", "renter", "renters",
    "lessee", "lessees", "licensee", "licensees", "shipper", "shippers",
    "advertiser", "advertisers", "enterprise customer", "enterprise customers",
    "paying subscriber", "paying subscribers",
]

DEFINITION_CUES = [
    "we define", "defined as", "we measure", "we calculate",
    "calculated as", "measured as", "formula", "metric"
]


def get_business_type_prompt_additions(business_type: Optional[str]) -> tuple[List[str], str]:
    """
    Get business-type-specific metric keywords and context.

    Args:
        business_type: One of 'saas', 'ecommerce', 'fintech', 'platform',
                      'healthtech', 'media', 'telecom', or None

    Returns:
        Tuple of (metric_keywords_list, business_context_string)
    """
    if not business_type:
        # Generic metrics for unclassified companies
        return [], ""

    business_type_lower = business_type.lower()

    # Map business types to metric sets
    type_mapping = {
        'saas': ('saas', 'SaaS/subscription software'),
        'software': ('saas', 'SaaS/subscription software'),
        'ecommerce': ('ecommerce', 'e-commerce/marketplace'),
        'e-commerce': ('ecommerce', 'e-commerce/marketplace'),
        'marketplace': ('ecommerce', 'e-commerce/marketplace'),
        'fintech': ('fintech', 'fintech/payments'),
        'crypto': ('fintech', 'fintech/payments'),
        'platform': ('platform', 'platform/network'),
        'network': ('platform', 'platform/network'),
        'healthtech': ('healthtech', 'healthcare technology'),
        'healthcare': ('healthtech', 'healthcare technology'),
        'media': ('media', 'media/subscription'),
        'subscription': ('media', 'media/subscription'),
        'telecom': ('telecom', 'telecommunications'),
    }

    for key, (metric_key, context) in type_mapping.items():
        if key in business_type_lower:
            return BUSINESS_TYPE_METRICS.get(metric_key, []), context

    return [], ""


def create_extraction_prompt(
    text: str,
    company_name: str,
    filing_id: int,
    business_type: Optional[str] = None
) -> str:
    """
    Create business-type-aware extraction prompt.

    Args:
        text: Filing text chunk
        company_name: Company name
        filing_id: Filing ID
        business_type: Business type classification

    Returns:
        Formatted prompt for LLM
    """
    # Get business-type-specific additions
    specific_metrics, business_context = get_business_type_prompt_additions(business_type)

    # Build metric keywords list (core + business-specific)
    core_metrics = [
        "active users", "paying users", "subscribers", "customer count",
        "revenue per user", "churn", "retention", "ltv", "cac",
    ]

    all_metrics = core_metrics + specific_metrics[:40]  # Limit to avoid prompt bloat

    # Add business context if available
    business_note = ""
    if business_context:
        business_note = f"\nNote: This is a {business_context} company. Pay special attention to industry-specific metrics."

    prompt = f"""
You are a precise SEC S-1 parser that extracts *customer-related metrics* from the text below.
{business_note}

Your task:
- Extract every relevant **metric value**, **definition**, or **calculation** mentioning customers/users or equivalents.
- Treat these as equivalent terms: {", ".join(CUSTOMER_SYNONYMS[:40])}, and similar terms.
- Focus on any metric using these words: {", ".join(all_metrics)}, and similar metrics.
- Also extract any definition or formula phrase using these: {", ".join(DEFINITION_CUES)}.

For each metric, return a clean JSON object with this exact schema:
{{
  "company": "Company name as written in filing",
  "metric_name": "Name of the customer metric (e.g. ARR, GMV, DAU, take rate)",
  "value": "Numeric or textual metric value (keep symbols and ~approximate text as in source)",
  "period": "Time period or date phrase as written (e.g. 'as of January 31, 2019', 'FY 2024')",
  "source_type": "text" | "table" | "graph",
  "source_details": "Brief context or section (e.g. 'Prospectus Summary', 'Key Metrics Table')",
  "filing_id": {filing_id},
  "missing_data_note": "" | "not found" | "not reported",
  "extracted_type": "value" | "definition" | "calculation"
}}

Rules:
- Each unique metric, definition, or calculation = one JSON object.
- Do not invent data. Quote text as-is when uncertain.
- Return only a **JSON array**; no commentary or extra text.
- Pay special attention to recurring revenue metrics (ARR, MRR).
- Look for engagement metrics (DAU, MAU, session duration).
- Capture transaction/volume metrics (GMV, TPV, orders).
- Extract retention and churn metrics carefully.

Text to analyze:
{text}
"""

    return prompt


def extract_metrics_from_filing(
    client: OpenAI,
    filing_path: Path,
    company_name: str,
    filing_id: int,
    business_type: Optional[str] = None,
    max_chars: int = 100000,
    chunk_size: int = 8000
) -> List[Dict[str, Any]]:
    """
    Extract metrics from a filing using business-type-aware prompts.

    Args:
        client: OpenAI client
        filing_path: Path to filing HTML file
        company_name: Company name
        filing_id: Filing ID
        business_type: Business type classification
        max_chars: Maximum characters to process
        chunk_size: Characters per chunk

    Returns:
        List of extracted metrics
    """
    # Read filing
    try:
        with open(filing_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()[:max_chars]
    except Exception as e:
        print(f"  ✗ Error reading {filing_path}: {e}")
        return []

    # Split into chunks
    chunks = []
    for i in range(0, len(content), chunk_size):
        chunks.append(content[i:i + chunk_size])

    print(f"  Processing {len(chunks)} chunks...")

    all_metrics = []
    for i, chunk in enumerate(chunks, 1):
        try:
            prompt = create_extraction_prompt(chunk, company_name, filing_id, business_type)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                timeout=90.0
            )

            result_text = response.choices[0].message.content.strip()

            # Parse JSON
            if result_text.startswith("```json"):
                result_text = result_text[7:]
            if result_text.startswith("```"):
                result_text = result_text[3:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()

            metrics = json.loads(result_text)
            if isinstance(metrics, list):
                all_metrics.extend(metrics)

            # Rate limiting
            time.sleep(0.6)

        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON parse error in chunk {i}: {e}")
            continue
        except Exception as e:
            print(f"    ⚠ Error processing chunk {i}: {e}")
            continue

    print(f"  ✓ Extracted {len(all_metrics)} metrics")
    return all_metrics


def get_test_sample() -> Dict[str, List[Dict[str, Any]]]:
    """
    Get the 3-tier test sample from database.

    Returns:
        Dictionary with 'tier1', 'tier2', 'tier3' keys containing filing info
    """
    db_url = os.getenv('DATABASE_URL')
    db = DatabaseAdapter(db_url)

    # Tier 1: Known-good filings (from Phase 2 test)
    tier1_ciks = ['0001754820', '0001831907', '0001819395', '0001820465', '0001781162']

    tier1_query = f"""
    SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        c.industry_code,
        NULL as business_type
    FROM filings f
    JOIN companies c ON f.company_id = c.company_id
    WHERE c.cik IN ({','.join(f"'{cik}'" for cik in tier1_ciks)})
        AND f.processing_status = 'fetched'
        AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
    LIMIT 5
    """

    # Tier 2: High-yield companies by business type
    tier2_query = """
    WITH ranked_companies AS (
      SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        c.industry_code,
        CASE
          WHEN bc.is_saas_software THEN 'SaaS'
          WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
          WHEN bc.is_fintech_crypto THEN 'Fintech'
          WHEN bc.is_healthcare_tech THEN 'HealthTech'
          WHEN bc.is_media_subscription THEN 'Media'
          WHEN bc.is_telecom THEN 'Telecom'
          WHEN bc.is_platform_network THEN 'Platform'
        END as business_type,
        ROW_NUMBER() OVER (
          PARTITION BY
            CASE
              WHEN bc.is_saas_software THEN 'SaaS'
              WHEN bc.is_ecommerce_marketplace THEN 'Ecommerce'
              WHEN bc.is_fintech_crypto THEN 'Fintech'
              WHEN bc.is_healthcare_tech THEN 'HealthTech'
              WHEN bc.is_media_subscription THEN 'Media'
              WHEN bc.is_telecom THEN 'Telecom'
              WHEN bc.is_platform_network THEN 'Platform'
            END
          ORDER BY c.company_name
        ) as rank_in_type
      FROM companies c
      JOIN business_classifications bc ON c.company_id = bc.company_id
      JOIN filings f ON c.company_id = f.company_id
      WHERE f.processing_status = 'fetched'
        AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
        AND (bc.is_saas_software OR bc.is_ecommerce_marketplace OR bc.is_fintech_crypto OR
             bc.is_healthcare_tech OR bc.is_media_subscription OR bc.is_telecom OR bc.is_platform_network)
    )
    SELECT filing_id, accession_number, company_name, cik, industry_code, business_type
    FROM ranked_companies
    WHERE rank_in_type <= 3
    ORDER BY business_type, company_name
    """

    # Tier 3: Control group (unclassified)
    tier3_query = """
    SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        c.industry_code,
        'Unclassified' as business_type
    FROM companies c
    JOIN business_classifications bc ON c.company_id = bc.company_id
    JOIN filings f ON c.company_id = f.company_id
    WHERE f.processing_status = 'fetched'
      AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
      AND NOT bc.is_saas_software
      AND NOT bc.is_ecommerce_marketplace
      AND NOT bc.is_fintech_crypto
      AND NOT bc.is_healthcare_tech
      AND NOT bc.is_media_subscription
      AND NOT bc.is_telecom
      AND NOT bc.is_platform_network
      AND c.industry_code NOT IN ('6770', '6722', '6726')
    ORDER BY RANDOM()
    LIMIT 10
    """

    return {
        'tier1': db.query(tier1_query),
        'tier2': db.query(tier2_query),
        'tier3': db.query(tier3_query)
    }


def main():
    """Main validation testing workflow."""
    print("="*60)
    print("PHASE 4 VALIDATION TEST")
    print("Business-Type-Specific Extraction")
    print("="*60)

    # Setup
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    data_dir = Path("data/filings")

    # Get test sample
    print("\nLoading test sample...")
    sample = get_test_sample()

    tier1_count = len(sample['tier1'])
    tier2_count = len(sample['tier2'])
    tier3_count = len(sample['tier3'])
    total_count = tier1_count + tier2_count + tier3_count

    print(f"  Tier 1 (Known-Good): {tier1_count} filings")
    print(f"  Tier 2 (High-Yield): {tier2_count} filings")
    print(f"  Tier 3 (Control):    {tier3_count} filings")
    print(f"  Total:               {total_count} filings")

    # Process all filings
    results = []

    for tier_name, filings in [('Tier 1', sample['tier1']),
                                ('Tier 2', sample['tier2']),
                                ('Tier 3', sample['tier3'])]:
        print(f"\n{tier_name}:")
        print("-" * 60)

        for filing in filings:
            cik = filing['cik']
            accession = filing['accession_number']
            # Remove dashes from accession number for file path
            accession_no_dashes = accession.replace('-', '')
            filing_path = data_dir / cik / accession_no_dashes / "primary.htm"

            business_type = filing.get('business_type')
            business_label = f" [{business_type}]" if business_type and business_type != 'Unclassified' else ""

            print(f"\n{filing['company_name']}{business_label}")
            print(f"  CIK: {cik} | Accession: {accession}")

            if not filing_path.exists():
                print(f"  ✗ Filing not found: {filing_path}")
                results.append({
                    'tier': tier_name,
                    'filing_id': filing['filing_id'],
                    'company_name': filing['company_name'],
                    'cik': cik,
                    'sic': filing['industry_code'],
                    'business_type': business_type,
                    'metrics_found': 0,
                    'status': 'file_not_found'
                })
                continue

            # Extract metrics
            metrics = extract_metrics_from_filing(
                client=client,
                filing_path=filing_path,
                company_name=filing['company_name'],
                filing_id=filing['filing_id'],
                business_type=business_type
            )

            results.append({
                'tier': tier_name,
                'filing_id': filing['filing_id'],
                'company_name': filing['company_name'],
                'cik': cik,
                'sic': filing['industry_code'],
                'business_type': business_type or 'Unclassified',
                'metrics_found': len(metrics),
                'status': 'success' if len(metrics) > 0 else 'no_metrics'
            })

    # Generate summary report
    print("\n" + "="*60)
    print("VALIDATION TEST RESULTS")
    print("="*60)

    tier1_results = [r for r in results if r['tier'] == 'Tier 1']
    tier2_results = [r for r in results if r['tier'] == 'Tier 2']
    tier3_results = [r for r in results if r['tier'] == 'Tier 3']

    def calc_success_rate(tier_results):
        total = len(tier_results)
        success = len([r for r in tier_results if r['metrics_found'] > 0])
        return (success / total * 100) if total > 0 else 0

    tier1_success = calc_success_rate(tier1_results)
    tier2_success = calc_success_rate(tier2_results)
    tier3_success = calc_success_rate(tier3_results)
    overall_success = calc_success_rate(results)

    print(f"\nTier 1 (Known-Good):  {tier1_success:.1f}% success ({len([r for r in tier1_results if r['metrics_found'] > 0])}/{len(tier1_results)})")
    print(f"Tier 2 (High-Yield):  {tier2_success:.1f}% success ({len([r for r in tier2_results if r['metrics_found'] > 0])}/{len(tier2_results)})")
    print(f"Tier 3 (Control):     {tier3_success:.1f}% success ({len([r for r in tier3_results if r['metrics_found'] > 0])}/{len(tier3_results)})")
    print(f"Overall:              {overall_success:.1f}% success ({len([r for r in results if r['metrics_found'] > 0])}/{len(results)})")

    # Save results
    output_file = 'phase4_validation_results.csv'
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'tier', 'filing_id', 'company_name', 'cik', 'sic',
            'business_type', 'metrics_found', 'status'
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✓ Results saved to {output_file}")

    # Business type breakdown for Tier 2
    print("\nTier 2 Breakdown by Business Type:")
    tier2_by_type = {}
    for r in tier2_results:
        btype = r['business_type']
        if btype not in tier2_by_type:
            tier2_by_type[btype] = {'total': 0, 'success': 0, 'metrics': 0}
        tier2_by_type[btype]['total'] += 1
        if r['metrics_found'] > 0:
            tier2_by_type[btype]['success'] += 1
            tier2_by_type[btype]['metrics'] += r['metrics_found']

    for btype, stats in sorted(tier2_by_type.items()):
        success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
        avg_metrics = (stats['metrics'] / stats['success']) if stats['success'] > 0 else 0
        print(f"  {btype:15s}: {success_rate:5.1f}% success ({stats['success']}/{stats['total']}), avg {avg_metrics:.1f} metrics/filing")


if __name__ == '__main__':
    main()
