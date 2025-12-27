#!/usr/bin/env python3
"""
HRV-2: Validation Script - Compare Review Candidates Against Gold Standard

Compares system-generated review candidates against the manually-curated
gold standard CSV to calculate precision, recall, and F1 metrics.

Usage:
    # Validate specific filing by database ID
    python scripts/validate_against_gold_standard.py --filing-id 2

    # Validate by company name
    python scripts/validate_against_gold_standard.py --company "Slack Technologies"

    # Validate all filings that have gold standard entries
    python scripts/validate_against_gold_standard.py --all

    # Output detailed report to file
    python scripts/validate_against_gold_standard.py --all --output report.json

    # Verbose mode shows per-candidate match details
    python scripts/validate_against_gold_standard.py --filing-id 2 --verbose
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Default gold standard path
GOLD_STANDARD_PATH = Path(__file__).parent.parent / "data" / "gold_standard" / "golden_set_251218.csv"


@dataclass
class GoldStandardEntry:
    """A single entry from the gold standard CSV."""
    document_url: str
    company: str
    metric_id: str  # Normalized from "Standard Metric Name"
    is_new_metric: bool
    text_variant: str  # "Name in the text"
    raw_value: str
    scaled_value: str
    scale_unit: str
    period: str
    definition: str
    source_quote: str  # "Quote/context"
    line_number: int  # Line number in CSV for reference


@dataclass
class ValidationMatch:
    """Represents a match between a candidate and gold standard entry."""
    candidate_id: int
    gold_entry: GoldStandardEntry
    match_type: str  # 'exact_value', 'close_value', 'metric_only'
    confidence: float


@dataclass
class ValidationResult:
    """Results of validating one filing."""
    filing_id: int | None
    company_name: str
    gold_standard_count: int
    candidate_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    fp_candidates: list[dict]  # Candidates not matching gold standard
    fn_entries: list[GoldStandardEntry]  # Gold standard entries not matched
    tp_matches: list[ValidationMatch]  # Matched pairs for debugging


def normalize_metric_id(raw_id: str) -> str:
    """
    Normalize metric ID to standard form.

    Examples:
        "cm_dau" -> "cm_dau"
        "cm_daily_active_users" -> "cm_daily_active_users"
        "" -> "" (empty stays empty)
    """
    if not raw_id:
        return ""
    # Already normalized if starts with cm_
    return raw_id.strip().lower()


def normalize_value(raw: str) -> float | None:
    """
    Normalize value strings to numeric.

    Examples:
        "10 million" -> 10_000_000
        "1.5B" -> 1_500_000_000
        "500K" -> 500_000
        "$1.2 billion" -> 1_200_000_000
        "15%" -> 0.15
        "chart" -> None (special value)
        "" -> None
    """
    if not raw or raw.strip().lower() in ('chart', 'n/a', '-', ''):
        return None

    # Remove currency symbols and commas
    cleaned = raw.strip()
    cleaned = re.sub(r'[$,]', '', cleaned)

    # Handle percentage
    if '%' in cleaned:
        cleaned = cleaned.replace('%', '')
        try:
            return float(cleaned) / 100
        except ValueError:
            return None

    # Multiplier patterns
    multipliers = {
        'trillion': 1_000_000_000_000,
        't': 1_000_000_000_000,
        'billion': 1_000_000_000,
        'b': 1_000_000_000,
        'million': 1_000_000,
        'm': 1_000_000,
        'thousand': 1_000,
        'k': 1_000,
    }

    # Try to extract number and multiplier
    # Match patterns like "1.5 million", "1.5M", "15 billion"
    pattern = r'([\d.]+)\s*(trillion|billion|million|thousand|t|b|m|k)?'
    match = re.search(pattern, cleaned, re.IGNORECASE)

    if match:
        try:
            num = float(match.group(1))
            mult_str = match.group(2)
            if mult_str:
                mult = multipliers.get(mult_str.lower(), 1)
                return num * mult
            return num
        except ValueError:
            pass

    # Try direct float conversion
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_gold_standard(path: Path) -> list[GoldStandardEntry]:
    """
    Load gold standard CSV and parse into entries.

    Args:
        path: Path to gold standard CSV file

    Returns:
        List of GoldStandardEntry objects
    """
    entries = []

    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):  # Line 1 is header
            # Normalize metric ID from "Standard Metric Name"
            metric_id = normalize_metric_id(row.get('Standard Metric Name', ''))

            # Check if it's a new metric (column "New standard metric?")
            new_metric_val = row.get('New standard metric?', '').strip()
            is_new_metric = bool(new_metric_val and new_metric_val.lower().startswith('cm_'))

            # If no standard metric but has new metric, use that
            if not metric_id and is_new_metric:
                metric_id = normalize_metric_id(new_metric_val)

            entry = GoldStandardEntry(
                document_url=row.get('Document URL', ''),
                company=row.get('Company', ''),
                metric_id=metric_id,
                is_new_metric=is_new_metric,
                text_variant=row.get('Name in the text', ''),
                raw_value=row.get('Raw value', ''),
                scaled_value=row.get('Scaled value', ''),
                scale_unit=row.get('Scale/unit', ''),
                period=row.get('Period', ''),
                definition=row.get('Definition', ''),
                source_quote=row.get('Quote/context', ''),
                line_number=line_num,
            )
            entries.append(entry)

    return entries


def normalize_company_name(name: str) -> str:
    """Normalize company name for matching (Ltd/Limited, Inc/Incorporated, etc.)."""
    name = name.lower().strip()
    # Remove trailing suffixes completely for comparison
    suffixes_to_remove = [
        ', inc.',
        ', inc',
        ' inc.',
        ' inc',
        ', ltd.',
        ', ltd',
        ' ltd.',
        ' ltd',
        ', llc',
        ' llc',
        ', plc',
        ' plc',
        ', corp.',
        ', corp',
        ' corp.',
        ' corp',
        ' limited',
        ' incorporated',
        ' corporation',
    ]
    for suffix in suffixes_to_remove:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    # Also remove commas
    name = name.replace(',', '')
    return name.strip()


def get_entries_for_company(
    entries: list[GoldStandardEntry],
    company_name: str
) -> list[GoldStandardEntry]:
    """Filter gold standard entries for a specific company (case-insensitive, fuzzy matching)."""
    normalized_name = normalize_company_name(company_name)
    return [e for e in entries if normalize_company_name(e.company) == normalized_name]


def match_candidate_to_gold_standard(
    candidate: dict,
    gold_entries: list[GoldStandardEntry],
    matched_entries: set[int],  # Line numbers already matched
) -> tuple[GoldStandardEntry | None, str]:
    """
    Try to match a candidate to a gold standard entry.

    Args:
        candidate: Review candidate dict from database
        gold_entries: List of gold standard entries for this company
        matched_entries: Set of line numbers already matched (to prevent double counting)

    Returns:
        Tuple of (matched entry or None, match type string)
    """
    candidate_metric = normalize_metric_id(candidate.get('suggested_metric_id', ''))
    candidate_value = candidate.get('parsed_value')
    candidate_raw = candidate.get('raw_number_text', '')

    best_match = None
    best_match_type = ''
    best_score = 0

    for entry in gold_entries:
        if entry.line_number in matched_entries:
            continue

        score = 0
        match_type = ''

        # Metric ID match (most important)
        if candidate_metric and entry.metric_id:
            if candidate_metric == entry.metric_id:
                score += 2
                match_type = 'metric_match'

        # Value match
        gold_value = normalize_value(entry.raw_value) or normalize_value(entry.scaled_value)

        if candidate_value is not None and gold_value is not None:
            try:
                # Check for exact or close match (within 1%)
                if candidate_value == gold_value:
                    score += 3
                    match_type = 'exact_value'
                elif abs(candidate_value - gold_value) / max(gold_value, 1e-10) < 0.01:
                    score += 2.5
                    match_type = 'close_value'
            except (TypeError, ZeroDivisionError):
                pass

        # Text variant match (fuzzy)
        if entry.text_variant:
            variant_lower = entry.text_variant.lower()
            raw_lower = candidate_raw.lower()
            context_lower = candidate.get('context_text', '').lower()

            if variant_lower in context_lower or variant_lower in raw_lower:
                score += 1

        # Triggering keyword match
        keyword = candidate.get('triggering_keyword', '').lower()
        if keyword and (keyword in entry.text_variant.lower() or
                       keyword in entry.definition.lower()):
            score += 0.5

        if score > best_score:
            best_score = score
            best_match = entry
            best_match_type = match_type

    # Only consider a match if score is high enough
    # Require at least metric OR value match
    if best_score >= 2:
        return best_match, best_match_type

    return None, ''


def validate_filing(
    db,  # DatabaseAdapter
    filing_id: int | None,
    company_name: str,
    gold_entries: list[GoldStandardEntry],
    verbose: bool = False,
) -> ValidationResult:
    """
    Validate candidates for a filing against gold standard.

    Args:
        db: Database adapter
        filing_id: Filing ID (or None if not in DB)
        company_name: Company name for matching
        gold_entries: Gold standard entries for this company
        verbose: Print per-candidate details

    Returns:
        ValidationResult with precision/recall metrics
    """
    # Get candidates from database
    candidates = []
    if filing_id:
        candidates = db.get_review_candidates_for_filing(filing_id)

    matched_entries: set[int] = set()  # Line numbers matched
    matched_candidates: set[int] = set()  # Candidate IDs matched
    tp_matches: list[ValidationMatch] = []

    # Try to match each candidate
    for candidate in candidates:
        match, match_type = match_candidate_to_gold_standard(
            candidate, gold_entries, matched_entries
        )

        if match:
            matched_entries.add(match.line_number)
            matched_candidates.add(candidate['candidate_id'])
            tp_matches.append(ValidationMatch(
                candidate_id=candidate['candidate_id'],
                gold_entry=match,
                match_type=match_type,
                confidence=1.0,
            ))

            if verbose:
                logger.info(
                    f"  TP: candidate {candidate['candidate_id']} matched "
                    f"gold entry line {match.line_number} ({match_type})"
                )

    # Calculate metrics
    true_positives = len(tp_matches)
    false_positives = len(candidates) - true_positives
    false_negatives = len(gold_entries) - true_positives

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    # Collect FP candidates
    fp_candidates = [c for c in candidates if c['candidate_id'] not in matched_candidates]

    # Collect FN entries
    fn_entries = [e for e in gold_entries if e.line_number not in matched_entries]

    return ValidationResult(
        filing_id=filing_id,
        company_name=company_name,
        gold_standard_count=len(gold_entries),
        candidate_count=len(candidates),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        fp_candidates=fp_candidates,
        fn_entries=fn_entries,
        tp_matches=tp_matches,
    )


def print_validation_report(result: ValidationResult, verbose: bool = False):
    """Print a validation report to stdout."""
    print(f"\n{'=' * 60}")
    print(f"Validation Report for {result.company_name}")
    if result.filing_id:
        print(f"(filing_id={result.filing_id})")
    print('=' * 60)

    print(f"\nGold Standard Entries: {result.gold_standard_count}")
    print(f"Review Candidates: {result.candidate_count}")

    print(f"\nMetrics:")
    print(f"  True Positives:  {result.true_positives}")
    print(f"  False Positives: {result.false_positives}")
    print(f"  False Negatives: {result.false_negatives}")
    print(f"  Precision:       {result.precision * 100:.1f}%")
    print(f"  Recall:          {result.recall * 100:.1f}%")
    print(f"  F1 Score:        {result.f1_score * 100:.1f}%")

    if result.false_positives > 0:
        print(f"\nFalse Positives (candidates not in gold standard):")
        for i, fp in enumerate(result.fp_candidates[:10], 1):  # Show first 10
            metric = fp.get('suggested_metric_id', 'unknown')
            raw = fp.get('raw_number_text', '')
            seg_id = fp.get('source_segment_id', 'N/A')
            print(f"  {i}. [{metric}] \"{raw}\" in segment {seg_id}")
        if len(result.fp_candidates) > 10:
            print(f"  ... and {len(result.fp_candidates) - 10} more")

    if result.false_negatives > 0:
        print(f"\nFalse Negatives (gold standard metrics not detected):")
        for i, fn in enumerate(result.fn_entries[:10], 1):  # Show first 10
            metric = fn.metric_id or 'unknown'
            variant = fn.text_variant or fn.raw_value
            print(f"  {i}. [{metric}] \"{variant}\" (line {fn.line_number} in CSV)")
        if len(result.fn_entries) > 10:
            print(f"  ... and {len(result.fn_entries) - 10} more")

    print()


def result_to_dict(result: ValidationResult) -> dict:
    """Convert ValidationResult to JSON-serializable dict."""
    return {
        'filing_id': result.filing_id,
        'company_name': result.company_name,
        'gold_standard_count': result.gold_standard_count,
        'candidate_count': result.candidate_count,
        'metrics': {
            'true_positives': result.true_positives,
            'false_positives': result.false_positives,
            'false_negatives': result.false_negatives,
            'precision': result.precision,
            'recall': result.recall,
            'f1_score': result.f1_score,
        },
        'false_positives': [
            {
                'candidate_id': fp['candidate_id'],
                'metric_id': fp.get('suggested_metric_id'),
                'raw_number_text': fp.get('raw_number_text'),
                'source_segment_id': fp.get('source_segment_id'),
            }
            for fp in result.fp_candidates
        ],
        'false_negatives': [
            {
                'line_number': fn.line_number,
                'metric_id': fn.metric_id,
                'text_variant': fn.text_variant,
                'raw_value': fn.raw_value,
            }
            for fn in result.fn_entries
        ],
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate review candidates against gold standard CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate specific filing
  python scripts/validate_against_gold_standard.py --filing-id 2

  # Validate by company name
  python scripts/validate_against_gold_standard.py --company "Slack Technologies"

  # Validate all filings with gold standard entries
  python scripts/validate_against_gold_standard.py --all

  # Output to JSON file
  python scripts/validate_against_gold_standard.py --all --output report.json
        """,
    )

    parser.add_argument(
        '--filing-id',
        type=int,
        help='Validate specific filing by database ID',
    )
    parser.add_argument(
        '--company',
        type=str,
        help='Validate by company name',
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Validate all filings with gold standard entries',
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Write detailed report to file (JSON or CSV)',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show per-candidate match details',
    )
    parser.add_argument(
        '--gold-standard',
        type=str,
        default=str(GOLD_STANDARD_PATH),
        help=f'Path to gold standard CSV (default: {GOLD_STANDARD_PATH})',
    )
    parser.add_argument(
        '--database-url',
        type=str,
        help='Database connection string (defaults to DATABASE_URL from .env)',
    )

    args = parser.parse_args()

    # Validate arguments
    if not (args.filing_id or args.company or args.all):
        parser.error("Must specify --filing-id, --company, or --all")

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(message)s',
    )

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv('DATABASE_URL')

    if not db_url:
        print("Error: DATABASE_URL not set. Use --database-url or set DATABASE_URL in .env",
              file=sys.stderr)
        sys.exit(1)

    # Load gold standard
    gold_standard_path = Path(args.gold_standard)
    if not gold_standard_path.exists():
        print(f"Error: Gold standard file not found: {gold_standard_path}", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Loading gold standard from {gold_standard_path}...")
    gold_entries = load_gold_standard(gold_standard_path)
    logger.info(f"Loaded {len(gold_entries)} gold standard entries")

    # Get unique companies in gold standard
    companies = sorted(set(e.company for e in gold_entries))
    logger.info(f"Companies in gold standard: {', '.join(companies)}")

    # Connect to database
    from src.infra.db import DatabaseAdapter
    db = DatabaseAdapter(db_url)

    results: list[ValidationResult] = []

    if args.filing_id:
        # Validate specific filing
        filing = db.get_filing_with_company(args.filing_id)
        if not filing:
            print(f"Error: Filing {args.filing_id} not found", file=sys.stderr)
            sys.exit(1)

        company_name = filing['company_name']
        company_entries = get_entries_for_company(gold_entries, company_name)

        if not company_entries:
            print(f"Warning: No gold standard entries for company '{company_name}'")

        result = validate_filing(db, args.filing_id, company_name, company_entries, args.verbose)
        results.append(result)

    elif args.company:
        # Validate by company name
        company_entries = get_entries_for_company(gold_entries, args.company)

        if not company_entries:
            print(f"Error: No gold standard entries for company '{args.company}'", file=sys.stderr)
            sys.exit(1)

        # Find filing in database
        query = """
            SELECT f.filing_id, c.company_name
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE LOWER(c.company_name) = LOWER(%(company)s)
            LIMIT 1
        """
        filing_rows = db.query(query, {'company': args.company})

        filing_id = filing_rows[0]['filing_id'] if filing_rows else None

        result = validate_filing(db, filing_id, args.company, company_entries, args.verbose)
        results.append(result)

    elif args.all:
        # Validate all companies in gold standard
        for company in companies:
            company_entries = get_entries_for_company(gold_entries, company)

            # Find filing in database
            query = """
                SELECT f.filing_id, c.company_name
                FROM filings f
                JOIN companies c ON f.company_id = c.company_id
                WHERE LOWER(c.company_name) = LOWER(%(company)s)
                LIMIT 1
            """
            filing_rows = db.query(query, {'company': company})

            filing_id = filing_rows[0]['filing_id'] if filing_rows else None

            result = validate_filing(db, filing_id, company, company_entries, args.verbose)
            results.append(result)

    # Print reports
    for result in results:
        print_validation_report(result, args.verbose)

    # Print summary if multiple filings
    if len(results) > 1:
        total_tp = sum(r.true_positives for r in results)
        total_fp = sum(r.false_positives for r in results)
        total_fn = sum(r.false_negatives for r in results)

        overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        overall_f1 = 2 * (overall_precision * overall_recall) / (overall_precision + overall_recall) if (overall_precision + overall_recall) > 0 else 0

        print('\n' + '=' * 60)
        print('OVERALL SUMMARY')
        print('=' * 60)
        print(f"Filings validated: {len(results)}")
        print(f"Total Gold Standard: {sum(r.gold_standard_count for r in results)}")
        print(f"Total Candidates: {sum(r.candidate_count for r in results)}")
        print(f"\nAggregate Metrics:")
        print(f"  True Positives:  {total_tp}")
        print(f"  False Positives: {total_fp}")
        print(f"  False Negatives: {total_fn}")
        print(f"  Precision:       {overall_precision * 100:.1f}%")
        print(f"  Recall:          {overall_recall * 100:.1f}%")
        print(f"  F1 Score:        {overall_f1 * 100:.1f}%")

    # Write output file if specified
    if args.output:
        output_path = Path(args.output)
        output_data = {
            'results': [result_to_dict(r) for r in results],
            'summary': {
                'filings_validated': len(results),
                'total_gold_standard': sum(r.gold_standard_count for r in results),
                'total_candidates': sum(r.candidate_count for r in results),
                'total_true_positives': sum(r.true_positives for r in results),
                'total_false_positives': sum(r.false_positives for r in results),
                'total_false_negatives': sum(r.false_negatives for r in results),
            }
        }

        if output_path.suffix == '.json':
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)
        elif output_path.suffix == '.csv':
            with open(output_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'company_name', 'filing_id', 'gold_standard_count', 'candidate_count',
                    'true_positives', 'false_positives', 'false_negatives',
                    'precision', 'recall', 'f1_score',
                ])
                writer.writeheader()
                for r in results:
                    writer.writerow({
                        'company_name': r.company_name,
                        'filing_id': r.filing_id,
                        'gold_standard_count': r.gold_standard_count,
                        'candidate_count': r.candidate_count,
                        'true_positives': r.true_positives,
                        'false_positives': r.false_positives,
                        'false_negatives': r.false_negatives,
                        'precision': f"{r.precision:.4f}",
                        'recall': f"{r.recall:.4f}",
                        'f1_score': f"{r.f1_score:.4f}",
                    })
        else:
            # Default to JSON
            with open(output_path, 'w') as f:
                json.dump(output_data, f, indent=2)

        logger.info(f"\nReport written to {output_path}")


if __name__ == '__main__':
    main()
