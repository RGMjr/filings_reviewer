"""
Tests for V2 Deduplication Stage.

Tests the grouping of duplicate facts, primary selection based on source quality,
and alternate evidence linking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.extraction_v2.models import (
    EvidencePack,
    MetricFact,
    PeriodType,
    Scope,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.stages.deduplication import (
    SOURCE_QUALITY_RANK,
    DeduplicationStage,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@dataclass
class MockPipelineConfig:
    """Mock pipeline config for testing."""

    value_tolerance: float = 0.02


@dataclass
class MockPipelineContext:
    """Mock pipeline context for testing."""

    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: MockPipelineConfig = field(default_factory=MockPipelineConfig)
    facts: list[MetricFact] = field(default_factory=list)
    deduplicated_facts: list[MetricFact] = field(default_factory=list)


def make_fact(
    fact_id: str = "fact-1",
    metric_id: str = "cm_average_order_value",
    value: float | None = 100.0,
    unit: Unit = Unit.CURRENCY,
    source_type: SourceType = SourceType.HTML_TABLE,
    confidence: float = 0.8,
    period_start: date | None = date(2024, 1, 1),
    period_end: date | None = date(2024, 12, 31),
    scope: Scope = Scope.COMPANY,
    cohort_def: str | None = None,
    customer_type: str | None = None,
) -> MetricFact:
    """Create a MetricFact for testing."""
    return MetricFact(
        fact_id=fact_id,
        doc_id="doc-1",
        canonical_metric_id=metric_id,
        value=value,
        value_raw=str(value) if value else "",
        unit=unit,
        source_type=source_type,
        source_locator=SourceLocator(),
        evidence_pack=EvidencePack(snippet_html="<mark>test</mark>"),
        confidence=confidence,
        period_type=PeriodType.ANNUAL,
        period_start=period_start,
        period_end=period_end,
        scope=scope,
        cohort_def=cohort_def,
        customer_type=customer_type,
    )


# ============================================================================
# Source Quality Ranking Tests
# ============================================================================


class TestSourceQualityRank:
    """Tests for source quality ranking constants."""

    def test_html_table_highest_quality(self) -> None:
        """HTML_TABLE should be highest quality."""
        assert SOURCE_QUALITY_RANK[SourceType.HTML_TABLE] == 4

    def test_text_second_quality(self) -> None:
        """TEXT should be second highest quality."""
        assert SOURCE_QUALITY_RANK[SourceType.TEXT] == 3

    def test_ocr_table_third_quality(self) -> None:
        """OCR_TABLE should be third quality."""
        assert SOURCE_QUALITY_RANK[SourceType.OCR_TABLE] == 2

    def test_chart_lowest_quality(self) -> None:
        """CHART should be lowest quality."""
        assert SOURCE_QUALITY_RANK[SourceType.CHART] == 1

    def test_ranking_order(self) -> None:
        """Verify complete ranking order."""
        assert (
            SOURCE_QUALITY_RANK[SourceType.HTML_TABLE]
            > SOURCE_QUALITY_RANK[SourceType.TEXT]
            > SOURCE_QUALITY_RANK[SourceType.OCR_TABLE]
            > SOURCE_QUALITY_RANK[SourceType.CHART]
        )


# ============================================================================
# Grouping Logic Tests
# ============================================================================


class TestGroupingLogic:
    """Tests for duplicate grouping logic."""

    def test_two_identical_facts_grouped(self) -> None:
        """Two facts with same identity should be grouped together."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="fact-1", value=100.0),
            make_fact(fact_id="fact-2", value=100.0),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_different_metric_id_not_grouped(self) -> None:
        """Facts with different metric_id should be in separate groups."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="fact-1", metric_id="cm_average_order_value", value=100.0),
            make_fact(fact_id="fact-2", metric_id="cm_lifetime_value_per_customer", value=100.0),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2
        assert len(groups[0]) == 1
        assert len(groups[1]) == 1

    def test_values_within_tolerance_grouped(self) -> None:
        """Facts with values within 2% tolerance should be grouped."""
        stage = DeduplicationStage()
        # 100 and 101 are within 2% (1% difference)
        facts = [
            make_fact(fact_id="fact-1", value=100.0),
            make_fact(fact_id="fact-2", value=101.0),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_values_outside_tolerance_not_grouped(self) -> None:
        """Facts with values outside 2% tolerance should not be grouped."""
        stage = DeduplicationStage()
        # 100 and 105 are outside 2% (5% difference)
        facts = [
            make_fact(fact_id="fact-1", value=100.0),
            make_fact(fact_id="fact-2", value=105.0),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2

    def test_different_periods_not_grouped(self) -> None:
        """Facts with different periods should be in separate groups."""
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-1",
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-2",
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
            ),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2

    def test_different_units_not_grouped(self) -> None:
        """Facts with different units should be in separate groups."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="fact-1", value=100.0, unit=Unit.CURRENCY),
            make_fact(fact_id="fact-2", value=100.0, unit=Unit.PERCENT),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2

    def test_different_scope_not_grouped(self) -> None:
        """Facts with different scope should be in separate groups."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="fact-1", scope=Scope.COMPANY),
            make_fact(fact_id="fact-2", scope=Scope.SEGMENT),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2

    def test_different_cohort_def_not_grouped(self) -> None:
        """Facts with different cohort_def should be in separate groups."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="fact-1", cohort_def="2022 cohort"),
            make_fact(fact_id="fact-2", cohort_def="2023 cohort"),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2

    def test_different_customer_type_not_grouped(self) -> None:
        """Facts with different customer_type should be in separate groups."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="fact-1", customer_type="Enterprise"),
            make_fact(fact_id="fact-2", customer_type="SMB"),
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        assert len(groups) == 2


# ============================================================================
# Primary Selection Tests
# ============================================================================


class TestPrimarySelection:
    """Tests for primary fact selection based on source quality."""

    def test_html_table_beats_text(self) -> None:
        """HTML_TABLE should be selected over TEXT."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="text", source_type=SourceType.TEXT, confidence=0.9),
            make_fact(fact_id="table", source_type=SourceType.HTML_TABLE, confidence=0.7),
        ]

        primary = stage._select_primary(facts)

        assert primary.fact_id == "table"

    def test_text_beats_ocr_table(self) -> None:
        """TEXT should be selected over OCR_TABLE."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="ocr", source_type=SourceType.OCR_TABLE, confidence=0.9),
            make_fact(fact_id="text", source_type=SourceType.TEXT, confidence=0.7),
        ]

        primary = stage._select_primary(facts)

        assert primary.fact_id == "text"

    def test_ocr_table_beats_chart(self) -> None:
        """OCR_TABLE should be selected over CHART."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="chart", source_type=SourceType.CHART, confidence=0.9),
            make_fact(fact_id="ocr", source_type=SourceType.OCR_TABLE, confidence=0.7),
        ]

        primary = stage._select_primary(facts)

        assert primary.fact_id == "ocr"

    def test_same_source_type_higher_confidence_wins(self) -> None:
        """When source type is same, higher confidence should win."""
        stage = DeduplicationStage()
        facts = [
            make_fact(fact_id="low", source_type=SourceType.HTML_TABLE, confidence=0.6),
            make_fact(fact_id="high", source_type=SourceType.HTML_TABLE, confidence=0.9),
        ]

        primary = stage._select_primary(facts)

        assert primary.fact_id == "high"

    def test_single_fact_returns_itself(self) -> None:
        """Single fact should return itself as primary."""
        stage = DeduplicationStage()
        fact = make_fact(fact_id="only")

        primary = stage._select_primary([fact])

        assert primary.fact_id == "only"


# ============================================================================
# Alternate Evidence Linking Tests
# ============================================================================


class TestAlternateEvidenceLinking:
    """Tests for alternate evidence linking."""

    def test_primary_has_alternate_fact_ids(self) -> None:
        """Primary fact should have alternate fact_ids populated."""
        stage = DeduplicationStage()
        # Both facts have the same source_type so they land in the same identity bucket
        # and the higher-quality (higher confidence) one is chosen as primary.
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1", source_type=SourceType.HTML_TABLE, confidence=0.9),
                make_fact(fact_id="fact-2", source_type=SourceType.HTML_TABLE, confidence=0.7),
            ]
        )

        stage.process(context)

        assert len(context.deduplicated_facts) == 1
        primary = context.deduplicated_facts[0]
        assert primary.fact_id == "fact-1"
        assert "fact-2" in primary.alternate_evidence

    def test_alternates_not_in_output(self) -> None:
        """Alternate facts should not be in output list."""
        stage = DeduplicationStage()
        # All three facts share the same source_type so they collapse to one primary.
        # source_type is now part of the identity key; cross-source-type facts are distinct.
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1", source_type=SourceType.HTML_TABLE, confidence=0.9),
                make_fact(fact_id="fact-2", source_type=SourceType.HTML_TABLE, confidence=0.8),
                make_fact(fact_id="fact-3", source_type=SourceType.HTML_TABLE, confidence=0.7),
            ]
        )

        stage.process(context)

        assert len(context.deduplicated_facts) == 1
        output_ids = {f.fact_id for f in context.deduplicated_facts}
        assert "fact-1" in output_ids
        assert "fact-2" not in output_ids
        assert "fact-3" not in output_ids

    def test_single_fact_no_alternates(self) -> None:
        """Single fact (no duplicates) should have no alternates."""
        stage = DeduplicationStage()
        context = MockPipelineContext(facts=[make_fact(fact_id="fact-1")])

        stage.process(context)

        assert len(context.deduplicated_facts) == 1
        assert context.deduplicated_facts[0].alternate_evidence == []


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_facts_list(self) -> None:
        """Empty facts list should return empty output."""
        stage = DeduplicationStage()
        context = MockPipelineContext(facts=[])

        result = stage.process(context)

        assert result.success
        assert len(context.deduplicated_facts) == 0
        assert result.items_processed == 0
        assert result.items_output == 0

    def test_all_unique_facts_preserved(self) -> None:
        """All unique facts should be preserved in output."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1", metric_id="cm_average_order_value"),
                make_fact(fact_id="fact-2", metric_id="cm_lifetime_value_per_customer"),
                make_fact(fact_id="fact-3", metric_id="cm_nrr"),
            ]
        )

        result = stage.process(context)

        assert len(context.deduplicated_facts) == 3
        assert result.metadata["duplicates_removed"] == 0

    def test_three_way_duplicate(self) -> None:
        """Three duplicates (same source_type) produce one primary with two alternates."""
        stage = DeduplicationStage()
        # source_type is now part of the identity key; all three must share the same
        # source_type to be treated as duplicates within a single bucket.
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1", source_type=SourceType.HTML_TABLE, confidence=0.9),
                make_fact(fact_id="fact-2", source_type=SourceType.HTML_TABLE, confidence=0.7),
                make_fact(fact_id="fact-3", source_type=SourceType.HTML_TABLE, confidence=0.5),
            ]
        )

        stage.process(context)

        assert len(context.deduplicated_facts) == 1
        primary = context.deduplicated_facts[0]
        assert primary.fact_id == "fact-1"
        assert len(primary.alternate_evidence) == 2
        assert "fact-2" in primary.alternate_evidence
        assert "fact-3" in primary.alternate_evidence

    def test_facts_with_none_value(self) -> None:
        """Facts with None value should be handled correctly."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1", value=None),
                make_fact(fact_id="fact-2", value=None),
            ]
        )

        stage.process(context)

        # Two facts with None values are duplicates (same identity)
        assert len(context.deduplicated_facts) == 1

    def test_facts_with_none_period(self) -> None:
        """Facts with None period should be handled correctly."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1", period_start=None, period_end=None),
                make_fact(fact_id="fact-2", period_start=None, period_end=None),
            ]
        )

        stage.process(context)

        # Two facts with None periods are duplicates
        assert len(context.deduplicated_facts) == 1


# ============================================================================
# Stage Result Tests
# ============================================================================


class TestStageResult:
    """Tests for stage result metadata."""

    def test_result_success(self) -> None:
        """Stage should return success=True."""
        stage = DeduplicationStage()
        context = MockPipelineContext(facts=[make_fact(fact_id="fact-1")])

        result = stage.process(context)

        assert result.success is True

    def test_result_items_processed(self) -> None:
        """items_processed should be initial fact count."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1"),
                make_fact(fact_id="fact-2"),
                make_fact(fact_id="fact-3"),
            ]
        )

        result = stage.process(context)

        assert result.items_processed == 3

    def test_result_items_output(self) -> None:
        """items_output should be deduplicated count."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1"),  # Duplicate
                make_fact(fact_id="fact-2"),  # Duplicate
                make_fact(fact_id="fact-3", metric_id="cm_lifetime_value_per_customer"),  # Unique
            ]
        )

        result = stage.process(context)

        assert result.items_output == 2  # One merged + one unique

    def test_result_duplicates_removed(self) -> None:
        """metadata should contain duplicates_removed count."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1"),
                make_fact(fact_id="fact-2"),
                make_fact(fact_id="fact-3"),
            ]
        )

        result = stage.process(context)

        assert result.metadata["duplicates_removed"] == 2  # 3 -> 1

    def test_result_groups_with_alternates(self) -> None:
        """metadata should contain groups_with_alternates count."""
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(fact_id="fact-1"),  # Duplicate group
                make_fact(fact_id="fact-2"),  # Duplicate group
                make_fact(fact_id="fact-3", metric_id="cm_lifetime_value_per_customer"),  # Unique
            ]
        )

        result = stage.process(context)

        assert result.metadata["groups_with_alternates"] == 1

    def test_result_duration_ms(self) -> None:
        """duration_ms should be populated."""
        stage = DeduplicationStage()
        context = MockPipelineContext(facts=[make_fact(fact_id="fact-1")])

        result = stage.process(context)

        assert result.duration_ms >= 0


# ============================================================================
# Config Integration Tests
# ============================================================================


class TestConfigIntegration:
    """Tests for config integration."""

    def test_uses_config_tolerance(self) -> None:
        """Stage should use tolerance from config."""
        stage = DeduplicationStage()
        # 100 and 110 are outside default 2% but within 15%
        config = MockPipelineConfig(value_tolerance=0.15)
        context = MockPipelineContext(
            config=config,
            facts=[
                make_fact(fact_id="fact-1", value=100.0),
                make_fact(fact_id="fact-2", value=110.0),
            ],
        )

        stage.process(context)

        # With 15% tolerance, these should be grouped
        assert len(context.deduplicated_facts) == 1

    def test_init_with_custom_tolerance(self) -> None:
        """Stage can be initialized with custom tolerance."""
        stage = DeduplicationStage(value_tolerance=0.05)

        assert stage.value_tolerance == 0.05


# ============================================================================
# Fuzzy Period Dedup Tests
# ============================================================================


class TestFuzzyPeriodDedup:
    """Tests for _fuzzy_period_dedup second-pass deduplication."""

    def test_same_metric_value_overlapping_periods_merged(self) -> None:
        """Same metric+value+source_type with overlapping periods merged into one.

        Note: fix A2 added source_type to the _fuzzy_period_dedup bucket key so that
        CHART and text/table facts for the same slot are kept separate (they map to
        distinct rows in the migration-23 unique index).  Within a single source_type,
        fuzzy dedup still collapses overlapping-period duplicates.
        """
        stage = DeduplicationStage()
        # period_start/end slightly different but overlapping; same source_type
        facts = [
            make_fact(
                fact_id="fact-table-a",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,
                confidence=0.9,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-table-b",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,
                confidence=0.7,
                period_start=date(2024, 6, 1),
                period_end=date(2024, 12, 31),
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        assert len(result) == 1
        assert result[0].fact_id == "fact-table-a"  # higher confidence wins
        assert "fact-table-b" in result[0].alternate_evidence

    def test_same_metric_value_non_overlapping_periods_kept_separate(self) -> None:
        """Same metric+value with non-overlapping periods should be kept separate."""
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-2024",
                metric_id="cm_average_order_value",
                value=100.0,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-2023",
                metric_id="cm_average_order_value",
                value=100.0,
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        assert len(result) == 2
        ids = {f.fact_id for f in result}
        assert "fact-2024" in ids
        assert "fact-2023" in ids

    def test_same_metric_different_values_kept_separate(self) -> None:
        """Two facts with same metric/period but different values and source_types
        are kept as separate facts — they represent distinct measurements."""
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-100",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,
                confidence=0.9,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-200",
                metric_id="cm_average_order_value",
                value=200.0,
                source_type=SourceType.TEXT,
                confidence=0.8,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        # Different values AND different source_types → kept separate under migration-23 index.
        assert len(result) == 2
        result_ids = {f.fact_id for f in result}
        assert "fact-100" in result_ids
        assert "fact-200" in result_ids

    def test_mix_of_exact_and_fuzzy_duplicates(self) -> None:
        """Mix of within-source-type fuzzy dups and genuinely-distinct cross-year facts.

        After identity dedup, we'd have primaries like these:
        - aov-table-a: AOV 100 HTML_TABLE FY2024 (full year)
        - aov-table-b: AOV 100 HTML_TABLE FY2024 (half-year overlap) — fuzzy dup, same source_type
        - ltv-2024: LTV 50 HTML_TABLE 2024
        - ltv-2023: LTV 50 HTML_TABLE 2023 — different year, keep separate

        Note: fix A2 added source_type to the fuzzy-dedup bucket key. Cross-source-type
        facts (HTML_TABLE vs TEXT) are NOT merged by this pass — they represent distinct
        DB rows per migration-23's unique index. Within-source-type overlapping-period
        duplicates are still merged.
        """
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-aov-a",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,
                confidence=0.9,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-aov-b",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,
                confidence=0.7,
                period_start=date(2024, 6, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-ltv-2024",
                metric_id="cm_lifetime_value_per_customer",
                value=50.0,
                source_type=SourceType.HTML_TABLE,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-ltv-2023",
                metric_id="cm_lifetime_value_per_customer",
                value=50.0,
                source_type=SourceType.HTML_TABLE,
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        # AOV: 2 → 1 (same source_type, fuzzy merged); LTV: 2 → 2 (different years)
        assert len(result) == 3
        result_ids = {f.fact_id for f in result}
        assert "fact-aov-a" in result_ids  # primary (higher confidence)
        assert "fact-aov-b" not in result_ids  # absorbed as alternate
        assert "fact-ltv-2024" in result_ids
        assert "fact-ltv-2023" in result_ids

    def test_fuzzy_dedup_called_via_process(self) -> None:
        """process() should call fuzzy period dedup as second pass.

        Two HTML_TABLE facts with same value but overlapping (not identical) periods
        survive identity-based dedup (different periods → different identity tuples)
        but are collapsed by the fuzzy pass.  Using same source_type ensures they land
        in the same fuzzy bucket.
        """
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(
                    fact_id="fact-table-a",
                    metric_id="cm_average_order_value",
                    value=100.0,
                    source_type=SourceType.HTML_TABLE,
                    confidence=0.9,
                    period_start=date(2024, 1, 1),
                    period_end=date(2024, 12, 31),
                ),
                make_fact(
                    fact_id="fact-table-b",
                    metric_id="cm_average_order_value",
                    value=100.0,
                    source_type=SourceType.HTML_TABLE,
                    confidence=0.7,
                    period_start=date(2024, 6, 1),
                    period_end=date(2024, 12, 31),
                ),
            ]
        )

        result = stage.process(context)

        assert len(context.deduplicated_facts) == 1
        assert result.metadata["fuzzy_period_removed"] == 1
        assert result.metadata["duplicates_removed"] == 1

    def test_none_period_compatible_with_any_period(self) -> None:
        """A fact with None period is compatible with any other period."""
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-with-period",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 12, 31),
            ),
            make_fact(
                fact_id="fact-no-period",
                metric_id="cm_average_order_value",
                value=100.0,
                source_type=SourceType.HTML_TABLE,  # same source_type — testing fuzzy period dedup, not cross-source-type merging
                period_start=None,
                period_end=None,
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        assert len(result) == 1
        assert result[0].fact_id == "fact-with-period"

    def test_period_transfer_different_value_different_source_type_both_survive(self) -> None:
        """Period-transfer facts with different values AND different source_types both survive.

        fact_a (HTML_TABLE, no period) merges with fact_donor (HTML_TABLE, period=2020)
        gaining period via transfer. fact_b (TEXT, period=2020, value=150k) is beyond 2%
        tolerance so it stays as a separate primary. Because fact_a and fact_b have
        different source_types, the migration-23 unique index treats them as separate rows
        → both survive after _collapse_post_transfer_collisions.
        """
        stage = DeduplicationStage()

        fact_a = make_fact(
            fact_id="fact-a",
            metric_id="cm_customers_period_end",
            value=100000.0,
            unit=Unit.COUNT,
            source_type=SourceType.HTML_TABLE,
            confidence=0.95,
            period_start=None,
            period_end=None,
        )
        fact_donor = make_fact(
            fact_id="fact-donor",
            metric_id="cm_customers_period_end",
            value=100000.0,
            unit=Unit.COUNT,
            source_type=SourceType.HTML_TABLE,
            confidence=0.80,
            period_start=date(2020, 1, 1),
            period_end=date(2020, 12, 31),
        )
        fact_b = make_fact(
            fact_id="fact-b",
            metric_id="cm_customers_period_end",
            value=150000.0,
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,  # different source_type → distinct DB row
            confidence=0.70,
            period_start=date(2020, 1, 1),
            period_end=date(2020, 12, 31),
        )

        result = stage._fuzzy_period_dedup([fact_a, fact_donor, fact_b], tolerance=0.02)

        # fact_a merges with fact_donor (same value ≈100k, compatible periods) → gains period.
        # fact_b stays separate (150k is > 2% away from 100k).
        # Different source_types → distinct identity tuples → no post-transfer collapse.
        assert len(result) == 2
        result_ids = {f.fact_id for f in result}
        assert "fact-a" in result_ids
        assert "fact-b" in result_ids

    def test_post_transfer_collision_collapse_fires(self) -> None:
        """Period-transfer onto a no-period primary can make two surviving primaries collide.

        fact_a (HTML_TABLE, no period) merges with fact_donor (HTML_TABLE, period=2020)
        gaining period=2020 via transfer.  fact_b (HTML_TABLE, period=2020, value=150k)
        is beyond 2% tolerance so it stays as a separate primary.  After transfer,
        fact_a has the same 8-tuple identity as fact_b (same source_type, period, metric,
        unit, scope, cohort, customer_type) → _collapse_post_transfer_collisions must
        resolve the collision, keeping only the higher-confidence HTML_TABLE winner.
        """
        stage = DeduplicationStage()

        fact_a = make_fact(
            fact_id="fact-a",
            metric_id="cm_customers_period_end",
            value=100000.0,
            unit=Unit.COUNT,
            source_type=SourceType.HTML_TABLE,
            confidence=0.95,
            period_start=None,
            period_end=None,
        )
        fact_donor = make_fact(
            fact_id="fact-donor",
            metric_id="cm_customers_period_end",
            value=100000.0,
            unit=Unit.COUNT,
            source_type=SourceType.HTML_TABLE,
            confidence=0.80,
            period_start=date(2020, 1, 1),
            period_end=date(2020, 12, 31),
        )
        fact_b = make_fact(
            fact_id="fact-b",
            metric_id="cm_customers_period_end",
            value=150000.0,
            unit=Unit.COUNT,
            source_type=SourceType.HTML_TABLE,  # same source_type → identity collision after transfer
            confidence=0.70,
            period_start=date(2020, 1, 1),
            period_end=date(2020, 12, 31),
        )

        result = stage._fuzzy_period_dedup([fact_a, fact_donor, fact_b], tolerance=0.02)

        # fact_a gains period=2020. Now fact_a and fact_b share the same 8-tuple identity.
        # Collapse keeps the higher-confidence winner (fact_a, confidence=0.95).
        assert len(result) == 1
        assert result[0].fact_id == "fact-a"
        assert "fact-b" in result[0].alternate_evidence
        assert stage._last_post_transfer_collisions == 1

    def test_distinct_customer_type_facts_kept_separate(self) -> None:
        """Facts with distinct customer_type values are kept as separate facts."""
        stage = DeduplicationStage()

        f1 = make_fact(
            fact_id="fact-paid",
            metric_id="cm_customers_period_end",
            value=88000.0,
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,
            confidence=0.90,
            period_start=date(2019, 1, 31),
            period_end=date(2019, 1, 31),
            customer_type="Paid",
        )
        f2 = make_fact(
            fact_id="fact-free",
            metric_id="cm_customers_period_end",
            value=500000.0,
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,
            confidence=0.90,
            period_start=date(2019, 1, 31),
            period_end=date(2019, 1, 31),
            customer_type="Free",
        )
        f3 = make_fact(
            fact_id="fact-total",
            metric_id="cm_customers_period_end",
            value=600000.0,
            unit=Unit.COUNT,
            source_type=SourceType.TEXT,
            confidence=0.85,
            period_start=date(2019, 1, 31),
            period_end=date(2019, 1, 31),
            customer_type=None,
        )

        result = stage._fuzzy_period_dedup([f1, f2, f3], tolerance=0.02)

        assert len(result) == 3
        result_ids = {f.fact_id for f in result}
        assert result_ids == {"fact-paid", "fact-free", "fact-total"}
        for fact in result:
            assert fact.alternate_evidence == []


# ============================================================================
# Performance Tests (Phase 4)
# ============================================================================


class TestGroupingPerformance:
    """Tests for optimized pre-grouping performance."""

    def test_large_fact_set_completes_quickly(self) -> None:
        """1000 facts with 50 unique identity tuples completes quickly."""
        import time

        stage = DeduplicationStage()

        # Create 1000 facts across 50 metric IDs (20 duplicates each)
        facts = []
        for metric_idx in range(50):
            for dup_idx in range(20):
                facts.append(
                    make_fact(
                        fact_id=f"fact-{metric_idx}-{dup_idx}",
                        metric_id=f"cm_metric_{metric_idx}",
                        value=100.0 + (dup_idx * 0.001),  # Within 2% tolerance
                    )
                )

        start = time.time()
        groups = stage._group_duplicates(facts, tolerance=0.02)
        elapsed = time.time() - start

        # Should complete in under 2 seconds (O(n) pre-grouping makes this fast)
        assert elapsed < 2.0
        # Should produce 50 groups (one per metric)
        assert len(groups) == 50

    def test_pre_grouping_preserves_correctness(self) -> None:
        """Pre-grouping produces same results as naive O(n²) approach."""
        stage = DeduplicationStage()

        facts = [
            make_fact(fact_id="f1", metric_id="cm_average_order_value", value=100.0),
            make_fact(fact_id="f2", metric_id="cm_average_order_value", value=101.0),  # Within tolerance
            make_fact(fact_id="f3", metric_id="cm_average_order_value", value=200.0),  # Different value
            make_fact(fact_id="f4", metric_id="cm_lifetime_value_per_customer", value=100.0),  # Different metric
            make_fact(fact_id="f5", metric_id="cm_lifetime_value_per_customer", value=100.0),  # Duplicate of f4
        ]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        # Should produce 3 groups: (f1,f2), (f3), (f4,f5)
        assert len(groups) == 3
        group_sizes = sorted(len(g) for g in groups)
        assert group_sizes == [1, 2, 2]

    def test_single_identity_bucket_many_values(self) -> None:
        """All facts same identity but different values: separate groups."""
        stage = DeduplicationStage()

        # Same metric, but widely different values
        facts = [make_fact(fact_id=f"f{i}", value=float(i * 100)) for i in range(1, 11)]

        groups = stage._group_duplicates(facts, tolerance=0.02)

        # Each value is far from others, so 10 groups
        assert len(groups) == 10


# ============================================================================
# Key Normalization Tests (Fix 1 + Fix 2)
# ============================================================================


class TestDeduplicationKeyNormalization:
    """Tests for None→"" normalization in dedup bucket keys (WP-xx)."""

    def test_none_vs_empty_string_cohort_in_same_fuzzy_bucket(self) -> None:
        """Facts with cohort_def=None and cohort_def="" land in the same fuzzy-period bucket.

        Fix 1b: _fuzzy_period_dedup normalizes cohort_def/customer_type to "" in the
        bucket key so that None and "" are treated as the same sentinel value —
        matching the SQL unique index COALESCE behaviour.
        """
        stage = DeduplicationStage()

        # A: HTML_TABLE, no period, cohort=None
        fact_a = make_fact(
            fact_id="fact-a",
            source_type=SourceType.HTML_TABLE,
            confidence=0.9,
            period_start=None,
            period_end=None,
            cohort_def=None,
        )
        # B: HTML_TABLE, period=2024, cohort=None — same bucket as A after Fix 1b (same source_type — testing fuzzy period dedup)
        fact_b = make_fact(
            fact_id="fact-b",
            source_type=SourceType.HTML_TABLE,
            confidence=0.6,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            cohort_def=None,
        )
        # C: HTML_TABLE, period=2024, cohort="" — same bucket as A/B after Fix 1b (same source_type — testing fuzzy period dedup)
        fact_c = make_fact(
            fact_id="fact-c",
            source_type=SourceType.HTML_TABLE,
            confidence=0.7,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            cohort_def="",
        )

        result = stage._fuzzy_period_dedup([fact_a, fact_b, fact_c], tolerance=0.02)

        # All three collapse to one fact: A wins (highest confidence), gets period from B/C,
        # and B and C appear in alternate_evidence.
        assert len(result) == 1
        winner = result[0]
        assert winner.fact_id == "fact-a"
        assert winner.period_start == date(2024, 1, 1)
        assert "fact-b" in winner.alternate_evidence
        assert "fact-c" in winner.alternate_evidence

    def test_none_vs_empty_string_cohort_in_same_identity_bucket(self) -> None:
        """_group_duplicates places cohort_def=None and cohort_def="" in the same bucket.

        Fix 1a: _group_duplicates normalizes cohort_def/customer_type to "" in the
        bucket key so these facts are compared to each other rather than silently
        placed in separate buckets. Note: is_duplicate_of compares cohort_def
        directly (None != ""), so they still emerge as two separate 1-element groups
        within the shared bucket — but they were at least evaluated together,
        matching the SQL COALESCE identity view.
        """
        stage = DeduplicationStage()

        fact_none = make_fact(fact_id="f-none", cohort_def=None, value=100.0)
        fact_empty = make_fact(fact_id="f-empty", cohort_def="", value=100.0)

        groups = stage._group_duplicates([fact_none, fact_empty], tolerance=0.02)

        # Same bucket (after normalization), but is_duplicate_of sees None != "" →
        # two separate 1-element groups, not one merged group.
        assert len(groups) == 2
        group_sizes = sorted(len(g) for g in groups)
        assert group_sizes == [1, 1]


# ============================================================================
# Source Type Identity Tests (Fix A1)
# ============================================================================


class TestSourceTypeInIdentityKey:
    """Tests that source_type is part of the dedup identity key in BOTH passes.

    Chart facts and text/table facts for the same metric slot must survive
    deduplication as separate facts — source_type is now part of the bucket key
    in both _group_duplicates (fix A1) and _fuzzy_period_dedup (fix A2), and is
    included in migration 23's unique index.
    """

    def test_chart_and_text_facts_for_same_slot_both_survive_dedup(self) -> None:
        """CHART and HTML_TABLE facts for the same metric slot both survive dedup.

        Before fix A1 the _group_duplicates bucket key omitted source_type, so
        the CHART fact would be dropped when an HTML_TABLE fact occupied the same slot.
        """
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(
                    fact_id="fact-chart",
                    source_type=SourceType.CHART,
                    value=100.0,
                ),
                make_fact(
                    fact_id="fact-table",
                    source_type=SourceType.HTML_TABLE,
                    value=100.0,
                ),
            ]
        )

        stage.process(context)

        assert len(context.deduplicated_facts) == 2
        surviving_source_types = {f.source_type for f in context.deduplicated_facts}
        assert SourceType.CHART in surviving_source_types
        assert SourceType.HTML_TABLE in surviving_source_types

    def test_fuzzy_period_dedup_preserves_chart_and_table_facts_separately(self) -> None:
        """_fuzzy_period_dedup must NOT collapse chart and table facts for the same slot.

        Before fix A2 the _fuzzy_period_dedup bucket key omitted source_type, so a
        CHART fact and an HTML_TABLE fact with the same metric+unit+scope+value would
        land in the same bucket and be collapsed — the CHART fact would be lost.

        With source_type in the key each source produces its own bucket, so both
        facts survive.
        """
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-chart",
                metric_id="cm_customers_period_end",
                value=50000.0,
                unit=Unit.COUNT,
                source_type=SourceType.CHART,
                confidence=0.85,
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
            ),
            make_fact(
                fact_id="fact-table",
                metric_id="cm_customers_period_end",
                value=50000.0,
                unit=Unit.COUNT,
                source_type=SourceType.HTML_TABLE,
                confidence=0.95,
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        assert len(result) == 2
        surviving_source_types = {f.source_type for f in result}
        assert SourceType.CHART in surviving_source_types
        assert SourceType.HTML_TABLE in surviving_source_types
        # Neither fact should have absorbed the other as alternate_evidence
        for fact in result:
            assert fact.alternate_evidence == []

    def test_fuzzy_period_dedup_same_source_type_still_collapses(self) -> None:
        """_fuzzy_period_dedup still collapses two HTML_TABLE facts for the same slot.

        Regression guard: the source_type-in-key fix must not prevent legitimate
        within-source-type fuzzy deduplication.  Two HTML_TABLE facts with the same
        metric+value and overlapping periods should still be merged into one.
        """
        stage = DeduplicationStage()
        facts = [
            make_fact(
                fact_id="fact-table-a",
                metric_id="cm_customers_period_end",
                value=50000.0,
                unit=Unit.COUNT,
                source_type=SourceType.HTML_TABLE,
                confidence=0.95,
                period_start=date(2023, 1, 1),
                period_end=date(2023, 12, 31),
            ),
            make_fact(
                fact_id="fact-table-b",
                metric_id="cm_customers_period_end",
                value=50000.0,
                unit=Unit.COUNT,
                source_type=SourceType.HTML_TABLE,
                confidence=0.75,
                period_start=date(2023, 6, 1),
                period_end=date(2023, 12, 31),
            ),
        ]

        result = stage._fuzzy_period_dedup(facts, tolerance=0.02)

        assert len(result) == 1
        assert result[0].fact_id == "fact-table-a"  # higher confidence wins
        assert "fact-table-b" in result[0].alternate_evidence

    def test_chart_and_table_both_survive_full_process(self) -> None:
        """End-to-end: process() preserves CHART and HTML_TABLE for the same slot.

        Exercises the complete dedup pipeline (identity pass + fuzzy pass) to confirm
        a CHART and an HTML_TABLE fact for the same metric/period/value survive as two
        separate output facts.
        """
        stage = DeduplicationStage()
        context = MockPipelineContext(
            facts=[
                make_fact(
                    fact_id="fact-chart",
                    metric_id="cm_customers_period_end",
                    value=75000.0,
                    unit=Unit.COUNT,
                    source_type=SourceType.CHART,
                    confidence=0.80,
                    period_start=date(2022, 1, 1),
                    period_end=date(2022, 12, 31),
                ),
                make_fact(
                    fact_id="fact-table",
                    metric_id="cm_customers_period_end",
                    value=75000.0,
                    unit=Unit.COUNT,
                    source_type=SourceType.HTML_TABLE,
                    confidence=0.95,
                    period_start=date(2022, 1, 1),
                    period_end=date(2022, 12, 31),
                ),
            ]
        )

        result = stage.process(context)

        assert result.success
        assert len(context.deduplicated_facts) == 2
        assert result.metadata["duplicates_removed"] == 0
        surviving_source_types = {f.source_type for f in context.deduplicated_facts}
        assert SourceType.CHART in surviving_source_types
        assert SourceType.HTML_TABLE in surviving_source_types
