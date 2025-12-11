#!/usr/bin/env python3
"""
Example script demonstrating Pattern Analyzer (E1) usage.

This script shows the complete workflow for:
1. Analyzing review decisions to identify important features
2. Discovering high-precision patterns from decisions
3. Saving patterns to the database with optional auto-approval

Usage:
    # Analyze all filings
    python scripts/analyze_review_patterns.py

    # Analyze specific filing
    python scripts/analyze_review_patterns.py --filing-id 123

    # Analyze specific metric
    python scripts/analyze_review_patterns.py --metric-id annual_recurring_revenue

    # Auto-approve high-precision patterns
    python scripts/analyze_review_patterns.py --auto-approve 0.90

Requirements:
    - DATABASE_URL environment variable set
    - Review schema applied (sql/07_create_review_schema.sql)
    - Review decisions exist in database
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.review.pattern_analyzer import PatternAnalyzer
from src.infra.logging_config import configure_logging


def format_feature_importance(features: list, feature_type: str) -> str:
    """Format feature importance results for display."""
    if not features:
        return f"  No significant {feature_type} features found.\n"

    lines = [f"\n  Top {feature_type.capitalize()} Features:"]
    lines.append("  " + "=" * 70)

    for i, feat in enumerate(features[:5], 1):  # Top 5
        name = feat["feature_name"]

        if feature_type == "categorical":
            chi2 = feat["chi_squared"]
            df = feat["degrees_of_freedom"]
            lines.append(f"  {i}. {name:30s} χ²={chi2:8.2f} (df={df})")

            # Show value distribution
            lines.append("     Value distribution:")
            for value, count in feat["value_distribution"].items():
                lines.append(f"       {value}: {count} instances")
        else:  # numeric
            effect = feat["effect_size"]
            mean_diff = feat["mean_difference"]
            lines.append(f"  {i}. {name:30s} Cohen's d={effect:6.2f} (Δμ={mean_diff:8.2f})")

            # Show mean by decision
            lines.append("     Mean by decision:")
            for decision, mean_val in feat["mean_by_decision"].items():
                lines.append(f"       {decision}: {mean_val:.2f}")

    return "\n".join(lines) + "\n"


def format_pattern(pattern, index: int) -> str:
    """Format a single pattern for display."""
    lines = [
        f"\n  Pattern #{index}:",
        f"    Name: {pattern.pattern_name}",
        f"    Type: {pattern.pattern_type}",
        f"    Precision: {pattern.precision_score:.3f}",
        f"    Recall: {pattern.recall_score:.3f}",
        f"    F1 Score: {pattern.f1_score:.3f}",
        f"    Support: {pattern.sample_count} instances",
    ]

    if pattern.metric_id:
        lines.append(f"    Metric: {pattern.metric_id}")

    # Show conditions
    lines.append("    Conditions:")
    for cond in pattern.pattern_definition["conditions"]:
        field = cond["field"]
        op = cond["op"]
        value = cond["value"]
        lines.append(f"      - {field} {op} {value}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze review decisions and discover patterns (E1 - Pattern Analyzer)"
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        help="Analyze decisions for specific filing only",
    )
    parser.add_argument(
        "--metric-id",
        type=str,
        help="Analyze decisions for specific metric only",
    )
    parser.add_argument(
        "--pattern-type",
        choices=["accept_rule", "reject_rule"],
        help="Generate only accept or reject patterns (default: both)",
    )
    parser.add_argument(
        "--min-precision",
        type=float,
        default=0.75,
        help="Minimum precision for patterns (default: 0.75)",
    )
    parser.add_argument(
        "--min-support",
        type=int,
        default=5,
        help="Minimum support (instances) for patterns (default: 5)",
    )
    parser.add_argument(
        "--auto-approve",
        type=float,
        help="Auto-approve patterns with precision >= this threshold (e.g., 0.90)",
    )
    parser.add_argument(
        "--save-patterns",
        action="store_true",
        help="Save discovered patterns to database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    configure_logging(level="DEBUG" if args.verbose else "INFO")
    logger = logging.getLogger(__name__)

    # Get database connection
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)

    # Initialize components
    logger.info("Initializing Pattern Analyzer...")
    db = DatabaseAdapter(database_url)
    analyzer = PatternAnalyzer(
        db,
        min_pattern_precision=args.min_precision,
        min_pattern_support=args.min_support,
    )

    # Step 1: Analyze decisions to find important features
    print("\n" + "=" * 80)
    print("STEP 1: Analyzing Review Decisions")
    print("=" * 80)

    analysis = analyzer.analyze_decisions(
        filing_id=args.filing_id,
        metric_id=args.metric_id,
    )

    print(f"\nTotal decisions analyzed: {analysis['total_decisions']}")
    print(f"Decision breakdown:")
    for decision, count in analysis["decision_counts"].items():
        print(f"  {decision}: {count}")

    # Check for warnings
    if analysis.get("warnings"):
        print("\nWarnings:")
        for warning in analysis["warnings"]:
            print(f"  ⚠️  {warning}")

    # Display categorical feature importance
    print(format_feature_importance(
        analysis["categorical_features"],
        "categorical"
    ))

    # Display numeric feature importance
    print(format_feature_importance(
        analysis["numeric_features"],
        "numeric"
    ))

    # Step 2: Discover patterns
    print("\n" + "=" * 80)
    print("STEP 2: Discovering High-Precision Patterns")
    print("=" * 80)

    patterns = analyzer.discover_patterns(
        filing_id=args.filing_id,
        metric_id=args.metric_id,
        pattern_type=args.pattern_type,
    )

    print(f"\nDiscovered {len(patterns)} patterns meeting criteria:")
    print(f"  Minimum precision: {args.min_precision}")
    print(f"  Minimum support: {args.min_support}")

    if not patterns:
        print("\n⚠️  No patterns found meeting the criteria.")
        print("   Try lowering --min-precision or --min-support thresholds.")
        return

    # Group patterns by type
    accept_patterns = [p for p in patterns if p.pattern_type == "accept_rule"]
    reject_patterns = [p for p in patterns if p.pattern_type == "reject_rule"]

    if accept_patterns:
        print(f"\n📈 Accept Patterns ({len(accept_patterns)}):")
        print("=" * 80)
        for i, pattern in enumerate(accept_patterns[:10], 1):  # Top 10
            print(format_pattern(pattern, i))

    if reject_patterns:
        print(f"\n📉 Reject Patterns ({len(reject_patterns)}):")
        print("=" * 80)
        for i, pattern in enumerate(reject_patterns[:10], 1):  # Top 10
            print(format_pattern(pattern, i))

    # Step 3: Save patterns (optional)
    if args.save_patterns:
        print("\n" + "=" * 80)
        print("STEP 3: Saving Patterns to Database")
        print("=" * 80)

        results = analyzer.save_patterns(
            patterns,
            auto_approve_threshold=args.auto_approve,
        )

        print(f"\n✅ Saved {results['saved_count']} patterns:")
        print(f"   - Auto-approved: {results['approved_count']}")
        print(f"   - Candidates: {results['candidate_count']}")

        if args.auto_approve:
            print(f"\n   Patterns with precision >= {args.auto_approve} were auto-approved.")
    else:
        print("\n" + "=" * 80)
        print("💡 Tip: Use --save-patterns to persist these patterns to the database")
        print("=" * 80)

    print("\n✨ Analysis complete!\n")


if __name__ == "__main__":
    main()
