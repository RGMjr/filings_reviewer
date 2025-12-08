#!/usr/bin/env python3
"""Quick test: Extract from a single company to verify Phase 1 improvements work."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.llm.openai_client import OpenAIClient

def main():
    print("Testing Phase 1 extraction on single company...")

    # Setup
    api_key = os.getenv('OPENAI_API_KEY')
    db_url = os.getenv('DATABASE_URL')

    if not api_key or not db_url:
        print("ERROR: Environment variables not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)
    llm_client = OpenAIClient(api_key=api_key)
    pipeline = ExtractionPipeline(db=db, llm_client=llm_client)

    # Get first company with fetched filing
    companies = db.query("""
        SELECT
            f.filing_id,
            c.company_name,
            c.cik
        FROM companies c
        JOIN filings f ON c.company_id = f.company_id
        LEFT JOIN business_classifications bc ON c.company_id = bc.company_id
        WHERE f.processing_status = 'fetched'
          AND f.html_storage_path IS NOT NULL
          AND bc.is_ecommerce_marketplace = TRUE
        LIMIT 1
    """)

    if not companies:
        print("ERROR: No companies found")
        sys.exit(1)

    company = companies[0]
    filing_id = company['filing_id']

    print(f"\nCompany: {company['company_name']}")
    print(f"CIK: {company['cik']}")
    print(f"Filing ID: {filing_id}")
    print("\nRunning extraction...\n")

    # Run extraction
    result = pipeline.process_filing(filing_id)

    print(f"\n{'='*60}")
    if result.success:
        print(f"✓ SUCCESS")
        print(f"  Segments processed: {result.num_segments}")
        print(f"  Values extracted: {result.num_values}")
        print(f"  Definitions extracted: {result.num_definitions}")
        print(f"  Metric incidences: {result.num_incidences}")
    else:
        print(f"✗ FAILED: {result.error}")
    print(f"{'='*60}")

    # Query extracted metrics
    if result.success and result.num_incidences > 0:
        print("\nChecking for CMASB priority metrics...")

        metrics = db.query("""
            SELECT metric_id, incidence_count
            FROM filing_metric_incidence
            WHERE filing_id = %s
            ORDER BY incidence_count DESC
            LIMIT 20
        """, (filing_id,))

        print(f"\nTop {len(metrics)} metrics found:")
        for m in metrics:
            metric_name = m['metric_id'].replace('cm_', '').replace('_', ' ').title()
            print(f"  {metric_name:40s}: {m['incidence_count']} occurrences")

        # Check for specific CMASB metrics
        cmasb_targets = [
            'cm_new_customers_acquired',
            'cm_net_revenue_retention',
            'cm_gross_margin_by_cohort',
            'cm_expansion_revenue',
            'cm_revenue_concentration',
        ]

        found_cmasb = [m for m in metrics if m['metric_id'] in cmasb_targets]

        if found_cmasb:
            print(f"\n✨ Phase 1 Success! Found {len(found_cmasb)} CMASB priority metrics:")
            for m in found_cmasb:
                metric_name = m['metric_id'].replace('cm_', '').replace('_', ' ').title()
                print(f"  ⭐ {metric_name}")
        else:
            print("\n⚠ No new CMASB priority metrics found in this company")

if __name__ == '__main__':
    main()
