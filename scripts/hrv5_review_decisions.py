#!/usr/bin/env python3
"""
HRV-5: Automated Review Decision Creation

Applies learned patterns from HRV-3/HRV-4 to create review decisions for
Snowflake (39), DocuSign (40), and Samsara Vision (38) filings.

Usage:
    DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
      python3 scripts/hrv5_review_decisions.py
"""

import os
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# False positive patterns learned from HRV-3/HRV-4
FP_PATTERNS = {
    # Financial statement line items - gross profit values from income statements
    'financial_statement': [
        r'\[ROW\].*Gross profit.*\[CELL\]',  # Table structure with gross profit
        r'Cost of revenue.*\[ROW\].*Gross profit',
        r'Consolidated Statements of Operations',
    ],
    # Values that are clearly RPO (Remaining Performance Obligations) not customer metrics
    'rpo_values': [
        r'Remaining performance obligations.*\$.*million',
        r'performance obligations \(in millions\)',
    ],
    # Date-like values (should already be filtered but may slip through)
    'date_values': [
        r'^(19|20)\d{2}$',  # Years
        r'^(0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])$',  # Month/Day
    ],
}

# True positive patterns - strong signals for customer metrics
TP_PATTERNS = {
    'net_revenue_retention': [
        r'net revenue retention rate.*was.*\d+%',
        r'Net revenue retention rate.*\d+\s*%',
        r'retention rate.*of.*\d+%',
    ],
    'total_customers': [
        r'had\s+[\d,]+\s+total customers',
        r'Total customers.*\[CELL\].*[\d,]+',
    ],
    'customers_over_threshold': [
        r'Customers with.*revenue greater than \$\d+ million',
        r'product revenue greater than \$\d+ million',
    ],
}


def is_false_positive(candidate: dict) -> tuple[bool, str]:
    """
    Check if a candidate is a false positive based on learned patterns.

    Returns:
        Tuple of (is_fp, rejection_reason)
    """
    context = candidate['context_text']
    metric_id = candidate['suggested_metric_id']
    raw_value = candidate['raw_number_text']
    parsed_value = candidate.get('parsed_value')

    # Pattern 1 (REMOVED): cm_gross_margin_overall is no longer tracked (deprecated 2025-12-29)
    # It is not a customer-specific metric. See cm_gross_margin_by_cohort for cohort-level tracking.

    # Pattern 2: Deferred revenue - almost always FP as it's a financial line item
    if metric_id == 'cm_deferred_revenue':
        # Most deferred revenue mentions are balance sheet items, not disclosed metrics
        return True, 'Deferred revenue is financial line item, not customer metric'

    # Pattern 3: Dollar values wrongly matched to customer count metrics
    if metric_id == 'cm_active_customers_total':
        # Decimal dollar values (e.g., 688.2, 221.1)
        if '.' in raw_value and parsed_value and parsed_value < 1000:
            return True, 'Dollar amount (decimal), not customer count'
        # Dollar signs
        if '$' in raw_value:
            return True, 'Dollar amount, not customer count'
        # NRR percentage values (180%)
        if parsed_value and parsed_value > 100 and parsed_value < 300:
            if 'retention rate' in context.lower():
                return True, 'Retention rate value, not customer count'

    # Pattern 4: Net revenue retention - check for invalid percentage values
    if metric_id == 'cm_net_revenue_retention':
        if parsed_value and not raw_value.endswith('%') and '%' not in raw_value:
            # Dollar values wrongly matched to NRR
            if '$' in raw_value or parsed_value > 1000:
                return True, 'Dollar value, not retention rate'
            # Customer counts wrongly matched (look for "Total customers" context)
            if parsed_value > 500 and 'Total customers' in context:
                return True, 'Customer count value, not retention rate'

    # Pattern 5: Date-like numbers (31 = day of month)
    if raw_value in ['31', '30', '28', '29', '12', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11']:
        if 'January 31' in context or 'July 31' in context or 'April 30' in context:
            return True, 'Date component, not metric value'

    # Pattern 6: Concatenated date strings (e.g., "9202020192020")
    if parsed_value and parsed_value > 1_000_000_000:
        return True, 'Malformed/concatenated number, not valid metric'

    # Pattern 7: Revenue concentration - large values in millions
    if metric_id == 'cm_revenue_concentration':
        if '%' not in raw_value:
            # Numbers without % are not concentration percentages
            return True, 'Not a percentage, not valid concentration metric'

    # Pattern 8: Expansion revenue - dollar values should be filtered
    if metric_id == 'cm_expansion_revenue':
        if '%' in raw_value:
            # Percentage values near expansion context are likely NRR related
            return True, 'Percentage value, likely NRR not standalone expansion metric'

    # Pattern 9: New customers acquired - percentage values are likely revenue concentration
    if metric_id == 'cm_new_customers_acquired':
        if '%' in raw_value:
            if 'product revenue' in context.lower() and 'accounted' not in context.lower():
                return True, 'Revenue percentage, not customer acquisition count'

    # Pattern 10: ACV - generic small numbers
    if metric_id == 'cm_acv':
        if parsed_value and parsed_value < 1000 and '$' not in raw_value:
            return True, 'Generic number, not ACV value'

    return False, ''


def is_true_positive(candidate: dict) -> bool:
    """
    Check if a candidate is a strong true positive.
    """
    context = candidate['context_text']
    metric_id = candidate['suggested_metric_id']
    raw_value = candidate['raw_number_text']
    parsed_value = candidate.get('parsed_value')

    # NRR with percentage values and strong context
    if metric_id == 'cm_net_revenue_retention':
        if '%' in raw_value:
            if any(phrase in context.lower() for phrase in [
                'net revenue retention rate',
                'retention rate was',
                'retention rate of',
            ]):
                return True
        # Also accept raw numbers in 100-300 range near NRR context (e.g., "180" near "Net revenue retention rate")
        if parsed_value and 100 <= parsed_value <= 300:
            if 'Net revenue retention rate' in context:
                return True

    # Customer counts with clear context
    if metric_id == 'cm_active_customers_total':
        if parsed_value and 100 <= parsed_value <= 10000:
            # Strong signals for true customer counts
            if 'total customers' in context.lower() and 'had' in context.lower():
                return True
            if 'Total customers [CELL]' in context:
                # Table cell with clear "Total customers" header
                return True

    # Customers over threshold (e.g., "$1 million" customers)
    if metric_id == 'cm_new_customers_acquired':
        if 'product revenue greater than' in context.lower():
            return True
        if 'trailing 12-month product revenue greater than' in context.lower():
            return True

    # Revenue concentration with percentage
    if metric_id == 'cm_revenue_concentration':
        if '%' in raw_value and parsed_value and parsed_value <= 100:
            if any(phrase in context.lower() for phrase in [
                'accounted for',
                'of revenue',
                'of our revenue',
                'customer a',  # Customer concentration table
                'customer b',
                'customer c',
            ]):
                return True

    return False


def analyze_filing(db, filing_id: int, dry_run: bool = False) -> dict:
    """
    Analyze candidates for a filing and create review decisions.

    Returns:
        Stats dict with accept/reject counts
    """
    # Get all pending candidates
    candidates = db.query("""
        SELECT
            candidate_id,
            suggested_metric_id,
            raw_number_text,
            parsed_value,
            triggering_keyword,
            context_text
        FROM review_candidates rc
        WHERE rc.filing_id = %(filing_id)s
        AND NOT EXISTS (
            SELECT 1 FROM review_decisions rd
            WHERE rd.candidate_id = rc.candidate_id
        )
        ORDER BY candidate_id
    """, {'filing_id': filing_id})

    stats = {
        'total': len(candidates),
        'accepted': 0,
        'rejected': 0,
        'skipped': 0,
        'fp_patterns': {},
    }

    for candidate in candidates:
        is_fp, rejection_reason = is_false_positive(candidate)

        if is_fp:
            # Reject as false positive
            if not dry_run:
                db.execute("""
                    INSERT INTO review_decisions
                        (candidate_id, decision, rejection_reason, rejection_category, reviewer_id, reviewer_notes)
                    VALUES
                        (%(candidate_id)s, 'reject', %(rejection_reason)s, 'not_a_metric', 'hrv5_script', 'Automated rejection based on HRV-3/4 patterns')
                """, {
                    'candidate_id': candidate['candidate_id'],
                    'rejection_reason': rejection_reason,
                })
            stats['rejected'] += 1
            stats['fp_patterns'][rejection_reason] = stats['fp_patterns'].get(rejection_reason, 0) + 1

        elif is_true_positive(candidate):
            # Accept with suggested metric ID
            if not dry_run:
                db.execute("""
                    INSERT INTO review_decisions
                        (candidate_id, decision, assigned_metric_id, reviewer_id, reviewer_notes)
                    VALUES
                        (%(candidate_id)s, 'accept', %(metric_id)s, 'hrv5_script', 'Automated acceptance based on strong TP patterns')
                """, {
                    'candidate_id': candidate['candidate_id'],
                    'metric_id': candidate['suggested_metric_id'],
                })
            stats['accepted'] += 1

        else:
            # Neither clear FP nor clear TP - needs manual review
            stats['skipped'] += 1

    return stats


def main():
    load_dotenv()
    db_url = os.getenv('DATABASE_URL')

    if not db_url:
        print("Error: DATABASE_URL not set")
        sys.exit(1)

    from src.infra.db import DatabaseAdapter
    db = DatabaseAdapter(db_url)

    # Target filings
    filings = [
        (39, 'Snowflake'),
        (40, 'DocuSign'),
        (38, 'Samsara Vision'),
    ]

    print("=" * 70)
    print("HRV-5: Automated Review Decision Creation")
    print("=" * 70)

    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("DRY RUN MODE - No changes will be made")

    total_stats = {'accepted': 0, 'rejected': 0, 'skipped': 0}

    for filing_id, company in filings:
        print(f"\nProcessing {company} (filing_id={filing_id})...")
        stats = analyze_filing(db, filing_id, dry_run=dry_run)

        print(f"  Total candidates: {stats['total']}")
        print(f"  Accepted: {stats['accepted']}")
        print(f"  Rejected: {stats['rejected']}")
        print(f"  Needs manual review: {stats['skipped']}")

        if stats['fp_patterns']:
            print("  FP patterns found:")
            for pattern, count in stats['fp_patterns'].items():
                print(f"    - {pattern}: {count}")

        total_stats['accepted'] += stats['accepted']
        total_stats['rejected'] += stats['rejected']
        total_stats['skipped'] += stats['skipped']

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total accepted: {total_stats['accepted']}")
    print(f"Total rejected: {total_stats['rejected']}")
    print(f"Needs manual review: {total_stats['skipped']}")

    if not dry_run:
        print("\nDecisions saved to database")
    else:
        print("\nRun without --dry-run to save decisions")


if __name__ == '__main__':
    main()
