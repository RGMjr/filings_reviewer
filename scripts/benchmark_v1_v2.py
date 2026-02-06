#!/usr/bin/env python3
"""
Benchmark V1 vs V2 extraction pipelines.

Compares execution time, fact counts, and quality metrics between
the V1 and V2 extraction pipelines on gold standard filings.

Usage:
    python scripts/benchmark_v1_v2.py --filings slack samsara
    python scripts/benchmark_v1_v2.py --filings slack --output reports/v2_benchmark.md

Output:
    Markdown report with comparison tables and metrics.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction_v2.comparison import (  # noqa: E402
    BatchComparisonResult,
    V1V2Comparator,
)
from src.extraction_v2.pipeline import PipelineConfig  # noqa: E402

if TYPE_CHECKING:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Gold standard filing paths
GOLD_STANDARD_DIR = PROJECT_ROOT / "data" / "gold_standard"
KNOWN_FILINGS = {
    "slack": (1, GOLD_STANDARD_DIR / "Slack_Technologies" / "filing.html", 1),
    "samsara": (2, GOLD_STANDARD_DIR / "Samsara_Vision_Inc_" / "filing.html", 2),
}


def _resolve_filings(filing_names: list[str]) -> list[tuple[int, Path, int]]:
    """Resolve filing names to (filing_id, path, company_id) tuples."""
    filings = []
    for name in filing_names:
        name_lower = name.lower()
        if name_lower in KNOWN_FILINGS:
            filing_id, path, company_id = KNOWN_FILINGS[name_lower]
            if not path.exists():
                logger.warning(f"Filing not found: {path}")
                continue
            filings.append((filing_id, path, company_id))
        else:
            logger.warning(f"Unknown filing: {name}. Known filings: {list(KNOWN_FILINGS.keys())}")
    return filings


def run_benchmark(
    filing_names: list[str],
    output_path: Path | None = None,
    verbose: bool = False,
    persist_v2: bool = False,
) -> BatchComparisonResult:
    """
    Run benchmark comparison on specified filings.

    Args:
        filing_names: List of filing names (e.g., ["slack", "samsara"])
        output_path: Optional path to save markdown report
        verbose: Enable verbose logging
        persist_v2: If True, persist V2 results to database after comparison

    Returns:
        BatchComparisonResult with all comparison data
    """
    filings = _resolve_filings(filing_names)

    if not filings:
        logger.error("No valid filings to benchmark")
        sys.exit(1)

    logger.info(f"Benchmarking {len(filings)} filing(s)...")

    # Configure V2 pipeline
    config = PipelineConfig(
        enable_image_extraction=True,
        enable_chart_extraction=True,
    )

    # Run comparison
    comparator = V1V2Comparator(v2_config=config, value_tolerance=0.02)
    batch_result = comparator.compare_batch(filings)

    # Generate report
    report = generate_markdown_report(batch_result, filing_names)

    # Output
    print("\n" + "=" * 80)
    print(report)
    print("=" * 80)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
        logger.info(f"Report saved to {output_path}")

    # Persist V2 results if requested
    if persist_v2:
        _persist_v2_results(filings, config)

    return batch_result


def _persist_v2_results(
    filings: list[tuple[int, Path, int]],
    config: PipelineConfig,
) -> None:
    """
    Re-run V2 pipeline and persist results to database.

    This is separate from the comparison run because V1V2Comparator
    doesn't expose the raw PipelineResult needed for persistence.
    The V2 pipeline is deterministic, so re-running produces identical facts.
    """
    import os

    from dotenv import load_dotenv

    from src.extraction_v2.persistence import V2PersistenceAdapter
    from src.extraction_v2.pipeline import V2Pipeline
    from src.infra.db import DatabaseAdapter

    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set — cannot persist V2 results")
        return

    db = DatabaseAdapter(database_url)
    adapter = V2PersistenceAdapter(db)
    pipeline = V2Pipeline(config=config)

    for filing_id, html_path, _company_id in filings:
        logger.info(f"Persisting V2 results for filing_id={filing_id}...")
        try:
            result = pipeline.process(html_path=html_path, filing_id=filing_id)
            if result.success:
                persist_result = adapter.persist_pipeline_result(result, filing_id)
                logger.info(
                    f"  Persisted: {persist_result.facts_upserted} facts, "
                    f"{persist_result.segments_upserted} segments, "
                    f"{persist_result.tables_upserted} tables"
                )
            else:
                logger.error(f"  V2 pipeline failed: {result.error_message}")
        except Exception as e:
            logger.error(f"  Error persisting filing {filing_id}: {e}")


def generate_markdown_report(
    batch_result: BatchComparisonResult,
    filing_names: list[str],
) -> str:
    """Generate markdown report from comparison results."""
    lines = [
        "# V1 vs V2 Extraction Pipeline Benchmark",
        "",
        f"**Generated**: {datetime.now().isoformat()}",
        "",
        "## Summary",
        "",
        f"- **Filings Tested**: {len(batch_result.results)}",
        f"- **Total V1 Facts**: {batch_result.total_v1_facts}",
        f"- **Total V2 Facts**: {batch_result.total_v2_facts}",
        f"- **Overall Coverage**: {batch_result.overall_coverage:.1%}",
        f"- **Total V1 Time**: {batch_result.total_v1_time_ms:,}ms",
        f"- **Total V2 Time**: {batch_result.total_v2_time_ms:,}ms",
        f"- **Overall Speedup**: {batch_result.overall_speedup:.2f}x",
        "",
        "## Per-Filing Results",
        "",
        "| Filing | V1 Facts | V2 Facts | Match | V1-Only | V2-Only | V1 Time | V2 Time | Speedup |",
        "|--------|----------|----------|-------|---------|---------|---------|---------|---------|",
    ]

    for i, result in enumerate(batch_result.results):
        name = filing_names[i] if i < len(filing_names) else f"Filing {result.filing_id}"
        speedup = f"{result.speedup_ratio:.2f}x" if result.v2_time_ms > 0 else "N/A"
        lines.append(
            f"| {name} | {result.v1_fact_count} | {result.v2_fact_count} | "
            f"{result.matching_facts} | {result.v1_only_facts} | {result.v2_only_facts} | "
            f"{result.v1_time_ms}ms | {result.v2_time_ms}ms | {speedup} |"
        )

    lines.extend([
        "",
        "## Metric Breakdown",
        "",
    ])

    # Aggregate metric breakdown
    all_metrics: dict[str, dict[str, int]] = {}
    for result in batch_result.results:
        for metric_id, breakdown in result.metrics_breakdown.items():
            if metric_id not in all_metrics:
                all_metrics[metric_id] = {
                    "v1_count": 0,
                    "v2_count": 0,
                    "matches": 0,
                    "v1_only": 0,
                    "v2_only": 0,
                }
            all_metrics[metric_id]["v1_count"] += breakdown.v1_count
            all_metrics[metric_id]["v2_count"] += breakdown.v2_count
            all_metrics[metric_id]["matches"] += breakdown.matches
            all_metrics[metric_id]["v1_only"] += breakdown.v1_only
            all_metrics[metric_id]["v2_only"] += breakdown.v2_only

    if all_metrics:
        lines.extend([
            "| Metric | V1 | V2 | Match | V1-Only | V2-Only | Coverage |",
            "|--------|----|----|-------|---------|---------|----------|",
        ])
        for metric_id, stats in sorted(all_metrics.items()):
            coverage = stats["matches"] / stats["v1_count"] if stats["v1_count"] > 0 else 1.0
            lines.append(
                f"| {metric_id} | {stats['v1_count']} | {stats['v2_count']} | "
                f"{stats['matches']} | {stats['v1_only']} | {stats['v2_only']} | "
                f"{coverage:.1%} |"
            )

    lines.extend([
        "",
        "## Analysis",
        "",
    ])

    # Analysis comments
    if batch_result.overall_coverage >= 0.90:
        lines.append("**Coverage**: Excellent - V2 captures 90%+ of V1 facts.")
    elif batch_result.overall_coverage >= 0.70:
        lines.append("**Coverage**: Good - V2 captures 70%+ of V1 facts.")
    else:
        lines.append("**Coverage**: Needs improvement - V2 captures <70% of V1 facts.")

    if batch_result.overall_speedup > 1.5:
        lines.append(f"**Performance**: V2 is {batch_result.overall_speedup:.1f}x faster than V1.")
    elif batch_result.overall_speedup > 1.0:
        lines.append(f"**Performance**: V2 is slightly faster ({batch_result.overall_speedup:.2f}x).")
    else:
        lines.append(f"**Performance**: V2 is slower ({1/batch_result.overall_speedup:.2f}x slower).")

    v2_discoveries = batch_result.total_v2_facts - batch_result.total_matching
    if v2_discoveries > 0:
        lines.append(f"**New Discoveries**: V2 found {v2_discoveries} additional facts not in V1.")

    lines.extend([
        "",
        "## Errors",
        "",
    ])

    errors = []
    for result in batch_result.results:
        if result.v1_error:
            errors.append(f"- V1 error on filing {result.filing_id}: {result.v1_error}")
        if result.v2_error:
            errors.append(f"- V2 error on filing {result.filing_id}: {result.v2_error}")

    if errors:
        lines.extend(errors)
    else:
        lines.append("No errors encountered.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark V1 vs V2 extraction pipelines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Benchmark both gold standard filings
    python scripts/benchmark_v1_v2.py --filings slack samsara

    # Benchmark single filing with output
    python scripts/benchmark_v1_v2.py --filings slack --output reports/v2_benchmark.md

    # List available filings
    python scripts/benchmark_v1_v2.py --list
        """,
    )
    parser.add_argument(
        "--filings",
        nargs="+",
        default=["slack", "samsara"],
        help="Filing names to benchmark (default: slack samsara)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output path for markdown report",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--persist-v2",
        action="store_true",
        help="Persist V2 extraction results to database (requires DATABASE_URL)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available filings and exit",
    )

    args = parser.parse_args()

    if args.list:
        print("Available filings:")
        for name, (_filing_id, path, _company_id) in KNOWN_FILINGS.items():
            exists = "✓" if path.exists() else "✗"
            print(f"  {exists} {name}: {path}")
        return

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    batch_result = run_benchmark(
        filing_names=args.filings,
        output_path=args.output,
        verbose=args.verbose,
        persist_v2=args.persist_v2,
    )

    # Exit with error if coverage is below threshold
    if batch_result.overall_coverage < 0.70:
        logger.warning(f"Coverage {batch_result.overall_coverage:.1%} is below 70% threshold")
        sys.exit(1)


if __name__ == "__main__":
    main()
