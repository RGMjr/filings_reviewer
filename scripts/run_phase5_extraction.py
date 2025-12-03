#!/usr/bin/env python3
"""
Phase 5: Full Extraction on Validated Categories

Extracts customer metrics from 43 companies across 4 validated business types:
- E-commerce & Marketplace (7 companies) - 100% validated success
- Platform & Network (14 companies) - 66.7% validated success
- HealthTech (10 companies) - 66.7% validated success
- Media & Subscription (12 companies) - 66.7% validated success

Expected: ~30 successful extractions, ~550 total metrics
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from openai import OpenAI
from src.infra.db import DatabaseAdapter

# Import business-type-specific prompt creation from Phase 4 script
sys.path.insert(0, str(Path(__file__).parent))
from run_validation_test_phase4 import (
    get_business_type_prompt_additions,
    CUSTOMER_SYNONYMS,
    DEFINITION_CUES
)


def create_extraction_prompt(
    text: str,
    company_name: str,
    filing_id: int,
    business_type: str
) -> str:
    """Create business-type-aware extraction prompt."""

    specific_metrics, business_context = get_business_type_prompt_additions(business_type)

    core_metrics = [
        "active users", "paying users", "subscribers", "customer count",
        "revenue per user", "churn", "retention", "ltv", "cac",
    ]

    all_metrics = core_metrics + specific_metrics[:40]

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
  "metric_name": "Name of the customer metric",
  "value": "Numeric or textual metric value (keep symbols and ~approximate text as in source)",
  "period": "Time period or date phrase as written",
  "source_type": "text" | "table" | "graph",
  "source_details": "Brief context or section",
  "filing_id": {filing_id},
  "missing_data_note": "" | "not found" | "not reported",
  "extracted_type": "value" | "definition" | "calculation"
}}

Rules:
- Each unique metric, definition, or calculation = one JSON object.
- Do not invent data. Quote text as-is when uncertain.
- Return only a **JSON array**; no commentary or extra text.

Text to analyze:
{text}
"""

    return prompt


def extract_metrics_from_filing(
    client: OpenAI,
    filing_path: Path,
    company_name: str,
    filing_id: int,
    business_type: str,
    max_chars: int = 100000,
    chunk_size: int = 8000
) -> List[Dict[str, Any]]:
    """Extract metrics from a filing using business-type-aware prompts."""

    try:
        with open(filing_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()[:max_chars]
    except Exception as e:
        print(f"  ✗ Error reading {filing_path}: {e}")
        return []

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

            time.sleep(0.6)

        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON parse error in chunk {i}")
            continue
        except Exception as e:
            error_msg = str(e)
            if "insufficient_quota" in error_msg or "429" in error_msg:
                print(f"    ⚠ API quota exceeded at chunk {i}")
                break
            print(f"    ⚠ Error in chunk {i}: {str(e)[:100]}")
            continue

    print(f"  ✓ Extracted {len(all_metrics)} metrics")
    return all_metrics


def get_validated_companies(db: DatabaseAdapter) -> List[Dict[str, Any]]:
    """Get companies from validated high-performing categories."""

    query = """
    SELECT
        f.filing_id,
        f.accession_number,
        c.company_name,
        c.cik,
        c.industry_code,
        CASE
            WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
            WHEN bc.is_platform_network THEN 'Platform'
            WHEN bc.is_healthcare_tech THEN 'HealthTech'
            WHEN bc.is_media_subscription THEN 'Media'
        END as business_type
    FROM companies c
    JOIN business_classifications bc ON c.company_id = bc.company_id
    JOIN filings f ON c.company_id = f.company_id
    WHERE f.processing_status = 'fetched'
      AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
      AND (bc.is_ecommerce_marketplace OR bc.is_platform_network OR
           bc.is_healthcare_tech OR bc.is_media_subscription)
    ORDER BY business_type, c.company_name
    """

    return db.query(query)


def main():
    """Main Phase 5 extraction workflow."""
    print("="*70)
    print("PHASE 5: FULL EXTRACTION ON VALIDATED CATEGORIES")
    print("="*70)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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

    # Get validated companies
    print("\nLoading validated companies...")
    companies = get_validated_companies(db)

    by_type = {}
    for c in companies:
        btype = c['business_type']
        if btype not in by_type:
            by_type[btype] = 0
        by_type[btype] += 1

    print(f"\nTotal Companies: {len(companies)}")
    for btype, count in sorted(by_type.items()):
        print(f"  {btype}: {count}")

    if not companies:
        print("ERROR: No companies found")
        sys.exit(1)

    # Process each company
    results = []
    all_extracted_metrics = []

    for i, company in enumerate(companies, 1):
        cik = company['cik']
        accession = company['accession_number']
        accession_no_dashes = accession.replace('-', '')
        filing_path = data_dir / cik / accession_no_dashes / "primary.htm"
        business_type = company['business_type']

        print(f"\n[{i}/{len(companies)}] {company['company_name']} [{business_type}]")
        print(f"  CIK: {cik} | SIC: {company['industry_code']}")

        if not filing_path.exists():
            print(f"  ✗ Filing not found")
            results.append({
                'company_name': company['company_name'],
                'cik': cik,
                'sic': company['industry_code'],
                'business_type': business_type,
                'metrics_found': 0,
                'status': 'file_not_found'
            })
            continue

        # Extract metrics
        metrics = extract_metrics_from_filing(
            client=client,
            filing_path=filing_path,
            company_name=company['company_name'],
            filing_id=company['filing_id'],
            business_type=business_type
        )

        results.append({
            'company_name': company['company_name'],
            'cik': cik,
            'sic': company['industry_code'],
            'business_type': business_type,
            'metrics_found': len(metrics),
            'status': 'success' if len(metrics) > 0 else 'no_metrics'
        })

        all_extracted_metrics.extend(metrics)

    # Generate summary
    print("\n" + "="*70)
    print("PHASE 5 EXTRACTION RESULTS")
    print("="*70)

    total = len(results)
    successful = len([r for r in results if r['metrics_found'] > 0])
    total_metrics = sum(r['metrics_found'] for r in results)

    success_rate = (successful / total * 100) if total > 0 else 0
    avg_metrics = (total_metrics / successful) if successful > 0 else 0

    print(f"\nTotal Companies Processed: {total}")
    print(f"Successful Extractions: {successful} ({success_rate:.1f}%)")
    print(f"Total Metrics Extracted: {total_metrics}")
    print(f"Average Metrics per Success: {avg_metrics:.1f}")

    # By business type
    print("\nResults by Business Type:")
    print("-" * 70)

    type_stats = {}
    for r in results:
        btype = r['business_type']
        if btype not in type_stats:
            type_stats[btype] = {'total': 0, 'success': 0, 'metrics': 0}
        type_stats[btype]['total'] += 1
        if r['metrics_found'] > 0:
            type_stats[btype]['success'] += 1
            type_stats[btype]['metrics'] += r['metrics_found']

    for btype, stats in sorted(type_stats.items()):
        success_pct = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
        avg_m = (stats['metrics'] / stats['success']) if stats['success'] > 0 else 0
        print(f"{btype:15s}: {success_pct:5.1f}% ({stats['success']:2d}/{stats['total']:2d}) | "
              f"{stats['metrics']:3d} metrics | {avg_m:5.1f} avg")

    # Save summary results
    summary_file = 'phase5_extraction_summary.csv'
    with open(summary_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'company_name', 'cik', 'sic', 'business_type', 'metrics_found', 'status'
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✓ Summary saved to {summary_file}")

    # Save detailed metrics
    if all_extracted_metrics:
        metrics_file = 'phase5_extracted_metrics.json'
        with open(metrics_file, 'w') as f:
            json.dump(all_extracted_metrics, f, indent=2)
        print(f"✓ Detailed metrics saved to {metrics_file}")

    # Top performers
    print("\nTop 10 Companies by Metrics Extracted:")
    print("-" * 70)
    top_companies = sorted(results, key=lambda x: x['metrics_found'], reverse=True)[:10]
    for idx, company in enumerate(top_companies, 1):
        if company['metrics_found'] > 0:
            print(f"{idx:2d}. {company['company_name']:40s} | {company['metrics_found']:3d} metrics | "
                  f"{company['business_type']}")

    print(f"\nEnd Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)


if __name__ == '__main__':
    main()
