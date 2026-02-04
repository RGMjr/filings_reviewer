"""
V1 vs V2 Extraction Pipeline Comparison Framework.

Provides tools to compare extraction results between V1 and V2 pipelines
for validation, benchmarking, and migration planning.

Usage:
    from src.extraction_v2.comparison import V1V2Comparator

    comparator = V1V2Comparator()
    result = comparator.compare_filing(
        filing_id=123,
        html_path=Path("filing.html")
    )
    print(f"V1: {result.v1_fact_count}, V2: {result.v2_fact_count}")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.extraction.html_segmenter import HTMLSegmenter
from src.extraction.metric_classifier import MetricClassifier
from src.extraction.models import MetricValue, SourceSegment
from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.value_extractor import ValueExtractor
from src.extraction_v2.models import MetricFact
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline

logger = logging.getLogger(__name__)


@dataclass
class FactMatch:
    """A matched fact pair between V1 and V2."""

    v1_value: MetricValue | None
    v2_fact: MetricFact | None
    metric_id: str
    match_type: str  # "exact", "fuzzy", "v1_only", "v2_only"
    value_delta: float | None = None  # Percentage difference if both present


@dataclass
class MetricBreakdown:
    """Per-metric comparison statistics."""

    metric_id: str
    v1_count: int = 0
    v2_count: int = 0
    matches: int = 0
    v1_only: int = 0
    v2_only: int = 0

    @property
    def coverage_ratio(self) -> float:
        """V2 coverage of V1 facts (recall)."""
        if self.v1_count == 0:
            return 1.0 if self.v2_count == 0 else 0.0
        return self.matches / self.v1_count


@dataclass
class ComparisonResult:
    """Result of comparing V1 and V2 extraction on a single filing."""

    filing_id: int
    html_path: str

    # Fact counts
    v1_fact_count: int
    v2_fact_count: int

    # Timing (milliseconds)
    v1_time_ms: int
    v2_time_ms: int

    # Match statistics
    matching_facts: int  # Same metric + value within tolerance
    v2_only_facts: int  # New facts V2 found
    v1_only_facts: int  # Facts V1 found but V2 missed

    # Per-metric breakdown
    metrics_breakdown: dict[str, MetricBreakdown] = field(default_factory=dict)

    # Detailed matches (optional, for debugging)
    fact_matches: list[FactMatch] = field(default_factory=list)

    # Errors during comparison
    v1_error: str | None = None
    v2_error: str | None = None

    @property
    def success(self) -> bool:
        """Both pipelines completed without error."""
        return self.v1_error is None and self.v2_error is None

    @property
    def v2_coverage_ratio(self) -> float:
        """Ratio of V1 facts covered by V2 (recall)."""
        if self.v1_fact_count == 0:
            return 1.0
        return self.matching_facts / self.v1_fact_count

    @property
    def v2_discovery_count(self) -> int:
        """Number of additional facts V2 found."""
        return self.v2_only_facts

    @property
    def speedup_ratio(self) -> float:
        """V2 speed relative to V1 (>1 means V2 is faster)."""
        if self.v2_time_ms == 0:
            return 0.0
        return self.v1_time_ms / self.v2_time_ms

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Filing {self.filing_id}: {self.html_path}",
            f"  V1: {self.v1_fact_count} facts in {self.v1_time_ms}ms",
            f"  V2: {self.v2_fact_count} facts in {self.v2_time_ms}ms",
            f"  Matching: {self.matching_facts}, V2-only: {self.v2_only_facts}, V1-only: {self.v1_only_facts}",
            f"  Coverage: {self.v2_coverage_ratio:.1%}, Speedup: {self.speedup_ratio:.2f}x",
        ]
        if self.v1_error:
            lines.append(f"  V1 Error: {self.v1_error}")
        if self.v2_error:
            lines.append(f"  V2 Error: {self.v2_error}")
        return "\n".join(lines)


@dataclass
class BatchComparisonResult:
    """Result of comparing V1 and V2 on multiple filings."""

    results: list[ComparisonResult]

    @property
    def total_v1_facts(self) -> int:
        return sum(r.v1_fact_count for r in self.results)

    @property
    def total_v2_facts(self) -> int:
        return sum(r.v2_fact_count for r in self.results)

    @property
    def total_matching(self) -> int:
        return sum(r.matching_facts for r in self.results)

    @property
    def total_v1_time_ms(self) -> int:
        return sum(r.v1_time_ms for r in self.results)

    @property
    def total_v2_time_ms(self) -> int:
        return sum(r.v2_time_ms for r in self.results)

    @property
    def overall_coverage(self) -> float:
        """Overall V2 coverage of V1 facts."""
        if self.total_v1_facts == 0:
            return 1.0
        return self.total_matching / self.total_v1_facts

    @property
    def overall_speedup(self) -> float:
        """Overall V2 speedup ratio."""
        if self.total_v2_time_ms == 0:
            return 0.0
        return self.total_v1_time_ms / self.total_v2_time_ms

    def summary(self) -> str:
        """Human-readable batch summary."""
        lines = [
            f"Batch Comparison: {len(self.results)} filings",
            f"  V1 Total: {self.total_v1_facts} facts in {self.total_v1_time_ms}ms",
            f"  V2 Total: {self.total_v2_facts} facts in {self.total_v2_time_ms}ms",
            f"  Overall Coverage: {self.overall_coverage:.1%}",
            f"  Overall Speedup: {self.overall_speedup:.2f}x",
        ]
        return "\n".join(lines)


class V1V2Comparator:
    """
    Compare V1 and V2 extraction pipelines on the same HTML content.

    This class runs both pipelines on the same filing HTML and compares
    the extracted values to measure:
    - Fact coverage (does V2 find what V1 found?)
    - New discoveries (what does V2 find that V1 missed?)
    - Performance (execution time comparison)
    """

    def __init__(
        self,
        v2_config: PipelineConfig | None = None,
        value_tolerance: float = 0.02,
    ):
        """
        Initialize comparator.

        Args:
            v2_config: Configuration for V2 pipeline
            value_tolerance: Tolerance for matching values (default 2%)
        """
        self.v2_config = v2_config or PipelineConfig()
        self.value_tolerance = value_tolerance

        # V2 pipeline
        self.v2_pipeline = V2Pipeline(config=self.v2_config)

        # V1 components (we'll use them directly without database)
        self.v1_segmenter = HTMLSegmenter()
        self.v1_classifier = MetricClassifier()
        self.v1_enricher = SegmentEnricher()
        self.v1_value_extractor = ValueExtractor(llm_client=None)

    def compare_filing(
        self,
        filing_id: int,
        html_path: Path | str,
        company_id: int = 0,
    ) -> ComparisonResult:
        """
        Compare V1 and V2 extraction on a single filing.

        Args:
            filing_id: Filing ID (for reference, not database lookup)
            html_path: Path to HTML file
            company_id: Company ID for V1 extraction

        Returns:
            ComparisonResult with comparison statistics
        """
        html_path = Path(html_path)

        result = ComparisonResult(
            filing_id=filing_id,
            html_path=str(html_path),
            v1_fact_count=0,
            v2_fact_count=0,
            v1_time_ms=0,
            v2_time_ms=0,
            matching_facts=0,
            v2_only_facts=0,
            v1_only_facts=0,
        )

        # Run V1 extraction
        v1_values: list[MetricValue] = []
        v1_start = time.time()
        try:
            v1_values = self._run_v1_extraction(
                filing_id=filing_id,
                html_path=html_path,
                company_id=company_id,
            )
            result.v1_fact_count = len(v1_values)
        except Exception as e:
            logger.error(f"V1 extraction failed for {html_path}: {e}")
            result.v1_error = str(e)
        result.v1_time_ms = int((time.time() - v1_start) * 1000)

        # Run V2 extraction
        v2_facts: list[MetricFact] = []
        v2_start = time.time()
        try:
            v2_result = self.v2_pipeline.process(
                html_path=html_path,
                filing_id=filing_id,
            )
            if v2_result.success:
                v2_facts = v2_result.facts
                result.v2_fact_count = len(v2_facts)
            else:
                result.v2_error = v2_result.error_message or "Unknown V2 error"
        except Exception as e:
            logger.error(f"V2 extraction failed for {html_path}: {e}")
            result.v2_error = str(e)
        result.v2_time_ms = int((time.time() - v2_start) * 1000)

        # Compare if both succeeded
        if result.v1_error is None and result.v2_error is None:
            self._compare_facts(v1_values, v2_facts, result)

        return result

    def compare_batch(
        self,
        filings: list[tuple[int, Path | str, int]],
    ) -> BatchComparisonResult:
        """
        Compare V1 and V2 on multiple filings.

        Args:
            filings: List of (filing_id, html_path, company_id) tuples

        Returns:
            BatchComparisonResult with aggregated statistics
        """
        results = []
        for filing_id, html_path, company_id in filings:
            logger.info(f"Comparing filing {filing_id}: {html_path}")
            result = self.compare_filing(
                filing_id=filing_id,
                html_path=html_path,
                company_id=company_id,
            )
            results.append(result)

        return BatchComparisonResult(results=results)

    def _run_v1_extraction(
        self,
        filing_id: int,
        html_path: Path,
        company_id: int,
    ) -> list[MetricValue]:
        """
        Run V1 extraction components directly on HTML file.

        This bypasses the database to allow fair comparison
        on the same HTML content.
        """
        # Step 1: Segment HTML
        segments = self.v1_segmenter.segment_filing(
            filing_id=filing_id,
            html_path=str(html_path),
        )

        if not segments:
            return []

        # Step 2: Classify segments
        classified_segments = self.v1_classifier.classify_batch(segments)

        # Step 3: Enrich segments
        self.v1_enricher.enrich_batch(classified_segments)

        # Step 4: Select segments (tiered prioritization)
        selected_segments = self._select_v1_segments(classified_segments)

        # Step 5: Extract values
        all_values: list[MetricValue] = []
        for seg in selected_segments:
            # Set a fake segment ID for the value extractor
            seg.source_segment_id = seg.sequence_index
            values = self.v1_value_extractor.extract_from_segment(
                seg,
                company_id=company_id,
            )
            all_values.extend(values)

        return all_values

    def _select_v1_segments(
        self,
        segments: list[SourceSegment],
    ) -> list[SourceSegment]:
        """
        Select segments using V1 tiered prioritization.

        Mirrors the logic in ExtractionPipeline._select_segments_tiered.
        """
        RICHNESS_THRESHOLD = 6.0
        MEDIUM_THRESHOLD = 4.0
        MAX_HIGH_RICHNESS = 30
        MAX_MEDIUM_RICHNESS = 40
        MAX_TOTAL = 80

        selected_ids: set[int] = set()
        result: list[SourceSegment] = []

        # Tier 1: High richness
        high_richness = sorted(
            [s for s in segments if (s.richness_score or 0) >= RICHNESS_THRESHOLD],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_HIGH_RICHNESS]

        for seg in high_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        # Tier 2: Medium richness
        medium_richness = sorted(
            [
                s
                for s in segments
                if MEDIUM_THRESHOLD <= (s.richness_score or 0) < RICHNESS_THRESHOLD
            ],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_MEDIUM_RICHNESS]

        for seg in medium_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        # Tier 3: Critical flags
        critical = [
            s
            for s in segments
            if (s.contains_definition_flag or s.contains_methodology_flag)
            and id(s) not in selected_ids
        ]

        for seg in critical:
            if len(result) >= MAX_TOTAL:
                break
            result.append(seg)
            selected_ids.add(id(seg))

        return result

    def _compare_facts(
        self,
        v1_values: list[MetricValue],
        v2_facts: list[MetricFact],
        result: ComparisonResult,
    ) -> None:
        """
        Compare V1 values with V2 facts and populate match statistics.
        """
        # Index V2 facts by metric_id for efficient lookup
        v2_by_metric: dict[str, list[MetricFact]] = {}
        for fact in v2_facts:
            metric_id = fact.canonical_metric_id
            if metric_id not in v2_by_metric:
                v2_by_metric[metric_id] = []
            v2_by_metric[metric_id].append(fact)

        # Track which V2 facts have been matched
        matched_v2_ids: set[str] = set()

        # Try to match each V1 value
        for v1_value in v1_values:
            metric_id = v1_value.metric_id
            v2_candidates = v2_by_metric.get(metric_id, [])

            matched = False
            for v2_fact in v2_candidates:
                if v2_fact.fact_id in matched_v2_ids:
                    continue

                if self._values_match(v1_value, v2_fact):
                    matched = True
                    matched_v2_ids.add(v2_fact.fact_id)
                    result.matching_facts += 1
                    result.fact_matches.append(
                        FactMatch(
                            v1_value=v1_value,
                            v2_fact=v2_fact,
                            metric_id=metric_id,
                            match_type="exact" if self._exact_match(v1_value, v2_fact) else "fuzzy",
                            value_delta=self._compute_delta(v1_value, v2_fact),
                        )
                    )
                    break

            if not matched:
                result.v1_only_facts += 1
                result.fact_matches.append(
                    FactMatch(
                        v1_value=v1_value,
                        v2_fact=None,
                        metric_id=metric_id,
                        match_type="v1_only",
                    )
                )

            # Update metric breakdown
            if metric_id not in result.metrics_breakdown:
                result.metrics_breakdown[metric_id] = MetricBreakdown(metric_id=metric_id)
            result.metrics_breakdown[metric_id].v1_count += 1
            if matched:
                result.metrics_breakdown[metric_id].matches += 1
            else:
                result.metrics_breakdown[metric_id].v1_only += 1

        # Count V2-only facts
        for metric_id, v2_list in v2_by_metric.items():
            if metric_id not in result.metrics_breakdown:
                result.metrics_breakdown[metric_id] = MetricBreakdown(metric_id=metric_id)

            for v2_fact in v2_list:
                result.metrics_breakdown[metric_id].v2_count += 1
                if v2_fact.fact_id not in matched_v2_ids:
                    result.v2_only_facts += 1
                    result.metrics_breakdown[metric_id].v2_only += 1
                    result.fact_matches.append(
                        FactMatch(
                            v1_value=None,
                            v2_fact=v2_fact,
                            metric_id=metric_id,
                            match_type="v2_only",
                        )
                    )

    def _values_match(
        self,
        v1_value: MetricValue,
        v2_fact: MetricFact,
    ) -> bool:
        """
        Check if V1 and V2 values match within tolerance.

        Matching criteria:
        - Same metric_id
        - Values within tolerance (for numeric values)
        - Overlapping period (if both have periods)
        """
        # Metric ID must match
        if v1_value.metric_id != v2_fact.canonical_metric_id:
            return False

        # Compare numeric values
        v1_num = v1_value.value_numeric
        v2_num = v2_fact.value

        if v1_num is not None and v2_num is not None:
            # Convert Decimal to float for comparison
            v1_float = float(v1_num)
            v2_float = float(v2_num)

            # Check tolerance
            if abs(v1_float) > 0.001:  # Avoid division by zero
                delta = abs(v2_float - v1_float) / abs(v1_float)
                if delta > self.value_tolerance:
                    return False
            elif abs(v2_float) > 0.001:
                delta = abs(v2_float - v1_float) / abs(v2_float)
                if delta > self.value_tolerance:
                    return False
            else:
                # Both near zero
                if abs(v2_float - v1_float) > 0.01:
                    return False

        # Period overlap check (optional, if both have periods)
        if (
            v1_value.period_start
            and v1_value.period_end
            and v2_fact.period_start
            and v2_fact.period_end
        ):
            # Periods should overlap
            if (
                v1_value.period_end < v2_fact.period_start
                or v2_fact.period_end < v1_value.period_start
            ):
                return False

        return True

    def _exact_match(
        self,
        v1_value: MetricValue,
        v2_fact: MetricFact,
    ) -> bool:
        """Check if values match exactly (no tolerance)."""
        v1_num = v1_value.value_numeric
        v2_num = v2_fact.value

        if v1_num is not None and v2_num is not None:
            return abs(float(v1_num) - float(v2_num)) < 0.0001
        return False

    def _compute_delta(
        self,
        v1_value: MetricValue,
        v2_fact: MetricFact,
    ) -> float | None:
        """Compute percentage difference between values."""
        v1_num = v1_value.value_numeric
        v2_num = v2_fact.value

        if v1_num is not None and v2_num is not None:
            v1_float = float(v1_num)
            v2_float = float(v2_num)

            if abs(v1_float) > 0.001:
                return (v2_float - v1_float) / abs(v1_float)
        return None


def compare_filing_quick(
    filing_id: int,
    html_path: Path | str,
    company_id: int = 0,
) -> ComparisonResult:
    """
    Quick comparison of V1 vs V2 on a single filing.

    Convenience function for one-off comparisons.
    """
    comparator = V1V2Comparator()
    return comparator.compare_filing(
        filing_id=filing_id,
        html_path=html_path,
        company_id=company_id,
    )
