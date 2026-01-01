#!/usr/bin/env python3
"""
Assess quality of fetched filings by checking document types.

Analyzes a sample of fetched filings to determine:
1. How many are exhibit files vs. actual prospectuses
2. File size distribution
3. Document type classification

Usage:
    python scripts/assess_document_quality.py --sample-size 50
"""

import argparse
import re
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

load_dotenv()


def extract_title_from_html(html_path: str) -> str:
    """Extract title tag from HTML file."""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            # Read first 5KB which should contain the title
            content = f.read(5000)

        # Try to find title tag
        match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return "NO TITLE TAG"
    except Exception as e:
        return f"ERROR: {e}"


def get_file_size(html_path: str) -> int:
    """Get file size in bytes."""
    try:
        return Path(html_path).stat().st_size
    except OSError:
        return 0


def classify_document(title: str, file_size: int) -> tuple[str, str]:
    """
    Classify document type based on title and size.

    Returns:
        (classification, confidence)

    Classifications:
        - EXHIBIT: Filing fee tables, cover pages, etc.
        - PROSPECTUS: Full S-1/F-1 prospectus
        - AMENDMENT: Amendment to prospectus
        - UNKNOWN: Cannot determine
    """
    title_lower = title.lower()

    # Exhibit indicators
    exhibit_markers = [
        'ex-filing fees',
        'exhibit',
        'filing fee',
        'cover page',
        'calculation of',
        'fee table',
    ]

    if any(marker in title_lower for marker in exhibit_markers):
        return "EXHIBIT", "HIGH"

    # Prospectus indicators
    prospectus_markers = [
        'prospectus',
        's-1',
        'f-1',
        'registration statement',
        'form s-1',
        'form f-1',
    ]

    if any(marker in title_lower for marker in prospectus_markers):
        # Check size - prospectuses are typically > 100KB
        if file_size > 100_000:
            return "PROSPECTUS", "HIGH"
        elif file_size > 50_000:
            return "PROSPECTUS", "MEDIUM"
        else:
            return "PROSPECTUS", "LOW"  # Suspiciously small

    # Amendment indicators
    if 'amendment' in title_lower or '/a' in title_lower:
        if file_size > 100_000:
            return "AMENDMENT", "HIGH"
        else:
            return "AMENDMENT", "LOW"

    # Size-based classification (fallback)
    if file_size < 10_000:
        return "EXHIBIT", "MEDIUM"  # Very small files are likely exhibits
    elif file_size > 200_000:
        return "PROSPECTUS", "MEDIUM"  # Large files are likely prospectuses

    return "UNKNOWN", "LOW"


def analyze_filings(db: DatabaseAdapter, sample_size: int = 50) -> dict:
    """Analyze a random sample of fetched filings."""

    # Get random sample
    query = """
        SELECT
            f.filing_id,
            f.cik,
            f.accession_number,
            c.company_name,
            f.form_type,
            f.html_storage_path,
            f.filing_date
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE
            f.html_storage_path IS NOT NULL
            AND f.html_fetched_at IS NOT NULL
        ORDER BY RANDOM()
        LIMIT %(limit)s
    """

    filings = db.query(query, {"limit": sample_size})

    print(f"\n{'='*100}")
    print(f"Analyzing {len(filings)} random fetched filings")
    print(f"{'='*100}\n")

    results = []
    classifications = {
        "EXHIBIT": 0,
        "PROSPECTUS": 0,
        "AMENDMENT": 0,
        "UNKNOWN": 0,
    }

    confidence_levels = {
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
    }

    file_sizes = []

    for i, filing in enumerate(filings, 1):
        html_path = filing['html_storage_path']

        # Check if file exists
        if not Path(html_path).exists():
            print(f"⚠️  File not found: {html_path}")
            continue

        # Extract info
        title = extract_title_from_html(html_path)
        file_size = get_file_size(html_path)
        classification, confidence = classify_document(title, file_size)

        # Update stats
        classifications[classification] += 1
        confidence_levels[confidence] += 1
        file_sizes.append(file_size)

        results.append({
            "filing_id": filing['filing_id'],
            "company_name": filing['company_name'],
            "form_type": filing['form_type'],
            "cik": filing['cik'],
            "accession_number": filing['accession_number'],
            "title": title[:80],
            "file_size": file_size,
            "classification": classification,
            "confidence": confidence,
        })

        # Print sample (first 10)
        if i <= 10:
            size_kb = file_size / 1024
            print(f"{i:2}. {filing['company_name'][:30]:<30} | {classification:<12} ({confidence:>6}) | {size_kb:>7.1f} KB")
            print(f"    Title: {title[:80]}")
            print()

    if len(filings) > 10:
        print(f"... and {len(filings) - 10} more\n")

    # Calculate statistics
    total = len(results)

    print(f"\n{'='*100}")
    print("ANALYSIS RESULTS")
    print(f"{'='*100}\n")

    print("Document Type Distribution:")
    print("-" * 50)
    for doc_type, count in sorted(classifications.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {doc_type:<15} {count:>4} ({pct:>5.1f}%)")

    print("\nConfidence Level Distribution:")
    print("-" * 50)
    for level, count in sorted(confidence_levels.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {level:<15} {count:>4} ({pct:>5.1f}%)")

    if file_sizes:
        print("\nFile Size Statistics:")
        print("-" * 50)
        print(f"  Minimum:  {min(file_sizes) / 1024:>10.1f} KB")
        print(f"  Maximum:  {max(file_sizes) / 1024:>10.1f} KB")
        print(f"  Average:  {sum(file_sizes) / len(file_sizes) / 1024:>10.1f} KB")
        print(f"  Median:   {sorted(file_sizes)[len(file_sizes)//2] / 1024:>10.1f} KB")

    # Calculate usability metrics
    usable = classifications["PROSPECTUS"] + classifications["AMENDMENT"]
    unusable = classifications["EXHIBIT"]
    uncertain = classifications["UNKNOWN"]

    print("\n" + "="*100)
    print("USABILITY ASSESSMENT")
    print("="*100)
    print(f"\n✅ Usable for extraction:     {usable:>4} ({usable/total*100:>5.1f}%)")
    print(f"❌ Not usable (exhibits):     {unusable:>4} ({unusable/total*100:>5.1f}%)")
    print(f"❓ Uncertain classification: {uncertain:>4} ({uncertain/total*100:>5.1f}%)")

    # Detailed breakdown of issues
    print("\n" + "="*100)
    print("DETAILED FINDINGS")
    print("="*100)

    exhibits = [r for r in results if r['classification'] == 'EXHIBIT']
    if exhibits:
        print(f"\n❌ Exhibit Files ({len(exhibits)} total):")
        print("-" * 100)
        for ex in exhibits[:5]:
            print(f"  • {ex['company_name'][:40]:<40} | {ex['title'][:50]}")
        if len(exhibits) > 5:
            print(f"  ... and {len(exhibits) - 5} more")

    small_prospectuses = [r for r in results if r['classification'] == 'PROSPECTUS'
                          and r['confidence'] == 'LOW']
    if small_prospectuses:
        print(f"\n⚠️  Suspiciously Small Prospectuses ({len(small_prospectuses)} total):")
        print("-" * 100)
        for sp in small_prospectuses[:5]:
            size_kb = sp['file_size'] / 1024
            print(f"  • {sp['company_name'][:40]:<40} | {size_kb:>7.1f} KB | {sp['title'][:40]}")
        if len(small_prospectuses) > 5:
            print(f"  ... and {len(small_prospectuses) - 5} more")

    good_prospectuses = [r for r in results if r['classification'] == 'PROSPECTUS'
                         and r['confidence'] == 'HIGH']
    if good_prospectuses:
        print(f"\n✅ High-Quality Prospectuses ({len(good_prospectuses)} total):")
        print("-" * 100)
        for gp in good_prospectuses[:5]:
            size_kb = gp['file_size'] / 1024
            print(f"  • {gp['company_name'][:40]:<40} | {size_kb:>7.1f} KB | {gp['title'][:40]}")
        if len(good_prospectuses) > 5:
            print(f"  ... and {len(good_prospectuses) - 5} more")

    print("\n" + "="*100)
    print("RECOMMENDATION")
    print("="*100)

    if unusable / total > 0.20:
        print("\n🚨 CRITICAL: >20% of filings are exhibit files, not prospectuses!")
        print("\nAction Required:")
        print("  1. Fix primary document URL selection in UniverseBuilder")
        print("  2. Re-download affected filings with correct URLs")
        print("  3. Consider using SEC's -index.htm URLs for reliability")
    elif unusable / total > 0.10:
        print("\n⚠️  WARNING: 10-20% of filings are exhibit files")
        print("\nRecommended:")
        print("  1. Review primary document selection logic")
        print("  2. Consider filtering exhibit files from extraction pipeline")
    else:
        print("\n✅ GOOD: <10% exhibit files - within acceptable range")
        print("\nNo immediate action required. Exhibit filtering can be added later.")

    if uncertain / total > 0.15:
        print(f"\n⚠️  NOTE: {uncertain/total*100:.1f}% of files could not be confidently classified")
        print("Consider manual review of UNKNOWN classifications")

    print("\n" + "="*100)

    return {
        "total": total,
        "classifications": classifications,
        "confidence": confidence_levels,
        "usable": usable,
        "unusable": unusable,
        "uncertain": uncertain,
        "results": results,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Assess quality of fetched filing documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of filings to analyze (default: 50)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )

    args = parser.parse_args()

    # Connect to database
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )
    db = DatabaseAdapter(db_url)

    # Run analysis
    analyze_filings(db, args.sample_size)


if __name__ == "__main__":
    main()
