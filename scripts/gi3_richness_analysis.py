#!/usr/bin/env python3
"""
GI-3: Richness Score Distribution Analysis

Analyzes the distribution of richness scores across the 6 validation filings
to understand why scores are low and identify calibration needs.

Usage:
    DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
      python3 scripts/gi3_richness_analysis.py
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent


def prepare_environment() -> None:
    """Load .env configuration and ensure src imports work."""
    load_dotenv()
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


if TYPE_CHECKING:
    from src.infra.db import DatabaseAdapter

# Filing ID to Company Name mapping
# Note: IDs 31/33 were incorrect (RLX Technology/Vodka Brands due to CIK mismatch)
# IDs 39/40 are the real Snowflake/DocuSign filings downloaded via SEC API (2024-12)
FILING_MAP = {
    29: "Farfetch Ltd",
    32: "Snap",
    34: "SUSHI GINZA ONODERA",
    35: "Slack Technologies",
    39: "Snowflake Inc",      # Real Snowflake S-1/A (CIK 0001640147, 2020-09-14)
    40: "DocuSign Inc",       # Real DocuSign S-1 (CIK 0001261333, 2018-09-11)
}

VALIDATION_FILING_IDS = (29, 32, 34, 35, 39, 40)


@dataclass
class SegmentData:
    """Data for a single segment."""

    filing_id: int
    company_name: str
    segment_id: int
    richness_score: float
    classifier_confidence: float | None
    distinct_metric_count: int | None
    contains_temporal_trend: bool
    contains_cohort_breakdown: bool
    contains_definition_flag: bool
    image_count: int | None


def fetch_segment_data(db: DatabaseAdapter) -> list[SegmentData]:
    """Fetch all segment data for validation filings."""
    # Use ANY with array parameter for psycopg3 compatibility
    query = """
    SELECT
        f.filing_id,
        c.company_name,
        ss.source_segment_id,
        ss.richness_score,
        ss.classifier_confidence,
        ss.distinct_metric_count,
        ss.contains_temporal_trend,
        ss.contains_cohort_breakdown,
        ss.contains_definition_flag,
        ss.image_count
    FROM source_segments ss
    JOIN filings f ON ss.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    WHERE f.filing_id = ANY(%(filing_ids)s)
    ORDER BY f.filing_id, ss.richness_score DESC;
    """

    rows = db.query(query, {"filing_ids": list(VALIDATION_FILING_IDS)})

    segments = []
    for row in rows:
        segments.append(
            SegmentData(
                filing_id=row["filing_id"],
                company_name=row["company_name"],
                segment_id=row["source_segment_id"],
                richness_score=float(row["richness_score"] or 0),
                classifier_confidence=float(row["classifier_confidence"])
                if row["classifier_confidence"]
                else None,
                distinct_metric_count=row["distinct_metric_count"],
                contains_temporal_trend=bool(row["contains_temporal_trend"]),
                contains_cohort_breakdown=bool(row["contains_cohort_breakdown"]),
                contains_definition_flag=bool(row["contains_definition_flag"]),
                image_count=row["image_count"],
            )
        )

    return segments


def calculate_percentiles(values: list[float]) -> dict[str, float]:
    """Calculate percentiles for a list of values."""
    if not values:
        return {}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def percentile(p: float) -> float:
        idx = (n - 1) * p / 100
        lower = int(idx)
        upper = lower + 1
        if upper >= n:
            return sorted_vals[-1]
        weight = idx - lower
        return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight

    return {
        "min": sorted_vals[0],
        "p25": percentile(25),
        "median": percentile(50),
        "p75": percentile(75),
        "p90": percentile(90),
        "p95": percentile(95),
        "p99": percentile(99),
        "max": sorted_vals[-1],
        "mean": sum(sorted_vals) / n,
        "std": (sum((x - sum(sorted_vals) / n) ** 2 for x in sorted_vals) / n) ** 0.5,
    }


def create_histogram(values: list[float], bins: int = 10) -> dict[str, int]:
    """Create histogram bins for score distribution."""
    hist = defaultdict(int)
    for v in values:
        bin_idx = min(int(v), bins - 1)
        hist[bin_idx] += 1
    return dict(hist)


def analyze_boolean_flags(segments: list[SegmentData]) -> dict[str, dict]:
    """Analyze boolean flag distributions."""
    total = len(segments)
    if total == 0:
        return {}

    flags = {
        "contains_temporal_trend": sum(1 for s in segments if s.contains_temporal_trend),
        "contains_cohort_breakdown": sum(
            1 for s in segments if s.contains_cohort_breakdown
        ),
        "contains_definition_flag": sum(
            1 for s in segments if s.contains_definition_flag
        ),
    }

    return {
        name: {"count": count, "pct": count / total * 100, "contribution": contrib}
        for name, count, contrib in [
            ("temporal_trend", flags["contains_temporal_trend"], 1.0),
            ("cohort_breakdown", flags["contains_cohort_breakdown"], 1.5),
            ("definition_flag", flags["contains_definition_flag"], 1.0),
        ]
    }


def analyze_numeric_components(segments: list[SegmentData]) -> dict[str, dict]:
    """Analyze numeric component distributions."""
    results = {}

    # Classifier confidence
    confidence_vals = [s.classifier_confidence for s in segments if s.classifier_confidence is not None]
    if confidence_vals:
        stats = calculate_percentiles(confidence_vals)
        results["classifier_confidence"] = {
            "mean": stats["mean"],
            "median": stats["median"],
            "max": stats["max"],
            "contribution_formula": "confidence * 3.0",
            "max_contribution": 3.0,
        }

    # Metric count
    metric_vals = [s.distinct_metric_count or 0 for s in segments]
    if metric_vals:
        stats = calculate_percentiles([float(v) for v in metric_vals])
        results["distinct_metric_count"] = {
            "mean": stats["mean"],
            "median": stats["median"],
            "max": stats["max"],
            "contribution_formula": "min(count * 0.5, 2.0)",
            "max_contribution": 2.0,
        }

    # Image count
    image_vals = [s.image_count or 0 for s in segments]
    if image_vals:
        stats = calculate_percentiles([float(v) for v in image_vals])
        results["image_count"] = {
            "mean": stats["mean"],
            "median": stats["median"],
            "max": stats["max"],
            "contribution_formula": "min(count * 0.5, 1.5)",
            "max_contribution": 1.5,
        }

    return results


def print_histogram_visual(hist: dict[str, int], max_width: int = 40) -> None:
    """Print a visual histogram."""
    max_count = max(hist.values()) if hist else 1

    print("\n### Score Distribution Histogram\n")
    print("```")
    print(f"{'Score Range':<12} | {'Count':>6} | Visual")
    print("-" * 60)

    for i in range(10):
        count = hist.get(i, 0)
        bar_width = int(count / max_count * max_width) if max_count > 0 else 0
        bar = "█" * bar_width
        print(f"{i:.1f} - {i+1:.1f}     | {count:>6} | {bar}")

    print("```")


def print_per_filing_stats(segments: list[SegmentData]) -> None:
    """Print per-filing statistics."""
    # Group by filing
    by_filing: dict[int, list[SegmentData]] = defaultdict(list)
    for s in segments:
        by_filing[s.filing_id].append(s)

    print("\n### Per-Filing Statistics\n")
    print("| Filing | Company | Segments | Mean | Median | Max | P95 | P99 |")
    print("|--------|---------|----------|------|--------|-----|-----|-----|")

    for filing_id in VALIDATION_FILING_IDS:
        filing_segments = by_filing.get(filing_id, [])
        if not filing_segments:
            company = FILING_MAP.get(filing_id, "Unknown")
            print(f"| {filing_id} | {company} | 0 | - | - | - | - | - |")
            continue

        company = filing_segments[0].company_name
        scores = [s.richness_score for s in filing_segments]
        stats = calculate_percentiles(scores)

        print(
            f"| {filing_id} | {company[:15]} | {len(scores)} | "
            f"{stats['mean']:.2f} | {stats['median']:.2f} | "
            f"{stats['max']:.2f} | {stats['p95']:.2f} | {stats['p99']:.2f} |"
        )


def print_boolean_flags(flag_stats: dict[str, dict]) -> None:
    """Print boolean flag analysis."""
    print("\n### Boolean Flag Analysis\n")
    print("| Component | % TRUE | Count | Max Contribution | Bottleneck? |")
    print("|-----------|--------|-------|------------------|-------------|")

    for name, stats in flag_stats.items():
        bottleneck = "**YES**" if stats["pct"] < 5 else "No"
        if name == "cohort_breakdown":
            bottleneck = "**CRITICAL (0%)**" if stats["pct"] == 0 else bottleneck
        print(
            f"| {name} | {stats['pct']:.1f}% | {stats['count']} | "
            f"+{stats['contribution']:.1f} | {bottleneck} |"
        )


def print_numeric_components(numeric_stats: dict[str, dict]) -> None:
    """Print numeric component analysis."""
    print("\n### Numeric Component Analysis\n")
    print("| Component | Mean | Median | Max | Contribution Formula | Max Contrib |")
    print("|-----------|------|--------|-----|---------------------|-------------|")

    for name, stats in numeric_stats.items():
        print(
            f"| {name} | {stats['mean']:.2f} | {stats['median']:.2f} | "
            f"{stats['max']:.2f} | {stats['contribution_formula']} | {stats['max_contribution']:.1f} |"
        )


def calculate_theoretical_max() -> float:
    """Calculate theoretical maximum score based on formula."""
    return 3.0 + 2.0 + 1.0 + 1.5 + 1.0 + 1.5  # = 10.0


def print_theoretical_vs_observed(segments: list[SegmentData]) -> None:
    """Print comparison of theoretical vs observed max."""
    scores = [s.richness_score for s in segments]
    observed_max = max(scores) if scores else 0

    cohort_detected = any(s.contains_cohort_breakdown for s in segments)
    achievable_max = 10.0 if cohort_detected else 8.5  # Without cohort bonus

    print("\n## Theoretical vs Observed Maximum\n")
    print("| Metric | Value |")
    print("|--------|-------|")
    print("| Theoretical max (formula allows) | 10.0 |")
    print("| Achievable max (without cohort) | 8.5 |")
    print(f"| Observed max (in data) | {observed_max:.2f} |")
    print(f"| Gap from theoretical | {10.0 - observed_max:.2f} points |")
    print(f"| Gap from achievable | {achievable_max - observed_max:.2f} points |")


def analyze_slack_ground_truth(segments: list[SegmentData]) -> None:
    """Cross-reference Slack segments with GI-2 ground truth."""
    slack_segments = [s for s in segments if s.filing_id == 35]

    if not slack_segments:
        print("\n## Slack Ground Truth Analysis\n")
        print("No Slack segments found in data.")
        return

    # Sort by richness score descending
    slack_segments.sort(key=lambda s: s.richness_score, reverse=True)

    print("\n## Ground Truth Comparison (Slack - filing_id=35)\n")
    print(
        "From GI-2: 25 goldmines identified, system detects 1 at threshold 6.0 (4% recall)\n"
    )

    # Threshold analysis
    thresholds = [4.0, 5.0, 5.5, 6.0, 7.0, 8.0]
    print("### Detection by Threshold\n")
    print("| Threshold | Segments Above | % of Total |")
    print("|-----------|----------------|------------|")
    for thresh in thresholds:
        count = sum(1 for s in slack_segments if s.richness_score >= thresh)
        pct = count / len(slack_segments) * 100
        print(f"| {thresh:.1f} | {count} | {pct:.1f}% |")

    # Top segments
    print("\n### Top 10 Slack Segments by Richness\n")
    print(
        "| Rank | Seg ID | Score | Conf | Metrics | Temporal | Cohort | Definition | Images |"
    )
    print(
        "|------|--------|-------|------|---------|----------|--------|------------|--------|"
    )

    for i, s in enumerate(slack_segments[:10], 1):
        conf = f"{s.classifier_confidence:.2f}" if s.classifier_confidence else "-"
        metrics = s.distinct_metric_count or 0
        temporal = "✓" if s.contains_temporal_trend else "-"
        cohort = "✓" if s.contains_cohort_breakdown else "-"
        defn = "✓" if s.contains_definition_flag else "-"
        images = s.image_count or 0

        print(
            f"| {i} | {s.segment_id} | {s.richness_score:.2f} | {conf} | "
            f"{metrics} | {temporal} | {cohort} | {defn} | {images} |"
        )

    # Component breakdown for Slack
    print("\n### Slack Component Analysis\n")
    flag_stats = analyze_boolean_flags(slack_segments)
    print("| Component | % TRUE | Contribution when TRUE |")
    print("|-----------|--------|------------------------|")
    for name, stats in flag_stats.items():
        print(f"| {name} | {stats['pct']:.1f}% | +{stats['contribution']:.1f} |")


def print_score_breakdown(segments: list[SegmentData]) -> None:
    """Print breakdown of scores by tier."""
    total = len(segments)

    tiers = {
        "Below 2.0": sum(1 for s in segments if s.richness_score < 2.0),
        "2.0 - 3.99": sum(
            1 for s in segments if 2.0 <= s.richness_score < 4.0
        ),
        "4.0 - 5.99": sum(
            1 for s in segments if 4.0 <= s.richness_score < 6.0
        ),
        "6.0 - 7.99 (Goldmine)": sum(
            1 for s in segments if 6.0 <= s.richness_score < 8.0
        ),
        "8.0+ (High-Value)": sum(1 for s in segments if s.richness_score >= 8.0),
    }

    print("\n### Score Tier Distribution\n")
    print("| Tier | Count | % of Total |")
    print("|------|-------|------------|")
    for tier, count in tiers.items():
        pct = count / total * 100 if total > 0 else 0
        print(f"| {tier} | {count} | {pct:.1f}% |")


def print_recommendations() -> None:
    """Print data-driven recommendations based on analysis."""
    print("\n## Weight Adjustment Recommendations for GI-6\n")

    recommendations = [
        {
            "title": "Add retention metric keyword bonus",
            "current": "No explicit NRR/retention boost in richness formula",
            "proposed": "+1.0 if segment contains 'Net Dollar Retention' or 'dollar-based retention'",
            "rationale": (
                "GI-1 found 87 retention-related snippets. GI-2 shows NRR segments score 5.0-5.55 "
                "but should be 6.5+. Adding explicit retention keyword boost would move these above threshold."
            ),
            "impact": "Would increase NRR-related segment scores by ~1.0, moving 5.55→6.55",
        },
        {
            "title": "Implement cohort pattern detection fixes (GI-4 prerequisite)",
            "current": "+1.5 for cohort_breakdown but NEVER triggered (0% detection)",
            "proposed": "Add missing patterns: 'fiscal year XXXX cohort', 'ARR.*cohort', 'Net Dollar Retention'",
            "rationale": (
                "GI-1 confirms all 9 current cohort patterns have 100% miss rate. "
                "The +1.5 bonus is never applied, artificially capping achievable max at 8.5."
            ),
            "impact": "Would unlock +1.5 points for ~10% of segments, enabling scores to reach 8.5+",
        },
        {
            "title": "Increase definition bonus with metric context",
            "current": "+1.0 for definition_flag alone",
            "proposed": "+1.5 if (definition_flag AND distinct_metric_count >= 2)",
            "rationale": (
                "GI-2 shows definitions combined with metrics (e.g., DAU definition with 10M value) "
                "score only 3.90. These are high-value disclosures deserving higher scores."
            ),
            "impact": "Would affect definition segments with metrics, increasing their scores by 0.5",
        },
        {
            "title": "Add usage metric keyword bonus",
            "current": "No explicit DAU/MAU/engagement boost",
            "proposed": "+0.5 if segment contains 'daily active users', 'monthly active users', or 'engagement'",
            "rationale": (
                "GI-2 shows Slack's '10 million daily active users' segment scores 3.90. "
                "Usage metrics are core customer metrics and deserve explicit boost."
            ),
            "impact": "Would increase usage-related segment scores by ~0.5",
        },
    ]

    for i, rec in enumerate(recommendations, 1):
        print(f"### Recommendation {i}: {rec['title']}\n")
        print(f"- **Current**: {rec['current']}")
        print(f"- **Proposed**: {rec['proposed']}")
        print(f"- **Rationale**: {rec['rationale']}")
        print(f"- **Expected Impact**: {rec['impact']}\n")

    print("## Threshold Recommendations\n")
    print("| Threshold | Current | Proposed | Rationale |")
    print("|-----------|---------|----------|-----------|")
    print(
        "| GOLDMINE_THRESHOLD | 6.0 | 5.5 | "
        "GI-2 shows 5.0 captures 5x more goldmines than 6.0 (20% vs 4% recall) |"
    )
    print(
        "| HIGH_VALUE_THRESHOLD | 8.0 | 7.5 | "
        "No segments reach 8.0; lowering enables meaningful high-value tier |"
    )


def main() -> None:
    """Main analysis function."""
    print("# GI-3: Richness Score Distribution Analysis\n")

    prepare_environment()

    from src.infra.db import DatabaseAdapter

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    db = DatabaseAdapter(db_url)
    segments = fetch_segment_data(db)

    if not segments:
        print("ERROR: No segments found for validation filings")
        sys.exit(1)

    print("## Executive Summary\n")
    print("- **Analysis date**: 2025-12-17")
    print(f"- **Total segments analyzed**: {len(segments)}")
    print(f"- **Filings analyzed**: {len(FILING_MAP)} (IDs: {', '.join(map(str, VALIDATION_FILING_IDS))})")

    # Overall stats
    scores = [s.richness_score for s in segments]
    overall_stats = calculate_percentiles(scores)

    print(f"- **Mean richness score**: {overall_stats['mean']:.2f}")
    print(f"- **Median richness score**: {overall_stats['median']:.2f}")
    print(f"- **Max richness score**: {overall_stats['max']:.2f}")
    print(f"- **Segments >= 6.0 (goldmine)**: {sum(1 for s in scores if s >= 6.0)}")
    print(f"- **Segments >= 8.0 (high-value)**: {sum(1 for s in scores if s >= 8.0)}")

    # Histogram
    hist = create_histogram(scores)
    print_histogram_visual(hist)

    # Score tiers
    print_score_breakdown(segments)

    # Per-filing stats
    print_per_filing_stats(segments)

    # Boolean flag analysis
    print("\n## Component Contribution Analysis")
    flag_stats = analyze_boolean_flags(segments)
    print_boolean_flags(flag_stats)

    # Numeric component analysis
    numeric_stats = analyze_numeric_components(segments)
    print_numeric_components(numeric_stats)

    # Theoretical vs observed
    print_theoretical_vs_observed(segments)

    # Slack ground truth
    analyze_slack_ground_truth(segments)

    # Recommendations
    print_recommendations()

    print("\n---\n")
    print("**Generated by**: `scripts/gi3_richness_analysis.py`")
    print("**Date**: 2025-12-17")
    print("**Task**: GI-3 (Analyze Richness Score Distribution)")


if __name__ == "__main__":
    main()
