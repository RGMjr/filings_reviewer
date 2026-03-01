#!/usr/bin/env python3
"""
Diagnose V2 Extraction False Positive Explosion.

Runs the V2 pipeline on gold standard filings with full intermediate state
capture, produces stage-by-stage funnels, gold standard validation metrics
(precision/recall/F1), and classifies every false positive into categories
matching V1 filter gaps.

Usage:
    python scripts/diagnose_v2_extraction.py
    python scripts/diagnose_v2_extraction.py --output reports/v2_diagnostic_report.json
    python scripts/diagnose_v2_extraction.py --company Slack
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction_v2.models import BoundValue, MetricCandidate, MetricFact
from src.extraction_v2.pipeline import (
    PipelineConfig,
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
    V2Pipeline,
)
from src.gold_standard.v2_validator import (
    GOLD_STANDARD_CSV,
    GOLD_STANDARD_DIR,
    GoldStandardEntry,
    V2GoldStandardValidator,
    normalize_metric_id,
    normalize_value,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Diagnostic Pipeline — exposes PipelineContext after processing
# =============================================================================


class DiagnosticPipeline(V2Pipeline):
    """V2Pipeline subclass that returns the full PipelineContext."""

    def process_with_context(
        self, html_path: Path | str, filing_id: int
    ) -> tuple[PipelineResult, PipelineContext]:
        """
        Run the full pipeline and return both result and context.

        Replicates V2Pipeline.process() but retains the PipelineContext
        so callers can inspect candidates, bound_values, facts, and
        deduplicated_facts.
        """
        html_path = Path(html_path)
        start_time = datetime.utcnow()

        context = PipelineContext(
            html_path=html_path,
            filing_id=filing_id,
            config=self.config,
        )

        for stage_id, processor in self._stages:
            try:
                result = processor.process(context)
                context.stage_results.append(result)

                if not result.success and stage_id in {
                    PipelineStage.INGESTION,
                    PipelineStage.TABLE_RECONSTRUCTION,
                }:
                    pr = self._build_failure_result(
                        context, start_time, f"Critical stage failed: {stage_id.value}"
                    )
                    return pr, context

            except Exception as e:
                logger.exception(f"Exception in stage {stage_id.value}: {e}")
                context.stage_results.append(
                    StageResult(
                        stage=stage_id,
                        success=False,
                        duration_ms=0,
                        items_processed=0,
                        items_output=0,
                        errors=[str(e)],
                    )
                )

        end_time = datetime.utcnow()
        total_ms = int((end_time - start_time).total_seconds() * 1000)

        from src.extraction_v2.models import Document

        pr = PipelineResult(
            document=context.document or Document(),
            facts=context.facts,
            tables=context.tables,
            images=context.images,
            segments=context.segments,
            stage_results=context.stage_results,
            total_duration_ms=total_ms,
            success=True,
        )
        return pr, context


# =============================================================================
# False Positive Classifier (read-only, adapted from V1 patterns)
# =============================================================================

# Year pattern: integer in 1990-2100 range
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|2100)\b")

# Date expressions
_DATE_RE = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?,?\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)
_DATE_SLASH_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")

# Reference numbers
_REFERENCE_RE = re.compile(
    r"\b(?:pages?|notes?|sections?|items?|exhibits?|figures?|chapters?|tables?)"
    r"\s+\d+",
    re.IGNORECASE,
)

# Measurement unit patterns
_MEASUREMENT_UNIT_RE = re.compile(
    r"\b\d+[-\s]?(?:hour|day|week|month|year|period|quarter|minute|second)s?\b",
    re.IGNORECASE,
)

# Label-embedded threshold
_LABEL_EMBEDDED_RE = re.compile(
    r"(?:>=?|<=?|≥|≤)\s*\$?\s*\d[\d,]*(?:\.\d+)?", re.IGNORECASE
)

# Financial line item keywords (subset for quick detection)
_FINANCIAL_KEYWORDS = {
    "revenue",
    "total revenue",
    "net revenue",
    "cost of revenue",
    "gross profit",
    "operating expenses",
    "operating income",
    "operating loss",
    "net income",
    "net loss",
    "earnings per share",
    "total assets",
    "cash and cash equivalents",
    "accounts receivable",
    "total liabilities",
    "deferred revenue",
    "stockholders equity",
    "free cash flow",
    "operating cash flow",
}

# Financial statement headers
_FINANCIAL_HEADER_RE = re.compile(
    r"(?:consolidated\s+)?(?:statements?\s+of\s+(?:operations|income|cash\s+flows?|financial\s+position)"
    r"|balance\s+sheets?|income\s+statements?|summary\s+(?:consolidated\s+)?(?:financial|operating)\s+data"
    r"|selected\s+financial\s+data)",
    re.IGNORECASE,
)


def classify_false_positive(
    fact: MetricFact,
    false_negatives: list[GoldStandardEntry] | None = None,
) -> str:
    """
    Classify a false positive fact into a category.

    Categories:
        wrong_metric     — value matches an FN expectation under a different metric
        year_value       — value is an integer in 1990-2100
        date_component   — value_raw or context contains a date expression
        reference_number — near page/note/section/item/exhibit patterns
        measurement_unit — near "24-hour", "30-day", "12-month" etc.
        label_embedded   — threshold notation like ">$100,000"
        financial_line_item — context contains financial statement keywords
        other            — uncategorized
    """
    # 0. Wrong-metric binding: FP value matches an FN expectation under a different metric
    if false_negatives and fact.value is not None:
        fact_metric = normalize_metric_id(fact.canonical_metric_id)
        for fn_entry in false_negatives:
            if not fn_entry.has_numeric_value or fn_entry.normalized_value is None:
                continue
            fn_metric = normalize_metric_id(fn_entry.metric_id)
            if fn_metric == fact_metric:
                continue
            if _values_match(fn_entry.normalized_value, fact.value):
                return "wrong_metric"
    raw = fact.value_raw or ""
    context = fact.evidence_pack.context_before + " " + fact.evidence_pack.context_after
    snippet = fact.evidence_pack.snippet_html or ""
    combined = f"{raw} {context} {snippet}"

    # 1. Year value
    if fact.value is not None:
        v = fact.value
        if v == int(v) and 1990 <= int(v) <= 2100:
            return "year_value"

    # 2. Date component — value_raw appears inside a date expression
    if _DATE_RE.search(combined) or _DATE_SLASH_RE.search(combined):
        # Check if the raw value is part of that date
        if raw and re.search(re.escape(raw.strip()), combined):
            return "date_component"

    # 3. Reference number
    if _REFERENCE_RE.search(combined):
        return "reference_number"

    # 4. Measurement unit
    if _MEASUREMENT_UNIT_RE.search(combined):
        return "measurement_unit"

    # 5. Label-embedded threshold
    if _LABEL_EMBEDDED_RE.search(combined):
        return "label_embedded"

    # 6. Financial line item
    combined_lower = combined.lower()
    # Check for financial statement header nearby
    if _FINANCIAL_HEADER_RE.search(combined_lower):
        for kw in _FINANCIAL_KEYWORDS:
            if kw in combined_lower:
                return "financial_line_item"

    # Also check stub_path / header_path for financial keywords
    paths = fact.evidence_pack.stub_path + fact.evidence_pack.header_path
    for p in paths:
        p_lower = p.lower()
        for kw in _FINANCIAL_KEYWORDS:
            if kw in p_lower:
                return "financial_line_item"

    return "other"


# =============================================================================
# Gold Standard Matching (reuses V2GoldStandardValidator logic)
# =============================================================================


def _values_match(expected: float, actual: float, tolerance: float = 0.02) -> bool:
    if abs(expected) > 0.001:
        return abs(actual - expected) / abs(expected) <= tolerance
    elif abs(actual) > 0.001:
        return abs(actual - expected) / abs(actual) <= tolerance
    else:
        return abs(actual - expected) <= 0.01


@dataclass
class MatchPartition:
    """TP / FP / FN partition of extracted facts vs gold standard."""

    true_positives: list[tuple[GoldStandardEntry, MetricFact]] = field(
        default_factory=list
    )
    false_positives: list[MetricFact] = field(default_factory=list)
    false_negatives: list[GoldStandardEntry] = field(default_factory=list)
    skipped: list[GoldStandardEntry] = field(default_factory=list)


def partition_facts(
    facts: list[MetricFact],
    entries: list[GoldStandardEntry],
    tolerance: float = 0.02,
) -> MatchPartition:
    """Partition extracted facts against gold standard entries into TP/FP/FN."""
    partition = MatchPartition()
    matched_fact_ids: set[str] = set()

    for entry in entries:
        if not entry.has_numeric_value:
            partition.skipped.append(entry)
            continue

        expected_value = entry.normalized_value
        if expected_value is None:
            partition.skipped.append(entry)
            continue

        entry_metric_id = normalize_metric_id(entry.metric_id)
        found = False

        for fact in facts:
            if fact.fact_id in matched_fact_ids:
                continue
            fact_metric_id = normalize_metric_id(fact.canonical_metric_id)
            if fact_metric_id != entry_metric_id:
                continue
            if fact.value is None:
                continue
            if not _values_match(expected_value, fact.value, tolerance):
                continue
            # Match found
            partition.true_positives.append((entry, fact))
            matched_fact_ids.add(fact.fact_id)
            found = True
            break

        if not found:
            partition.false_negatives.append(entry)

    # All unmatched facts are false positives
    for fact in facts:
        if fact.fact_id not in matched_fact_ids:
            partition.false_positives.append(fact)

    return partition


# =============================================================================
# Report Builder
# =============================================================================


@dataclass
class CompanyDiagnostic:
    company_name: str
    filing_path: str
    pipeline_success: bool
    total_duration_ms: int

    # Stage funnel
    stage_funnel: list[dict]

    # Counts
    num_segments: int
    num_tables: int
    num_candidates: int
    num_bound_values: int
    num_facts: int
    num_dedup_facts: int

    # Per-metric breakdown
    metric_breakdown: dict[str, dict]

    # Gold standard
    num_gold_expected: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float

    # FP classification
    fp_categories: dict[str, int]
    fp_samples: dict[str, list[dict]]

    # TP details
    tp_details: list[dict] = field(default_factory=list)
    fn_details: list[dict] = field(default_factory=list)


def build_stage_funnel(stage_results: list[StageResult]) -> list[dict]:
    """Build stage-by-stage funnel from StageResult list."""
    funnel = []
    for sr in stage_results:
        funnel.append(
            {
                "stage": sr.stage.value,
                "success": sr.success,
                "duration_ms": sr.duration_ms,
                "items_in": sr.items_processed,
                "items_out": sr.items_output,
                "errors": sr.errors[:3],  # Truncate
                "warnings": sr.warnings[:3],
            }
        )
    return funnel


def build_metric_breakdown(
    candidates: list, bound_values: list, facts: list[MetricFact]
) -> dict[str, dict]:
    """Group candidates → bound_values → facts by metric_id."""
    breakdown: dict[str, dict] = defaultdict(
        lambda: {"candidates": 0, "bound_values": 0, "facts": 0, "source_types": Counter()}
    )

    candidate_ids_by_metric: dict[str, set[str]] = defaultdict(set)

    for c in candidates:
        mid = getattr(c, "metric_id", "unknown")
        breakdown[mid]["candidates"] += 1
        cid = getattr(c, "candidate_id", None)
        if cid:
            candidate_ids_by_metric[mid].add(cid)
        st = getattr(c, "source_type", None)
        if st:
            breakdown[mid]["source_types"][str(st)] += 1

    for bv in bound_values:
        cid = getattr(bv, "candidate_id", "")
        # Find which metric this bound value belongs to
        for mid, cids in candidate_ids_by_metric.items():
            if cid in cids:
                breakdown[mid]["bound_values"] += 1
                break

    for f in facts:
        mid = f.canonical_metric_id
        breakdown[mid]["facts"] += 1

    # Convert Counters to dicts for JSON serialization
    result = {}
    for mid, data in breakdown.items():
        result[mid] = {
            "candidates": data["candidates"],
            "bound_values": data["bound_values"],
            "facts": data["facts"],
            "source_types": dict(data["source_types"]),
        }

    return dict(sorted(result.items(), key=lambda x: -x[1]["candidates"]))


def diagnose_company(
    company_name: str,
    filing_path: Path,
    entries: list[GoldStandardEntry],
    config: PipelineConfig,
) -> CompanyDiagnostic:
    """Run full diagnostic for one company."""
    pipeline = DiagnosticPipeline(config=config)
    pr, ctx = pipeline.process_with_context(html_path=filing_path, filing_id=0)

    # Stage funnel
    funnel = build_stage_funnel(ctx.stage_results)

    # Metric breakdown
    metric_breakdown = build_metric_breakdown(
        ctx.candidates, ctx.bound_values, ctx.facts
    )

    # Gold standard partition — compare against ALL extracted facts (not dedup)
    # Use deduplicated_facts if available, otherwise facts
    eval_facts = ctx.deduplicated_facts if ctx.deduplicated_facts else ctx.facts
    partition = partition_facts(eval_facts, entries)

    tp_count = len(partition.true_positives)
    fp_count = len(partition.false_positives)
    fn_count = len(partition.false_negatives)

    precision = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 0.0
    recall = tp_count / (tp_count + fn_count) if (tp_count + fn_count) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # Classify false positives
    fp_cats: Counter = Counter()
    fp_samples: dict[str, list[dict]] = defaultdict(list)

    for fp_fact in partition.false_positives:
        cat = classify_false_positive(fp_fact, partition.false_negatives)
        fp_cats[cat] += 1
        # Keep up to 3 samples per category
        if len(fp_samples[cat]) < 3:
            fp_samples[cat].append(
                {
                    "metric_id": fp_fact.canonical_metric_id,
                    "value": fp_fact.value,
                    "value_raw": fp_fact.value_raw,
                    "unit": str(fp_fact.unit),
                    "source_type": str(fp_fact.source_type),
                    "context_before": fp_fact.evidence_pack.context_before[:80],
                    "context_after": fp_fact.evidence_pack.context_after[:80],
                    "header_path": fp_fact.evidence_pack.header_path[:3],
                    "stub_path": fp_fact.evidence_pack.stub_path[:3],
                }
            )

    # TP details
    tp_details = []
    for entry, fact in partition.true_positives:
        tp_details.append(
            {
                "metric_id": entry.metric_id,
                "expected_value": entry.normalized_value,
                "extracted_value": fact.value,
                "value_raw": fact.value_raw,
            }
        )

    # FN details
    fn_details = []
    for entry in partition.false_negatives:
        fn_details.append(
            {
                "metric_id": entry.metric_id,
                "expected_value": entry.normalized_value,
                "raw_value": entry.raw_value,
                "name_in_text": entry.name_in_text,
            }
        )

    numeric_expected = sum(1 for e in entries if e.has_numeric_value and e.normalized_value is not None)

    return CompanyDiagnostic(
        company_name=company_name,
        filing_path=str(filing_path),
        pipeline_success=pr.success,
        total_duration_ms=pr.total_duration_ms,
        stage_funnel=funnel,
        num_segments=len(ctx.segments),
        num_tables=len(ctx.tables),
        num_candidates=len(ctx.candidates),
        num_bound_values=len(ctx.bound_values),
        num_facts=len(ctx.facts),
        num_dedup_facts=len(ctx.deduplicated_facts),
        metric_breakdown=metric_breakdown,
        num_gold_expected=numeric_expected,
        true_positives=tp_count,
        false_positives=fp_count,
        false_negatives=fn_count,
        precision=precision,
        recall=recall,
        f1=f1,
        fp_categories=dict(fp_cats.most_common()),
        fp_samples=dict(fp_samples),
        tp_details=tp_details,
        fn_details=fn_details,
    )


# =============================================================================
# Console Report
# =============================================================================

DIVIDER = "=" * 78


def print_report(diagnostics: list[CompanyDiagnostic]) -> None:
    """Print a human-readable diagnostic report."""
    print()
    print(DIVIDER)
    print("  V2 EXTRACTION FALSE POSITIVE DIAGNOSTIC REPORT")
    print(f"  Generated: {datetime.utcnow().isoformat()}")
    print(DIVIDER)

    for diag in diagnostics:
        print()
        print(f"  COMPANY: {diag.company_name}")
        print(f"  Filing:  {diag.filing_path}")
        print(f"  Status:  {'OK' if diag.pipeline_success else 'FAILED'} ({diag.total_duration_ms}ms)")
        print()

        # Stage funnel
        print("  Stage Funnel:")
        print(f"  {'Stage':<28} {'In':>7} {'Out':>7} {'Time':>8} {'Status':>8}")
        print(f"  {'-'*28} {'-'*7} {'-'*7} {'-'*8} {'-'*8}")
        for s in diag.stage_funnel:
            status = "OK" if s["success"] else "FAIL"
            print(
                f"  {s['stage']:<28} {s['items_in']:>7} {s['items_out']:>7} "
                f"{s['duration_ms']:>6}ms {status:>8}"
            )
            if s["errors"]:
                for err in s["errors"]:
                    print(f"    ERROR: {err[:100]}")
            if s["warnings"]:
                for warn in s["warnings"]:
                    print(f"    WARN:  {warn[:100]}")
        print()

        # Summary counts
        print("  Pipeline Counts:")
        print(f"    Segments:       {diag.num_segments:>6}")
        print(f"    Tables:         {diag.num_tables:>6}")
        print(f"    Candidates:     {diag.num_candidates:>6}")
        print(f"    Bound Values:   {diag.num_bound_values:>6}")
        print(f"    Facts:          {diag.num_facts:>6}")
        print(f"    Dedup Facts:    {diag.num_dedup_facts:>6}")
        print()

        # Gold standard
        print("  Gold Standard Validation:")
        print(f"    Expected (numeric): {diag.num_gold_expected}")
        print(f"    True Positives:     {diag.true_positives}")
        print(f"    False Positives:    {diag.false_positives}")
        print(f"    False Negatives:    {diag.false_negatives}")
        print(f"    Precision:          {diag.precision:.1%}")
        print(f"    Recall:             {diag.recall:.1%}")
        print(f"    F1:                 {diag.f1:.1%}")
        print()

        # TP details
        if diag.tp_details:
            print("  True Positives (matched):")
            for tp in diag.tp_details:
                print(
                    f"    {tp['metric_id']}: expected={tp['expected_value']}, "
                    f"got={tp['extracted_value']} (raw: {tp['value_raw']})"
                )
            print()

        # FN details
        if diag.fn_details:
            print("  False Negatives (missed):")
            for fn in diag.fn_details:
                print(
                    f"    {fn['metric_id']}: expected={fn['expected_value']} "
                    f"(raw: {fn['raw_value']}, label: {fn['name_in_text'][:50]})"
                )
            print()

        # FP categories
        if diag.fp_categories:
            total_fp = sum(diag.fp_categories.values())
            other_count = diag.fp_categories.get("other", 0)
            classified_pct = (
                (total_fp - other_count) / total_fp * 100 if total_fp > 0 else 0
            )
            print(f"  False Positive Classification ({total_fp} total, {classified_pct:.0f}% classified):")
            for cat, count in sorted(diag.fp_categories.items(), key=lambda x: -x[1]):
                pct = count / total_fp * 100 if total_fp > 0 else 0
                print(f"    {cat:<24} {count:>5}  ({pct:>5.1f}%)")
            print()

            # Samples
            print("  FP Samples (up to 3 per category):")
            for cat, samples in diag.fp_samples.items():
                print(f"    [{cat}]")
                for s in samples:
                    ctx = s.get("context_before", "")[-40:] + " | " + s.get("context_after", "")[:40]
                    print(
                        f"      {s['metric_id']}: {s['value']} ({s['value_raw']}) "
                        f"[{s['unit']}] ctx: {ctx.strip()}"
                    )
            print()

        # Per-metric breakdown (top 15)
        if diag.metric_breakdown:
            print("  Top Metrics by Candidate Count:")
            print(f"  {'Metric ID':<36} {'Cands':>6} {'Bound':>6} {'Facts':>6}")
            print(f"  {'-'*36} {'-'*6} {'-'*6} {'-'*6}")
            for i, (mid, data) in enumerate(diag.metric_breakdown.items()):
                if i >= 15:
                    remaining = len(diag.metric_breakdown) - 15
                    print(f"  ... and {remaining} more metrics")
                    break
                print(
                    f"  {mid:<36} {data['candidates']:>6} {data['bound_values']:>6} "
                    f"{data['facts']:>6}"
                )
            print()

        print(DIVIDER)

    # Aggregate summary
    if len(diagnostics) > 1:
        total_tp = sum(d.true_positives for d in diagnostics)
        total_fp = sum(d.false_positives for d in diagnostics)
        total_fn = sum(d.false_negatives for d in diagnostics)
        agg_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        agg_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        agg_f1 = 2 * agg_p * agg_r / (agg_p + agg_r) if (agg_p + agg_r) > 0 else 0.0

        print()
        print("  AGGREGATE RESULTS")
        print(f"    TP: {total_tp}  FP: {total_fp}  FN: {total_fn}")
        print(f"    Precision: {agg_p:.1%}  Recall: {agg_r:.1%}  F1: {agg_f1:.1%}")

        # Aggregate FP categories
        all_cats: Counter = Counter()
        for d in diagnostics:
            all_cats.update(d.fp_categories)
        total_fp_all = sum(all_cats.values())
        other_all = all_cats.get("other", 0)
        classified_pct = (
            (total_fp_all - other_all) / total_fp_all * 100 if total_fp_all > 0 else 0
        )
        print(f"\n    FP Categories (aggregate, {classified_pct:.0f}% classified):")
        for cat, count in all_cats.most_common():
            pct = count / total_fp_all * 100 if total_fp_all > 0 else 0
            print(f"      {cat:<24} {count:>5}  ({pct:>5.1f}%)")

        # Top noisy metrics
        all_metrics: Counter = Counter()
        for d in diagnostics:
            for mid, data in d.metric_breakdown.items():
                all_metrics[mid] += data["candidates"]
        print(f"\n    Noisiest Metrics (by candidate count):")
        for mid, count in all_metrics.most_common(10):
            print(f"      {mid:<36} {count:>6} candidates")

        print()
        print(DIVIDER)


# =============================================================================
# JSON Export
# =============================================================================


def export_json(diagnostics: list[CompanyDiagnostic], output_path: Path) -> None:
    """Export diagnostic report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "generated_at": datetime.utcnow().isoformat(),
        "companies": [],
    }

    for diag in diagnostics:
        company_data = {
            "company_name": diag.company_name,
            "filing_path": diag.filing_path,
            "pipeline_success": diag.pipeline_success,
            "total_duration_ms": diag.total_duration_ms,
            "stage_funnel": diag.stage_funnel,
            "counts": {
                "segments": diag.num_segments,
                "tables": diag.num_tables,
                "candidates": diag.num_candidates,
                "bound_values": diag.num_bound_values,
                "facts": diag.num_facts,
                "dedup_facts": diag.num_dedup_facts,
            },
            "gold_standard": {
                "expected": diag.num_gold_expected,
                "true_positives": diag.true_positives,
                "false_positives": diag.false_positives,
                "false_negatives": diag.false_negatives,
                "precision": round(diag.precision, 4),
                "recall": round(diag.recall, 4),
                "f1": round(diag.f1, 4),
            },
            "tp_details": diag.tp_details,
            "fn_details": diag.fn_details,
            "fp_categories": diag.fp_categories,
            "fp_samples": diag.fp_samples,
            "metric_breakdown": diag.metric_breakdown,
        }
        data["companies"].append(company_data)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\n  JSON report written to: {output_path}")


# =============================================================================
# Main
# =============================================================================


def find_filing_path(company_name: str) -> Path | None:
    """
    Find the HTML filing path for a company.

    More robust than V2GoldStandardValidator._find_filing_path — normalizes
    punctuation and does fuzzy directory matching.
    """
    # Normalize: lowercase, replace non-alphanumeric with underscore
    def normalize(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

    norm_name = normalize(company_name)

    for subdir in GOLD_STANDARD_DIR.iterdir():
        if not subdir.is_dir():
            continue
        norm_dir = normalize(subdir.name)
        # Check if one is a substring of the other, or they share a long prefix
        if norm_name in norm_dir or norm_dir in norm_name:
            filing = subdir / "filing.html"
            if filing.exists():
                return filing

    # Fallback to validator's logic
    validator = V2GoldStandardValidator()
    return validator._find_filing_path(company_name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose V2 extraction false positives against gold standard"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Path for JSON output (e.g. reports/v2_diagnostic_report.json)",
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Run for a single company (substring match, e.g. 'Slack' or 'Samsara')",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Load gold standard
    validator = V2GoldStandardValidator()
    entries_by_company = validator.load_gold_standard()

    # Filter by company if requested
    if args.company:
        filtered = {
            k: v
            for k, v in entries_by_company.items()
            if args.company.lower() in k.lower()
        }
        if not filtered:
            print(f"ERROR: No company matching '{args.company}' in gold standard.")
            print(f"Available: {list(entries_by_company.keys())}")
            sys.exit(1)
        entries_by_company = filtered

    config = PipelineConfig(
        enable_image_extraction=False,
        enable_chart_extraction=False,
    )

    diagnostics: list[CompanyDiagnostic] = []

    for company_name, entries in entries_by_company.items():
        filing_path = find_filing_path(company_name)
        if filing_path is None:
            print(f"WARNING: No filing found for {company_name}, skipping.")
            continue

        print(f"Processing {company_name}...", flush=True)
        diag = diagnose_company(company_name, filing_path, entries, config)
        diagnostics.append(diag)

    if not diagnostics:
        print("ERROR: No companies processed.")
        sys.exit(1)

    print_report(diagnostics)

    if args.output:
        export_json(diagnostics, Path(args.output))


if __name__ == "__main__":
    main()
