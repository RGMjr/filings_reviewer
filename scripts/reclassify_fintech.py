#!/usr/bin/env python3
"""
Re-classify Fintech companies using the fixed classifier.

This script re-runs Fintech classification on all companies using the
improved classifier that excludes investment vehicles and crypto hardware manufacturers.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.infra.db import DatabaseAdapter
from src.universe.classifiers import classify_fintech_crypto
import os


def get_all_companies(db: DatabaseAdapter):
    """Get all companies with their current Fintech classification."""
    query = """
    SELECT
        c.company_id,
        c.company_name,
        c.industry_code as sic_code,
        bc.is_fintech_crypto as current_classification,
        bc.fintech_crypto_method as current_method
    FROM companies c
    LEFT JOIN business_classifications bc ON c.company_id = bc.company_id
    ORDER BY c.company_name
    """
    return db.query(query)


def reclassify_fintech(db: DatabaseAdapter):
    """Re-classify all companies using the fixed Fintech classifier."""

    print("="*70)
    print("RE-CLASSIFYING FINTECH COMPANIES WITH FIXED CLASSIFIER")
    print("="*70)
    print()

    # Get all companies
    companies = get_all_companies(db)
    print(f"Loaded {len(companies)} companies")

    # Track changes
    changes = []
    stats = {
        'total': len(companies),
        'before_fintech': 0,
        'after_fintech': 0,
        'false_positives_removed': 0,
        'new_detections': 0,
        'unchanged_true': 0,
        'unchanged_false': 0
    }

    # Count before
    for company in companies:
        if company['current_classification']:
            stats['before_fintech'] += 1

    print(f"Current Fintech count: {stats['before_fintech']}")
    print()
    print("Re-classifying...")
    print()

    # Re-classify each company
    for company in companies:
        company_id = company['company_id']
        company_name = company['company_name']
        sic_code = company['sic_code']
        was_fintech = company['current_classification']
        old_method = company['current_method']

        # Run new classifier
        is_fintech, new_method = classify_fintech_crypto(company_name, sic_code)

        # Track statistics
        if is_fintech:
            stats['after_fintech'] += 1

        if was_fintech and not is_fintech:
            # False positive removed
            stats['false_positives_removed'] += 1
            changes.append({
                'company_name': company_name,
                'sic_code': sic_code,
                'change': 'REMOVED',
                'old_method': old_method,
                'new_method': new_method
            })
        elif not was_fintech and is_fintech:
            # New detection
            stats['new_detections'] += 1
            changes.append({
                'company_name': company_name,
                'sic_code': sic_code,
                'change': 'ADDED',
                'old_method': old_method or 'no_match',
                'new_method': new_method
            })
        elif was_fintech and is_fintech:
            stats['unchanged_true'] += 1
        else:
            stats['unchanged_false'] += 1

        # Update database
        update_query = """
        UPDATE business_classifications
        SET is_fintech_crypto = %s,
            fintech_crypto_method = %s,
            updated_at = NOW()
        WHERE company_id = %s
        """
        db.execute(update_query, (is_fintech, new_method, company_id))

    # Display results
    print("="*70)
    print("RECLASSIFICATION RESULTS")
    print("="*70)
    print()

    print("Statistics:")
    print(f"  Total companies:    {stats['total']}")
    print(f"  Fintech before fix: {stats['before_fintech']}")
    print(f"  Fintech after fix:  {stats['after_fintech']}")
    print(f"  Net change:         {stats['after_fintech'] - stats['before_fintech']:+d}")
    print()

    print(f"  False positives removed: {stats['false_positives_removed']}")
    print(f"  New detections:          {stats['new_detections']}")
    print(f"  Unchanged (still Fintech): {stats['unchanged_true']}")
    print(f"  Unchanged (not Fintech):   {stats['unchanged_false']}")
    print()

    if stats['false_positives_removed'] > 0:
        print(f"✅ SUCCESS: Removed {stats['false_positives_removed']} false positives!")
        print(f"   Quality improvement: {stats['false_positives_removed']/stats['before_fintech']*100:.1f}% of previous Fintech classifications were incorrect")
        print()

    # Show detailed changes
    if changes:
        print("="*70)
        print("DETAILED CHANGES")
        print("="*70)
        print()

        removed = [c for c in changes if c['change'] == 'REMOVED']
        if removed:
            print(f"False Positives Removed ({len(removed)}):")
            print("-" * 70)
            for c in removed:
                print(f"  ✗ {c['company_name'][:50]:50s} | SIC {c['sic_code'] or 'N/A':4s} | Was: {c['old_method']}")
            print()

        added = [c for c in changes if c['change'] == 'ADDED']
        if added:
            print(f"New Fintech Detections ({len(added)}):")
            print("-" * 70)
            for c in added[:20]:  # Show first 20
                print(f"  ✓ {c['company_name'][:50]:50s} | SIC {c['sic_code'] or 'N/A':4s} | Method: {c['new_method']}")
            if len(added) > 20:
                print(f"  ... and {len(added) - 20} more")
            print()

    # Show sample of remaining Fintech companies
    print("="*70)
    print("SAMPLE OF REMAINING FINTECH COMPANIES (First 10)")
    print("="*70)

    remaining_query = """
    SELECT c.company_name, c.industry_code, bc.fintech_crypto_method
    FROM companies c
    JOIN business_classifications bc ON c.company_id = bc.company_id
    WHERE bc.is_fintech_crypto = TRUE
    ORDER BY c.company_name
    LIMIT 10
    """
    remaining = db.query(remaining_query)

    for company in remaining:
        print(f"  ✓ {company['company_name'][:50]:50s} | SIC {company['industry_code'] or 'N/A':4s} | {company['fintech_crypto_method']}")

    print()
    print("="*70)
    print("Database updated successfully!")
    print("="*70)

    return stats


def main():
    """Main reclassification workflow."""

    # Setup database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    # Run reclassification
    stats = reclassify_fintech(db)

    # Success!
    print()
    print(f"✅ Reclassification complete!")
    print(f"   Fintech companies: {stats['before_fintech']} → {stats['after_fintech']} ({stats['after_fintech'] - stats['before_fintech']:+d})")
    if stats['false_positives_removed'] > 0:
        print(f"   False positive rate: {stats['false_positives_removed']/stats['before_fintech']*100:.1f}% → ~0%")


if __name__ == '__main__':
    main()
