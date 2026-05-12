"""End-to-end safety guards for PipelineConfig override threading.

PR-A2 of the simulate-and-ship recommendation flow. PR #607 (foundation)
added the TypedDict fields + getter `override` params. This PR wires
`PipelineConfig.keyword_override` and `PipelineConfig.fp_filter_override`
through to CandidateGenerationStage, ValueBindingStage,
FalsePositiveFilterStage, and the chart classifiers via ChartFactBridgeStage.

Two safety gates here:

1. **Override-threading completeness**: an explicit override on a target
   metric must reach every consumer's compiled-pattern state, NOT just
   pass through silently.
2. **fp_filter_override propagates**: the TypedDict kwargs must land on
   the V1 FalsePositiveFilter constructor (both normal + relaxed
   instances).

These tests do not exercise full pipeline.process() — they verify the
stage-level construction contract that the simulation script will rely
on. The byte-identity (`config=None` default) guard already lives in
`tests/unit/shared/test_keyword_config_override.py` (PR #607).
"""

from __future__ import annotations

import pytest

from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.pipeline import PipelineConfig
from src.extraction_v2.stages.candidate_generation import CandidateGenerationStage
from src.extraction_v2.stages.false_positive_filter import FalsePositiveFilterStage
from src.extraction_v2.stages.value_binding import ValueBindingStage
from src.shared.keyword_config import get_metric_keywords, reload_config


@pytest.fixture(autouse=True)
def _reset_cache():
    reload_config()
    yield
    reload_config()


# ---------------------------------------------------------------------------
# 1. Override-threading completeness
# ---------------------------------------------------------------------------


def test_candidate_generation_uses_keyword_override():
    """CandidateGenerationStage must compile from the override, not the YAML."""
    target = next(iter(get_metric_keywords()))
    sentinel = r"\bzzzzz_override_sentinel\b"

    config = PipelineConfig(keyword_override={"metric_keywords": {target: [sentinel]}})
    stage = CandidateGenerationStage(config=config)
    assert stage._ensure_initialized() is True

    assert stage._keywords[target] == [sentinel]
    # Compiled patterns must reflect the sentinel (not the YAML patterns)
    compiled_for_target = stage._compiled_patterns.get(target, [])
    assert any(p.pattern == sentinel for p in compiled_for_target)


def test_candidate_generation_none_config_uses_yaml_defaults():
    """No config = no override = byte-identical to pre-PR behavior."""
    stage_default = CandidateGenerationStage()
    stage_none = CandidateGenerationStage(config=None)
    stage_no_override = CandidateGenerationStage(config=PipelineConfig())

    assert stage_default._ensure_initialized() is True
    assert stage_none._ensure_initialized() is True
    assert stage_no_override._ensure_initialized() is True

    assert stage_default._keywords == stage_none._keywords
    assert stage_default._keywords == stage_no_override._keywords


def test_value_binding_uses_specific_patterns_override():
    """ValueBindingStage stub-pattern compilation must reflect the override."""
    config = PipelineConfig(
        keyword_override={
            "specific_patterns": {
                "cm_active_customers_total": [r"override_only_specific"],
            }
        }
    )
    stage = ValueBindingStage(config=config)
    stage._ensure_stub_patterns()

    assert stage._stub_metric_patterns is not None
    target_patterns = stage._stub_metric_patterns.get("cm_active_customers_total")
    assert target_patterns is not None
    # Pattern is anchored with \A prefix; sentinel must appear in compiled regex
    assert any("override_only_specific" in p.pattern for p in target_patterns)


def test_chart_classifier_uses_keyword_override():
    """ChartMetricClassifier must read from the override."""
    sentinel_pattern = r"\bchart_sentinel_xyz\b"
    config = PipelineConfig(
        keyword_override={"metric_keywords": {"cm_revenue_by_cohort": [sentinel_pattern]}}
    )
    classifier = ChartMetricClassifier(config=config)

    assert classifier._keywords["cm_revenue_by_cohort"] == [sentinel_pattern]


# ---------------------------------------------------------------------------
# 2. fp_filter_override propagation
# ---------------------------------------------------------------------------


def test_fp_filter_override_lands_on_normal_v1_instance():
    """fp_filter_override kwargs must flow into the V1 FalsePositiveFilter."""
    config = PipelineConfig(fp_filter_override={"min_value": 999999, "filter_years": False})
    stage = FalsePositiveFilterStage(config=config)

    # The V1 filter's min_value attribute name may differ; assert via the
    # constructor-stored params we know are public.
    assert stage._filter.min_value == 999999
    assert stage._filter.filter_years is False


def test_fp_filter_override_also_lands_on_relaxed_v1_instance():
    """Both normal and relaxed V1 filters receive the override (override wins)."""
    config = PipelineConfig(fp_filter_override={"min_value": 12345})
    stage = FalsePositiveFilterStage(config=config)

    # Relaxed defaults set filter_financial_statements=False, filter_years=False,
    # min_value=2. Override should bump min_value to 12345 while preserving
    # the relaxed defaults for unmentioned kwargs.
    assert stage._filter_relaxed.min_value == 12345
    assert stage._filter_relaxed.filter_financial_statements is False
    assert stage._filter_relaxed.filter_years is False


def test_fp_filter_no_override_preserves_defaults():
    """config=None / no fp_filter_override keeps the historical defaults."""
    stage_default = FalsePositiveFilterStage()
    stage_explicit = FalsePositiveFilterStage(config=PipelineConfig())

    # Normal filter uses V1 defaults (min_value=10 historically)
    assert stage_default._filter.min_value == stage_explicit._filter.min_value
    # Relaxed filter still hard-codes its relaxed kwargs
    assert stage_default._filter_relaxed.min_value == 2
    assert stage_explicit._filter_relaxed.min_value == 2
