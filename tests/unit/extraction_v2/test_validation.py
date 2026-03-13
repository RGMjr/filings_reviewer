"""
Unit tests for V2 Validation & Review Routing Stage.

Tests cover:
- Confidence-based routing (auto-accept, pending review, auto-reject candidate)
- Schema validation (required fields)
- Review reason assignment
- Edge cases (empty lists, boundary conditions)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.extraction_v2.models import (
    EvidencePack,
    MetricFact,
    ReviewStatus,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.stages.validation import ValidationStage


@dataclass
class MockPipelineConfig:
    """Mock pipeline configuration for testing."""

    min_confidence_auto_accept: float = 0.90
    max_confidence_auto_reject: float = 0.15


class EmptyConfig:
    """Config with no threshold attributes, for testing __init__ defaults."""

    pass


@dataclass
class MockPipelineContext:
    """Mock pipeline context for testing."""

    html_path: Path = field(default_factory=lambda: Path("/tmp/test.html"))
    filing_id: int = 1
    config: Any = field(default_factory=MockPipelineConfig)
    facts: list[MetricFact] = field(default_factory=list)
    deduplicated_facts: list[MetricFact] = field(default_factory=list)
    stage_results: list[Any] = field(default_factory=list)


def create_valid_fact(
    confidence: float = 0.85,
    source_type: SourceType = SourceType.HTML_TABLE,
    canonical_metric_id: str = "cm_test_metric",
    value: float | None = 100.0,
    value_raw: str = "100",
    segment_id: str = "seg-123",
    snippet_html: str = "<span>Test</span>",
) -> MetricFact:
    """Create a valid MetricFact for testing."""
    return MetricFact(
        canonical_metric_id=canonical_metric_id,
        value=value,
        value_raw=value_raw,
        unit=Unit.COUNT,
        confidence=confidence,
        source_type=source_type,
        source_locator=SourceLocator(segment_id=segment_id),
        evidence_pack=EvidencePack(snippet_html=snippet_html),
        requires_review=True,
        review_status=ReviewStatus.PENDING_REVIEW,
    )


class TestConfidenceRouting:
    """Tests for confidence-based routing."""

    def test_high_confidence_auto_accepted(self) -> None:
        """Fact with confidence >= 0.90 is auto-accepted."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert result.success
        assert fact.requires_review is False
        assert fact.review_status == ReviewStatus.AUTO_ACCEPTED
        assert fact.review_reason is None
        assert result.metadata["auto_accepted"] == 1
        assert result.metadata["pending_review"] == 0

    def test_exactly_at_auto_accept_threshold(self) -> None:
        """Fact with confidence exactly at 0.90 is auto-accepted."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.90)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert fact.review_status == ReviewStatus.AUTO_ACCEPTED

    def test_just_below_auto_accept_threshold(self) -> None:
        """Fact with confidence 0.89 goes to pending review."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.89)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert fact.review_status == ReviewStatus.PENDING_REVIEW
        assert "89%" in fact.review_reason or "below auto-accept" in fact.review_reason
        assert result.metadata["pending_review"] == 1

    def test_at_auto_reject_boundary(self) -> None:
        """Fact with confidence exactly at 0.15 goes to pending review (not auto-reject)."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.15)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert fact.review_status == ReviewStatus.PENDING_REVIEW
        assert "auto-reject" not in fact.review_reason.lower()

    def test_below_auto_reject_threshold(self) -> None:
        """Fact with confidence 0.14 is an auto-reject candidate."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.14)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert fact.review_status == ReviewStatus.PENDING_REVIEW
        assert "auto-reject candidate" in fact.review_reason.lower()
        assert result.metadata["auto_reject_candidates"] == 1

    def test_zero_confidence(self) -> None:
        """Fact with confidence 0.0 is an auto-reject candidate."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.0)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "auto-reject candidate" in fact.review_reason.lower()

    def test_mixed_confidence_facts(self) -> None:
        """Multiple facts with different confidences are routed correctly."""
        stage = ValidationStage()
        high_conf = create_valid_fact(confidence=0.95)
        mid_conf = create_valid_fact(confidence=0.50)
        low_conf = create_valid_fact(confidence=0.10)
        context = MockPipelineContext(deduplicated_facts=[high_conf, mid_conf, low_conf])

        result = stage.process(context)  # noqa: F841

        assert high_conf.requires_review is False
        assert mid_conf.requires_review is True
        assert low_conf.requires_review is True
        assert result.metadata["auto_accepted"] == 1
        assert result.metadata["pending_review"] == 2
        assert result.metadata["auto_reject_candidates"] == 1


class TestSchemaValidation:
    """Tests for schema validation."""

    def test_missing_canonical_metric_id(self) -> None:
        """Fact missing canonical_metric_id is flagged."""
        stage = ValidationStage()
        fact = create_valid_fact(canonical_metric_id="", confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "canonical_metric_id" in fact.review_reason
        assert result.metadata["schema_validation_failures"] == 1

    def test_missing_both_value_and_value_raw(self) -> None:
        """Fact missing both value and value_raw is flagged."""
        stage = ValidationStage()
        fact = create_valid_fact(value=None, value_raw="", confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "value" in fact.review_reason.lower()
        assert result.metadata["schema_validation_failures"] == 1

    def test_value_none_but_value_raw_present(self) -> None:
        """Fact with value=None but value_raw populated passes validation."""
        stage = ValidationStage()
        fact = create_valid_fact(value=None, value_raw="N/A", confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert result.metadata["schema_validation_failures"] == 0

    def test_missing_source_locator(self) -> None:
        """Fact with empty source locator is flagged."""
        stage = ValidationStage()
        fact = create_valid_fact(segment_id="", confidence=0.95)
        fact.source_locator = SourceLocator()  # Empty locator
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "source_locator" in fact.review_reason
        assert result.metadata["schema_validation_failures"] == 1

    def test_source_locator_with_table_id_only(self) -> None:
        """Fact with only table_id in source locator is valid."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95)
        fact.source_locator = SourceLocator(table_id="tbl-123")
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert result.metadata["schema_validation_failures"] == 0

    def test_source_locator_with_img_id_only(self) -> None:
        """Fact with only img_id in source locator is valid."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95)
        fact.source_locator = SourceLocator(img_id="img-123")
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert result.metadata["schema_validation_failures"] == 0

    def test_missing_snippet_html(self) -> None:
        """Fact missing snippet_html is flagged."""
        stage = ValidationStage()
        fact = create_valid_fact(snippet_html="", confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "snippet_html" in fact.review_reason
        assert result.metadata["schema_validation_failures"] == 1

    def test_valid_fact_passes_schema_validation(self) -> None:
        """Fully valid fact passes schema validation."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert result.metadata["schema_validation_failures"] == 0


class TestReviewReasonAssignment:
    """Tests for review reason assignment."""

    def test_ocr_source_adds_verification_reason(self) -> None:
        """OCR source type adds verification reason."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95, source_type=SourceType.OCR_TABLE)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "OCR" in fact.review_reason

    def test_chart_source_adds_verification_reason(self) -> None:
        """Chart source type adds verification reason."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95, source_type=SourceType.CHART)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "Chart" in fact.review_reason

    def test_html_table_source_no_extra_reason(self) -> None:
        """HTML_TABLE source type doesn't add verification reason."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95, source_type=SourceType.HTML_TABLE)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert fact.review_reason is None

    def test_text_source_no_extra_reason(self) -> None:
        """TEXT source type doesn't add verification reason."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95, source_type=SourceType.TEXT)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert fact.review_reason is None

    def test_multiple_reasons_concatenated(self) -> None:
        """Multiple review reasons are concatenated with semicolon."""
        stage = ValidationStage()
        fact = create_valid_fact(
            confidence=0.10,  # Auto-reject
            source_type=SourceType.OCR_TABLE,  # Adds OCR reason
            canonical_metric_id="",  # Schema failure
        )
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        # Should have multiple reasons joined by semicolon
        assert ";" in fact.review_reason
        assert "canonical_metric_id" in fact.review_reason
        assert "OCR" in fact.review_reason

    def test_high_confidence_fact_no_review_reason(self) -> None:
        """High confidence valid fact has no review reason."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95)
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.review_reason is None

    def test_existing_review_reason_preserved(self) -> None:
        """Existing review reason from prior stage is preserved."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.50)
        fact.review_reason = "Period ambiguous"
        context = MockPipelineContext(deduplicated_facts=[fact])

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is True
        assert "Period ambiguous" in fact.review_reason


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_facts_list(self) -> None:
        """Empty facts list returns success with zero counts."""
        stage = ValidationStage()
        context = MockPipelineContext(deduplicated_facts=[])

        result = stage.process(context)  # noqa: F841

        assert result.success
        assert result.items_processed == 0
        assert result.items_output == 0
        assert result.metadata["auto_accepted"] == 0
        assert result.metadata["pending_review"] == 0

    def test_all_facts_auto_accepted(self) -> None:
        """All high-confidence facts are auto-accepted."""
        stage = ValidationStage()
        facts = [create_valid_fact(confidence=0.95) for _ in range(5)]
        context = MockPipelineContext(deduplicated_facts=facts)

        result = stage.process(context)  # noqa: F841

        assert result.metadata["auto_accepted"] == 5
        assert result.metadata["pending_review"] == 0
        assert all(not f.requires_review for f in facts)

    def test_all_facts_low_confidence(self) -> None:
        """All low-confidence facts are flagged for review."""
        stage = ValidationStage()
        facts = [create_valid_fact(confidence=0.10) for _ in range(5)]
        context = MockPipelineContext(deduplicated_facts=facts)

        result = stage.process(context)  # noqa: F841

        assert result.metadata["auto_accepted"] == 0
        assert result.metadata["pending_review"] == 5
        assert result.metadata["auto_reject_candidates"] == 5
        assert all(f.requires_review for f in facts)

    def test_custom_thresholds_via_init(self) -> None:
        """Custom thresholds can be set via __init__ when config lacks them."""
        stage = ValidationStage(auto_accept_threshold=0.80, auto_reject_threshold=0.20)
        fact = create_valid_fact(confidence=0.85)
        # Use EmptyConfig so init thresholds are used
        context = MockPipelineContext(deduplicated_facts=[fact], config=EmptyConfig())

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert fact.review_status == ReviewStatus.AUTO_ACCEPTED

    def test_custom_thresholds_via_config(self) -> None:
        """Custom thresholds from config override init values."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.85)
        config = MockPipelineConfig(
            min_confidence_auto_accept=0.80,
            max_confidence_auto_reject=0.20,
        )
        context = MockPipelineContext(deduplicated_facts=[fact], config=config)

        result = stage.process(context)  # noqa: F841

        assert fact.requires_review is False
        assert fact.review_status == ReviewStatus.AUTO_ACCEPTED

    def test_uses_facts_if_deduplicated_facts_empty(self) -> None:
        """Uses context.facts if deduplicated_facts is empty."""
        stage = ValidationStage()
        fact = create_valid_fact(confidence=0.95)
        context = MockPipelineContext(
            facts=[fact],
            deduplicated_facts=[],
        )

        result = stage.process(context)  # noqa: F841

        assert result.items_processed == 1
        assert fact.requires_review is False

    def test_stage_result_metadata(self) -> None:
        """StageResult contains correct metadata."""
        stage = ValidationStage()
        facts = [
            create_valid_fact(confidence=0.95),  # auto-accept
            create_valid_fact(confidence=0.50),  # pending review
            create_valid_fact(confidence=0.10),  # auto-reject candidate
            create_valid_fact(confidence=0.95, canonical_metric_id=""),  # schema failure
        ]
        context = MockPipelineContext(deduplicated_facts=facts)

        result = stage.process(context)  # noqa: F841

        assert result.metadata["auto_accepted"] == 1
        assert result.metadata["pending_review"] == 3
        assert result.metadata["auto_reject_candidates"] == 1
        assert result.metadata["schema_validation_failures"] == 1

    def test_stage_result_has_duration(self) -> None:
        """StageResult includes duration_ms."""
        stage = ValidationStage()
        context = MockPipelineContext(deduplicated_facts=[create_valid_fact()])

        result = stage.process(context)  # noqa: F841

        assert result.duration_ms >= 0

    def test_stage_result_stage_name(self) -> None:
        """StageResult has correct stage identifier."""
        from src.extraction_v2.pipeline import PipelineStage

        stage = ValidationStage()
        context = MockPipelineContext(deduplicated_facts=[create_valid_fact()])

        result = stage.process(context)  # noqa: F841

        assert result.stage == PipelineStage.VALIDATION
