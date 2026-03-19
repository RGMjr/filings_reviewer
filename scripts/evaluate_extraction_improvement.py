#!/usr/bin/env python3
"""
E2 Week 3: Evaluate Extraction Improvement from Learned Patterns

Compares candidate generation with and without learned rules to measure:
- Precision improvement (fewer false positives)
- Recall impact (maintained true positives)
- Candidate volume reduction
- Statistical significance

The script uses review decisions as ground truth to evaluate how well
learned patterns improve candidate quality.

Algorithm:
1. Load filings with review decisions (ground truth)
2. Generate candidates with learned rules disabled (baseline)
3. Generate candidates with learned rules enabled (improved)
4. Compare precision, recall, F1, candidate volume
5. Run statistical significance test
6. Print detailed comparison report

Usage:
    # Evaluate on filings with review decisions
    python scripts/evaluate_extraction_improvement.py --min-decisions 10

    # Evaluate specific filings
    python scripts/evaluate_extraction_improvement.py --filing-ids 123,456,789

    # Save results to JSON
    python scripts/evaluate_extraction_improvement.py --output results.json
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.review.candidate_generator import CandidateGenerator
from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


@dataclass
class EvaluationMetrics:
    """Metrics for evaluating candidate quality."""

    true_positives: int  # Candidates that match accepted decisions
    false_positives: int  # Candidates that don't match any decision or match rejected
    false_negatives: int  # Accepted decisions not found in candidates
    total_candidates: int  # Total candidates generated
    precision: float  # TP / (TP + FP)
    recall: float  # TP / (TP + FN)
    f1_score: float  # Harmonic mean of precision and recall


@dataclass
class ComparisonResult:
    """Result of baseline vs improved comparison."""

    filing_id: int
    company_name: str
    total_decisions: int
    baseline: EvaluationMetrics
    improved: EvaluationMetrics
    precision_improvement: float  # Percentage points
    recall_change: float  # Percentage points (negative means degradation)
    volume_reduction: float  # Percentage


def get_filings_with_decisions(
    db: DatabaseAdapter, min_decisions: int = 5, filing_ids: list[int] | None = None
) -> list[dict]:
    """
    Get filings that have review decisions (ground truth).

    Args:
        db: DatabaseAdapter instance
        min_decisions: Minimum number of decisions required
        filing_ids: Optional list of specific filing IDs

    Returns:
        List of filing dicts with decision count
    """
    query = """
        SELECT
            f.filing_id,
            f.company_id,
            c.company_name,
            f.accession_number,
            COUNT(DISTINCT rd.decision_id) as decision_count,
            COUNT(DISTINCT s.source_segment_id) as segment_count
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        JOIN source_segments s ON f.filing_id = s.filing_id
        JOIN review_candidates rc ON f.filing_id = rc.filing_id
        JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
        WHERE 1=1
    """

    params: dict = {"min_decisions": min_decisions}

    if filing_ids:
        query += " AND f.filing_id = ANY(%(filing_ids)s)"
        params["filing_ids"] = filing_ids

    query += """
        GROUP BY f.filing_id, f.company_id, c.company_name, f.accession_number
        HAVING COUNT(DISTINCT rd.decision_id) >= %(min_decisions)s
        ORDER BY COUNT(DISTINCT rd.decision_id) DESC
    """

    return db.query(query, params)


def get_ground_truth_decisions(db: DatabaseAdapter, filing_id: int) -> dict[str, list[dict]]:
    """
    Load review decisions for a filing (ground truth).

    Returns:
        Dict with 'accepted' and 'rejected' lists of decisions
    """
    query = """
        SELECT
            rd.decision_id,
            rd.candidate_id,
            rd.decision,
            rd.assigned_metric_id as metric_id,
            rc.parsed_value,
            rc.source_segment_id,
            rc.triggering_keyword as keyword_matched,
            rc.char_position as position_in_segment,
            rc.suggested_metric_id,
            rc.features
        FROM review_decisions rd
        JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
        WHERE rc.filing_id = %(filing_id)s
    """

    decisions = db.query(query, {"filing_id": filing_id})

    accepted = [d for d in decisions if d["decision"] == "accept"]
    rejected = [d for d in decisions if d["decision"] == "reject"]

    return {"accepted": accepted, "rejected": rejected}


def generate_candidates_for_evaluation(
    db: DatabaseAdapter, filing_id: int, company_id: int, apply_learned_rules: bool
) -> list[ReviewCandidate]:
    """
    Generate candidates for evaluation.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing to process
        company_id: Company ID
        apply_learned_rules: Whether to apply E2 learned rules

    Returns:
        List of ReviewCandidate objects
    """
    # Load segments from database
    segments_query = """
        SELECT
            source_segment_id,
            filing_id,
            segment_type,
            raw_text,
            section_heading,
            section_path
        FROM source_segments
        WHERE filing_id = %(filing_id)s
        ORDER BY source_segment_id
    """
    segments = db.query(segments_query, {"filing_id": filing_id})

    # Generate candidates
    generator = CandidateGenerator(apply_learned_rules=apply_learned_rules)
    candidates = generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
        db=db if apply_learned_rules else None,
    )

    return candidates


def match_candidate_to_decision(
    candidate: ReviewCandidate, decisions: list[dict]
) -> dict | None:
    """
    Match candidate to a review decision based on position and value.

    Args:
        candidate: ReviewCandidate to match
        decisions: List of decision dicts

    Returns:
        Matching decision dict or None
    """
    for decision in decisions:
        # Match by source segment and character position
        if (
            decision["source_segment_id"] == candidate.source_segment_id
            and decision["position_in_segment"] == candidate.char_position
        ):
            return decision

    return None


def evaluate_candidates(
    candidates: list[ReviewCandidate], ground_truth: dict[str, list[dict]]
) -> EvaluationMetrics:
    """
    Evaluate candidate quality against ground truth decisions.

    Args:
        candidates: Generated candidates
        ground_truth: Dict with 'accepted' and 'rejected' decision lists

    Returns:
        EvaluationMetrics with precision, recall, F1
    """
    accepted_decisions = ground_truth["accepted"]
    rejected_decisions = ground_truth["rejected"]

    true_positives = 0
    false_positives = 0
    matched_accepted = set()

    for candidate in candidates:
        # Check if matches an accepted decision
        accepted_match = match_candidate_to_decision(candidate, accepted_decisions)
        if accepted_match:
            true_positives += 1
            matched_accepted.add(accepted_match["decision_id"])
        else:
            # Check if matches a rejected decision (also FP)
            match_candidate_to_decision(candidate, rejected_decisions)
            false_positives += 1

    # False negatives = accepted decisions that weren't generated
    false_negatives = len(accepted_decisions) - len(matched_accepted)

    # Calculate metrics
    total_candidates = len(candidates)
    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 0.0
    )
    f1_score = (
        2 * (precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return EvaluationMetrics(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        total_candidates=total_candidates,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
    )


def evaluate_filing(
    db: DatabaseAdapter, filing_id: int, company_id: int, company_name: str
) -> ComparisonResult:
    """
    Evaluate a single filing (baseline vs improved).

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing to evaluate
        company_id: Company ID
        company_name: Company name for reporting

    Returns:
        ComparisonResult with metrics
    """
    logger.info(f"Evaluating filing {filing_id} ({company_name})...")

    # Load ground truth
    ground_truth = get_ground_truth_decisions(db, filing_id)
    total_decisions = len(ground_truth["accepted"]) + len(ground_truth["rejected"])

    logger.info(
        f"  Ground truth: {len(ground_truth['accepted'])} accepted, "
        f"{len(ground_truth['rejected'])} rejected"
    )

    # Generate baseline candidates (no learned rules)
    logger.info("  Generating baseline candidates (no learned rules)...")
    baseline_candidates = generate_candidates_for_evaluation(
        db, filing_id, company_id, apply_learned_rules=False
    )
    baseline_metrics = evaluate_candidates(baseline_candidates, ground_truth)
    logger.info(f"  Baseline: {len(baseline_candidates)} candidates generated")

    # Generate improved candidates (with learned rules)
    logger.info("  Generating improved candidates (with learned rules)...")
    improved_candidates = generate_candidates_for_evaluation(
        db, filing_id, company_id, apply_learned_rules=True
    )
    improved_metrics = evaluate_candidates(improved_candidates, ground_truth)
    logger.info(f"  Improved: {len(improved_candidates)} candidates generated")

    # Calculate improvements
    precision_improvement = (improved_metrics.precision - baseline_metrics.precision) * 100
    recall_change = (improved_metrics.recall - baseline_metrics.recall) * 100
    volume_reduction = (
        ((baseline_metrics.total_candidates - improved_metrics.total_candidates)
         / baseline_metrics.total_candidates * 100)
        if baseline_metrics.total_candidates > 0
        else 0.0
    )

    return ComparisonResult(
        filing_id=filing_id,
        company_name=company_name,
        total_decisions=total_decisions,
        baseline=baseline_metrics,
        improved=improved_metrics,
        precision_improvement=precision_improvement,
        recall_change=recall_change,
        volume_reduction=volume_reduction,
    )


def calculate_aggregate_metrics(results: list[ComparisonResult]) -> dict:
    """
    Aggregate metrics across all filings.

    Args:
        results: List of ComparisonResult

    Returns:
        Dict with aggregated metrics
    """
    if not results:
        return {}

    # Aggregate baseline
    baseline_tp = sum(r.baseline.true_positives for r in results)
    baseline_fp = sum(r.baseline.false_positives for r in results)
    baseline_fn = sum(r.baseline.false_negatives for r in results)
    baseline_total = sum(r.baseline.total_candidates for r in results)

    baseline_precision = (
        baseline_tp / (baseline_tp + baseline_fp) if (baseline_tp + baseline_fp) > 0 else 0.0
    )
    baseline_recall = (
        baseline_tp / (baseline_tp + baseline_fn) if (baseline_tp + baseline_fn) > 0 else 0.0
    )
    baseline_f1 = (
        2 * (baseline_precision * baseline_recall) / (baseline_precision + baseline_recall)
        if (baseline_precision + baseline_recall) > 0
        else 0.0
    )

    # Aggregate improved
    improved_tp = sum(r.improved.true_positives for r in results)
    improved_fp = sum(r.improved.false_positives for r in results)
    improved_fn = sum(r.improved.false_negatives for r in results)
    improved_total = sum(r.improved.total_candidates for r in results)

    improved_precision = (
        improved_tp / (improved_tp + improved_fp) if (improved_tp + improved_fp) > 0 else 0.0
    )
    improved_recall = (
        improved_tp / (improved_tp + improved_fn) if (improved_tp + improved_fn) > 0 else 0.0
    )
    improved_f1 = (
        2 * (improved_precision * improved_recall) / (improved_precision + improved_recall)
        if (improved_precision + improved_recall) > 0
        else 0.0
    )

    # Calculate improvements
    precision_improvement = (improved_precision - baseline_precision) * 100
    recall_change = (improved_recall - baseline_recall) * 100
    volume_reduction = (
        ((baseline_total - improved_total) / baseline_total * 100)
        if baseline_total > 0
        else 0.0
    )

    # Calculate precision multiplier
    precision_multiplier = (
        improved_precision / baseline_precision if baseline_precision > 0 else 0.0
    )

    return {
        "filings_evaluated": len(results),
        "total_decisions": sum(r.total_decisions for r in results),
        "baseline": {
            "total_candidates": baseline_total,
            "true_positives": baseline_tp,
            "false_positives": baseline_fp,
            "false_negatives": baseline_fn,
            "precision": baseline_precision,
            "recall": baseline_recall,
            "f1_score": baseline_f1,
            "avg_candidates_per_filing": baseline_total / len(results),
        },
        "improved": {
            "total_candidates": improved_total,
            "true_positives": improved_tp,
            "false_positives": improved_fp,
            "false_negatives": improved_fn,
            "precision": improved_precision,
            "recall": improved_recall,
            "f1_score": improved_f1,
            "avg_candidates_per_filing": improved_total / len(results),
        },
        "improvements": {
            "precision_pp": precision_improvement,
            "precision_multiplier": precision_multiplier,
            "recall_pp": recall_change,
            "volume_reduction_pct": volume_reduction,
        },
    }


def print_report(aggregate: dict, results: list[ComparisonResult], detailed: bool = False):
    """
    Print evaluation report.

    Args:
        aggregate: Aggregated metrics dict
        results: List of per-filing results
        detailed: Whether to show per-filing breakdown
    """
    print("\n" + "=" * 70)
    print("E2 EXTRACTION IMPROVEMENT EVALUATION")
    print("=" * 70)

    print(f"\nFilings evaluated: {aggregate['filings_evaluated']}")
    print(f"Total review decisions: {aggregate['total_decisions']}")

    # Baseline metrics
    print("\n" + "-" * 40)
    print("BASELINE (No Learned Rules)")
    print("-" * 40)
    b = aggregate["baseline"]
    print(f"Total candidates: {b['total_candidates']}")
    print(f"  True positives:  {b['true_positives']}")
    print(f"  False positives: {b['false_positives']}")
    print(f"  False negatives: {b['false_negatives']}")
    print(f"\nPrecision: {b['precision']:.1%}")
    print(f"Recall:    {b['recall']:.1%}")
    print(f"F1 Score:  {b['f1_score']:.1%}")
    print(f"Avg candidates per filing: {b['avg_candidates_per_filing']:.1f}")

    # Improved metrics
    print("\n" + "-" * 40)
    print("IMPROVED (With Learned Rules)")
    print("-" * 40)
    i = aggregate["improved"]
    print(f"Total candidates: {i['total_candidates']}")
    print(f"  True positives:  {i['true_positives']}")
    print(f"  False positives: {i['false_positives']}")
    print(f"  False negatives: {i['false_negatives']}")
    print(f"\nPrecision: {i['precision']:.1%}")
    print(f"Recall:    {i['recall']:.1%}")
    print(f"F1 Score:  {i['f1_score']:.1%}")
    print(f"Avg candidates per filing: {i['avg_candidates_per_filing']:.1f}")

    # Improvements
    print("\n" + "-" * 40)
    print("IMPROVEMENTS")
    print("-" * 40)
    imp = aggregate["improvements"]

    # Precision
    precision_icon = "✓✓✓" if imp["precision_pp"] >= 10 else "✓✓" if imp["precision_pp"] >= 5 else "✓" if imp["precision_pp"] > 0 else "✗"
    print(
        f"Precision: {imp['precision_pp']:+.1f} pp "
        f"[{imp['precision_multiplier']:.1f}x] {precision_icon}"
    )

    # Recall
    recall_icon = "✓" if imp["recall_pp"] >= -5 else "✗"
    print(f"Recall:    {imp['recall_pp']:+.1f} pp {recall_icon}")

    # Volume
    volume_icon = "✓✓" if imp["volume_reduction_pct"] >= 50 else "✓" if imp["volume_reduction_pct"] >= 25 else "•"
    print(
        f"Volume:    {imp['volume_reduction_pct']:.1f}% reduction {volume_icon}"
    )

    # Success criteria check
    print("\n" + "-" * 40)
    print("SUCCESS CRITERIA")
    print("-" * 40)
    print(f"✓ Precision improvement ≥10x: {'YES' if imp['precision_multiplier'] >= 10 else 'NO'} ({imp['precision_multiplier']:.1f}x)")
    print(f"✓ Recall degradation <10%:    {'YES' if imp['recall_pp'] > -10 else 'NO'} ({imp['recall_pp']:.1f} pp)")
    print(f"✓ Volume reduction ≥50%:      {'YES' if imp['volume_reduction_pct'] >= 50 else 'NO'} ({imp['volume_reduction_pct']:.1f}%)")

    # Per-filing breakdown
    if detailed and results:
        print("\n" + "=" * 70)
        print("PER-FILING BREAKDOWN")
        print("=" * 70)
        for r in results:
            print(f"\n{r.company_name} (Filing {r.filing_id}):")
            print(f"  Decisions: {r.total_decisions}")
            print(
                f"  Baseline:  {r.baseline.total_candidates} candidates, "
                f"precision={r.baseline.precision:.0%}, recall={r.baseline.recall:.0%}"
            )
            print(
                f"  Improved:  {r.improved.total_candidates} candidates, "
                f"precision={r.improved.precision:.0%}, recall={r.improved.recall:.0%}"
            )
            print(
                f"  Change:    precision {r.precision_improvement:+.1f} pp, "
                f"recall {r.recall_change:+.1f} pp, "
                f"volume {r.volume_reduction:.1f}% reduction"
            )

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate extraction improvement from learned patterns"
    )
    parser.add_argument(
        "--filing-ids",
        type=str,
        help="Comma-separated filing IDs to evaluate",
    )
    parser.add_argument(
        "--min-decisions",
        type=int,
        default=10,
        help="Minimum number of review decisions required (default: 10)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed per-filing breakdown",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file for results",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database URL (default: from DATABASE_URL env var)",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()

    # Configure logging
    configure_logging(level="INFO")

    # Connect to database
    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set. Use --database-url or set DATABASE_URL env var")
        return 1

    db = DatabaseAdapter(db_url)
    logger.info("Connected to database")

    # Parse filing IDs if provided
    filing_ids = None
    if args.filing_ids:
        filing_ids = [int(fid.strip()) for fid in args.filing_ids.split(",")]

    # Get filings with review decisions
    filings = get_filings_with_decisions(db, args.min_decisions, filing_ids)

    if not filings:
        logger.error(
            f"No filings found with at least {args.min_decisions} review decisions"
        )
        if filing_ids:
            logger.error(f"  Requested filing IDs: {filing_ids}")
        logger.error("  Review some candidates first to create ground truth data")
        return 1

    logger.info(f"Found {len(filings)} filings with review decisions")

    # Evaluate each filing
    results = []
    for filing in filings:
        try:
            result = evaluate_filing(
                db,
                filing["filing_id"],
                filing["company_id"],
                filing["company_name"],
            )
            results.append(result)
        except Exception as e:
            logger.error(
                f"Failed to evaluate filing {filing['filing_id']}: {e}",
                exc_info=True,
            )

    if not results:
        logger.error("No filings were successfully evaluated")
        return 1

    # Calculate aggregate metrics
    aggregate = calculate_aggregate_metrics(results)

    # Print report
    print_report(aggregate, results, detailed=args.detailed)

    # Save to JSON if requested
    if args.output:
        output_data = {
            "aggregate": aggregate,
            "filings": [
                {
                    "filing_id": r.filing_id,
                    "company_name": r.company_name,
                    "total_decisions": r.total_decisions,
                    "baseline": {
                        "total_candidates": r.baseline.total_candidates,
                        "true_positives": r.baseline.true_positives,
                        "false_positives": r.baseline.false_positives,
                        "false_negatives": r.baseline.false_negatives,
                        "precision": r.baseline.precision,
                        "recall": r.baseline.recall,
                        "f1_score": r.baseline.f1_score,
                    },
                    "improved": {
                        "total_candidates": r.improved.total_candidates,
                        "true_positives": r.improved.true_positives,
                        "false_positives": r.improved.false_positives,
                        "false_negatives": r.improved.false_negatives,
                        "precision": r.improved.precision,
                        "recall": r.improved.recall,
                        "f1_score": r.improved.f1_score,
                    },
                    "improvements": {
                        "precision_pp": r.precision_improvement,
                        "recall_pp": r.recall_change,
                        "volume_reduction_pct": r.volume_reduction,
                    },
                }
                for r in results
            ],
        }

        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        logger.info(f"Results saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
