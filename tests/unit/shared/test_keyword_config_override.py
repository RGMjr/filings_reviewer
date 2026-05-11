"""Override-plumbing tests for keyword_config public getters.

Foundation for the simulate-and-ship flow on /v2/review/stats. Each public
getter accepts an optional `override` dict; these tests guard two
invariants:

1. The override actually replaces the relevant per-metric pattern list.
2. The override never poisons the LRU-cached YAML; subsequent calls without
   override return the YAML defaults.
3. Calling with `override=None` is byte-identical to calling without the
   keyword (no-override identity guard).

These tests do not exercise pipeline-level threading — that lands in the
follow-up PR that wires PipelineConfig.keyword_override through consumer
stages.
"""

from __future__ import annotations

import pytest

from src.shared.keyword_config import (
    get_exclusion_patterns,
    get_metric_keywords,
    get_specific_patterns,
    get_specific_patterns_by_metric,
    reload_config,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reload_config()
    yield
    reload_config()


# ---------------------------------------------------------------------------
# 1. Override application
# ---------------------------------------------------------------------------


def test_get_metric_keywords_override_replaces_patterns_for_listed_metric():
    """Override per-metric pattern list fully replaces the YAML list."""
    baseline = get_metric_keywords()
    target_metric = next(iter(baseline))  # any active metric

    sentinel = ["zzzzz_sentinel_pattern_not_in_yaml"]
    patched = get_metric_keywords(override={target_metric: sentinel})

    assert patched[target_metric] == sentinel
    # Untouched metrics survive
    other_metrics = [m for m in baseline if m != target_metric]
    if other_metrics:
        sample = other_metrics[0]
        assert patched[sample] == baseline[sample]


def test_get_exclusion_patterns_override_adds_to_metrics_without_yaml_exclusions():
    """Override may introduce exclusions for a metric that has none in YAML."""
    yaml_excl = get_exclusion_patterns()
    # Pick a metric without YAML exclusions, or fall back to any metric
    candidates = [m for m in get_metric_keywords() if m not in yaml_excl]
    target = candidates[0] if candidates else next(iter(yaml_excl))

    patched = get_exclusion_patterns(override={target: ["custom_excl"]})
    assert patched[target] == ["custom_excl"]


def test_get_specific_patterns_by_metric_override_replaces_per_metric():
    baseline = get_specific_patterns_by_metric()
    target = next(iter(baseline)) if baseline else None
    if target is None:
        pytest.skip("No specific_patterns in YAML to override")

    patched = get_specific_patterns_by_metric(override={target: ["zzz_specific"]})
    assert patched[target] == ["zzz_specific"]


def test_get_specific_patterns_flat_list_reflects_override():
    """The flat list getter must rebuild from the overridden per-metric dict."""
    baseline_by_metric = get_specific_patterns_by_metric()
    if not baseline_by_metric:
        pytest.skip("No specific_patterns in YAML to override")
    target = next(iter(baseline_by_metric))

    flat = get_specific_patterns(override={target: ["zzz_flat"]})
    assert "zzz_flat" in flat
    # Original patterns for the target are gone (replaced, not appended)
    for original in baseline_by_metric[target]:
        assert original not in flat or original == "zzz_flat"


# ---------------------------------------------------------------------------
# 2. Cache non-poisoning
# ---------------------------------------------------------------------------


def test_metric_keywords_override_does_not_poison_cache():
    """A call with override must not affect a subsequent call without it."""
    baseline_before = get_metric_keywords()
    target = next(iter(baseline_before))

    # Apply an override on one call
    _ = get_metric_keywords(override={target: ["zzz_temp"]})

    # Subsequent no-override call must equal the YAML baseline
    baseline_after = get_metric_keywords()
    assert baseline_after == baseline_before
    assert baseline_after[target] == baseline_before[target]


def test_exclusion_patterns_override_does_not_poison_cache():
    baseline_before = get_exclusion_patterns()
    target = next(iter(get_metric_keywords()))

    _ = get_exclusion_patterns(override={target: ["zzz_temp_excl"]})

    baseline_after = get_exclusion_patterns()
    assert baseline_after == baseline_before


# ---------------------------------------------------------------------------
# 3. No-override identity
# ---------------------------------------------------------------------------


def test_get_metric_keywords_none_override_identity():
    """override=None must produce identical output to no-arg call."""
    assert get_metric_keywords(override=None) == get_metric_keywords()


def test_get_exclusion_patterns_none_override_identity():
    assert get_exclusion_patterns(override=None) == get_exclusion_patterns()


def test_get_specific_patterns_none_override_identity():
    assert get_specific_patterns(override=None) == get_specific_patterns()


def test_get_specific_patterns_by_metric_none_override_identity():
    assert get_specific_patterns_by_metric(override=None) == get_specific_patterns_by_metric()
