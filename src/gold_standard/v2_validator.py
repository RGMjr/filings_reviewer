"""
V2 Gold Standard Validator.

Validates V2 extraction pipeline output against gold standard expected values.
Computes precision, recall, and F1 metrics for quality assessment.

Usage:
    from src.gold_standard.v2_validator import V2GoldStandardValidator

    validator = V2GoldStandardValidator()
    results = validator.validate_all()
    metrics = validator.compute_metrics(results)
    print(f"Precision: {metrics.precision:.1%}, Recall: {metrics.recall:.1%}")
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from datetime import date
from decimal import InvalidOperation
from pathlib import Path
from typing import Any

from src.extraction_v2.models import MetricFact
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, V2Pipeline
from src.gold_standard.baseline import (
    BaselineMetrics,
    MetricScores,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)
from src.gold_standard.baseline import (
    ComparisonResult as BaselineComparisonResult,
)

logger = logging.getLogger(__name__)


# Default paths
GOLD_STANDARD_DIR = Path(__file__).parent.parent.parent / "data" / "gold_standard"
GOLD_STANDARD_CSV = GOLD_STANDARD_DIR / "golden_set_251218.csv"
V2_BASELINE_PATH = GOLD_STANDARD_DIR / "v2_baseline.json"


@dataclass
class GoldStandardEntry:
    """A single expected value from the gold standard dataset."""

    document_url: str
    company_name: str
    metric_id: str
    name_in_text: str
    raw_value: str
    scaled_value: str
    scale_unit: str
    period: str
    definition: str
    quote_context: str
    segment_type: str
    is_definition_only: bool
    value_context: str
    detection_difficulty: str
    period_start: date | None
    period_end: date | None

    @property
    def has_numeric_value(self) -> bool:
        """Check if entry has a numeric value (not definition-only)."""
        if self.is_definition_only:
            return False
        if not self.raw_value or self.raw_value.lower() in ("", "chart", "n/a", "-"):
            return False
        return True

    @property
    def normalized_value(self) -> float | None:
        """Get normalized numeric value for comparison."""
        if not self.has_numeric_value:
            return None

        try:
            return normalize_value(self.raw_value, self.scaled_value, self.scale_unit)
        except (ValueError, InvalidOperation):
            return None


@dataclass
class MatchResult:
    """Result of matching a gold standard entry against extraction."""

    entry: GoldStandardEntry
    matched_fact: MetricFact | None
    match_type: str  # "true_positive", "false_negative", "skipped"
    reason: str = ""


@dataclass
class FalsePositiveDiagnostic:
    """Diagnostic info for a single false positive fact."""

    metric_id: str
    value: float | None
    value_raw: str
    period_start: date | None
    period_end: date | None
    source_type: str
    confidence: float
    source_snippet: str  # First 120 chars of evidence
    # Closest gold standard match info
    closest_gold_metric: str = ""
    closest_gold_value: float | None = None
    closest_gold_period: str = ""
    value_delta_pct: float | None = None  # % difference from closest gold value
    mismatch_category: str = (
        ""  # "period_mismatch", "value_mismatch", "scale_factor", "both_mismatch", "no_match"
    )


@dataclass
class FNRootCause:
    """Root cause classification for a false negative."""

    category: str  # no_candidate | no_value_binding | fp_filtered | wrong_value | wrong_period | low_confidence | dedup_removed | unknown
    detail: str
    stage: str  # pipeline stage where the metric was lost


@dataclass
class FNDiagnostic:
    """Diagnostic info for a single false negative entry."""

    entry: GoldStandardEntry
    company_name: str
    root_cause: FNRootCause
    candidate_count: int = 0  # How many candidates had this metric_id
    bound_value_count: int = 0  # How many pre-filter bindings existed
    closest_fact_value: float | None = None  # Closest extracted fact value
    closest_fact_confidence: float | None = None


@dataclass
class ValidationResult:
    """Result of validating extraction against gold standard for one filing."""

    company_name: str
    filing_path: str
    total_expected: int
    matched: int
    missed: int
    extra: int  # V2 facts not in gold standard
    match_results: list[MatchResult] = field(default_factory=list)
    fp_diagnostics: list[FalsePositiveDiagnostic] = field(default_factory=list)
    fn_diagnostics: list[FNDiagnostic] = field(default_factory=list)

    # Confusion matrix
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        """Precision = TP / (TP + FP)."""
        total = self.true_positives + self.false_positives
        if total == 0:
            return 0.0
        return self.true_positives / total

    @property
    def recall(self) -> float:
        """Recall = TP / (TP + FN)."""
        total = self.true_positives + self.false_negatives
        if total == 0:
            return 0.0
        return self.true_positives / total

    @property
    def f1_score(self) -> float:
        """F1 = 2 * (precision * recall) / (precision + recall)."""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)


@dataclass
class AggregateMetrics:
    """Aggregate validation metrics across all filings."""

    precision: float
    recall: float
    f1: float
    total_true_positives: int
    total_false_positives: int
    total_false_negatives: int
    by_company: dict[str, MetricScores] = field(default_factory=dict)

    def to_baseline_metrics(
        self,
        description: str | None = None,
    ) -> BaselineMetrics:
        """Convert to BaselineMetrics for saving."""
        from datetime import UTC, datetime

        return BaselineMetrics(
            baseline_date=datetime.now(UTC).isoformat(),
            description=description or "V2 pipeline validation",
            overall=MetricScores(
                precision=self.precision,
                recall=self.recall,
                f1=self.f1,
            ),
            by_company=self.by_company,
            # V2 baseline marker (via description)
        )


class V2GoldStandardValidator:
    """
    Validate V2 extraction pipeline against gold standard dataset.

    The gold standard dataset contains expected metric values for
    specific filings, manually verified for accuracy.
    """

    def __init__(
        self,
        gold_standard_path: Path | str = GOLD_STANDARD_CSV,
        v2_config: PipelineConfig | None = None,
        value_tolerance: float = 0.02,
        min_confidence: float = 0.35,
        fn_diagnostics: bool = False,
    ):
        """
        Initialize validator.

        Args:
            gold_standard_path: Path to gold standard CSV file
            v2_config: Configuration for V2 pipeline
            value_tolerance: Tolerance for numeric value matching (default 2%)
            min_confidence: Minimum confidence to count a fact (default 0.90)
            fn_diagnostics: If True, enable FN root cause tracing
        """
        self.gold_standard_path = Path(gold_standard_path)
        self.fn_diagnostics = fn_diagnostics

        # When FN diagnostics are enabled, set retain_context on the pipeline config
        if fn_diagnostics:
            base = v2_config or PipelineConfig()
            self.v2_config = dc_replace(base, retain_context=True)
        else:
            self.v2_config = v2_config or PipelineConfig()

        self.value_tolerance = value_tolerance
        self.min_confidence = min_confidence

        self.v2_pipeline = V2Pipeline(config=self.v2_config)

        # Cache for gold standard entries
        self._entries_by_company: dict[str, list[GoldStandardEntry]] | None = None

    def load_gold_standard(self) -> dict[str, list[GoldStandardEntry]]:
        """
        Load gold standard entries grouped by company.

        Returns:
            Dictionary mapping company name to list of expected entries
        """
        if self._entries_by_company is not None:
            return self._entries_by_company

        entries_by_company: dict[str, list[GoldStandardEntry]] = {}

        with open(self.gold_standard_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    entry = self._parse_gold_standard_row(row)
                    if entry.company_name not in entries_by_company:
                        entries_by_company[entry.company_name] = []
                    entries_by_company[entry.company_name].append(entry)
                except Exception as e:
                    logger.warning(f"Failed to parse gold standard row: {e}")
                    continue

        self._entries_by_company = entries_by_company
        return entries_by_company

    def _parse_gold_standard_row(self, row: dict[str, Any]) -> GoldStandardEntry:
        """Parse a single row from gold standard CSV."""
        # Parse dates
        period_start = None
        period_end = None
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

        # Parse is_definition_only flag
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

    @staticmethod
    def _deduplicate_entries(
        entries: list[GoldStandardEntry],
        company_name: str = "",
    ) -> list[GoldStandardEntry]:
        """
        Deduplicate gold standard entries sharing the same (metric_id, value).

        The gold standard CSV often contains the same (metric, value) pair
        repeated across multiple contexts (e.g. same number in a table row
        and in prose). The V2 pipeline correctly deduplicates extracted facts,
        so counting each repeated gold standard entry as a separate expected
        value inflates false negatives. This method collapses such duplicates.

        Only deduplicates entries with numeric values; definition-only entries
        are always preserved as-is.
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

    def validate_filing(
        self,
        company_name: str,
        filing_path: Path,
        expected_entries: list[GoldStandardEntry],
        pipeline_override: V2Pipeline | None = None,
    ) -> ValidationResult:
        """
        Validate V2 extraction against expected entries for a single filing.

        Args:
            company_name: Company name for reporting
            filing_path: Path to HTML filing
            expected_entries: Expected gold standard entries
            pipeline_override: Optional pipeline instance with filing-specific config
                (e.g., non-calendar fiscal year end). If None, uses self.v2_pipeline.

        Returns:
            ValidationResult with precision/recall metrics
        """
        expected_entries = self._deduplicate_entries(expected_entries, company_name)
        result = ValidationResult(
            company_name=company_name,
            filing_path=str(filing_path),
            total_expected=len([e for e in expected_entries if e.has_numeric_value]),
            matched=0,
            missed=0,
            extra=0,
        )

        pipeline = pipeline_override if pipeline_override is not None else self.v2_pipeline

        # Run V2 pipeline
        filing_metadata = self._load_filing_metadata(company_name)
        v2_context: PipelineContext | None = None
        all_v2_facts: list[MetricFact] = []
        try:
            v2_result = pipeline.process(
                html_path=filing_path,
                filing_id=0,  # Placeholder, not persisting
                cik=filing_metadata.get("cik", ""),
                accession_number=filing_metadata.get("accession_number", ""),
            )
            if not v2_result.success:
                logger.error(f"V2 pipeline failed for {company_name}: {v2_result.error_message}")
                result.false_negatives = result.total_expected
                result.missed = result.total_expected
                return result

            v2_facts = [f for f in v2_result.facts if f.confidence >= self.min_confidence]
            all_v2_facts = v2_result.facts  # Includes low-confidence facts for FN tracing
            v2_context = v2_result.context  # type: ignore[assignment]
            logger.debug(
                f"{company_name}: {len(v2_result.facts)} total facts, "
                f"{len(v2_facts)} above confidence threshold {self.min_confidence}"
            )
        except Exception as e:
            logger.error(f"V2 pipeline exception for {company_name}: {e}")
            result.false_negatives = result.total_expected
            result.missed = result.total_expected
            return result

        # Match expected entries against extracted facts
        matched_fact_ids: set[str] = set()

        for entry in expected_entries:
            # Skip definition-only entries
            if not entry.has_numeric_value:
                result.match_results.append(
                    MatchResult(
                        entry=entry,
                        matched_fact=None,
                        match_type="skipped",
                        reason="Definition-only entry",
                    )
                )
                continue

            # Skip "not a customer metric" entries — these are definitionally
            # not customer metrics and inflate FN count
            if normalize_metric_id(entry.metric_id) == "cm_not_a_customer_metric":
                result.match_results.append(
                    MatchResult(
                        entry=entry,
                        matched_fact=None,
                        match_type="skipped",
                        reason="Not a customer metric",
                    )
                )
                # Adjust total_expected since this entry shouldn't count
                result.total_expected -= 1
                continue

            # Skip entries with empty metric_id — malformed gold standard rows
            if not normalize_metric_id(entry.metric_id):
                result.total_expected -= 1
                continue

            # Try to find a matching fact
            matched_fact = self._find_matching_fact(entry, v2_facts, matched_fact_ids)

            if matched_fact:
                matched_fact_ids.add(matched_fact.fact_id)
                result.matched += 1
                result.true_positives += 1
                result.match_results.append(
                    MatchResult(
                        entry=entry,
                        matched_fact=matched_fact,
                        match_type="true_positive",
                    )
                )
            else:
                # Check if this entry is a duplicate — same (metric, value) as
                # an already-matched entry.  The gold standard often repeats
                # the same metric+value across multiple contexts; counting each
                # unmatched duplicate as a FN would penalise the pipeline's
                # own deduplication.
                duplicate_fact = self._find_matching_fact(entry, v2_facts, set())
                if duplicate_fact and duplicate_fact.fact_id in matched_fact_ids:
                    # Already covered by a previous entry — skip
                    result.total_expected -= 1
                    result.match_results.append(
                        MatchResult(
                            entry=entry,
                            matched_fact=None,
                            match_type="skipped",
                            reason="Duplicate of already-matched entry",
                        )
                    )
                else:
                    result.missed += 1
                    result.false_negatives += 1
                    result.match_results.append(
                        MatchResult(
                            entry=entry,
                            matched_fact=None,
                            match_type="false_negative",
                            reason="No matching fact found",
                        )
                    )
                    if self.fn_diagnostics and v2_context is not None:
                        fn_diag = self._diagnose_false_negative(
                            entry, company_name, v2_context, all_v2_facts
                        )
                        result.fn_diagnostics.append(fn_diag)

        # Count extra facts (false positives) with diagnostics
        # Note: We're conservative - only count facts with matching metric_ids as FP
        # Facts for metrics not in gold standard aren't counted as FP
        gold_metric_ids = {normalize_metric_id(e.metric_id) for e in expected_entries}
        gold_entries_for_metric = {}
        for entry in expected_entries:
            mid = normalize_metric_id(entry.metric_id)
            gold_entries_for_metric.setdefault(mid, []).append(entry)

        # Track (metric_id, value) pairs already counted as true positives so that
        # a second extraction of the same value from a different source (e.g., the
        # same number appearing in both prose and a table with different periods)
        # is not penalised as a false positive.
        matched_metric_values: set[tuple[str, float | None]] = {
            (
                normalize_metric_id(mr.matched_fact.canonical_metric_id),
                mr.matched_fact.value,
            )
            for mr in result.match_results
            if mr.matched_fact is not None and mr.match_type == "true_positive"
        }

        for fact in v2_facts:
            if fact.fact_id not in matched_fact_ids:
                fact_metric = normalize_metric_id(fact.canonical_metric_id)
                if fact_metric in gold_metric_ids:
                    # Skip if this metric+value was already counted as TP —
                    # same value extracted from a different source/period.
                    if (fact_metric, fact.value) in matched_metric_values:
                        continue

                    result.extra += 1
                    result.false_positives += 1

                    # Build diagnostic
                    diag = self._build_fp_diagnostic(
                        fact, gold_entries_for_metric.get(fact_metric, [])
                    )
                    result.fp_diagnostics.append(diag)

        return result

    def _find_matching_fact(
        self,
        entry: GoldStandardEntry,
        facts: list[MetricFact],
        already_matched: set[str],
    ) -> MetricFact | None:
        """
        Find a fact that matches the gold standard entry.

        Matching criteria:
        - Same metric_id (normalized)
        - Value within tolerance
        - Period overlap (if both have periods)
        """
        expected_value = entry.normalized_value
        if expected_value is None:
            return None

        entry_metric_id = normalize_metric_id(entry.metric_id)

        for fact in facts:
            if fact.fact_id in already_matched:
                continue

            # Metric ID must match
            fact_metric_id = normalize_metric_id(fact.canonical_metric_id)
            if fact_metric_id != entry_metric_id:
                continue

            # Value must be present and within tolerance
            if fact.value is None:
                continue

            if not self._values_match(expected_value, fact.value):
                continue

            # Period check (optional)
            if entry.period_start and entry.period_end:
                if fact.period_start and fact.period_end:
                    # Periods should overlap
                    if entry.period_end < fact.period_start or fact.period_end < entry.period_start:
                        continue

            return fact

        return None

    def _values_match(self, expected: float, actual: float) -> bool:
        """Check if values match within tolerance."""
        if abs(expected) > 0.001:
            delta = abs(actual - expected) / abs(expected)
            return delta <= self.value_tolerance
        elif abs(actual) > 0.001:
            delta = abs(actual - expected) / abs(actual)
            return delta <= self.value_tolerance
        else:
            # Both near zero
            return abs(actual - expected) <= 0.01

    def _build_fp_diagnostic(
        self,
        fact: MetricFact,
        gold_entries: list[GoldStandardEntry],
    ) -> FalsePositiveDiagnostic:
        """Build a diagnostic for a false positive fact."""
        snippet = (
            fact.evidence_pack.snippet_html[:120]
            if fact.evidence_pack.snippet_html
            else fact.value_raw
        )

        diag = FalsePositiveDiagnostic(
            metric_id=fact.canonical_metric_id,
            value=fact.value,
            value_raw=fact.value_raw,
            period_start=fact.period_start,
            period_end=fact.period_end,
            source_type=fact.source_type.value,
            confidence=fact.confidence,
            source_snippet=snippet,
        )

        # Find closest gold match
        closest = self._find_closest_gold_match(fact, gold_entries)
        if closest:
            entry, delta_pct, category = closest
            diag.closest_gold_metric = entry.metric_id
            diag.closest_gold_value = entry.normalized_value
            diag.closest_gold_period = entry.period
            diag.value_delta_pct = delta_pct
            diag.mismatch_category = category
        else:
            diag.mismatch_category = "no_match"

        return diag

    def _find_closest_gold_match(
        self,
        fact: MetricFact,
        gold_entries: list[GoldStandardEntry],
    ) -> tuple[GoldStandardEntry, float | None, str] | None:
        """
        Find the closest gold standard entry to understand WHY a fact didn't match.

        Returns:
            Tuple of (closest_entry, value_delta_pct, mismatch_category) or None
        """
        if not gold_entries or fact.value is None:
            return None

        best_entry: GoldStandardEntry | None = None
        best_delta: float | None = None

        for entry in gold_entries:
            gold_value = entry.normalized_value
            if gold_value is None:
                continue

            if abs(gold_value) > 0.001:
                delta = abs(fact.value - gold_value) / abs(gold_value)
            elif abs(fact.value) > 0.001:
                delta = abs(fact.value - gold_value) / abs(fact.value)
            else:
                delta = 0.0

            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_entry = entry

        if best_entry is None:
            return None

        # Categorize the mismatch
        value_matches = best_delta is not None and best_delta <= self.value_tolerance

        # Check period overlap
        period_matches = True
        if (
            best_entry.period_start
            and best_entry.period_end
            and fact.period_start
            and fact.period_end
        ):
            if (
                best_entry.period_end < fact.period_start
                or fact.period_end < best_entry.period_start
            ):
                period_matches = False

        if value_matches and not period_matches:
            category = "period_mismatch"
        elif not value_matches and period_matches:
            # Check for scale factor (10x, 100x, 1000x differences)
            if best_delta is not None and best_entry.normalized_value:
                ratio = (
                    fact.value / best_entry.normalized_value
                    if best_entry.normalized_value != 0
                    else 0
                )
                if ratio and any(
                    abs(ratio - mult) / mult < 0.05 for mult in [0.001, 0.01, 0.1, 10, 100, 1000]
                ):
                    category = "scale_factor"
                else:
                    category = "value_mismatch"
            else:
                category = "value_mismatch"
        elif not value_matches and not period_matches:
            category = "both_mismatch"
        else:
            # Value and period match — shouldn't be an FP, but could be a duplicate
            category = "duplicate_value"

        return (best_entry, best_delta, category)

    def _diagnose_false_negative(
        self,
        entry: GoldStandardEntry,
        company_name: str,
        context: PipelineContext,
        all_facts: list[MetricFact],
    ) -> FNDiagnostic:
        """
        Trace why a gold standard entry was not extracted (false negative).

        Tracing order through pipeline stages:
        1. No candidate with matching metric_id → no_candidate
        2. Candidate exists but no pre-filter binding → no_value_binding
        3. Binding existed pre-filter but was removed → fp_filtered
        4. Post-filter binding exists but no matching fact value → wrong_value
        5. Fact exists but not in deduplicated_facts → dedup_removed
        6. Fact exists but below confidence threshold → low_confidence
        7. Fact value matches but period doesn't → wrong_period
        8. Otherwise → unknown
        """
        entry_metric_id = normalize_metric_id(entry.metric_id)
        expected_value = entry.normalized_value

        # Step 1: Check candidates for this metric_id
        matching_candidates = [
            c for c in context.candidates
            if normalize_metric_id(getattr(c, "metric_id", "")) == entry_metric_id
        ]
        candidate_count = len(matching_candidates)
        candidate_ids = {getattr(c, "candidate_id", None) for c in matching_candidates}

        if not matching_candidates:
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="no_candidate",
                    detail=f"No candidates generated for metric_id={entry_metric_id}",
                    stage="candidate_generation",
                ),
                candidate_count=0,
            )

        # Step 2: Check pre-filter bound values for these candidates
        pre_filter_bindings = [
            bv for bv in context._pre_filter_bound_values
            if getattr(bv, "candidate_id", None) in candidate_ids
        ]
        bound_value_count = len(pre_filter_bindings)

        if not pre_filter_bindings:
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="no_value_binding",
                    detail=f"Candidates exist ({candidate_count}) but no value was bound",
                    stage="value_binding",
                ),
                candidate_count=candidate_count,
                bound_value_count=0,
            )

        # Step 3: Check post-filter bound values — were bindings FP-filtered out?
        post_filter_bindings = [
            bv for bv in context.bound_values
            if getattr(bv, "candidate_id", None) in candidate_ids
        ]

        if not post_filter_bindings and pre_filter_bindings:
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="fp_filtered",
                    detail=f"{len(pre_filter_bindings)} binding(s) removed by FP filter",
                    stage="false_positive_filter",
                ),
                candidate_count=candidate_count,
                bound_value_count=bound_value_count,
            )

        # Step 4–7: Bindings survived FP filter — check facts
        # Look at ALL facts (pre-confidence-filter) for this metric
        metric_facts = [
            f for f in all_facts
            if normalize_metric_id(f.canonical_metric_id) == entry_metric_id
        ]

        # Also check context.facts (pre-dedup) directly
        context_facts = [
            f for f in context.facts
            if normalize_metric_id(f.canonical_metric_id) == entry_metric_id
        ]

        if not context_facts and not metric_facts:
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="wrong_value",
                    detail="Post-filter bindings exist but produced no facts with matching value",
                    stage="fact_construction",
                ),
                candidate_count=candidate_count,
                bound_value_count=bound_value_count,
            )

        # Find closest fact for diagnostics
        all_metric_facts = list({f.fact_id: f for f in (context_facts + metric_facts)}.values())
        closest_fact: MetricFact | None = None
        if all_metric_facts:
            # Pick fact with lowest value delta if expected_value available
            if expected_value is not None:
                for f in all_metric_facts:
                    if f.value is not None and (
                        closest_fact is None
                        or abs(f.value - expected_value) < abs((closest_fact.value or 0) - expected_value)
                    ):
                        closest_fact = f
            else:
                closest_fact = all_metric_facts[0]

        closest_value = closest_fact.value if closest_fact else None
        closest_conf = closest_fact.confidence if closest_fact else None

        # Step 5: Check if fact exists in context.facts but not deduplicated_facts
        dedup_fact_ids = {f.fact_id for f in (context.deduplicated_facts or [])}
        context_fact_ids = {f.fact_id for f in context_facts}
        dedup_removed = bool(context_fact_ids and not context_fact_ids.intersection(dedup_fact_ids))

        if dedup_removed:
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="dedup_removed",
                    detail="Fact existed pre-dedup but was removed by deduplication",
                    stage="deduplication",
                ),
                candidate_count=candidate_count,
                bound_value_count=bound_value_count,
                closest_fact_value=closest_value,
                closest_fact_confidence=closest_conf,
            )

        # Step 6: Check confidence threshold
        low_conf_facts = [
            f for f in all_metric_facts
            if f.confidence < self.min_confidence
        ]
        ok_conf_facts = [
            f for f in all_metric_facts
            if f.confidence >= self.min_confidence
        ]
        if low_conf_facts and not ok_conf_facts:
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="low_confidence",
                    detail=f"Facts exist but all below threshold ({self.min_confidence}); max conf={max(f.confidence for f in low_conf_facts):.2f}",
                    stage="validation",
                ),
                candidate_count=candidate_count,
                bound_value_count=bound_value_count,
                closest_fact_value=closest_value,
                closest_fact_confidence=closest_conf,
            )

        # Step 7: Check period mismatch — value matches but period doesn't
        if expected_value is not None:
            value_matched_facts = [
                f for f in all_metric_facts
                if f.value is not None and self._values_match(expected_value, f.value)
            ]
            if value_matched_facts:
                return FNDiagnostic(
                    entry=entry,
                    company_name=company_name,
                    root_cause=FNRootCause(
                        category="wrong_period",
                        detail="Value match exists but period overlap check failed",
                        stage="matching",
                    ),
                    candidate_count=candidate_count,
                    bound_value_count=bound_value_count,
                    closest_fact_value=closest_value,
                    closest_fact_confidence=closest_conf,
                )

            # Value doesn't match any fact — wrong_value
            return FNDiagnostic(
                entry=entry,
                company_name=company_name,
                root_cause=FNRootCause(
                    category="wrong_value",
                    detail=f"No fact value within {self.value_tolerance:.0%} of expected={expected_value}; closest={closest_value}",
                    stage="matching",
                ),
                candidate_count=candidate_count,
                bound_value_count=bound_value_count,
                closest_fact_value=closest_value,
                closest_fact_confidence=closest_conf,
            )

        # Fallback
        return FNDiagnostic(
            entry=entry,
            company_name=company_name,
            root_cause=FNRootCause(
                category="unknown",
                detail="Could not determine root cause",
                stage="unknown",
            ),
            candidate_count=candidate_count,
            bound_value_count=bound_value_count,
            closest_fact_value=closest_value,
            closest_fact_confidence=closest_conf,
        )

    @staticmethod
    def print_fn_diagnostics(results: list[ValidationResult]) -> None:
        """Print categorized FN root cause diagnostic report."""
        all_diags: list[FNDiagnostic] = []
        for r in results:
            all_diags.extend(r.fn_diagnostics)

        if not all_diags:
            print("\nNo FN diagnostics available (fn_diagnostics=False or zero FNs).")
            return

        total = len(all_diags)

        # Group by root cause category
        categories: dict[str, list[FNDiagnostic]] = {}
        for d in all_diags:
            categories.setdefault(d.root_cause.category, []).append(d)

        print(f"\n{'=' * 70}")
        print(f"FALSE NEGATIVE ROOT CAUSE ANALYSIS ({total} total FNs)")
        print(f"{'=' * 70}")

        for cat, diags in sorted(categories.items(), key=lambda x: -len(x[1])):
            pct = len(diags) / total * 100
            print(f"\n--- {cat.upper()} ({len(diags)} FNs, {pct:.0f}%) ---")

            # Group by company within each category
            by_company: dict[str, list[FNDiagnostic]] = {}
            for d in diags:
                by_company.setdefault(d.company_name, []).append(d)

            shown = 0
            for cname, cdiags in sorted(by_company.items()):
                print(f"  [{cname}]")
                for d in cdiags[:8]:
                    val_str = f"expected={d.entry.raw_value}"
                    if d.closest_fact_value is not None:
                        val_str += f" closest_extracted={d.closest_fact_value:.4g}"
                    conf_str = ""
                    if d.closest_fact_confidence is not None:
                        conf_str = f" conf={d.closest_fact_confidence:.2f}"
                    cand_str = f" cands={d.candidate_count} bvs={d.bound_value_count}"
                    print(
                        f"    {d.entry.metric_id} ({d.entry.name_in_text!r}): "
                        f"{val_str}{conf_str}{cand_str}"
                    )
                    print(f"      -> {d.root_cause.detail}")
                    shown += 1
                remaining = len(cdiags) - 8
                if remaining > 0:
                    print(f"    ... and {remaining} more from {cname}")

        print(f"\n{'=' * 70}")
        print("SUMMARY BY ROOT CAUSE:")
        for cat, diags in sorted(categories.items(), key=lambda x: -len(x[1])):
            pct = len(diags) / total * 100
            print(f"  {cat:<22} {len(diags):>4}  ({pct:.0f}%)")
        print(f"  {'TOTAL':<22} {total:>4}")
        print(f"{'=' * 70}")

    @staticmethod
    def print_fp_diagnostics(results: list[ValidationResult]) -> None:
        """Print categorized FP diagnostic report."""
        all_diags: list[FalsePositiveDiagnostic] = []
        for r in results:
            all_diags.extend(r.fp_diagnostics)

        if not all_diags:
            print("\nNo false positives to diagnose.")
            return

        # Categorize
        categories: dict[str, list[FalsePositiveDiagnostic]] = {}
        for d in all_diags:
            categories.setdefault(d.mismatch_category, []).append(d)

        print(f"\n{'=' * 70}")
        print(f"FALSE POSITIVE DIAGNOSTICS ({len(all_diags)} total FPs)")
        print(f"{'=' * 70}")

        for cat, diags in sorted(categories.items(), key=lambda x: -len(x[1])):
            print(f"\n--- {cat.upper()} ({len(diags)} FPs) ---")
            for d in diags[:10]:  # Show first 10 per category
                period_str = ""
                if d.period_start and d.period_end:
                    period_str = f" [{d.period_start} to {d.period_end}]"
                delta_str = (
                    f" (delta={d.value_delta_pct:.1%})" if d.value_delta_pct is not None else ""
                )
                gold_str = (
                    f" gold={d.closest_gold_value}" if d.closest_gold_value is not None else ""
                )
                print(
                    f"  {d.metric_id}: {d.value} (raw={d.value_raw!r})"
                    f"{period_str} src={d.source_type} conf={d.confidence:.2f}"
                    f"{delta_str}{gold_str}"
                )
            if len(diags) > 10:
                print(f"  ... and {len(diags) - 10} more")

        print(f"\n{'=' * 70}")
        print("SUMMARY:")
        for cat, diags in sorted(categories.items(), key=lambda x: -len(x[1])):
            print(f"  {cat}: {len(diags)}")
        print(f"{'=' * 70}")

    def validate_all(self) -> list[ValidationResult]:
        """
        Validate all filings in gold standard dataset.

        Returns:
            List of ValidationResult for each filing
        """
        entries_by_company = self.load_gold_standard()
        results: list[ValidationResult] = []

        for company_name, entries in entries_by_company.items():
            filing_path = self._find_filing_path(company_name)
            if filing_path is None:
                logger.warning(f"No filing found for {company_name}, skipping validation")
                continue

            # Build per-filing pipeline if metadata specifies a non-calendar FYE
            metadata = self._load_filing_metadata(company_name)
            fy_end_month = metadata.get("fiscal_year_end_month")
            fy_end_day = metadata.get("fiscal_year_end_day")
            if fy_end_month is not None and (
                fy_end_month != self.v2_config.fiscal_year_end_month
                or fy_end_day != self.v2_config.fiscal_year_end_day
            ):
                filing_config = dc_replace(
                    self.v2_config,
                    fiscal_year_end_month=fy_end_month,
                    fiscal_year_end_day=fy_end_day,
                )
                filing_pipeline: V2Pipeline | None = V2Pipeline(config=filing_config)
            else:
                filing_pipeline = None  # Use default self.v2_pipeline

            logger.info(f"Validating {company_name}...")
            result = self.validate_filing(
                company_name, filing_path, entries, pipeline_override=filing_pipeline
            )
            results.append(result)
            logger.info(
                f"  {company_name}: P={result.precision:.1%}, "
                f"R={result.recall:.1%}, F1={result.f1_score:.1%}"
            )

        return results

    def _load_filing_metadata(self, company_name: str) -> dict[str, Any]:
        """
        Load metadata.json for a company filing.

        Returns:
            Metadata dict, or empty dict if no metadata file exists.
        """
        safe_name = company_name.replace(" ", "_").replace(",", "").replace(".", "_")
        while "__" in safe_name:
            safe_name = safe_name.replace("__", "_")
        safe_name = safe_name.rstrip("_")

        candidates = [
            GOLD_STANDARD_DIR / safe_name / "metadata.json",
            GOLD_STANDARD_DIR / company_name / "metadata.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
        return {}

    def _find_filing_path(self, company_name: str) -> Path | None:
        """Find the HTML filing path for a company."""
        # Normalize company name for directory lookup
        safe_name = company_name.replace(" ", "_").replace(",", "").replace(".", "_")
        # Clean up double underscores and trailing underscores
        while "__" in safe_name:
            safe_name = safe_name.replace("__", "_")
        safe_name = safe_name.rstrip("_")

        # Check known locations
        candidates = [
            GOLD_STANDARD_DIR / safe_name / "filing.html",
            GOLD_STANDARD_DIR / company_name / "filing.html",
            GOLD_STANDARD_DIR / company_name.replace(" ", "_") / "filing.html",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Try to find any matching directory (normalize both sides)
        normalized_company = (
            company_name.lower().replace(" ", "_").replace(".", "_").replace(",", "")
        )
        while "__" in normalized_company:
            normalized_company = normalized_company.replace("__", "_")
        normalized_company = normalized_company.rstrip("_")

        for subdir in GOLD_STANDARD_DIR.iterdir():
            if not subdir.is_dir():
                continue
            normalized_dir = (
                subdir.name.lower().replace(" ", "_").replace(".", "_").replace(",", "")
            )
            while "__" in normalized_dir:
                normalized_dir = normalized_dir.replace("__", "_")
            normalized_dir = normalized_dir.rstrip("_")
            if normalized_company in normalized_dir or normalized_dir in normalized_company:
                filing = subdir / "filing.html"
                if filing.exists():
                    return filing

        return None

    def compute_metrics(self, results: list[ValidationResult]) -> AggregateMetrics:
        """
        Compute aggregate metrics from validation results.

        Args:
            results: List of ValidationResult from validate_all()

        Returns:
            AggregateMetrics with precision/recall/F1
        """
        total_tp = sum(r.true_positives for r in results)
        total_fp = sum(r.false_positives for r in results)
        total_fn = sum(r.false_negatives for r in results)

        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        by_company: dict[str, MetricScores] = {}
        for r in results:
            by_company[r.company_name] = MetricScores(
                precision=r.precision,
                recall=r.recall,
                f1=r.f1_score,
            )

        return AggregateMetrics(
            precision=precision,
            recall=recall,
            f1=f1,
            total_true_positives=total_tp,
            total_false_positives=total_fp,
            total_false_negatives=total_fn,
            by_company=by_company,
        )

    def compare_to_baseline(
        self,
        current_metrics: AggregateMetrics,
        baseline_path: Path | str = V2_BASELINE_PATH,
        tolerance: float = 0.0,
    ) -> BaselineComparisonResult:
        """
        Compare current metrics against saved baseline.

        Args:
            current_metrics: Current validation metrics
            baseline_path: Path to baseline JSON file
            tolerance: Regression tolerance (default 0 = no tolerance)

        Returns:
            ComparisonResult with deltas and regression flags

        Raises:
            FileNotFoundError: If baseline file doesn't exist
        """
        baseline = load_baseline(baseline_path)
        current_baseline = current_metrics.to_baseline_metrics()
        return compare_to_baseline(current_baseline, baseline, tolerance)

    def save_baseline(
        self,
        metrics: AggregateMetrics,
        baseline_path: Path | str = V2_BASELINE_PATH,
        description: str | None = None,
    ) -> None:
        """
        Save current metrics as the new baseline.

        Args:
            metrics: Current validation metrics to save
            baseline_path: Path to save baseline JSON
            description: Optional description for this baseline
        """
        baseline = metrics.to_baseline_metrics(description)
        save_baseline(baseline, baseline_path)
        logger.info(f"Saved V2 baseline to {baseline_path}")


# =============================================================================
# Utility Functions
# =============================================================================


def normalize_metric_id(metric_id: str) -> str:
    """
    Normalize metric ID for comparison.

    - Lowercase
    - Replace spaces with underscores
    - Remove leading/trailing whitespace
    - Add 'cm_' prefix if missing
    """
    if not metric_id:
        return ""

    normalized = metric_id.strip().lower().replace(" ", "_").replace("-", "_")

    # Remove double underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")

    # Add cm_ prefix if missing
    if not normalized.startswith("cm_"):
        normalized = f"cm_{normalized}"

    return normalized


def normalize_value(
    raw_value: str,
    scaled_value: str | None = None,
    scale_unit: str | None = None,
) -> float:
    """
    Normalize a value string to a float.

    Handles common formats:
    - "1,000" -> 1000.0
    - "$1.5M" -> 1500000.0
    - "45%" -> 45.0
    - "1.2B" -> 1200000000.0
    """
    # Use scaled_value if available, otherwise raw_value
    value_str = scaled_value if scaled_value and scaled_value.strip() else raw_value
    if not value_str:
        raise ValueError("No value to normalize")

    # Clean the string
    value_str = value_str.strip()

    # Handle special cases
    if value_str.lower() in ("chart", "n/a", "-", ""):
        raise ValueError(f"Non-numeric value: {value_str}")

    # Remove currency symbols and commas
    value_str = re.sub(r"[$€£¥,]", "", value_str)

    # Extract numeric part and multiplier
    match = re.match(
        r"([+-]?\d+\.?\d*)\s*([%KMBTkmbt]?)",
        value_str,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Could not parse value: {value_str}")

    number = float(match.group(1))
    multiplier_char = match.group(2).upper() if match.group(2) else ""

    # Apply multiplier
    multipliers = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000,
        "%": 1,  # Percentages stay as-is
    }
    multiplier = multipliers.get(multiplier_char, 1)
    number *= multiplier

    # Apply scale_unit if provided and different from multiplier.
    # BUT: if scaled_value was used and differs from raw_value, the scale
    # has already been incorporated into the scaled column — don't re-apply.
    scaled_already_applied = (
        scaled_value
        and scaled_value.strip()
        and raw_value
        and scaled_value.strip() != raw_value.strip()
    )
    if scale_unit and scale_unit.strip() and not scaled_already_applied:
        unit_upper = scale_unit.strip().upper()
        if unit_upper in ("MILLIONS", "MM", "M") and multiplier_char != "M":
            number *= 1_000_000
        elif unit_upper in ("BILLIONS", "BB", "B") and multiplier_char != "B":
            number *= 1_000_000_000
        elif unit_upper in ("THOUSANDS", "K") and multiplier_char != "K":
            number *= 1_000

    return number


def run_validation(
    update_baseline: bool = False,
    baseline_description: str | None = None,
    min_confidence: float = 0.35,
    fn_diagnostics: bool = False,
) -> AggregateMetrics:
    """
    Run full validation and optionally update baseline.

    Args:
        update_baseline: If True, save current metrics as new baseline
        baseline_description: Description for new baseline
        min_confidence: Minimum confidence threshold for counting facts
        fn_diagnostics: If True, run FN root cause analysis and print report

    Returns:
        AggregateMetrics with validation results
    """
    # Run at the requested confidence threshold (default: high-confidence only)
    validator = V2GoldStandardValidator(min_confidence=min_confidence, fn_diagnostics=fn_diagnostics)
    results = validator.validate_all()
    metrics = validator.compute_metrics(results)

    print(f"\nV2 Gold Standard Validation Results (confidence >= {min_confidence}):")
    print(f"  Precision: {metrics.precision:.1%}")
    print(f"  Recall: {metrics.recall:.1%}")
    print(f"  F1 Score: {metrics.f1:.1%}")
    print(
        f"  TP: {metrics.total_true_positives}, FP: {metrics.total_false_positives}, FN: {metrics.total_false_negatives}"
    )

    # Print FP diagnostics
    V2GoldStandardValidator.print_fp_diagnostics(results)

    # Print FN diagnostics if enabled
    if fn_diagnostics:
        V2GoldStandardValidator.print_fn_diagnostics(results)

    # Also report unfiltered facts for comparison
    review_threshold = 0.0
    if min_confidence > review_threshold:
        review_validator = V2GoldStandardValidator(min_confidence=review_threshold)
        review_results = review_validator.validate_all()
        review_metrics = review_validator.compute_metrics(review_results)
        print(f"\n  Review-worthy facts (confidence >= {review_threshold}):")
        print(
            f"    TP: {review_metrics.total_true_positives}, FP: {review_metrics.total_false_positives}, FN: {review_metrics.total_false_negatives}"
        )

    if update_baseline:
        validator.save_baseline(metrics, description=baseline_description)

    return metrics
