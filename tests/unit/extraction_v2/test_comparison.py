"""Tests for src/extraction_v2/comparison.py."""

from __future__ import annotations

import pytest

from src.extraction_v2.comparison import (
    AggregateReport,
    FilingComparison,
    V1Candidate,
    align,
    build_aggregate,
)
from src.extraction_v2.models import MetricFact

# ============================================================================
# Helpers
# ============================================================================


def make_v1(
    candidate_id: int,
    metric_id: str | None,
    value: float | None,
    confidence: float = 0.9,
    decision: str | None = None,
) -> V1Candidate:
    return V1Candidate(
        candidate_id=candidate_id,
        filing_id=1,
        company_id=1,
        metric_id=metric_id,
        original_suggested_metric_id=metric_id,
        value=value,
        unit_raw="%",
        raw_text=str(value),
        context="context text",
        detected_period_raw=None,
        suggestion_confidence=confidence,
        decision=decision,
        rejection_category=None,
    )


def make_v2(metric_id: str, value: float) -> MetricFact:
    return MetricFact(canonical_metric_id=metric_id, value=value)


def make_filing_comparison(
    matches: list,
    v1_only: list,
    v2_only: list,
    v1_candidates: list,
    v2_facts: list,
) -> FilingComparison:
    return FilingComparison(
        filing_id=1,
        company_name="Test Co",
        accession_number="0001234567-21-000001",
        v1_candidates=v1_candidates,
        v2_facts=v2_facts,
        matches=matches,
        v1_only=v1_only,
        v2_only=v2_only,
        v2_pipeline_ms=100,
        v2_pipeline_success=True,
    )


# ============================================================================
# align() — basic matching
# ============================================================================


class TestAlignExactMatch:
    def test_exact_match_produces_one_match(self) -> None:
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("net_retention", 110.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        assert len(matches) == 1
        assert len(v1_only) == 0
        assert len(v2_only) == 0

    def test_exact_match_value_delta_pct_is_zero(self) -> None:
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("net_retention", 110.0)]
        matches, _, _ = align(v1s, v2s)
        assert matches[0].value_delta_pct == 0.0

    def test_exact_match_references_correct_objects(self) -> None:
        v1 = make_v1(1, "net_retention", 110.0)
        v2 = make_v2("net_retention", 110.0)
        matches, _, _ = align([v1], [v2])
        assert matches[0].v1 is v1
        assert matches[0].v2 is v2


class TestAlignTolerance:
    def test_within_tolerance_matches(self) -> None:
        """1% difference is within default 2% tolerance."""
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("net_retention", 111.1)]
        matches, v1_only, v2_only = align(v1s, v2s)
        assert len(matches) == 1
        assert len(v1_only) == 0
        assert len(v2_only) == 0

    def test_outside_tolerance_no_match(self) -> None:
        """3.6% difference exceeds default 2% tolerance."""
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("net_retention", 114.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        assert len(matches) == 0
        assert len(v1_only) == 1
        assert len(v2_only) == 1

    def test_custom_tolerance_respected(self) -> None:
        """With 5% tolerance, a 3.6% difference should match."""
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("net_retention", 114.0)]
        matches, v1_only, v2_only = align(v1s, v2s, value_tolerance=0.05)
        assert len(matches) == 1
        assert len(v1_only) == 0
        assert len(v2_only) == 0

    def test_at_tolerance_boundary_matches(self) -> None:
        """Exactly 2% difference should match at default tolerance."""
        v1s = [make_v1(1, "net_retention", 100.0)]
        v2s = [make_v2("net_retention", 102.0)]
        matches, _, _ = align(v1s, v2s)
        assert len(matches) == 1


class TestAlignMetricIdMismatch:
    def test_different_metric_id_no_match(self) -> None:
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("gross_retention", 110.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        assert len(matches) == 0
        assert len(v1_only) == 1
        assert len(v2_only) == 1
        assert v1_only[0].candidate_id == 1


# ============================================================================
# align() — None handling
# ============================================================================


class TestAlignNoneHandling:
    def test_v1_none_metric_id_not_matched(self) -> None:
        """V1 with None metric_id cannot match; ends up in v1_only."""
        v1s = [make_v1(1, None, 100.0)]
        v2s = [make_v2("net_retention", 100.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        assert len(matches) == 0
        assert len(v1_only) == 1
        assert v1_only[0].candidate_id == 1
        assert len(v2_only) == 1

    def test_v1_none_value_not_matched(self) -> None:
        """V1 with None value cannot match; ends up in v1_only."""
        v1s = [make_v1(1, "net_retention", None)]
        v2s = [make_v2("net_retention", 100.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        assert len(matches) == 0
        assert len(v1_only) == 1
        assert v1_only[0].candidate_id == 1
        assert len(v2_only) == 1


# ============================================================================
# align() — empty inputs
# ============================================================================


class TestAlignEmptyInputs:
    def test_both_empty(self) -> None:
        matches, v1_only, v2_only = align([], [])
        assert matches == []
        assert v1_only == []
        assert v2_only == []

    def test_v1_only_input(self) -> None:
        v1 = make_v1(1, "net_retention", 110.0)
        matches, v1_only, v2_only = align([v1], [])
        assert matches == []
        assert len(v1_only) == 1
        assert v1_only[0] is v1
        assert v2_only == []

    def test_v2_only_input(self) -> None:
        v2 = make_v2("net_retention", 110.0)
        matches, v1_only, v2_only = align([], [v2])
        assert matches == []
        assert v1_only == []
        assert len(v2_only) == 1
        assert v2_only[0] is v2


# ============================================================================
# align() — greedy one-to-one matching (no double-counting)
# ============================================================================


class TestAlignGreedyMatching:
    def test_higher_confidence_v1_claims_single_v2(self) -> None:
        """Two V1 candidates, one V2 fact — the higher-confidence V1 wins."""
        v1a = make_v1(1, "net_retention", 110.0, confidence=0.9)
        v1b = make_v1(2, "net_retention", 110.0, confidence=0.8)
        v2 = make_v2("net_retention", 110.0)
        matches, v1_only, v2_only = align([v1a, v1b], [v2])
        assert len(matches) == 1
        assert len(v1_only) == 1
        assert len(v2_only) == 0
        # Higher-confidence candidate (v1a) should own the match
        assert matches[0].v1.candidate_id == 1
        assert v1_only[0].candidate_id == 2

    def test_two_v1_two_v2_both_match(self) -> None:
        """When two distinct V2 facts exist, both V1 candidates can match."""
        v1a = make_v1(1, "net_retention", 110.0)
        v1b = make_v1(2, "net_retention", 90.0)
        v2a = make_v2("net_retention", 110.0)
        v2b = make_v2("net_retention", 90.0)
        matches, v1_only, v2_only = align([v1a, v1b], [v2a, v2b])
        assert len(matches) == 2
        assert v1_only == []
        assert v2_only == []

    def test_none_confidence_v1_loses_to_valued_confidence(self) -> None:
        """V1 with None confidence sorts after V1 with explicit confidence."""
        v1_hi = make_v1(1, "net_retention", 110.0, confidence=0.5)
        v1_none = make_v1(2, "net_retention", 110.0, confidence=None)  # type: ignore[arg-type]
        v2 = make_v2("net_retention", 110.0)
        # Manually construct with None confidence to bypass type hint
        v1_none = V1Candidate(
            candidate_id=2,
            filing_id=1,
            company_id=1,
            metric_id="net_retention",
            original_suggested_metric_id="net_retention",
            value=110.0,
            unit_raw="%",
            raw_text="110.0",
            context="context text",
            detected_period_raw=None,
            suggestion_confidence=None,
            decision=None,
            rejection_category=None,
        )
        matches, v1_only, _ = align([v1_hi, v1_none], [v2])
        assert len(matches) == 1
        assert matches[0].v1.candidate_id == 1
        assert v1_only[0].candidate_id == 2


# ============================================================================
# FilingComparison.agreement_rate()
# ============================================================================


class TestAgreementRate:
    def test_zero_candidates_returns_zero(self) -> None:
        """No candidates → agreement rate is 0.0 (no ZeroDivisionError)."""
        fc = make_filing_comparison(
            matches=[],
            v1_only=[],
            v2_only=[],
            v1_candidates=[],
            v2_facts=[],
        )
        assert fc.agreement_rate() == 0.0

    def test_perfect_agreement(self) -> None:
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("net_retention", 110.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=v1s,
            v2_facts=v2s,
        )
        assert fc.agreement_rate() == 1.0

    def test_no_agreement(self) -> None:
        """V1 candidate with different metric from V2 → agreement rate 0."""
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [make_v2("gross_retention", 110.0)]
        matches, v1_only, v2_only = align(v1s, v2s)
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=v1s,
            v2_facts=v2s,
        )
        assert fc.agreement_rate() == 0.0

    def test_partial_agreement(self) -> None:
        """Two V1 candidates, only one matched → 0.5 agreement rate."""
        v1a = make_v1(1, "net_retention", 110.0)
        v1b = make_v1(2, "gross_retention", 90.0)
        v2s = [make_v2("net_retention", 110.0)]  # only net_retention exists in V2
        matches, v1_only, v2_only = align([v1a, v1b], v2s)
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=[v1a, v1b],
            v2_facts=v2s,
        )
        assert fc.agreement_rate() == pytest.approx(0.5)

    def test_v2_extras_dont_affect_rate(self) -> None:
        """V2-only facts don't change the agreement rate denominator."""
        v1s = [make_v1(1, "net_retention", 110.0)]
        v2s = [
            make_v2("net_retention", 110.0),
            make_v2("gross_retention", 90.0),  # extra V2 fact
        ]
        matches, v1_only, v2_only = align(v1s, v2s)
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=v1s,
            v2_facts=v2s,
        )
        # 1 match / max(1 v1 candidate, 1) = 1.0
        assert fc.agreement_rate() == 1.0


# ============================================================================
# AggregateReport / build_aggregate()
# ============================================================================


class TestBuildAggregate:
    def test_build_aggregate_returns_aggregate_report(self) -> None:
        fc = make_filing_comparison(
            matches=[],
            v1_only=[],
            v2_only=[],
            v1_candidates=[],
            v2_facts=[],
        )
        report = build_aggregate([fc])
        assert isinstance(report, AggregateReport)

    def test_empty_filings_list(self) -> None:
        report = build_aggregate([])
        d = report.to_dict()
        assert d["summary"]["filings_processed"] == 0
        assert d["summary"]["total_matched"] == 0
        assert d["summary"]["overall_agreement_rate"] == 0.0

    def test_summary_counts_are_correct(self) -> None:
        v1a = make_v1(1, "net_retention", 110.0)
        v1b = make_v1(2, "gross_retention", 90.0)
        v2a = make_v2("net_retention", 110.0)
        matches, v1_only, v2_only = align([v1a, v1b], [v2a])
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=[v1a, v1b],
            v2_facts=[v2a],
        )
        report = build_aggregate([fc])
        d = report.to_dict()
        s = d["summary"]
        assert s["filings_processed"] == 1
        assert s["filings_failed"] == 0
        assert s["total_v1_candidates"] == 2
        assert s["total_v2_facts"] == 1
        assert s["total_matched"] == 1
        assert s["total_v1_only"] == 1
        assert s["total_v2_only"] == 0

    def test_failed_pipeline_counted(self) -> None:
        fc = FilingComparison(
            filing_id=1,
            company_name="Broken Co",
            accession_number="0001111111-21-000001",
            v1_candidates=[],
            v2_facts=[],
            matches=[],
            v1_only=[],
            v2_only=[],
            v2_pipeline_ms=500,
            v2_pipeline_success=False,
        )
        report = build_aggregate([fc])
        d = report.to_dict()
        assert d["summary"]["filings_failed"] == 1


class TestAggregateHumanReviewedSubset:
    def test_agrees_accept_and_agrees_reject(self) -> None:
        """
        V1 accepted candidate matched by V2 → agrees_accept.
        V1 rejected candidate NOT matched → agrees_reject.
        """
        v1_accepted = make_v1(1, "ndr", 110.0, decision="accept")
        v1_rejected = make_v1(2, "grr", 90.0, decision="reject")
        v2_match = make_v2("ndr", 110.0)

        matches, v1_only, v2_only = align([v1_accepted, v1_rejected], [v2_match])
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=[v1_accepted, v1_rejected],
            v2_facts=[v2_match],
        )
        report = build_aggregate([fc])
        subset = report.to_dict()["human_reviewed_subset"]

        assert subset["v2_agrees_accept"] == 1
        assert subset["v2_agrees_reject"] == 1
        assert subset["v2_disagrees_accept"] == 0
        assert subset["v2_disagrees_reject"] == 0

    def test_disagrees_accept(self) -> None:
        """V1 accepted candidate that V2 missed → disagrees_accept."""
        v1_accepted = make_v1(1, "ndr", 110.0, decision="accept")
        # No V2 facts for ndr → v1_accepted ends up in v1_only

        matches, v1_only, v2_only = align([v1_accepted], [])
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=[v1_accepted],
            v2_facts=[],
        )
        report = build_aggregate([fc])
        subset = report.to_dict()["human_reviewed_subset"]

        assert subset["v2_disagrees_accept"] == 1
        assert subset["v2_agrees_accept"] == 0
        assert subset["v2_agrees_reject"] == 0
        assert subset["v2_disagrees_reject"] == 0

    def test_disagrees_reject(self) -> None:
        """V1 rejected candidate that V2 still found → disagrees_reject."""
        v1_rejected = make_v1(1, "ndr", 110.0, decision="reject")
        v2 = make_v2("ndr", 110.0)

        matches, v1_only, v2_only = align([v1_rejected], [v2])
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=[v1_rejected],
            v2_facts=[v2],
        )
        report = build_aggregate([fc])
        subset = report.to_dict()["human_reviewed_subset"]

        assert subset["v2_disagrees_reject"] == 1
        assert subset["v2_agrees_reject"] == 0
        assert subset["v2_agrees_accept"] == 0
        assert subset["v2_disagrees_accept"] == 0

    def test_undecided_candidates_excluded_from_subset(self) -> None:
        """Candidates with decision=None are excluded from the human-reviewed subset."""
        v1_no_decision = make_v1(1, "ndr", 110.0, decision=None)
        v2 = make_v2("ndr", 110.0)

        matches, v1_only, v2_only = align([v1_no_decision], [v2])
        fc = make_filing_comparison(
            matches=matches,
            v1_only=v1_only,
            v2_only=v2_only,
            v1_candidates=[v1_no_decision],
            v2_facts=[v2],
        )
        report = build_aggregate([fc])
        subset = report.to_dict()["human_reviewed_subset"]

        # Match exists but no decision → not counted in any subset bucket
        assert subset["v2_agrees_accept"] == 0
        assert subset["v2_agrees_reject"] == 0
        assert subset["v2_disagrees_accept"] == 0
        assert subset["v2_disagrees_reject"] == 0

    def test_aggregate_across_multiple_filings(self) -> None:
        """Counts accumulate correctly across multiple FilingComparison objects."""
        # Filing 1: accepted match
        v1_a = make_v1(1, "ndr", 110.0, decision="accept")
        v2_a = make_v2("ndr", 110.0)
        m1, o1, g1 = align([v1_a], [v2_a])
        fc1 = make_filing_comparison(
            matches=m1,
            v1_only=o1,
            v2_only=g1,
            v1_candidates=[v1_a],
            v2_facts=[v2_a],
        )

        # Filing 2: rejected + unmatched (agrees_reject)
        v1_b = make_v1(2, "grr", 80.0, decision="reject")
        m2, o2, g2 = align([v1_b], [])
        fc2 = FilingComparison(
            filing_id=2,
            company_name="Other Co",
            accession_number="0009999999-21-000001",
            v1_candidates=[v1_b],
            v2_facts=[],
            matches=m2,
            v1_only=o2,
            v2_only=g2,
            v2_pipeline_ms=200,
            v2_pipeline_success=True,
        )

        report = build_aggregate([fc1, fc2])
        d = report.to_dict()
        subset = d["human_reviewed_subset"]
        assert subset["v2_agrees_accept"] == 1
        assert subset["v2_agrees_reject"] == 1
        assert subset["v2_disagrees_accept"] == 0
        assert subset["v2_disagrees_reject"] == 0
        assert d["summary"]["filings_processed"] == 2
