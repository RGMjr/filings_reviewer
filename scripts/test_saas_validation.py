#!/usr/bin/env python3
"""
SaaS-Specific Validation Test

Critical test to validate SaaS-specific prompts work before Phase 5.
SaaS represents 62.8% of high-yield corpus (86 companies).
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from openai import OpenAI
from src.infra.db import DatabaseAdapter


# SaaS-specific metric keywords
SAAS_METRICS = [
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
    'magic number', 'payback period', 'rule of 40'
]

CUSTOMER_SYNONYMS = [
    "customer", "customers", "user", "users", "client", "clients",
    "subscriber", "subscribers", "member", "members", "account", "accounts",
    "organization", "organizations", "tenant", "tenants",
    "enterprise customer", "enterprise customers", "paying subscriber", "paying subscribers",
]


def create_saas_prompt(text: str, company_name: str, filing_id: int) -> str:
    """Create SaaS-specific extraction prompt."""

    prompt = f"""
You are a precise SEC S-1 parser that extracts *SaaS and subscription business metrics* from the text below.

Note: This is a SaaS/software company. Pay special attention to recurring revenue metrics, retention rates, and subscription-based customer metrics.

Your task:
- Extract every relevant **metric value**, **definition**, or **calculation** mentioning customers/users or equivalents.
- Treat these as equivalent terms: {", ".join(CUSTOMER_SYNONYMS)}.
- Focus heavily on these SaaS metrics: {", ".join(SAAS_METRICS[:40])}.
- Look for recurring revenue metrics (ARR, MRR), retention metrics (NRR, churn), and unit economics (LTV, CAC, payback).

For each metric, return a clean JSON object with this exact schema:
{{
  "company": "Company name as written in filing",
  "metric_name": "Name of the metric (e.g. ARR, NRR, DAU, churn rate)",
  "value": "Numeric or textual metric value (keep symbols and ~approximate text as in source)",
  "period": "Time period or date phrase as written",
  "source_type": "text" | "table" | "graph",
  "source_details": "Brief context or section",
  "filing_id": {filing_id},
  "missing_data_note": "" | "not found" | "not reported",
  "extracted_type": "value" | "definition" | "calculation"
}}

Rules:
- Each unique metric = one JSON object.
- Do not invent data. Quote text as-is when uncertain.
- Return only a **JSON array**; no commentary or extra text.
- Pay special attention to:
  * Annual/Monthly Recurring Revenue (ARR, MRR)
  * Net Revenue/Dollar Retention (NRR, NDR)
  * Customer/Logo retention, churn, cancellation rates
  * Expansion revenue, upsells, downgrades
  * Active users, paying users, DAU, MAU
  * ARPU, LTV, CAC, payback period
  * Bookings, ACV, TCV

Text to analyze:
{text}
"""
    return prompt


def extract_metrics_from_filing(
    client: OpenAI,
    filing_path: Path,
    company_name: str,
    filing_id: int,
    max_chars: int = 100000,
    chunk_size: int = 8000
) -> List[Dict[str, Any]]:
    """Extract SaaS metrics from a filing."""

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
            prompt = create_saas_prompt(chunk, company_name, filing_id)

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
            error_msg = str(e)
            if "insufficient_quota" in error_msg or "429" in error_msg:
                print(f"    ⚠ API quota exceeded at chunk {i}")
                break
            print(f"    ⚠ Error processing chunk {i}: {e}")
            continue

    print(f"  ✓ Extracted {len(all_metrics)} metrics")
    return all_metrics


def get_saas_test_sample(db: DatabaseAdapter, limit: int = 10) -> List[Dict[str, Any]]:
    """Get SaaS companies for validation testing."""

    query = f"""
    SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        c.industry_code
    FROM companies c
    JOIN business_classifications bc ON c.company_id = bc.company_id
    JOIN filings f ON c.company_id = f.company_id
    WHERE f.processing_status = 'fetched'
      AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
      AND bc.is_saas_software = TRUE
    ORDER BY c.company_name
    LIMIT {limit}
    """

    return db.query(query)


def main():
    """Main SaaS validation workflow."""
    print("="*60)
    print("SAAS VALIDATION TEST")
    print("Critical test for Phase 4 completion")
    print("="*60)

    # Setup
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    db = DatabaseAdapter(db_url)
    data_dir = Path("data/filings")

    # Get SaaS test sample
    print("\nLoading SaaS companies for testing...")
    saas_filings = get_saas_test_sample(db, limit=10)

    print(f"Found {len(saas_filings)} SaaS filings to test\n")

    if not saas_filings:
        print("ERROR: No SaaS filings found")
        sys.exit(1)

    # Process each filing
    results = []

    for i, filing in enumerate(saas_filings, 1):
        cik = filing['cik']
        accession = filing['accession_number']
        accession_no_dashes = accession.replace('-', '')
        filing_path = data_dir / cik / accession_no_dashes / "primary.htm"

        print(f"\n[{i}/{len(saas_filings)}] {filing['company_name']}")
        print(f"  CIK: {cik} | SIC: {filing['industry_code']} | Accession: {accession}")

        if not filing_path.exists():
            print(f"  ✗ Filing not found: {filing_path}")
            results.append({
                'company_name': filing['company_name'],
                'cik': cik,
                'sic': filing['industry_code'],
                'metrics_found': 0,
                'status': 'file_not_found'
            })
            continue

        # Extract metrics
        metrics = extract_metrics_from_filing(
            client=client,
            filing_path=filing_path,
            company_name=filing['company_name'],
            filing_id=filing['filing_id']
        )

        results.append({
            'company_name': filing['company_name'],
            'cik': cik,
            'sic': filing['industry_code'],
            'metrics_found': len(metrics),
            'status': 'success' if len(metrics) > 0 else 'no_metrics'
        })

    # Generate summary
    print("\n" + "="*60)
    print("SAAS VALIDATION RESULTS")
    print("="*60)

    total_filings = len(results)
    successful = len([r for r in results if r['metrics_found'] > 0])
    total_metrics = sum(r['metrics_found'] for r in results)

    success_rate = (successful / total_filings * 100) if total_filings > 0 else 0
    avg_metrics = (total_metrics / successful) if successful > 0 else 0

    print(f"\nTotal SaaS Filings Tested: {total_filings}")
    print(f"Successful Extractions: {successful}")
    print(f"Success Rate: {success_rate:.1f}%")
    print(f"Total Metrics Extracted: {total_metrics}")
    print(f"Average Metrics per Success: {avg_metrics:.1f}")

    print("\nDetailed Results:")
    print("-" * 60)
    for r in results:
        status_icon = "✓" if r['metrics_found'] > 0 else "✗"
        print(f"{status_icon} {r['company_name']:40s} | {r['metrics_found']:2d} metrics | SIC {r['sic']}")

    # Save results
    output_file = 'saas_validation_results.csv'
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['company_name', 'cik', 'sic', 'metrics_found', 'status'])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✓ Results saved to {output_file}")

    # Decision guidance
    print("\n" + "="*60)
    print("PHASE 5 DECISION GUIDANCE")
    print("="*60)

    if success_rate >= 50:
        print(f"✅ RECOMMENDATION: PROCEED TO PHASE 5")
        print(f"   Success rate {success_rate:.1f}% exceeds 50% target")
        print(f"   SaaS validation successful!")
    elif success_rate >= 40:
        print(f"⚠️  RECOMMENDATION: PROCEED WITH CAUTION")
        print(f"   Success rate {success_rate:.1f}% meets minimum 40% threshold")
        print(f"   Consider refining SaaS prompts for better results")
    else:
        print(f"❌ RECOMMENDATION: DO NOT PROCEED TO PHASE 5")
        print(f"   Success rate {success_rate:.1f}% below 40% minimum")
        print(f"   Focus on non-SaaS categories (E-commerce, Platform, HealthTech)")


if __name__ == '__main__':
    main()
