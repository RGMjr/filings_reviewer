#!/usr/bin/env python3
"""
Business Type Classification Script

Classifies companies in the database using the new business type classifiers
from Phase 3 of the extraction optimization project.

Stores results in a new business_classifications table.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
from src.universe.classifiers import (
    classify_saas_software,
    classify_ecommerce_marketplace,
    classify_fintech_crypto,
    classify_healthcare_tech,
    classify_media_subscription,
    classify_telecom,
    classify_platform_network,
)


def create_business_classifications_table(db: DatabaseAdapter) -> None:
    """Create the business_classifications table if it doesn't exist."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS business_classifications (
        company_id BIGINT PRIMARY KEY REFERENCES companies(company_id),
        is_saas_software BOOLEAN DEFAULT FALSE,
        saas_software_method TEXT,
        is_ecommerce_marketplace BOOLEAN DEFAULT FALSE,
        ecommerce_marketplace_method TEXT,
        is_fintech_crypto BOOLEAN DEFAULT FALSE,
        fintech_crypto_method TEXT,
        is_healthcare_tech BOOLEAN DEFAULT FALSE,
        healthcare_tech_method TEXT,
        is_media_subscription BOOLEAN DEFAULT FALSE,
        media_subscription_method TEXT,
        is_telecom BOOLEAN DEFAULT FALSE,
        telecom_method TEXT,
        is_platform_network BOOLEAN DEFAULT FALSE,
        platform_network_method TEXT,
        classified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_business_class_saas ON business_classifications(is_saas_software);
    CREATE INDEX IF NOT EXISTS idx_business_class_ecommerce ON business_classifications(is_ecommerce_marketplace);
    CREATE INDEX IF NOT EXISTS idx_business_class_fintech ON business_classifications(is_fintech_crypto);
    """

    db.execute(create_table_sql)
    print("✓ Created business_classifications table")


def get_companies_to_classify(db: DatabaseAdapter, limit: int = None) -> List[Dict[str, Any]]:
    """
    Get companies that have fetched filings.

    Args:
        db: Database adapter
        limit: Optional limit on number of companies (for testing)

    Returns:
        List of company dictionaries with company_id, cik, company_name, industry_code
    """
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
    SELECT DISTINCT
        c.company_id,
        c.cik,
        c.company_name,
        c.industry_code
    FROM companies c
    JOIN filings f ON c.company_id = f.company_id
    WHERE f.processing_status = 'fetched'
    ORDER BY c.company_id
    {limit_clause}
    """

    results = db.query(query)
    print(f"Found {len(results)} companies to classify")
    return results


def classify_company(
    company_name: str,
    sic_code: str | None,
) -> Dict[str, Any]:
    """
    Run all business type classifiers on a company.

    Args:
        company_name: Company name
        sic_code: SIC code (4-digit string or None)

    Returns:
        Dictionary with classification results
    """
    # Note: We're not using filing_text here to keep it fast
    # Filing text could be added later for enhanced classification

    classifications = {}

    # SaaS & Software
    is_saas, saas_method = classify_saas_software(company_name, sic_code)
    classifications['is_saas_software'] = is_saas
    classifications['saas_software_method'] = saas_method

    # E-commerce & Marketplace
    is_ecommerce, ecommerce_method = classify_ecommerce_marketplace(company_name, sic_code)
    classifications['is_ecommerce_marketplace'] = is_ecommerce
    classifications['ecommerce_marketplace_method'] = ecommerce_method

    # Fintech & Crypto
    is_fintech, fintech_method = classify_fintech_crypto(company_name, sic_code)
    classifications['is_fintech_crypto'] = is_fintech
    classifications['fintech_crypto_method'] = fintech_method

    # Healthcare Tech
    is_healthtech, healthtech_method = classify_healthcare_tech(company_name, sic_code)
    classifications['is_healthcare_tech'] = is_healthtech
    classifications['healthcare_tech_method'] = healthtech_method

    # Media & Subscription
    is_media, media_method = classify_media_subscription(company_name, sic_code)
    classifications['is_media_subscription'] = is_media
    classifications['media_subscription_method'] = media_method

    # Telecom
    is_telecom, telecom_method = classify_telecom(company_name, sic_code)
    classifications['is_telecom'] = is_telecom
    classifications['telecom_method'] = telecom_method

    # Platform & Network
    is_platform, platform_method = classify_platform_network(company_name, sic_code)
    classifications['is_platform_network'] = is_platform
    classifications['platform_network_method'] = platform_method

    return classifications


def save_classification(db: DatabaseAdapter, company_id: int, classifications: Dict[str, Any]) -> None:
    """Save classification results to database."""
    upsert_sql = """
    INSERT INTO business_classifications (
        company_id,
        is_saas_software, saas_software_method,
        is_ecommerce_marketplace, ecommerce_marketplace_method,
        is_fintech_crypto, fintech_crypto_method,
        is_healthcare_tech, healthcare_tech_method,
        is_media_subscription, media_subscription_method,
        is_telecom, telecom_method,
        is_platform_network, platform_network_method
    ) VALUES (
        %(company_id)s,
        %(is_saas_software)s, %(saas_software_method)s,
        %(is_ecommerce_marketplace)s, %(ecommerce_marketplace_method)s,
        %(is_fintech_crypto)s, %(fintech_crypto_method)s,
        %(is_healthcare_tech)s, %(healthcare_tech_method)s,
        %(is_media_subscription)s, %(media_subscription_method)s,
        %(is_telecom)s, %(telecom_method)s,
        %(is_platform_network)s, %(platform_network_method)s
    )
    ON CONFLICT (company_id)
    DO UPDATE SET
        is_saas_software = EXCLUDED.is_saas_software,
        saas_software_method = EXCLUDED.saas_software_method,
        is_ecommerce_marketplace = EXCLUDED.is_ecommerce_marketplace,
        ecommerce_marketplace_method = EXCLUDED.ecommerce_marketplace_method,
        is_fintech_crypto = EXCLUDED.is_fintech_crypto,
        fintech_crypto_method = EXCLUDED.fintech_crypto_method,
        is_healthcare_tech = EXCLUDED.is_healthcare_tech,
        healthcare_tech_method = EXCLUDED.healthcare_tech_method,
        is_media_subscription = EXCLUDED.is_media_subscription,
        media_subscription_method = EXCLUDED.media_subscription_method,
        is_telecom = EXCLUDED.is_telecom,
        telecom_method = EXCLUDED.telecom_method,
        is_platform_network = EXCLUDED.is_platform_network,
        platform_network_method = EXCLUDED.platform_network_method,
        updated_at = NOW()
    """

    params = {'company_id': company_id, **classifications}
    db.execute(upsert_sql, params)


def generate_classification_report(db: DatabaseAdapter) -> None:
    """Generate and print a classification distribution report."""
    report_sql = """
    SELECT
        COUNT(*) as total_companies,
        SUM(CASE WHEN is_saas_software THEN 1 ELSE 0 END) as saas_count,
        SUM(CASE WHEN is_ecommerce_marketplace THEN 1 ELSE 0 END) as ecommerce_count,
        SUM(CASE WHEN is_fintech_crypto THEN 1 ELSE 0 END) as fintech_count,
        SUM(CASE WHEN is_healthcare_tech THEN 1 ELSE 0 END) as healthtech_count,
        SUM(CASE WHEN is_media_subscription THEN 1 ELSE 0 END) as media_count,
        SUM(CASE WHEN is_telecom THEN 1 ELSE 0 END) as telecom_count,
        SUM(CASE WHEN is_platform_network THEN 1 ELSE 0 END) as platform_count,
        SUM(CASE WHEN
            is_saas_software OR is_ecommerce_marketplace OR is_fintech_crypto OR
            is_healthcare_tech OR is_media_subscription OR is_telecom OR is_platform_network
            THEN 1 ELSE 0 END) as classified_count
    FROM business_classifications
    """

    results = db.query(report_sql)
    if results:
        stats = results[0]
        total = stats['total_companies']
        classified = stats['classified_count']

        print("\n" + "="*60)
        print("BUSINESS TYPE CLASSIFICATION REPORT")
        print("="*60)
        print(f"Total Companies Classified: {total}")
        print(f"Companies with Business Type: {classified} ({100*classified/total:.1f}%)")
        print(f"Companies with No Type: {total - classified} ({100*(total-classified)/total:.1f}%)")
        print("\nBusiness Type Distribution:")
        print(f"  SaaS & Software:          {stats['saas_count']:3d} ({100*stats['saas_count']/total:5.1f}%)")
        print(f"  E-commerce & Marketplace: {stats['ecommerce_count']:3d} ({100*stats['ecommerce_count']/total:5.1f}%)")
        print(f"  Fintech & Crypto:         {stats['fintech_count']:3d} ({100*stats['fintech_count']/total:5.1f}%)")
        print(f"  Healthcare Tech:          {stats['healthtech_count']:3d} ({100*stats['healthtech_count']/total:5.1f}%)")
        print(f"  Media & Subscription:     {stats['media_count']:3d} ({100*stats['media_count']/total:5.1f}%)")
        print(f"  Telecom:                  {stats['telecom_count']:3d} ({100*stats['telecom_count']/total:5.1f}%)")
        print(f"  Platform & Network:       {stats['platform_count']:3d} ({100*stats['platform_count']/total:5.1f}%)")
        print("="*60)

    # Get sample companies for each type
    sample_sql = """
    SELECT
        c.company_name,
        c.industry_code,
        bc.is_saas_software,
        bc.is_ecommerce_marketplace,
        bc.is_fintech_crypto,
        bc.is_healthcare_tech,
        bc.is_media_subscription,
        bc.is_telecom,
        bc.is_platform_network
    FROM business_classifications bc
    JOIN companies c ON bc.company_id = c.company_id
    WHERE is_saas_software OR is_ecommerce_marketplace OR is_fintech_crypto OR
          is_healthcare_tech OR is_media_subscription OR is_telecom OR is_platform_network
    ORDER BY c.company_name
    LIMIT 20
    """

    samples = db.query(sample_sql)
    if samples:
        print("\nSample Classified Companies:")
        print("-" * 60)
        for company in samples:
            types = []
            if company['is_saas_software']: types.append('SaaS')
            if company['is_ecommerce_marketplace']: types.append('E-commerce')
            if company['is_fintech_crypto']: types.append('Fintech')
            if company['is_healthcare_tech']: types.append('HealthTech')
            if company['is_media_subscription']: types.append('Media')
            if company['is_telecom']: types.append('Telecom')
            if company['is_platform_network']: types.append('Platform')

            types_str = ', '.join(types)
            sic = company['industry_code'] or 'N/A'
            print(f"{company['company_name'][:40]:40s} | SIC {sic:4s} | {types_str}")


def main():
    """Main classification workflow."""
    import argparse

    parser = argparse.ArgumentParser(description='Classify business types for companies')
    parser.add_argument('--limit', type=int, help='Limit number of companies to classify (for testing)')
    parser.add_argument('--report-only', action='store_true', help='Only generate report, skip classification')
    args = parser.parse_args()

    # Connect to database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    if args.report_only:
        print("Generating classification report...")
        generate_classification_report(db)
        return

    # Create table
    print("Setting up database...")
    create_business_classifications_table(db)

    # Get companies to classify
    companies = get_companies_to_classify(db, limit=args.limit)

    if not companies:
        print("No companies found to classify")
        return

    # Classify each company
    print(f"\nClassifying {len(companies)} companies...")
    classified_count = 0
    high_yield_count = 0

    for i, company in enumerate(companies, 1):
        classifications = classify_company(
            company['company_name'],
            company['industry_code']
        )

        save_classification(db, company['company_id'], classifications)

        # Track high-yield companies (any business type detected)
        if any(classifications[k] for k in classifications if k.startswith('is_')):
            high_yield_count += 1

        classified_count += 1

        # Progress indicator
        if i % 50 == 0 or i == len(companies):
            print(f"  Progress: {i}/{len(companies)} companies classified")

    print(f"\n✓ Classification complete!")
    print(f"  Total classified: {classified_count}")
    print(f"  High-yield companies: {high_yield_count} ({100*high_yield_count/classified_count:.1f}%)")

    # Generate report
    print("\nGenerating classification report...")
    generate_classification_report(db)


if __name__ == '__main__':
    main()
