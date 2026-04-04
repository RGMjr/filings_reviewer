#!/usr/bin/env python3
"""
V1 vs V2 vs Gold Standard Unified Comparison Tool.

Runs V1 and V2 extraction against the gold standard dataset and produces a
3-way comparison report showing per-pipeline P/R/F1, gains, regressions, and
the contribution of image extraction.

Usage:
    # Compare a single company (name must match gold standard CSV exactly)
    python3 scripts/compare_v1_v2_gold.py --company "Samsara Inc_"

    # Compare all gold standard companies (default)
    python3 scripts/compare_v1_v2_gold.py --all

    # Skip V2-text-only run (faster, no image contribution analysis)
    python3 scripts/compare_v1_v2_gold.py --all --skip-image-comparison

    # Write JSON output to a specific path
    python3 scripts/compare_v1_v2_gold.py --all --output reports/my_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.gold_standard.unified_comparison import UnifiedComparisonRunner  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare V1, V2-full, and V2-text-only extraction pipelines against "
            "the gold standard dataset and report P/R/F1 for each pipeline."
        )
    )

    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--company",
        metavar="NAME",
        type=str,
        default=None,
        help="Single company name to evaluate (must match gold standard CSV exactly).",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Evaluate all gold standard companies (default if nothing specified).",
    )

    parser.add_argument(
        "--skip-image-comparison",
        action="store_true",
        help=(
            "Skip the V2-text-only run. Faster, but image contribution analysis "
            "will not be available."
        ),
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.02,
        metavar="FLOAT",
        help="Fractional value tolerance for matching (default: 0.02 = 2%%).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help=("Path for JSON output (default: reports/unified_comparison_<timestamp>.json)."),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-company match details (gains, regressions, image gains).",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.50,
        metavar="FLOAT",
        help="Minimum V2 confidence threshold (default: 0.50).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Check for OpenAI API key
    skip_image = args.skip_image_comparison
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning(
            "OPENAI_API_KEY not set — V2 image extraction will be disabled. "
            "Use --skip-image-comparison to suppress this warning."
        )
        skip_image = True

    # Build output path
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = PROJECT_ROOT / "reports" / f"unified_comparison_{timestamp}.json"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve company filter
    companies: list[str] | None = None
    if args.company:
        companies = [args.company]
    # args.all or neither flag → companies=None (run all)

    logger.info(
        "Starting unified comparison | companies=%s | skip_image=%s | tolerance=%.2f | min_confidence=%.2f",
        args.company if args.company else "ALL",
        skip_image,
        args.tolerance,
        args.min_confidence,
    )

    try:
        runner = UnifiedComparisonRunner(
            value_tolerance=args.tolerance,
            skip_image_comparison=skip_image,
        )

        report = runner.run(companies=companies)
    except Exception as exc:
        logger.error("Comparison failed: %s", exc, exc_info=True)
        return 1

    # Terminal summary
    report.print_summary()

    # Verbose per-company detail
    if args.verbose:
        print("\nPER-COMPANY DETAIL")
        print("=" * 70)
        for cc in report.companies:
            print(f"\n{cc.company_name}")
            print(f"  Gold entries:  {len(cc.gold_entries)}")
            print(
                f"  V1  F1: {cc.v1_scores.f1:.1%}  (P={cc.v1_scores.precision:.1%}  R={cc.v1_scores.recall:.1%})"
            )
            print(
                f"  V2-full F1: {cc.v2_full_scores.f1:.1%}  (P={cc.v2_full_scores.precision:.1%}  R={cc.v2_full_scores.recall:.1%})"
            )
            if cc.v2_text_only_scores is not None:
                print(
                    f"  V2-text F1: {cc.v2_text_only_scores.f1:.1%}  "
                    f"(P={cc.v2_text_only_scores.precision:.1%}  "
                    f"R={cc.v2_text_only_scores.recall:.1%})"
                )
            else:
                print("  V2-text F1: N/A")
            if cc.v2_gains:
                gain_ids = ", ".join(e.metric_id for e in cc.v2_gains)
                print(f"  V2 gains ({len(cc.v2_gains)}): {gain_ids}")
            if cc.v2_regressions:
                regr_ids = ", ".join(e.metric_id for e in cc.v2_regressions)
                print(f"  V2 regressions ({len(cc.v2_regressions)}): {regr_ids}")
            if cc.image_gains:
                img_ids = ", ".join(e.metric_id for e in cc.image_gains)
                print(f"  Image gains ({len(cc.image_gains)}): {img_ids}")

    # Save JSON report
    try:
        report_dict = report.to_dict()
        output_path.write_text(json.dumps(report_dict, indent=2, default=str))
        print(f"\nReport saved to: {output_path}")
    except Exception as exc:
        logger.error("Failed to write JSON report to %s: %s", output_path, exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
