#!/usr/bin/env python3
"""
Analyze potential exclusion candidates based on SIC codes and name patterns.

This script generates a sample of companies that would be excluded under
various criteria, allowing for manual review before implementing exclusions.

Usage:
    python scripts/analyze_exclusion_candidates.py
    python scripts/analyze_exclusion_candidates.py --sample-size 50
    python scripts/analyze_exclusion_candidates.py --output candidates.csv
"""

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


# SIC Code ranges for exclusion
INVESTMENT_VEHICLE_SIC_CODES = [
    '6722',  # Management investment offices, open-end (mutual funds, ETFs)
    '6726',  # Unit investment trusts, closed-end funds
    '6798',  # Real Estate Investment Trusts (REITs)
]

RESOURCE_EXTRACTION_SIC_PREFIXES = [
    '10',    # Metal mining (1000-1099)
    '12',    # Coal mining (1200-1299)
    '13',    # Oil and gas extraction (1300-1399)
]


def get_exclusion_candidates(db: DatabaseAdapter) -> dict:
    """
    Get all potential exclusion candidates categorized by reason.

    Returns:
        Dictionary with categories as keys and lists of companies as values
    """
    candidates = {
        'investment_vehicles_sic': [],
        'investment_vehicles_name': [],
        'resource_extraction_sic': [],
        'resource_extraction_name': [],
    }

    # 1. Investment vehicles by SIC code
    sic_codes_list = "','".join(INVESTMENT_VEHICLE_SIC_CODES)
    query = f"""
        SELECT DISTINCT
            c.company_id,
            c.cik,
            c.company_name,
            c.industry_code as sic_code,
            COUNT(f.filing_id) as filing_count,
            SUM(CASE WHEN f.is_in_scope_phase1 THEN 1 ELSE 0 END) as in_scope_count
        FROM companies c
        LEFT JOIN filings f ON c.company_id = f.company_id
        WHERE c.industry_code IN ('{sic_codes_list}')
        GROUP BY c.company_id, c.cik, c.company_name, c.industry_code
        ORDER BY in_scope_count DESC, filing_count DESC
    """
    candidates['investment_vehicles_sic'] = db.query(query)

    # 2. Investment vehicles by name pattern
    query = """
        SELECT DISTINCT
            c.company_id,
            c.cik,
            c.company_name,
            c.industry_code as sic_code,
            COUNT(f.filing_id) as filing_count,
            SUM(CASE WHEN f.is_in_scope_phase1 THEN 1 ELSE 0 END) as in_scope_count
        FROM companies c
        LEFT JOIN filings f ON c.company_id = f.company_id
        WHERE (
            c.company_name ILIKE '%%ETF%%'
            OR c.company_name ILIKE '%%Trust%%'
            OR c.company_name ~* '\y(Fund|Funds)\y'
            OR c.company_name ILIKE '%%REIT%%'
        )
        AND (c.industry_code IS NULL OR c.industry_code NOT IN ('6722', '6726', '6798'))
        GROUP BY c.company_id, c.cik, c.company_name, c.industry_code
        ORDER BY in_scope_count DESC, filing_count DESC
    """
    candidates['investment_vehicles_name'] = db.query(query)

    # 3. Resource extraction by SIC code
    query = """
        SELECT DISTINCT
            c.company_id,
            c.cik,
            c.company_name,
            c.industry_code as sic_code,
            COUNT(f.filing_id) as filing_count,
            SUM(CASE WHEN f.is_in_scope_phase1 THEN 1 ELSE 0 END) as in_scope_count
        FROM companies c
        LEFT JOIN filings f ON c.company_id = f.company_id
        WHERE (
            c.industry_code LIKE '10%%'
            OR c.industry_code LIKE '12%%'
            OR c.industry_code LIKE '13%%'
        )
        GROUP BY c.company_id, c.cik, c.company_name, c.industry_code
        ORDER BY in_scope_count DESC, filing_count DESC
    """
    candidates['resource_extraction_sic'] = db.query(query)

    # 4. Resource extraction by name pattern
    query = """
        SELECT DISTINCT
            c.company_id,
            c.cik,
            c.company_name,
            c.industry_code as sic_code,
            COUNT(f.filing_id) as filing_count,
            SUM(CASE WHEN f.is_in_scope_phase1 THEN 1 ELSE 0 END) as in_scope_count
        FROM companies c
        LEFT JOIN filings f ON c.company_id = f.company_id
        WHERE (
            c.company_name ILIKE '%%Oil%%'
            OR c.company_name ILIKE '%%Gas%%'
            OR c.company_name ILIKE '%%Petroleum%%'
            OR c.company_name ILIKE '%%Mining%%'
            OR c.company_name ILIKE '%%Gold%%'
            OR c.company_name ILIKE '%%Silver%%'
            OR c.company_name ILIKE '%%Copper%%'
            OR c.company_name ILIKE '%%Coal%%'
            OR c.company_name ILIKE '%%Mineral%%'
            OR c.company_name ILIKE '%%Drilling%%'
            OR c.company_name ILIKE '%%Rare Earth%%'
        )
        AND (c.industry_code IS NULL OR NOT (c.industry_code LIKE '10%%' OR c.industry_code LIKE '12%%' OR c.industry_code LIKE '13%%'))
        GROUP BY c.company_id, c.cik, c.company_name, c.industry_code
        ORDER BY in_scope_count DESC, filing_count DESC
    """
    candidates['resource_extraction_name'] = db.query(query)

    return candidates


def generate_sample(candidates: dict, sample_size: int = 50) -> list:
    """
    Generate a representative sample across all categories.

    Args:
        candidates: Dictionary of candidate lists by category
        sample_size: Number of samples to generate per category

    Returns:
        List of sampled companies with metadata
    """
    samples = []

    for category, company_list in candidates.items():
        # Take stratified sample: high in-scope count, medium, and random
        if len(company_list) == 0:
            continue

        # Sort by in_scope_count
        sorted_list = sorted(company_list, key=lambda x: x['in_scope_count'], reverse=True)

        # Take samples from different segments
        high_impact = sorted_list[:min(sample_size // 3, len(sorted_list))]
        mid_impact = sorted_list[len(sorted_list) // 3 : len(sorted_list) // 3 + sample_size // 3]
        low_impact = sorted_list[-sample_size // 3:]

        for company in high_impact + mid_impact + low_impact:
            samples.append({
                'category': category,
                'company_id': company['company_id'],
                'cik': company['cik'],
                'company_name': company['company_name'],
                'sic_code': company.get('sic_code', ''),
                'total_filings': company['filing_count'],
                'in_scope_filings': company['in_scope_count'],
                'sec_url': f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={company['cik']}&type=&dateb=&owner=exclude&count=40",
            })

    return samples


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze potential exclusion candidates"
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of samples per category (default: 50)",
    )
    parser.add_argument(
        "--output",
        help="Output CSV file (optional)",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info("=" * 80)
    logger.info("Analyzing Exclusion Candidates")
    logger.info("=" * 80)
    logger.info(f"Database: {db_url}")
    logger.info(f"Sample size per category: {args.sample_size}")
    logger.info("=" * 80)

    # Set up database connection
    db = DatabaseAdapter(db_url)

    # Get all candidates
    logger.info("Fetching exclusion candidates...")
    candidates = get_exclusion_candidates(db)

    # Print summary statistics
    logger.info("")
    logger.info("Summary Statistics:")
    logger.info("-" * 80)

    total_companies = 0
    total_in_scope_filings = 0

    for category, company_list in candidates.items():
        category_name = category.replace('_', ' ').title()
        company_count = len(company_list)
        in_scope_count = sum(c['in_scope_count'] for c in company_list)

        logger.info(f"{category_name}:")
        logger.info(f"  Companies: {company_count}")
        logger.info(f"  In-scope filings: {in_scope_count}")

        total_companies += company_count
        total_in_scope_filings += in_scope_count

    logger.info("-" * 80)
    logger.info(f"TOTAL Unique Companies: {total_companies}")
    logger.info(f"TOTAL In-Scope Filings at Risk: {total_in_scope_filings}")
    logger.info("-" * 80)

    # Generate sample
    logger.info("")
    logger.info(f"Generating sample of {args.sample_size} companies per category...")
    samples = generate_sample(candidates, args.sample_size)

    logger.info(f"Generated {len(samples)} total samples for review")

    # Output samples
    if args.output:
        with open(args.output, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'category', 'company_id', 'cik', 'company_name', 'sic_code',
                'total_filings', 'in_scope_filings', 'sec_url'
            ])
            writer.writeheader()
            writer.writerows(samples)

        logger.info(f"Wrote samples to: {args.output}")
    else:
        # Print sample to console
        logger.info("")
        logger.info("Sample Companies for Review:")
        logger.info("=" * 120)

        for sample in samples[:100]:  # Limit console output
            logger.info(
                f"{sample['category']:30} | {sample['company_name']:50} | "
                f"SIC: {sample['sic_code']:4} | In-scope: {sample['in_scope_filings']:3}"
            )

        if len(samples) > 100:
            logger.info(f"... and {len(samples) - 100} more samples")
        logger.info("=" * 120)

    logger.info("")
    logger.info("Done! Review the samples and provide feedback.")


if __name__ == "__main__":
    main()
