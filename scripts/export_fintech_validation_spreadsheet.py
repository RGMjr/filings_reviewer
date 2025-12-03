#!/usr/bin/env python3
"""
Export fintech companies to CSV for manual validation review.

Creates a spreadsheet with all fintech companies for manual categorization:
- True fintech platform
- Traditional finance company
- Investment vehicle
- Crypto-related but not platform
- Other

This allows manual quality review of the 163 fintech companies identified.
"""
import sys
import csv
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
import os


def export_fintech_companies(output_file: str):
    """Export all fintech companies to CSV for manual review."""

    # Setup database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    # Query all fintech companies
    query = """
    SELECT
        c.company_id,
        c.company_name,
        c.cik,
        c.ticker,
        c.industry_code as sic_code,
        bc.fintech_crypto_method as classification_method,
        CASE
            WHEN EXISTS (
                SELECT 1 FROM filings f
                WHERE f.company_id = c.company_id
                AND f.form_type IN ('S-1', 'S-1/A')
            ) THEN 'Yes'
            ELSE 'No'
        END as has_filing
    FROM companies c
    JOIN business_classifications bc ON c.company_id = bc.company_id
    WHERE bc.is_fintech_crypto = TRUE
    ORDER BY c.company_name
    """

    print("Querying database for fintech companies...")
    companies = db.query(query)
    print(f"Found {len(companies)} fintech companies")

    # Export to CSV
    print(f"\nExporting to: {output_file}")

    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'company_name',
            'ticker',
            'cik',
            'sic_code',
            'classification_method',
            'has_filing',
            'manual_category',
            'notes',
            'confidence'
        ]

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for company in companies:
            writer.writerow({
                'company_name': company['company_name'],
                'ticker': company['ticker'] or '',
                'cik': company['cik'],
                'sic_code': company['sic_code'] or '',
                'classification_method': company['classification_method'] or '',
                'has_filing': company['has_filing'],
                'manual_category': '',  # To be filled in manually
                'notes': '',  # To be filled in manually
                'confidence': ''  # To be filled in manually
            })

    print(f"✅ Exported {len(companies)} companies to {output_file}")
    print()
    print("Manual Review Instructions:")
    print("=" * 70)
    print()
    print("For each company, fill in the following columns:")
    print()
    print("1. manual_category - Choose one of:")
    print("   - 'True Fintech Platform' - Digital payment, crypto exchange, robo-advisor")
    print("   - 'Crypto Mining' - Mining operations (not hardware)")
    print("   - 'Traditional Finance' - Regular finance company with SIC 6199")
    print("   - 'Investment Vehicle' - SPAC, fund, trust, holding company")
    print("   - 'Unclear' - Need more research")
    print("   - 'Other' - Doesn't fit categories")
    print()
    print("2. notes - Brief description of what the company does")
    print()
    print("3. confidence - Your confidence level (High / Medium / Low)")
    print()
    print("Prioritize companies with 'has_filing' = 'Yes' for potential extraction.")
    print()
    print("=" * 70)

    # Print summary statistics
    print()
    print("Summary Statistics:")
    print("-" * 70)

    with_filing = sum(1 for c in companies if c['has_filing'] == 'Yes')
    without_filing = len(companies) - with_filing

    print(f"Total fintech companies:          {len(companies)}")
    print(f"With S-1 filings:                 {with_filing}")
    print(f"Without S-1 filings:              {without_filing}")
    print()

    # Breakdown by classification method
    method_counts = {}
    for company in companies:
        method = company['classification_method'] or 'unknown'
        method_counts[method] = method_counts.get(method, 0) + 1

    print("Classification Method Breakdown:")
    for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"  {method:30s}: {count:3d} ({count/len(companies)*100:.1f}%)")

    print()
    print("=" * 70)

    return len(companies)


if __name__ == '__main__':
    # Output file path
    output_file = project_root / "fintech_validation_review.csv"

    count = export_fintech_companies(str(output_file))

    print()
    print(f"✅ Spreadsheet created: {output_file}")
    print()
    print("Open this file in Excel, Google Sheets, or your preferred spreadsheet app")
    print("to perform manual validation review.")
