#!/usr/bin/env python3
"""
Re-run extraction on Phase 1B timed-out companies with longer timeout.

The 13 companies that timed out likely have larger, more complex filings
with potentially rich metric disclosures. This script retries them with
a 10-minute timeout (vs 5 minutes in Phase 1B).
"""

import json
import os
import sys
import signal
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

# Extended timeout: 10 minutes per filing
FILING_TIMEOUT_SECONDS = 600

# The 13 filing IDs that timed out in Phase 1B
TIMEOUT_FILING_IDS = [
    7607,   # Netshoes (E-commerce)
    26938,  # SIGNA Sports United (E-commerce)
    38058,  # GLAMOORE Capital (Fintech)
    20923,  # agilon health (HealthTech)
    36870,  # VSEE Health (HealthTech)
    25861,  # Mynaric AG (Media)
    24790,  # Alight, Inc. (Platform)
    17472,  # American Well (Platform)
    17488,  # Executive Network Partnering (Platform)
    12087,  # Farfetch (Platform)
    5443,   # FOTV Media Networks (Platform)
    27011,  # Grab Holdings (Platform)
    9262,   # Sea Ltd (Platform)
]


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


def get_timeout_companies(db: DatabaseAdapter) -> List[Dict[str, Any]]:
    """Get the 13 companies that timed out in Phase 1B."""

    placeholders = ','.join(['%s'] * len(TIMEOUT_FILING_IDS))

    query = f"""
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
    WHERE f.filing_id IN ({placeholders})
    ORDER BY c.company_name
    """

    return db.query(query, tuple(TIMEOUT_FILING_IDS))


def main():
    """Re-run extraction on timed-out companies."""
    print("=" * 80)
    print("RE-RUNNING EXTRACTION ON TIMED-OUT COMPANIES")
    print("=" * 80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Timeout: {FILING_TIMEOUT_SECONDS} seconds ({FILING_TIMEOUT_SECONDS // 60} minutes)")
    print(f"Target: {len(TIMEOUT_FILING_IDS)} companies that timed out in Phase 1B")
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

    # Get timed-out companies
    print("Loading timed-out companies...")
    companies = get_timeout_companies(db)

    if not companies:
        print("ERROR: No companies found")
        sys.exit(1)

    print(f"\nTarget Companies ({len(companies)}):")
    print("-" * 80)

    for company in companies:
        print(f"  • {company['company_name']:50s} [{company['business_type']}]")

    print("\n" + "=" * 80)
    print("Starting extraction with extended timeout...")
    print()

    # Process each company
    results = []
    successful = 0
    failed = 0
    total_values = 0
    total_definitions = 0
    total_incidences = 0

    for i, company in enumerate(companies, 1):
        filing_id = company['filing_id']

        print(f"\n[{i}/{len(companies)}] {company['company_name']}")
        print(f"  CIK: {company['cik']} | Business: {company['business_type']}")
        print(f"  Filing ID: {filing_id}")

        # Run extraction pipeline with extended timeout
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(FILING_TIMEOUT_SECONDS)

            result = pipeline.process_filing(filing_id)

            signal.alarm(0)

            if result.success:
                successful += 1
                total_values += result.num_values
                total_definitions += result.num_definitions
                total_incidences += result.num_incidences
                print(f"  ✓ Success: {result.num_values} values, {result.num_definitions} definitions, "
                      f"{result.num_incidences} incidences")
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
            signal.alarm(0)
            failed += 1
            print(f"  ✗ TIMEOUT (still): Filing took longer than {FILING_TIMEOUT_SECONDS}s")
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
            signal.alarm(0)
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

    # Summary
    print("\n" + "=" * 80)
    print("EXTRACTION SUMMARY")
    print("=" * 80 + "\n")

    print(f"Results:")
    print(f"  Companies processed: {len(companies)}")
    print(f"  Successful:          {successful}")
    print(f"  Still failed:        {failed}")
    print(f"  Success rate:        {successful/len(companies)*100:.1f}%")

    print(f"\nMetrics extracted:")
    print(f"  Total values:        {total_values}")
    print(f"  Total definitions:   {total_definitions}")
    print(f"  Total incidences:    {total_incidences}")

    # Save results
    summary_file = 'timeout_rerun_results.json'
    with open(summary_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'timeout_seconds': FILING_TIMEOUT_SECONDS,
            'results': results,
            'statistics': {
                'total': len(companies),
                'successful': successful,
                'failed': failed,
                'success_rate': successful/len(companies)*100,
                'total_values': total_values,
                'total_definitions': total_definitions,
                'total_incidences': total_incidences,
            },
        }, f, indent=2)

    print(f"\n✓ Results saved to {summary_file}")
    print(f"\nEnd Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == '__main__':
    main()
