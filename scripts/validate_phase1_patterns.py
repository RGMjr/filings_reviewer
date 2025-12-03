#!/usr/bin/env python3
"""
Quick Phase 1 Pattern Validation

Tests if Phase 1 keyword pattern improvements would detect CMASB priority metrics
that were missed in Phase 5 extraction.

Fast validation approach:
1. Sample filing text from companies with existing Phase 5 extractions
2. Test old vs new keyword patterns against same text
3. Count new CMASB metric matches
4. Generate GO/NO-GO recommendation

Runtime: 2-3 minutes
"""

import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.infra.db import DatabaseAdapter

# OLD PATTERNS (Phase 5 baseline)
OLD_PATTERNS = {
    'cm_new_customers_acquired': [
        r"\bnew\s+customers?\b",
        r"\bcustomers?\s+acquired\b",
        r"\bacquired\s+customers?\b",
        r"\bnewly\s+acquired\b",
    ],
    'cm_net_revenue_retention': [
        r"\bnrr\b",
        r"\bnet\s+revenue\s+retention\b",
        r"\bnet\s+retention\b",
    ],
}

# NEW PATTERNS (Phase 1 improvements)
NEW_PATTERNS = {
    'cm_new_customers_acquired': [
        r"\bnew\s+customers?\b",
        r"\bcustomers?\s+acquired\b",
        r"\bacquired\s+customers?\b",
        r"\bnewly\s+acquired\b",
        r"\bnew\s+customer\s+additions?\b",
        r"\bnet\s+new\s+customers?\b",
        r"\bcustomers?\s+added\b",
        r"\bcustomer\s+growth\b",
        r"\bacquisition\s+of\s+customers?\b",
        r"\bnew\s+users?\s+acquired\b",
        r"\bacquired\s+users?\b",
    ],
    'cm_net_revenue_retention': [
        r"\bnrr\b",
        r"\bnet\s+revenue\s+retention\b",
        r"\bnet\s+retention\b",
        r"\bnet\s+dollar\s+retention\b",
        r"\bndr\b",
        r"\bretention\s+rate.*\d+%",
        r"\bnet\s+retention\s+rate\b",
    ],
    'cm_gross_margin_by_cohort': [
        r"\bgross\s+margin\b",
        r"\bgross\s+profit\b",
        r"\bmargin\s+by\s+cohort\b",
        r"\bcohort\s+margin\b",
        r"\bgross\s+margin\s+%\b",
        r"\bgross\s+profit\s+margin\b",
    ],
    'cm_expansion_revenue': [
        r"\bexpansion\s+revenue\b",
        r"\bcross[- ]sell\b",
        r"\bupsell\b",
        r"\bproducts?\s+per\s+customer\b",
        r"\baverage\s+products?\s+owned\b",
        r"\bexpand\b.*\brevenue\b",
        r"\badditional\s+products?\b",
        r"\bmulti[- ]product\b",
    ],
    'cm_revenue_concentration': [
        r"\brevenue\s+concentration\b",
        r"\bcustomer\s+concentration\b",
        r"\btop\s+\d+\s+customers?\b",
        r"\blargest\s+customers?\b",
        r"\b\d+%\s+of\s+revenue\b",
        r"\bconcentration\s+risk\b",
        r"\bconcentration\s+of\s+revenue\b",
        r"\bmajor\s+customers?\b",
    ],
}

# Test companies (companies with fetched filings in database)
TEST_COMPANIES = [
    ('0000058361', 'LEE ENTERPRISES, Inc', 'Media'),
    ('0000315545', 'PROVECTUS BIOPHARMACEUTICALS, INC.', 'HealthTech'),
    ('0000720154', 'Inotiv, Inc.', 'HealthTech'),
    ('0000744455', 'Empower Annuity Insurance Co of America', 'Financial'),
    ('0000771266', 'KOPIN CORP', 'Technology'),
]


def get_filing_text(db: DatabaseAdapter, cik: str, max_chars: int = 100000) -> str:
    """Get filing HTML/text content from stored files."""
    # Get company_id
    query = "SELECT company_id FROM companies WHERE cik = %s"
    result = db.query(query, (cik,))
    if not result:
        return ""

    company_id = result[0]['company_id']

    # Get filing file paths
    filing_query = """
    SELECT html_storage_path, txt_storage_path
    FROM filings
    WHERE company_id = %s
    AND form_type IN ('S-1', 'S-1/A')
    ORDER BY filing_date DESC
    LIMIT 1
    """
    filing_result = db.query(filing_query, (company_id,))

    if not filing_result:
        return ""

    # Read from file (prefer HTML, fall back to TXT)
    html_path = filing_result[0].get('html_storage_path')
    txt_path = filing_result[0].get('txt_storage_path')

    content = ""

    # Get project root (scripts/../)
    project_root = Path(__file__).parent.parent

    # Try HTML first
    if html_path:
        full_html_path = project_root / html_path
        if full_html_path.exists():
            try:
                with open(full_html_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                print(f"  ⚠ Error reading HTML file: {e}")

    # Fall back to TXT
    if not content and txt_path:
        full_txt_path = project_root / txt_path
        if full_txt_path.exists():
            try:
                with open(full_txt_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                print(f"  ⚠ Error reading TXT file: {e}")

    # Return first N characters
    return content[:max_chars]


def test_patterns_on_text(
    text: str, old_patterns: Dict[str, List[str]], new_patterns: Dict[str, List[str]]
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, List[str]]]:
    """
    Test old vs new patterns on text.

    Returns:
        (old_matches, new_matches, new_match_examples)
    """
    text_lower = text.lower()

    old_matches = {}
    new_matches = {}
    new_match_examples = defaultdict(list)

    # Test old patterns
    for metric_id, patterns in old_patterns.items():
        count = 0
        for pattern in patterns:
            matches = re.finditer(pattern, text_lower, re.IGNORECASE)
            count += len(list(matches))
        old_matches[metric_id] = count

    # Test new patterns
    for metric_id, patterns in new_patterns.items():
        count = 0
        for pattern in patterns:
            matches = list(re.finditer(pattern, text_lower, re.IGNORECASE))
            count += len(matches)

            # Capture first few examples
            if matches and len(new_match_examples[metric_id]) < 3:
                for match in matches[:3]:
                    # Get context around match (50 chars before and after)
                    start = max(0, match.start() - 50)
                    end = min(len(text), match.end() + 50)
                    context = text[start:end].strip()
                    # Clean up whitespace
                    context = ' '.join(context.split())
                    if context not in new_match_examples[metric_id]:
                        new_match_examples[metric_id].append(context)

        new_matches[metric_id] = count

    return old_matches, new_matches, dict(new_match_examples)


def main():
    """Main validation function."""
    print("=" * 80)
    print("PHASE 1 KEYWORD PATTERN VALIDATION")
    print("=" * 80)
    print("\nQuick validation: Testing if Phase 1 patterns would detect")
    print("CMASB priority metrics that Phase 5 missed.\n")
    print("=" * 80 + "\n")

    # Initialize database
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    # Results storage
    all_old_matches = Counter()
    all_new_matches = Counter()
    all_improvements = defaultdict(int)
    company_results = []

    # Test each company
    for cik, company_name, business_type in TEST_COMPANIES:
        print(f"Testing: {company_name} ({business_type})")
        print(f"CIK: {cik}")

        # Get filing text
        text = get_filing_text(db, cik)

        if not text:
            print(f"  ⚠ No filing content found, skipping...\n")
            continue

        print(f"  ✓ Loaded {len(text):,} characters of filing text")

        # Test patterns
        old_matches, new_matches, examples = test_patterns_on_text(
            text, OLD_PATTERNS, NEW_PATTERNS
        )

        # Calculate improvements
        improvements = {}
        for metric_id in NEW_PATTERNS.keys():
            old_count = old_matches.get(metric_id, 0)
            new_count = new_matches.get(metric_id, 0)
            improvement = new_count - old_count
            improvements[metric_id] = improvement

            all_old_matches[metric_id] += old_count
            all_new_matches[metric_id] += new_count
            if improvement > 0:
                all_improvements[metric_id] += improvement

        # Store results
        company_results.append({
            'company_name': company_name,
            'business_type': business_type,
            'old_matches': dict(old_matches),
            'new_matches': dict(new_matches),
            'improvements': improvements,
            'examples': examples,
        })

        # Print summary for this company
        print(f"\n  Pattern Matching Results:")
        for metric_id, improvement in improvements.items():
            metric_name = metric_id.replace('cm_', '').replace('_', ' ').title()
            old_count = old_matches.get(metric_id, 0)
            new_count = new_matches.get(metric_id, 0)

            if improvement > 0:
                print(f"    ✨ {metric_name:30s}  {old_count:3d} → {new_count:3d}  (+{improvement})")
            elif new_count > 0:
                print(f"    ✓ {metric_name:30s}  {old_count:3d} → {new_count:3d}  (no change)")

        print()

    # Overall Summary
    print("\n" + "=" * 80)
    print("OVERALL PATTERN MATCHING IMPROVEMENTS")
    print("=" * 80 + "\n")

    print(f"{'Metric':<40} {'Old':>8} {'New':>8} {'Improvement':>12}")
    print("-" * 80)

    total_old = 0
    total_new = 0
    total_improvement = 0

    for metric_id in sorted(NEW_PATTERNS.keys()):
        metric_name = metric_id.replace('cm_', '').replace('_', ' ').title()
        old_count = all_old_matches[metric_id]
        new_count = all_new_matches[metric_id]
        improvement = all_improvements[metric_id]

        marker = "⭐" if improvement > 0 else ""
        print(f"{metric_name:<40} {old_count:>8d} {new_count:>8d} {improvement:>+12d} {marker}")

        total_old += old_count
        total_new += new_count
        total_improvement += improvement

    print("-" * 80)
    print(f"{'TOTAL':<40} {total_old:>8d} {total_new:>8d} {total_improvement:>+12d}")

    if total_old > 0:
        pct_improvement = (total_improvement / total_old * 100)
        print(f"\nPercentage Improvement: {pct_improvement:+.1f}%")

    # Show examples of new matches
    print("\n" + "=" * 80)
    print("EXAMPLE MATCHES FROM NEW PATTERNS")
    print("=" * 80 + "\n")

    for result in company_results:
        if result['examples']:
            print(f"{result['company_name']}:")
            for metric_id, examples in result['examples'].items():
                if examples:
                    metric_name = metric_id.replace('cm_', '').replace('_', ' ').title()
                    print(f"\n  {metric_name}:")
                    for example in examples[:2]:  # Show first 2 examples
                        print(f"    → \"{example}\"")
            print()

    # Success Criteria
    print("\n" + "=" * 80)
    print("SUCCESS CRITERIA")
    print("=" * 80 + "\n")

    criteria_results = []

    # Criterion 1: At least 5 new "new customers acquired" matches
    new_customers_improvement = all_improvements['cm_new_customers_acquired']
    criterion1 = new_customers_improvement >= 5
    criteria_results.append((
        f"At least 5 new 'new customers acquired' matches (actual: {new_customers_improvement})",
        criterion1
    ))

    # Criterion 2: At least 1 new NRR match
    nrr_improvement = all_improvements['cm_net_revenue_retention']
    criterion2 = nrr_improvement >= 1
    criteria_results.append((
        f"At least 1 new NRR match (actual: {nrr_improvement})",
        criterion2
    ))

    # Criterion 3: New metrics detected (gross margin, expansion, revenue concentration)
    new_metrics_detected = sum(1 for m in ['cm_gross_margin_by_cohort', 'cm_expansion_revenue', 'cm_revenue_concentration']
                               if all_new_matches[m] > 0)
    criterion3 = new_metrics_detected >= 2
    criteria_results.append((
        f"At least 2 new metric categories detected (actual: {new_metrics_detected}/3)",
        criterion3
    ))

    # Criterion 4: Overall 25%+ improvement
    if total_old > 0:
        pct = (total_improvement / total_old * 100)
        criterion4 = pct >= 25
        criteria_results.append((
            f"Overall 25%+ improvement in matches (actual: {pct:+.1f}%)",
            criterion4
        ))
    else:
        criterion4 = total_improvement >= 10
        criteria_results.append((
            f"Overall improvement with baseline data (actual: {total_improvement} new matches)",
            criterion4
        ))

    for criterion, result in criteria_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {criterion}")

    # Final Recommendation
    passed = sum(1 for _, result in criteria_results if result)
    total_criteria = len(criteria_results)

    print(f"\n\nFINAL RECOMMENDATION")
    print("-" * 80)
    print(f"Criteria Passed: {passed}/{total_criteria}\n")

    if passed >= 3:
        print("✅ RECOMMENDATION: **GO** - Phase 1 patterns show strong improvements")
        print("   New keyword patterns successfully detect CMASB priority metrics")
        print("   that were missed in Phase 5.")
        print("\n   NEXT STEP: Deploy Phase 1 to production on 48 validated companies")
    elif passed >= 2:
        print("⚠️  RECOMMENDATION: **CONDITIONAL GO** - Moderate improvements")
        print("   Consider minor pattern adjustments before production deployment")
    else:
        print("❌ RECOMMENDATION: **NO GO** - Insufficient pattern improvements")
        print("   Refine keyword patterns and re-test")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
