"""
Unified 3-way comparison of V1 vs V2 vs Gold Standard extraction.

Provides dataclasses and a runner for evaluating extraction pipelines
against the gold standard dataset, computing precision/recall/F1 metrics
and surfacing gains/regressions between pipelines.

Usage::

    from src.gold_standard.unified_comparison import UnifiedComparisonRunner

    runner = UnifiedComparisonRunner()
    report = runner.run()
    report.print_summary()
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.extraction.keyword_config import metrics_are_equivalent
from src.extraction_v2.models import MetricFact, SourceType
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline
from src.gold_standard.baseline import MetricScores
from src.gold_standard.fresh_extractor import segment_and_generate
from src.gold_standard.v2_validator import (
    GOLD_STANDARD_CSV,
    GOLD_STANDARD_DIR,
    GoldStandardEntry,
    normalize_metric_id,
    normalize_value,
)
from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NormalizedExtraction
# ---------------------------------------------------------------------------


@dataclass
class NormalizedExtraction:
    """
    Pipeline-agnostic representation of a single extracted metric value.

    Used to compare V1 and V2 outputs on equal footing against gold standard.
    """

    extraction_id: str
    metric_id: str  # cm_xxx form
    value: float | None
    source_type: str  # "text" | "table" | "chart" | "unknown"
    period_start: date | None
    period_end: date | None
    confidence: float
    pipeline: str  # "v1" | "v2"
    raw_context: str  # first 200 chars for debugging


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def v1_candidate_to_normalized(candidate: ReviewCandidate) -> NormalizedExtraction:
    """
    Convert a V1 ReviewCandidate to a NormalizedExtraction.

    V1 does not carry structured period information, so period_start/period_end
    are always None. Source type is derived from the candidate's features if
    available, falling back to "unknown".
    """
    if candidate.candidate_id is not None:
        extraction_id = str(candidate.candidate_id)
    else:
        extraction_id = str(uuid.uuid4())

    metric_id = normalize_metric_id(candidate.suggested_metric_id or "")

    value: float | None = None
    if candidate.parsed_value is not None:
        try:
            value = float(candidate.parsed_value)
        except (ValueError, TypeError):
            value = None

    # Derive source_type from features
    source_type = "unknown"
    if candidate.features is not None:
        if candidate.features.is_in_table:
            source_type = "table"
        else:
            source_type = "text"

    confidence = (
        candidate.suggestion_confidence if candidate.suggestion_confidence is not None else 0.5
    )

    raw_context = (candidate.context_text or "")[:200]

    return NormalizedExtraction(
        extraction_id=extraction_id,
        metric_id=metric_id,
        value=value,
        source_type=source_type,
        period_start=None,
        period_end=None,
        confidence=confidence,
        pipeline="v1",
        raw_context=raw_context,
    )


def v2_fact_to_normalized(fact: MetricFact) -> NormalizedExtraction:
    """
    Convert a V2 MetricFact to a NormalizedExtraction.

    Source type is mapped from the V2 SourceType enum to the shared vocabulary:
    html_table/ocr_table -> "table", chart -> "chart", text -> "text", else "unknown".
    """
    metric_id = normalize_metric_id(fact.canonical_metric_id)

    # Map SourceType enum to shared vocabulary
    st = fact.source_type
    if st in (SourceType.HTML_TABLE, SourceType.OCR_TABLE):
        source_type = "table"
    elif st == SourceType.CHART:
        source_type = "chart"
    elif st == SourceType.TEXT:
        source_type = "text"
    else:
        source_type = "unknown"

    raw_context = (fact.evidence_pack.snippet_html or "")[:200]

    return NormalizedExtraction(
        extraction_id=fact.fact_id,
        metric_id=metric_id,
        value=fact.value,
        source_type=source_type,
        period_start=fact.period_start,
        period_end=fact.period_end,
        confidence=fact.confidence,
        pipeline="v2",
        raw_context=raw_context,
    )


# ---------------------------------------------------------------------------
# MatchingResult
# ---------------------------------------------------------------------------


@dataclass
class MatchPair:
    """A true-positive match between an extraction and a gold standard entry."""

    extraction: NormalizedExtraction
    gold_entry: GoldStandardEntry
    value_delta_pct: float


@dataclass
class MatchingResult:
    """
    Matching outcome for a set of extractions against gold standard entries.

    tp_pairs contains every matched (extraction, gold_entry) pair.
    fp_extractions contains only extractions whose metric_id appears in the
    gold set but were not matched (metric known to be expected but value/metric
    is wrong).
    fn_entries contains gold entries that were not matched.
    """

    tp_pairs: list[MatchPair]
    fp_extractions: list[NormalizedExtraction]  # Only those whose metric_id appears in gold set
    fn_entries: list[GoldStandardEntry]
    precision: float
    recall: float
    f1: float


# ---------------------------------------------------------------------------
# Deduplication helper (inlined from v2_validator._deduplicate_entries)
# ---------------------------------------------------------------------------


def _deduplicate_gold_entries(
    entries: list[GoldStandardEntry],
    company_name: str = "",
) -> list[GoldStandardEntry]:
    """
    Deduplicate gold standard entries sharing the same (metric_id, value).

    Collapses entries with the same (metric_id, normalized_value) pair, keeping
    the first occurrence. Definition-only entries are always preserved.

    This mirrors the logic in V2GoldStandardValidator._deduplicate_entries to
    avoid penalising the pipeline for its own deduplication.
    """
    seen: set[tuple[str, float]] = set()
    deduped: list[GoldStandardEntry] = []
    removed = 0

    for entry in entries:
        if not entry.has_numeric_value:
            deduped.append(entry)
            continue

        norm_value = entry.normalized_value
        if norm_value is None:
            deduped.append(entry)
            continue

        key = (normalize_metric_id(entry.metric_id), norm_value)
        if key in seen:
            removed += 1
            continue

        seen.add(key)
        deduped.append(entry)

    if removed > 0:
        logger.debug(
            "%s: deduplicated %d/%d gold standard entries (%d unique)",
            company_name,
            removed,
            len(entries),
            len(deduped),
        )

    return deduped


# ---------------------------------------------------------------------------
# Core matching function
# ---------------------------------------------------------------------------


def match_extractions_to_gold(
    extractions: list[NormalizedExtraction],
    gold_entries: list[GoldStandardEntry],
    value_tolerance: float = 0.02,
    company_name: str = "",
) -> MatchingResult:
    """
    Match extractions against gold standard entries and compute P/R/F1.

    Uses a greedy scoring approach:
      - Score += 2 for metric equivalence
      - Score += 3 for value match within tolerance
      - Minimum score of 4 required (both metric AND value must match)

    Only extractions whose metric_id appears in the gold set are counted as
    false positives (metric-in-scope FPs). Extractions for metrics not
    represented at all in gold are ignored for precision computation (we
    cannot judge them without a gold standard).

    Args:
        extractions: Normalized extractions from any pipeline.
        gold_entries: Gold standard expected values.
        value_tolerance: Fractional tolerance for numeric value comparison (default 2%).
        company_name: For debug logging only.

    Returns:
        MatchingResult with tp_pairs, fp_extractions, fn_entries, and P/R/F1.
    """
    # 1. Deduplicate gold entries
    gold_entries = _deduplicate_gold_entries(gold_entries, company_name)

    # 2. Filter to only actionable gold entries
    active_gold: list[GoldStandardEntry] = [
        e
        for e in gold_entries
        if e.has_numeric_value
        and normalize_metric_id(e.metric_id) not in ("", "cm_not_a_customer_metric")
    ]

    if not active_gold:
        return MatchingResult(
            tp_pairs=[],
            fp_extractions=[],
            fn_entries=[],
            precision=0.0,
            recall=0.0,
            f1=0.0,
        )

    # Build set of metric_ids that appear in gold (for FP scoping)
    gold_metric_ids: set[str] = {normalize_metric_id(e.metric_id) for e in active_gold}

    # 3. Build all candidate pairs with scores
    CandidatePair = tuple[float, int, int]  # (score, extraction_idx, gold_idx)
    candidate_pairs: list[CandidatePair] = []

    for e_idx, extraction in enumerate(extractions):
        if not extraction.metric_id:
            continue
        for g_idx, gold_entry in enumerate(active_gold):
            score = 0.0

            # Metric equivalence check
            try:
                if metrics_are_equivalent(
                    extraction.metric_id, normalize_metric_id(gold_entry.metric_id)
                ):
                    score += 2
            except Exception:
                # metrics_are_equivalent may raise on unknown IDs
                if extraction.metric_id == normalize_metric_id(gold_entry.metric_id):
                    score += 2

            if score < 2:
                # No metric match — cannot reach minimum score of 4
                continue

            # Value match check
            if extraction.value is not None:
                try:
                    gold_value = normalize_value(
                        gold_entry.raw_value,
                        gold_entry.scaled_value,
                        gold_entry.scale_unit,
                    )
                    if gold_value != 0.0:
                        delta_pct = abs(extraction.value - gold_value) / abs(gold_value)
                    else:
                        delta_pct = 0.0 if extraction.value == 0.0 else float("inf")

                    if delta_pct <= value_tolerance:
                        score += 3
                except (ValueError, ZeroDivisionError):
                    pass

            if score >= 4:
                candidate_pairs.append((score, e_idx, g_idx))

    # 4. Sort by score descending; greedy one-to-one assignment
    candidate_pairs.sort(key=lambda t: t[0], reverse=True)
    matched_extractions: set[int] = set()
    matched_gold: set[int] = set()
    tp_pairs: list[MatchPair] = []

    for _score, e_idx, g_idx in candidate_pairs:
        if e_idx in matched_extractions or g_idx in matched_gold:
            continue
        matched_extractions.add(e_idx)
        matched_gold.add(g_idx)

        extraction = extractions[e_idx]
        gold_entry = active_gold[g_idx]

        # Compute value delta for reporting
        value_delta_pct = 0.0
        if extraction.value is not None:
            try:
                gold_value = normalize_value(
                    gold_entry.raw_value,
                    gold_entry.scaled_value,
                    gold_entry.scale_unit,
                )
                if gold_value != 0.0:
                    value_delta_pct = abs(extraction.value - gold_value) / abs(gold_value)
            except (ValueError, ZeroDivisionError):
                pass

        tp_pairs.append(
            MatchPair(
                extraction=extraction,
                gold_entry=gold_entry,
                value_delta_pct=value_delta_pct,
            )
        )

    # 5. Collect FPs: unmatched extractions whose metric_id is in the gold set
    fp_extractions: list[NormalizedExtraction] = [
        extractions[i]
        for i in range(len(extractions))
        if i not in matched_extractions and extractions[i].metric_id in gold_metric_ids
    ]

    # 6. Collect FNs: unmatched gold entries
    fn_entries: list[GoldStandardEntry] = [
        active_gold[i] for i in range(len(active_gold)) if i not in matched_gold
    ]

    # 7. Compute P/R/F1
    tp_count = len(tp_pairs)
    fp_count = len(fp_extractions)
    fn_count = len(fn_entries)

    precision = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 0.0
    recall = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return MatchingResult(
        tp_pairs=tp_pairs,
        fp_extractions=fp_extractions,
        fn_entries=fn_entries,
        precision=precision,
        recall=recall,
        f1=f1,
    )


# ---------------------------------------------------------------------------
# Source-type partitioning
# ---------------------------------------------------------------------------


@dataclass
class SourceTypeScores:
    """Scores partitioned by the gold standard's annotated segment_type."""

    source_type: str
    gold_count: int
    v1_result: MatchingResult
    v2_full_result: MatchingResult
    v2_text_only_result: MatchingResult | None


def partition_by_source_type(
    gold_entries: list[GoldStandardEntry],
    v1_extractions: list[NormalizedExtraction],
    v2_full_extractions: list[NormalizedExtraction],
    v2_text_only_extractions: list[NormalizedExtraction] | None,
    value_tolerance: float = 0.02,
) -> dict[str, SourceTypeScores]:
    """
    Partition gold entries by segment_type and compute per-source-type scores.

    For each partition, the full extraction lists are passed to the matcher
    (not filtered by source_type) because gold segment_type annotations are
    incomplete. The matcher is free to find matches from any source.

    Args:
        gold_entries: All gold standard entries for this scope.
        v1_extractions: V1 normalized extractions.
        v2_full_extractions: V2 full (including images) normalized extractions.
        v2_text_only_extractions: V2 text-only normalized extractions, or None.
        value_tolerance: Fractional value match tolerance.

    Returns:
        Dict mapping source_type string to SourceTypeScores.
    """
    # Group gold entries by segment_type
    partitions: dict[str, list[GoldStandardEntry]] = {}
    for entry in gold_entries:
        st = entry.segment_type or ""
        partitions.setdefault(st, []).append(entry)

    result: dict[str, SourceTypeScores] = {}
    for source_type, entries in partitions.items():
        gold_count = sum(
            1
            for e in entries
            if e.has_numeric_value
            and normalize_metric_id(e.metric_id) not in ("", "cm_not_a_customer_metric")
        )
        v1_result = match_extractions_to_gold(v1_extractions, entries, value_tolerance)
        v2_full_result = match_extractions_to_gold(v2_full_extractions, entries, value_tolerance)
        v2_text_only_result = (
            match_extractions_to_gold(v2_text_only_extractions, entries, value_tolerance)
            if v2_text_only_extractions is not None
            else None
        )
        result[source_type] = SourceTypeScores(
            source_type=source_type,
            gold_count=gold_count,
            v1_result=v1_result,
            v2_full_result=v2_full_result,
            v2_text_only_result=v2_text_only_result,
        )

    return result


# ---------------------------------------------------------------------------
# PipelineScores
# ---------------------------------------------------------------------------


@dataclass
class PipelineScores:
    """Scores for a single pipeline run."""

    pipeline: str  # "v1", "v2_full", "v2_text_only"
    matching_result: MatchingResult
    tp_count: int
    fp_count: int
    fn_count: int

    @property
    def precision(self) -> float:
        """Precision = TP / (TP + FP)."""
        return self.matching_result.precision

    @property
    def recall(self) -> float:
        """Recall = TP / (TP + FN)."""
        return self.matching_result.recall

    @property
    def f1(self) -> float:
        """F1 = 2 * P * R / (P + R)."""
        return self.matching_result.f1


def _pipeline_scores_from_result(
    pipeline: str,
    result: MatchingResult,
) -> PipelineScores:
    """Build a PipelineScores from a MatchingResult."""
    return PipelineScores(
        pipeline=pipeline,
        matching_result=result,
        tp_count=len(result.tp_pairs),
        fp_count=len(result.fp_extractions),
        fn_count=len(result.fn_entries),
    )


# ---------------------------------------------------------------------------
# CompanyComparison
# ---------------------------------------------------------------------------


@dataclass
class CompanyComparison:
    """All comparison results for a single company."""

    company_name: str
    gold_entries: list[GoldStandardEntry]
    v1_scores: PipelineScores
    v2_full_scores: PipelineScores
    v2_text_only_scores: PipelineScores | None
    v2_gains: list[GoldStandardEntry]  # Gold entries V2 found that V1 missed
    v2_regressions: list[GoldStandardEntry]  # Gold entries V1 found that V2 missed
    image_gains: list[GoldStandardEntry]  # Found by V2-full but not V2-text-only


# ---------------------------------------------------------------------------
# UnifiedReport
# ---------------------------------------------------------------------------


@dataclass
class UnifiedReport:
    """
    Complete 3-way comparison report across all companies.

    Contains per-company breakdowns, aggregate P/R/F1 scores for each pipeline,
    source-type partitioned scores, and an overall verdict.
    """

    companies: list[CompanyComparison]
    v1_overall: MetricScores
    v2_full_overall: MetricScores
    v2_text_only_overall: MetricScores | None
    by_source_type: dict[str, SourceTypeScores]
    verdict: str  # "V2_READY" | "V2_NOT_READY"
    verdict_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""

        def ms_dict(ms: MetricScores | None) -> dict[str, float] | None:
            if ms is None:
                return None
            return {"precision": ms.precision, "recall": ms.recall, "f1": ms.f1}

        def mr_dict(mr: MatchingResult) -> dict[str, Any]:
            return {
                "tp": len(mr.tp_pairs),
                "fp": len(mr.fp_extractions),
                "fn": len(mr.fn_entries),
                "precision": round(mr.precision, 4),
                "recall": round(mr.recall, 4),
                "f1": round(mr.f1, 4),
            }

        def ps_dict(ps: PipelineScores | None) -> dict[str, Any] | None:
            if ps is None:
                return None
            return {
                "pipeline": ps.pipeline,
                "tp": ps.tp_count,
                "fp": ps.fp_count,
                "fn": ps.fn_count,
                "precision": round(ps.precision, 4),
                "recall": round(ps.recall, 4),
                "f1": round(ps.f1, 4),
            }

        companies_list = []
        for cc in self.companies:
            companies_list.append(
                {
                    "company_name": cc.company_name,
                    "gold_count": len(cc.gold_entries),
                    "v1": ps_dict(cc.v1_scores),
                    "v2_full": ps_dict(cc.v2_full_scores),
                    "v2_text_only": ps_dict(cc.v2_text_only_scores),
                    "v2_gains": [e.metric_id for e in cc.v2_gains],
                    "v2_regressions": [e.metric_id for e in cc.v2_regressions],
                    "image_gains": [e.metric_id for e in cc.image_gains],
                }
            )

        by_st: dict[str, Any] = {}
        for st, scores in self.by_source_type.items():
            by_st[st or "(unclassified)"] = {
                "gold_count": scores.gold_count,
                "v1": mr_dict(scores.v1_result),
                "v2_full": mr_dict(scores.v2_full_result),
                "v2_text_only": (
                    mr_dict(scores.v2_text_only_result)
                    if scores.v2_text_only_result is not None
                    else None
                ),
            }

        return {
            "companies": companies_list,
            "v1_overall": ms_dict(self.v1_overall),
            "v2_full_overall": ms_dict(self.v2_full_overall),
            "v2_text_only_overall": ms_dict(self.v2_text_only_overall),
            "by_source_type": by_st,
            "verdict": self.verdict,
            "verdict_reasons": self.verdict_reasons,
        }

    def print_summary(self) -> None:
        """Print a tabular summary of results to stdout."""
        print("\n" + "=" * 70)
        print("UNIFIED EXTRACTION COMPARISON REPORT")
        print("=" * 70)

        # Per-company table
        header = f"{'Company':<30} {'V1 F1':>7} {'V2Full F1':>10} {'V2Text F1':>10} {'V2Gains':>8} {'V2Regr':>7}"
        print(f"\n{header}")
        print("-" * 70)
        for cc in self.companies:
            v2t_f1 = f"{cc.v2_text_only_scores.f1:.1%}" if cc.v2_text_only_scores else "   N/A"
            name = cc.company_name[:29]
            print(
                f"{name:<30} "
                f"{cc.v1_scores.f1:>7.1%} "
                f"{cc.v2_full_scores.f1:>10.1%} "
                f"{v2t_f1:>10} "
                f"{len(cc.v2_gains):>8} "
                f"{len(cc.v2_regressions):>7}"
            )

        # Overall
        print("\n" + "-" * 70)
        v2t_text = (
            f"  V2-text-only: P={self.v2_text_only_overall.precision:.1%} "
            f"R={self.v2_text_only_overall.recall:.1%} "
            f"F1={self.v2_text_only_overall.f1:.1%}"
            if self.v2_text_only_overall is not None
            else "  V2-text-only: N/A"
        )
        print(
            f"\nOVERALL:\n"
            f"  V1:           P={self.v1_overall.precision:.1%} "
            f"R={self.v1_overall.recall:.1%} "
            f"F1={self.v1_overall.f1:.1%}\n"
            f"  V2-full:      P={self.v2_full_overall.precision:.1%} "
            f"R={self.v2_full_overall.recall:.1%} "
            f"F1={self.v2_full_overall.f1:.1%}\n"
            f"{v2t_text}"
        )

        # Source-type breakdown
        if self.by_source_type:
            print("\nBY SOURCE TYPE:")
            hdr2 = f"  {'SegType':<12} {'Gold':>5} {'V1 F1':>7} {'V2Full F1':>10} {'V2Text F1':>10}"
            print(hdr2)
            print("  " + "-" * 46)
            for st, scores in sorted(self.by_source_type.items()):
                label = st or "(unclass)"
                v2t_f1_str = (
                    f"{scores.v2_text_only_result.f1:>10.1%}"
                    if scores.v2_text_only_result is not None
                    else f"{'N/A':>10}"
                )
                print(
                    f"  {label:<12} "
                    f"{scores.gold_count:>5} "
                    f"{scores.v1_result.f1:>7.1%} "
                    f"{scores.v2_full_result.f1:>10.1%} "
                    f"{v2t_f1_str}"
                )

        # Verdict
        print(f"\nVERDICT: {self.verdict}")
        for reason in self.verdict_reasons:
            print(f"  - {reason}")
        print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# UnifiedComparisonRunner
# ---------------------------------------------------------------------------


def _aggregate_metric_scores(results: list[MatchingResult]) -> MetricScores:
    """Aggregate MatchingResult objects into a single MetricScores."""
    total_tp = sum(len(r.tp_pairs) for r in results)
    total_fp = sum(len(r.fp_extractions) for r in results)
    total_fn = sum(len(r.fn_entries) for r in results)
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return MetricScores(precision=precision, recall=recall, f1=f1)


class UnifiedComparisonRunner:
    """
    Orchestrates a 3-way comparison of V1, V2-full, and V2-text-only pipelines.

    For each company in the gold standard dataset, it:
      1. Loads gold standard entries from the CSV.
      2. Runs V1 extraction via fresh_extractor.segment_and_generate().
      3. Runs V2-full extraction via V2Pipeline.process().
      4. Optionally runs V2-text-only (no image/chart stages).
      5. Matches all outputs against the gold standard.
      6. Aggregates per-company and overall scores, then generates a verdict.
    """

    def __init__(
        self,
        gold_standard_csv: Path = GOLD_STANDARD_CSV,
        gold_standard_dir: Path = GOLD_STANDARD_DIR,
        value_tolerance: float = 0.02,
        skip_image_comparison: bool = False,
    ) -> None:
        """
        Initialise the runner.

        Args:
            gold_standard_csv: Path to the gold standard CSV file.
            gold_standard_dir: Root directory containing per-company subdirectories.
            value_tolerance: Fractional tolerance for value matching (default 2%).
            skip_image_comparison: If True, omit V2-text-only run (saves time).
        """
        self.gold_standard_csv = Path(gold_standard_csv)
        self.gold_standard_dir = Path(gold_standard_dir)
        self.value_tolerance = value_tolerance
        self.skip_image_comparison = skip_image_comparison

        # Lazily initialised V2 pipeline instances
        self._v2_full_pipeline: V2Pipeline | None = None
        self._v2_text_pipeline: V2Pipeline | None = None

    @property
    def v2_full_pipeline(self) -> V2Pipeline:
        """Lazily create the V2 full (images-enabled) pipeline."""
        if self._v2_full_pipeline is None:
            self._v2_full_pipeline = V2Pipeline(config=PipelineConfig())
        return self._v2_full_pipeline

    @property
    def v2_text_pipeline(self) -> V2Pipeline:
        """Lazily create the V2 text-only pipeline."""
        if self._v2_text_pipeline is None:
            config = PipelineConfig(
                enable_image_extraction=False,
                enable_chart_extraction=False,
            )
            self._v2_text_pipeline = V2Pipeline(config=config)
        return self._v2_text_pipeline

    def run(self, companies: list[str] | None = None) -> UnifiedReport:
        """
        Execute the full comparison across all (or a subset of) companies.

        Args:
            companies: Optional list of company names to process. If None, all
                companies with a matching gold standard directory are processed.

        Returns:
            UnifiedReport with per-company and aggregate results.
        """
        gold_by_company = self._load_gold_standard()

        if companies is not None:
            gold_by_company = {k: v for k, v in gold_by_company.items() if k in companies}

        if not gold_by_company:
            logger.warning("No companies to process.")
            empty_scores = MetricScores(precision=0.0, recall=0.0, f1=0.0)
            return UnifiedReport(
                companies=[],
                v1_overall=empty_scores,
                v2_full_overall=empty_scores,
                v2_text_only_overall=None if self.skip_image_comparison else empty_scores,
                by_source_type={},
                verdict="V2_NOT_READY",
                verdict_reasons=["No companies processed."],
            )

        company_comparisons: list[CompanyComparison] = []

        for company_name, entries in gold_by_company.items():
            logger.info("Processing company: %s", company_name)
            filing_path = self._find_filing_path(company_name)
            if filing_path is None:
                logger.warning("No filing.html found for %s — skipping.", company_name)
                continue

            metadata = self._load_metadata(company_name)

            v1_extractions = self._run_v1(company_name, filing_path)
            v2_full_extractions = self._run_v2(
                company_name, filing_path, metadata, enable_images=True
            )
            v2_text_extractions: list[NormalizedExtraction] | None = None
            if not self.skip_image_comparison:
                v2_text_extractions = self._run_v2(
                    company_name, filing_path, metadata, enable_images=False
                )

            v1_result = match_extractions_to_gold(
                v1_extractions, entries, self.value_tolerance, company_name
            )
            v2_full_result = match_extractions_to_gold(
                v2_full_extractions, entries, self.value_tolerance, company_name
            )
            v2_text_result: MatchingResult | None = None
            if v2_text_extractions is not None:
                v2_text_result = match_extractions_to_gold(
                    v2_text_extractions, entries, self.value_tolerance, company_name
                )

            v1_scores = _pipeline_scores_from_result("v1", v1_result)
            v2_full_scores = _pipeline_scores_from_result("v2_full", v2_full_result)
            v2_text_scores: PipelineScores | None = (
                _pipeline_scores_from_result("v2_text_only", v2_text_result)
                if v2_text_result is not None
                else None
            )

            # V2 gains: gold entries V2-full found but V1 missed
            v1_matched_gold = {id(p.gold_entry) for p in v1_result.tp_pairs}
            v2_full_matched_gold = {id(p.gold_entry) for p in v2_full_result.tp_pairs}
            v2_gains: list[GoldStandardEntry] = [
                p.gold_entry
                for p in v2_full_result.tp_pairs
                if id(p.gold_entry) not in v1_matched_gold
            ]
            v2_regressions: list[GoldStandardEntry] = [
                p.gold_entry
                for p in v1_result.tp_pairs
                if id(p.gold_entry) not in v2_full_matched_gold
            ]

            # Image gains: found by V2-full but not V2-text-only
            image_gains: list[GoldStandardEntry] = []
            if v2_text_result is not None:
                v2_text_matched_gold = {id(p.gold_entry) for p in v2_text_result.tp_pairs}
                image_gains = [
                    p.gold_entry
                    for p in v2_full_result.tp_pairs
                    if id(p.gold_entry) not in v2_text_matched_gold
                ]

            company_comparisons.append(
                CompanyComparison(
                    company_name=company_name,
                    gold_entries=entries,
                    v1_scores=v1_scores,
                    v2_full_scores=v2_full_scores,
                    v2_text_only_scores=v2_text_scores,
                    v2_gains=v2_gains,
                    v2_regressions=v2_regressions,
                    image_gains=image_gains,
                )
            )

        # Aggregate overall scores
        v1_results = [cc.v1_scores.matching_result for cc in company_comparisons]
        v2_full_results = [cc.v2_full_scores.matching_result for cc in company_comparisons]

        v1_overall = _aggregate_metric_scores(v1_results)
        v2_full_overall = _aggregate_metric_scores(v2_full_results)
        v2_text_only_overall: MetricScores | None = None
        if not self.skip_image_comparison:
            v2_text_results = [
                cc.v2_text_only_scores.matching_result
                for cc in company_comparisons
                if cc.v2_text_only_scores is not None
            ]
            if v2_text_results:
                v2_text_only_overall = _aggregate_metric_scores(v2_text_results)

        # Aggregate gold entries for source-type partitioning
        all_gold: list[GoldStandardEntry] = [
            e for cc in company_comparisons for e in cc.gold_entries
        ]
        all_v1: list[NormalizedExtraction] = []
        all_v2_full: list[NormalizedExtraction] = []
        all_v2_text: list[NormalizedExtraction] | None = (
            [] if not self.skip_image_comparison else None
        )

        for cc in company_comparisons:
            # Re-use extractions from the company scores tp_pairs + fp + fn
            # Re-collect the normalized extractions by re-running is expensive;
            # instead collect them from the MatchingResult tp_pairs and fp lists.
            for pair in cc.v1_scores.matching_result.tp_pairs:
                all_v1.append(pair.extraction)
            all_v1.extend(cc.v1_scores.matching_result.fp_extractions)
            for pair in cc.v2_full_scores.matching_result.tp_pairs:
                all_v2_full.append(pair.extraction)
            all_v2_full.extend(cc.v2_full_scores.matching_result.fp_extractions)
            if all_v2_text is not None and cc.v2_text_only_scores is not None:
                for pair in cc.v2_text_only_scores.matching_result.tp_pairs:
                    all_v2_text.append(pair.extraction)
                all_v2_text.extend(cc.v2_text_only_scores.matching_result.fp_extractions)

        by_source_type = partition_by_source_type(
            all_gold,
            all_v1,
            all_v2_full,
            all_v2_text,
            self.value_tolerance,
        )

        # Verdict logic
        verdict, verdict_reasons = self._compute_verdict(
            v1_overall, v2_full_overall, v2_text_only_overall, company_comparisons
        )

        return UnifiedReport(
            companies=company_comparisons,
            v1_overall=v1_overall,
            v2_full_overall=v2_full_overall,
            v2_text_only_overall=v2_text_only_overall,
            by_source_type=by_source_type,
            verdict=verdict,
            verdict_reasons=verdict_reasons,
        )

    def _compute_verdict(
        self,
        v1_overall: MetricScores,
        v2_full_overall: MetricScores,
        v2_text_only_overall: MetricScores | None,
        companies: list[CompanyComparison],
    ) -> tuple[str, list[str]]:
        """
        Determine V2_READY / V2_NOT_READY verdict.

        V2_READY if:
          - V2 text-only F1 >= V1 F1 - 0.05
          - No company has V2 text-only recall drop > 0.15 vs V1

        Args:
            v1_overall: Aggregate V1 scores.
            v2_full_overall: Aggregate V2-full scores.
            v2_text_only_overall: Aggregate V2-text-only scores, or None.
            companies: Per-company comparison objects.

        Returns:
            Tuple of (verdict_string, list_of_reason_strings).
        """
        reasons: list[str] = []

        if v2_text_only_overall is None:
            return "V2_NOT_READY", [
                "V2 text-only scores not available (skip_image_comparison=True)."
            ]

        # Check overall F1 threshold
        f1_drop = v1_overall.f1 - v2_text_only_overall.f1
        if f1_drop > 0.05:
            reasons.append(
                f"V2 text-only F1 ({v2_text_only_overall.f1:.1%}) is more than 5pp below "
                f"V1 F1 ({v1_overall.f1:.1%}) — drop = {f1_drop:.1%}."
            )

        # Check per-company recall drops
        for cc in companies:
            if cc.v2_text_only_scores is None:
                continue
            recall_drop = cc.v1_scores.recall - cc.v2_text_only_scores.recall
            if recall_drop > 0.15:
                reasons.append(
                    f"{cc.company_name}: V2 text-only recall dropped {recall_drop:.1%} "
                    f"(V1={cc.v1_scores.recall:.1%}, V2={cc.v2_text_only_scores.recall:.1%})."
                )

        if reasons:
            return "V2_NOT_READY", reasons

        return "V2_READY", [
            f"V2 text-only F1 ({v2_text_only_overall.f1:.1%}) >= V1 F1 ({v1_overall.f1:.1%}) - 5pp threshold.",
            "No company has V2 text-only recall drop > 15pp vs V1.",
        ]

    def _load_gold_standard(self) -> dict[str, list[GoldStandardEntry]]:
        """
        Load and parse the gold standard CSV, returning entries grouped by company.

        Returns:
            Dict mapping company name to list of GoldStandardEntry.
        """
        entries_by_company: dict[str, list[GoldStandardEntry]] = {}

        with open(self.gold_standard_csv, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    entry = self._parse_gold_standard_row(row)
                    entries_by_company.setdefault(entry.company_name, []).append(entry)
                except Exception as exc:
                    logger.warning("Failed to parse gold standard row: %s", exc)
                    continue

        logger.info(
            "Loaded gold standard: %d companies, %d total entries.",
            len(entries_by_company),
            sum(len(v) for v in entries_by_company.values()),
        )
        return entries_by_company

    def _parse_gold_standard_row(self, row: dict[str, Any]) -> GoldStandardEntry:
        """Parse a single CSV row into a GoldStandardEntry."""
        period_start: date | None = None
        period_end: date | None = None
        if row.get("period_start"):
            try:
                period_start = date.fromisoformat(row["period_start"])
            except ValueError:
                pass
        if row.get("period_end"):
            try:
                period_end = date.fromisoformat(row["period_end"])
            except ValueError:
                pass

        is_def_only = str(row.get("is_definition_only", "")).lower() in (
            "true",
            "x",
            "yes",
            "1",
        )

        return GoldStandardEntry(
            document_url=row.get("Document URL", ""),
            company_name=row.get("Company", ""),
            metric_id=normalize_metric_id(row.get("Standard Metric Name", "")),
            name_in_text=row.get("Name in the text", ""),
            raw_value=row.get("Raw value", ""),
            scaled_value=row.get("Scaled value", ""),
            scale_unit=row.get("Scale/unit", ""),
            period=row.get("Period", ""),
            definition=row.get("Definition", ""),
            quote_context=row.get("Quote/context", ""),
            segment_type=row.get("segment_type", ""),
            is_definition_only=is_def_only,
            value_context=row.get("value_context", ""),
            detection_difficulty=row.get("detection_difficulty", ""),
            period_start=period_start,
            period_end=period_end,
        )

    def _run_v1(
        self,
        company_name: str,
        filing_path: Path,
    ) -> list[NormalizedExtraction]:
        """
        Run V1 extraction on a filing and return normalized extractions.

        Args:
            company_name: Company name for logging.
            filing_path: Path to filing.html.

        Returns:
            List of NormalizedExtraction from V1.
        """
        try:
            candidates, segment_count, error = segment_and_generate(filing_path)
            if error:
                logger.warning("V1 extraction error for %s: %s", company_name, error)
                return []
            logger.debug(
                "V1 %s: %d segments, %d candidates", company_name, segment_count, len(candidates)
            )
            return [v1_candidate_to_normalized(c) for c in candidates]
        except Exception as exc:
            logger.error("V1 extraction exception for %s: %s", company_name, exc)
            return []

    def _run_v2(
        self,
        company_name: str,
        filing_path: Path,
        metadata: dict[str, Any],
        enable_images: bool,
    ) -> list[NormalizedExtraction]:
        """
        Run V2 extraction on a filing and return normalized extractions.

        Args:
            company_name: Company name for logging.
            filing_path: Path to filing.html.
            metadata: Parsed metadata.json dict (for cik/accession_number).
            enable_images: Whether to enable image/chart extraction stages.

        Returns:
            List of NormalizedExtraction from V2.
        """
        pipeline = self.v2_full_pipeline if enable_images else self.v2_text_pipeline
        try:
            result = pipeline.process(
                html_path=filing_path,
                filing_id=0,
                cik=metadata.get("cik", ""),
                accession_number=metadata.get("accession_number", ""),
            )
            if not result.success:
                logger.warning("V2 pipeline failed for %s: %s", company_name, result.error_message)
                return []
            logger.debug(
                "V2 %s (images=%s): %d facts", company_name, enable_images, len(result.facts)
            )
            return [v2_fact_to_normalized(f) for f in result.facts]
        except Exception as exc:
            logger.error("V2 extraction exception for %s: %s", company_name, exc)
            return []

    def _find_filing_path(self, company_name: str) -> Path | None:
        """
        Locate the filing.html for a given company under the gold standard directory.

        Normalises the company name (spaces→underscores, periods→underscores,
        collapse double underscores) and does a case-insensitive directory scan.

        Args:
            company_name: Company name as it appears in the gold standard CSV.

        Returns:
            Path to filing.html if found, else None.
        """
        if not self.gold_standard_dir.exists():
            return None

        # Normalize: spaces→_, periods→_, collapse __
        normalized = company_name.replace(" ", "_").replace(".", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        normalized_lower = normalized.lower()

        for subdir in self.gold_standard_dir.iterdir():
            if not subdir.is_dir():
                continue
            if subdir.name.lower() == normalized_lower:
                candidate = subdir / "filing.html"
                if candidate.exists():
                    return candidate

        return None

    def _load_metadata(self, company_name: str) -> dict[str, Any]:
        """
        Load metadata.json for a company, returning an empty dict on failure.

        Args:
            company_name: Company name as it appears in the gold standard CSV.

        Returns:
            Parsed metadata dict (may be empty if file not found or invalid).
        """
        filing_path = self._find_filing_path(company_name)
        if filing_path is None:
            return {}
        metadata_path = filing_path.parent / "metadata.json"
        if not metadata_path.exists():
            return {}
        try:
            with open(metadata_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load metadata for %s: %s", company_name, exc)
            return {}
