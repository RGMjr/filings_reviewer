"""
V1-vs-V2 extraction comparison tool.

Aligns V2 MetricFact output against V1 review_candidates + review_decisions
to quantify extraction quality delta before cutting SEC filings to V2.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.extraction_v2.models import MetricFact
    from src.infra.db import DatabaseAdapter


# ============================================================================
# Dataclasses
# ============================================================================


@dataclass
class V1Candidate:
    """Normalized representation of a V1 review_candidates row."""

    candidate_id: int
    filing_id: int
    company_id: int
    # metric_id: resolved to assigned_metric_id when decision == 'reclassify'
    metric_id: str | None
    original_suggested_metric_id: str | None
    value: float | None
    unit_raw: str | None
    raw_text: str
    context: str
    detected_period_raw: str | None
    suggestion_confidence: float | None
    decision: str | None  # 'accept', 'reject', 'reclassify', or None
    rejection_category: str | None


@dataclass
class ComparisonMatch:
    """A matched pair: one V1Candidate aligned to one MetricFact."""

    v1: V1Candidate
    v2: MetricFact
    value_delta_pct: float  # abs relative difference


@dataclass
class FilingComparison:
    """Per-filing comparison result."""

    filing_id: int
    company_name: str
    accession_number: str
    v1_candidates: list[V1Candidate]
    v2_facts: list[MetricFact]
    matches: list[ComparisonMatch]
    v1_only: list[V1Candidate]   # V1 found, V2 missed (regressions)
    v2_only: list[MetricFact]    # V2 found, V1 missed (gains)
    v2_pipeline_ms: int
    v2_pipeline_success: bool

    def agreement_rate(self) -> float:
        """Fraction of V1 candidates that V2 also found."""
        return len(self.matches) / max(len(self.v1_candidates), 1)

    def to_dict(self) -> dict:
        return {
            "filing_id": self.filing_id,
            "company_name": self.company_name,
            "accession_number": self.accession_number,
            "v2_pipeline_success": self.v2_pipeline_success,
            "v2_pipeline_ms": self.v2_pipeline_ms,
            "counts": {
                "v1_total": len(self.v1_candidates),
                "v2_total": len(self.v2_facts),
                "matched": len(self.matches),
                "v1_only": len(self.v1_only),
                "v2_only": len(self.v2_only),
            },
            "agreement_rate": round(self.agreement_rate(), 4),
            "matches": [
                {
                    "metric_id": m.v1.metric_id,
                    "v1_value": m.v1.value,
                    "v2_value": m.v2.value,
                    "value_delta_pct": round(m.value_delta_pct * 100, 2),
                    "v1_period": m.v1.detected_period_raw,
                    "v2_period_start": (
                        m.v2.period_start.isoformat() if m.v2.period_start else None
                    ),
                    "v2_period_end": (
                        m.v2.period_end.isoformat() if m.v2.period_end else None
                    ),
                }
                for m in self.matches
            ],
            "v1_only": [
                {
                    "metric_id": c.metric_id,
                    "value": c.value,
                    "unit": c.unit_raw,
                    "period": c.detected_period_raw,
                    "source_text": c.context,
                    "decision": c.decision,
                }
                for c in self.v1_only
            ],
            "v2_only": [
                {
                    "metric_id": f.canonical_metric_id,
                    "value": f.value,
                    "unit": f.unit.value if f.unit else None,
                    "period_start": (
                        f.period_start.isoformat() if f.period_start else None
                    ),
                    "period_end": (
                        f.period_end.isoformat() if f.period_end else None
                    ),
                    "source_text": f.evidence_pack.snippet_html,
                    "confidence": round(f.confidence, 3),
                }
                for f in self.v2_only
            ],
        }


@dataclass
class AggregateReport:
    """Cross-filing summary."""

    filings: list[FilingComparison]

    def to_dict(self) -> dict:
        total_v1 = sum(len(f.v1_candidates) for f in self.filings)
        total_v2 = sum(len(f.v2_facts) for f in self.filings)
        total_matched = sum(len(f.matches) for f in self.filings)
        total_v1_only = sum(len(f.v1_only) for f in self.filings)
        total_v2_only = sum(len(f.v2_only) for f in self.filings)
        overall_agreement_rate = total_matched / max(total_v1, 1)

        # Human-reviewed subset: candidates that have decisions
        reviewed_matches = [
            m for f in self.filings for m in f.matches if m.v1.decision is not None
        ]
        reviewed_v1_only = [
            c for f in self.filings for c in f.v1_only if c.decision is not None
        ]
        v2_agrees_accept = sum(
            1 for m in reviewed_matches if m.v1.decision == "accept"
        )
        v2_agrees_reject = sum(
            1 for c in reviewed_v1_only if c.decision == "reject"
        )
        v2_disagrees_accept = sum(
            1 for c in reviewed_v1_only if c.decision == "accept"
        )
        v2_disagrees_reject = sum(
            1 for m in reviewed_matches if m.v1.decision == "reject"
        )

        return {
            "summary": {
                "filings_processed": len(self.filings),
                "filings_failed": sum(
                    1 for f in self.filings if not f.v2_pipeline_success
                ),
                "total_v1_candidates": total_v1,
                "total_v2_facts": total_v2,
                "total_matched": total_matched,
                "total_v1_only": total_v1_only,
                "total_v2_only": total_v2_only,
                "overall_agreement_rate": round(overall_agreement_rate, 4),
            },
            "human_reviewed_subset": {
                "v2_agrees_accept": v2_agrees_accept,
                "v2_agrees_reject": v2_agrees_reject,
                "v2_disagrees_accept": v2_disagrees_accept,
                "v2_disagrees_reject": v2_disagrees_reject,
            },
            "filings": [f.to_dict() for f in self.filings],
        }

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    def print_summary(self) -> None:
        d = self.to_dict()
        s = d["summary"]
        h = d["human_reviewed_subset"]
        print()
        print("=" * 60)
        print("V1 vs V2 Extraction Comparison Summary")
        print("=" * 60)
        print(f"  Filings processed:     {s['filings_processed']}")
        print(f"  Filings failed (V2):   {s['filings_failed']}")
        print(f"  V1 candidates:         {s['total_v1_candidates']}")
        print(f"  V2 facts:              {s['total_v2_facts']}")
        print(f"  Matched:               {s['total_matched']}")
        print(f"  V1-only (regressions): {s['total_v1_only']}")
        print(f"  V2-only (gains):       {s['total_v2_only']}")
        print(f"  Agreement rate:        {s['overall_agreement_rate']:.1%}")
        print()
        print("  Human-reviewed subset:")
        print(f"    V2 agrees with accept:    {h['v2_agrees_accept']}")
        print(f"    V2 agrees with reject:    {h['v2_agrees_reject']}")
        print(f"    V2 misses accepted (reg): {h['v2_disagrees_accept']}")
        print(f"    V2 finds rejected (FP?):  {h['v2_disagrees_reject']}")
        print("=" * 60)


# ============================================================================
# Module-level functions
# ============================================================================


def load_v1_candidates(
    db: DatabaseAdapter, filing_id: int
) -> list[V1Candidate]:
    """Load V1 review candidates (with decisions if any) for a filing."""
    rows = db.query(
        """
        SELECT
            rc.candidate_id,
            rc.filing_id,
            rc.company_id,
            rc.suggested_metric_id,
            rc.parsed_value,
            rc.parsed_unit,
            rc.raw_number_text,
            rc.context_text,
            rc.features->>'detected_period' AS detected_period_raw,
            rc.suggestion_confidence,
            rd.decision,
            rd.assigned_metric_id,
            rd.rejection_category
        FROM review_candidates rc
        LEFT JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
        WHERE rc.filing_id = %(filing_id)s
        ORDER BY rc.candidate_id
        """,
        {"filing_id": filing_id},
    )
    candidates = []
    for row in rows:
        decision = row.get("decision")
        assigned = row.get("assigned_metric_id")
        suggested = row.get("suggested_metric_id")
        metric_id = (
            assigned if (decision == "reclassify" and assigned) else suggested
        )
        raw_value = row.get("parsed_value")
        raw_conf = row.get("suggestion_confidence")
        candidates.append(
            V1Candidate(
                candidate_id=row["candidate_id"],
                filing_id=row["filing_id"],
                company_id=row["company_id"],
                metric_id=metric_id,
                original_suggested_metric_id=suggested,
                value=float(raw_value) if raw_value is not None else None,
                unit_raw=row.get("parsed_unit"),
                raw_text=row.get("raw_number_text", ""),
                context=row.get("context_text", ""),
                detected_period_raw=row.get("detected_period_raw"),
                suggestion_confidence=(
                    float(raw_conf) if raw_conf is not None else None
                ),
                decision=decision,
                rejection_category=row.get("rejection_category"),
            )
        )
    return candidates


def find_filings_with_candidates(
    db: DatabaseAdapter, limit: int | None = None
) -> list[dict]:
    """Return filings that have at least one V1 review candidate."""
    sql = """
        SELECT DISTINCT
            f.filing_id,
            f.accession_number,
            f.form_type,
            f.html_storage_path,
            c.company_name,
            c.cik,
            c.company_id
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        JOIN review_candidates rc ON rc.filing_id = f.filing_id
        ORDER BY f.filing_id
    """
    params: dict = {}
    if limit is not None:
        sql += " LIMIT %(limit)s"
        params["limit"] = limit
    return db.query(sql, params)


def _value_matches(v1_val: float, v2_val: float | None, tol: float) -> bool:
    if v2_val is None:
        return False
    if v1_val == 0 and v2_val == 0:
        return True
    if v2_val == 0:
        return abs(v1_val) <= tol
    return abs(v1_val - v2_val) / abs(v2_val) <= tol


def align(
    v1_candidates: list[V1Candidate],
    v2_facts: list[MetricFact],
    value_tolerance: float = 0.02,
) -> tuple[list[ComparisonMatch], list[V1Candidate], list[MetricFact]]:
    """
    Greedy one-to-one alignment of V1 candidates to V2 facts.

    Matches on (canonical_metric_id, value within tolerance).
    Higher-confidence V1 candidates claim V2 facts first.

    Returns (matches, v1_only, v2_only).
    """
    v2_by_metric: dict[str, list[MetricFact]] = defaultdict(list)
    for fact in v2_facts:
        if fact.canonical_metric_id:
            v2_by_metric[fact.canonical_metric_id].append(fact)

    sorted_v1 = sorted(
        v1_candidates,
        key=lambda c: (
            c.suggestion_confidence is None,
            -(c.suggestion_confidence or 0),
        ),
    )

    matched_v2_ids: set[str] = set()
    matched_v1_ids: set[int] = set()
    matches: list[ComparisonMatch] = []

    for v1 in sorted_v1:
        if v1.metric_id is None or v1.value is None:
            continue
        available = [
            f
            for f in v2_by_metric[v1.metric_id]
            if f.fact_id not in matched_v2_ids
        ]
        best: MetricFact | None = None
        best_delta = float("inf")
        for fact in available:
            if not _value_matches(v1.value, fact.value, value_tolerance):
                continue
            delta = (
                abs(v1.value - fact.value) / abs(fact.value)
                if fact.value
                else 0.0
            )
            if delta < best_delta:
                best_delta = delta
                best = fact
        if best is not None:
            matched_v2_ids.add(best.fact_id)
            matched_v1_ids.add(v1.candidate_id)
            delta_pct = (
                abs(v1.value - best.value) / abs(best.value)
                if best.value
                else 0.0
            )
            matches.append(
                ComparisonMatch(v1=v1, v2=best, value_delta_pct=delta_pct)
            )

    v1_only = [
        c for c in v1_candidates if c.candidate_id not in matched_v1_ids
    ]
    v2_only = [f for f in v2_facts if f.fact_id not in matched_v2_ids]
    return matches, v1_only, v2_only


def build_aggregate(comparisons: list[FilingComparison]) -> AggregateReport:
    """Aggregate a list of per-filing comparisons into a report."""
    return AggregateReport(filings=comparisons)
