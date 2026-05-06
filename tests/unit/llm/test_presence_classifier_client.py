"""Unit tests for src/llm/presence_classifier_client.py.

Covers config loading, threshold resolution, paraphrase-recall enrollment
lookup, and the classify_segment wire path (multi-label call + Sonnet
fallback) with a fake Anthropic client.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.llm.presence_classifier_client import (
    PresenceClassifierClient,
    _build_system_text,
    _metric_set_hash,
    load_all_prompts,
    load_classifier_config,
    load_metric_prompt,
    load_recall_augmentation,
    load_thresholds,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


@pytest.fixture
def config_root(tmp_path: Path) -> Path:
    _write(
        tmp_path / "recall_augmentation.yaml",
        """\
        version: 1
        enrolled_metrics:
          - cm_net_revenue_retention
          - cm_revenue_concentration
        section_whitelist:
          - mda
          - business
        """,
    )
    _write(
        tmp_path / "thresholds.yaml",
        """\
        version: 1
        thresholds:
          cm_net_revenue_retention:
            threshold: 0.62
            sonnet_band: [0.40, 0.70]
        defaults:
          threshold: 0.50
          sonnet_band: [0.35, 0.65]
        """,
    )
    _write(
        tmp_path / "prompts" / "cm_net_revenue_retention.yaml",
        """\
        prompt_version: "0.1.0-test"
        metric_id: cm_net_revenue_retention
        definition: |
          NRR is the dollar-based retention rate including expansion.
        positive_signals:
          - explicit "net revenue retention"
        negative_signals:
          - customer-count retention only
        few_shot_examples: []
        decision_format: |
          {"present": <bool>, "score": <0..1>, "rationale": "..."}
        """,
    )
    _write(
        tmp_path / "prompts" / "cm_revenue_concentration.yaml",
        """\
        prompt_version: "0.1.0-test"
        metric_id: cm_revenue_concentration
        definition: |
          Revenue concentration is the share of revenue from top customers.
        positive_signals:
          - explicit "revenue concentration"
        negative_signals:
          - customer-count metrics
        decision_format: "{}"
        """,
    )
    return tmp_path


def test_load_recall_augmentation(config_root: Path) -> None:
    cfg = load_recall_augmentation(config_root / "recall_augmentation.yaml")
    assert "cm_net_revenue_retention" in cfg.enrolled_metrics
    assert "cm_revenue_concentration" in cfg.enrolled_metrics
    assert cfg.section_whitelist == frozenset({"mda", "business"})


def test_load_thresholds_with_defaults(config_root: Path) -> None:
    cfg = load_thresholds(config_root / "thresholds.yaml")
    assert cfg.per_metric["cm_net_revenue_retention"].threshold == 0.62
    assert cfg.per_metric["cm_net_revenue_retention"].sonnet_band == (0.40, 0.70)
    assert cfg.default_threshold == 0.50
    assert cfg.default_sonnet_band == (0.35, 0.65)


def test_load_thresholds_rejects_inverted_sonnet_band(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text(
        textwrap.dedent("""\
        version: 1
        thresholds: {}
        defaults:
          threshold: 0.50
          sonnet_band: [0.70, 0.30]
    """)
    )
    with pytest.raises(AssertionError, match="sonnet_band must satisfy lo < hi"):
        load_thresholds(bad)


def test_load_metric_prompt(config_root: Path) -> None:
    prompt = load_metric_prompt("cm_net_revenue_retention", prompts_dir=config_root / "prompts")
    assert prompt.metric_id == "cm_net_revenue_retention"
    assert prompt.prompt_version == "0.1.0-test"
    assert "dollar-based" in prompt.definition
    assert prompt.positive_signals == ('explicit "net revenue retention"',)
    assert prompt.negative_signals == ("customer-count retention only",)
    assert prompt.few_shot_examples == ()
    assert prompt.decision_format.startswith('{"present"')


def test_load_metric_prompt_rejects_mismatched_metric_id(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    _write(
        prompts / "cm_net_revenue_retention.yaml",
        """\
        prompt_version: "0.1.0-test"
        metric_id: cm_some_other_metric
        definition: x
        decision_format: "{}"
        """,
    )
    with pytest.raises(AssertionError, match="declares metric_id"):
        load_metric_prompt("cm_net_revenue_retention", prompts_dir=prompts)


def test_load_all_prompts_skips_when_missing(tmp_path: Path) -> None:
    # No prompts/ dir under tmp_path -> empty dict, no error
    assert load_all_prompts(tmp_path / "prompts") == {}


def test_load_classifier_config_aggregates_all(config_root: Path) -> None:
    cfg = load_classifier_config(config_root=config_root)
    assert cfg.recall_augmentation is not None
    assert "cm_net_revenue_retention" in cfg.recall_augmentation.enrolled_metrics
    assert "cm_net_revenue_retention" in cfg.prompts
    assert "cm_net_revenue_retention" in cfg.thresholds
    assert cfg.default_threshold == 0.50


def test_threshold_for_uses_per_metric_when_present(config_root: Path) -> None:
    client = PresenceClassifierClient(load_classifier_config(config_root=config_root))
    thr, band = client.threshold_for("cm_net_revenue_retention")
    assert thr == 0.62
    assert band == (0.40, 0.70)


def test_threshold_for_falls_back_to_defaults(config_root: Path) -> None:
    client = PresenceClassifierClient(load_classifier_config(config_root=config_root))
    thr, band = client.threshold_for("cm_brand_new_metric_no_calibration_yet")
    assert thr == 0.50
    assert band == (0.35, 0.65)


def test_is_paraphrase_enrolled(config_root: Path) -> None:
    client = PresenceClassifierClient(load_classifier_config(config_root=config_root))
    assert client.is_paraphrase_enrolled("cm_net_revenue_retention") is True
    assert client.is_paraphrase_enrolled("cm_active_customers_total") is False


def test_default_config_loads_from_repo(tmp_path: Path) -> None:
    """Smoke-test that the repo's actual config files are well-formed.

    Loads from the default CONFIG_ROOT (no override). If any YAML file in
    config/llm_classifier/ is malformed, this test fails fast.
    """
    cfg = load_classifier_config()
    assert cfg.recall_augmentation is not None
    assert isinstance(cfg.default_threshold, float)
    # The shipped NRR template must parse
    assert "cm_net_revenue_retention" in cfg.prompts
    nrr = cfg.prompts["cm_net_revenue_retention"]
    assert nrr.prompt_version
    assert nrr.definition


# ---------------------------------------------------------------------------
# classify_segment — fake Anthropic client
# ---------------------------------------------------------------------------


def _fake_response(metrics: list[dict[str, Any]], *, usage: dict[str, int] | None = None) -> Any:
    """Build a SimpleNamespace shaped like an anthropic.Message response."""
    text_block = SimpleNamespace(type="text", text=json.dumps({"metrics": metrics}))
    usage_obj = SimpleNamespace(
        input_tokens=(usage or {}).get("input_tokens", 100),
        output_tokens=(usage or {}).get("output_tokens", 50),
        cache_read_input_tokens=(usage or {}).get("cache_read_input_tokens", 0),
        cache_creation_input_tokens=(usage or {}).get("cache_creation_input_tokens", 0),
    )
    return SimpleNamespace(content=[text_block], usage=usage_obj)


class _FakeAnthropic:
    """Records every messages.create call; pops responses from a queue."""

    def __init__(self, responses: list[Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError(
                f"FakeAnthropic ran out of canned responses (call #{len(self.calls)})"
            )
        return self._responses.pop(0)


def _make_client(
    config_root: Path,
    responses: list[Any],
) -> tuple[PresenceClassifierClient, _FakeAnthropic]:
    fake = _FakeAnthropic(responses)
    cfg = load_classifier_config(config_root=config_root)
    client = PresenceClassifierClient(cfg, anthropic_client=fake)
    return client, fake


def test_classify_segment_empty_metric_ids_returns_empty(config_root: Path) -> None:
    client, fake = _make_client(config_root, responses=[])
    assert client.classify_segment("some text", []) == []
    assert fake.calls == []  # no API call


def test_classify_segment_unknown_metric_raises(config_root: Path) -> None:
    client, _fake = _make_client(config_root, responses=[])
    with pytest.raises(ValueError, match="No classifier prompt loaded"):
        client.classify_segment("text", ["cm_does_not_exist"])


def test_classify_segment_happy_path_no_sonnet_fallback(config_root: Path) -> None:
    """Both metrics return scores well outside the [0.40, 0.70] / [0.35, 0.65]
    Sonnet bands → no fallback call."""
    response = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": True,
                "score": 0.92,
                "rationale": "explicit NRR",
            },
            {
                "metric_id": "cm_revenue_concentration",
                "present": False,
                "score": 0.05,
                "rationale": "no concentration",
            },
        ]
    )
    client, fake = _make_client(config_root, responses=[response])
    out = client.classify_segment(
        "Net Dollar Retention was 132%.",
        ["cm_net_revenue_retention", "cm_revenue_concentration"],
    )
    assert len(fake.calls) == 1, "should not have fallen back to Sonnet"
    assert fake.calls[0]["model"] == client.config.haiku_model
    by_metric = {c.metric_id: c for c in out}
    assert by_metric["cm_net_revenue_retention"].score == 0.92
    assert by_metric["cm_net_revenue_retention"].present is True
    assert by_metric["cm_net_revenue_retention"].sonnet_fallback is False
    assert by_metric["cm_net_revenue_retention"].model == client.config.haiku_model
    assert by_metric["cm_revenue_concentration"].present is False
    assert by_metric["cm_revenue_concentration"].sonnet_fallback is False


def test_classify_segment_sonnet_fallback_replaces_borderline_only(config_root: Path) -> None:
    """NRR scores 0.55 (inside band [0.40, 0.70]) → Sonnet retry for NRR only.
    Concentration scores 0.05 → stays on Haiku."""
    haiku = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": False,
                "score": 0.55,
                "rationale": "ambiguous",
            },
            {
                "metric_id": "cm_revenue_concentration",
                "present": False,
                "score": 0.05,
                "rationale": "no signal",
            },
        ]
    )
    sonnet = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": True,
                "score": 0.81,
                "rationale": "Sonnet says yes",
            },
        ]
    )
    client, fake = _make_client(config_root, responses=[haiku, sonnet])
    out = client.classify_segment(
        "ambiguous prose",
        ["cm_net_revenue_retention", "cm_revenue_concentration"],
    )
    assert len(fake.calls) == 2
    assert fake.calls[0]["model"] == client.config.haiku_model
    assert fake.calls[1]["model"] == client.config.sonnet_model
    by_metric = {c.metric_id: c for c in out}
    assert by_metric["cm_net_revenue_retention"].score == 0.81
    assert by_metric["cm_net_revenue_retention"].sonnet_fallback is True
    assert by_metric["cm_net_revenue_retention"].model == client.config.sonnet_model
    assert by_metric["cm_revenue_concentration"].sonnet_fallback is False
    assert by_metric["cm_revenue_concentration"].model == client.config.haiku_model


def test_classify_segment_present_uses_threshold(config_root: Path) -> None:
    """NRR threshold is 0.62; a 0.85 Sonnet score crosses it (`present=True`)
    but a 0.30 score does not (`present=False`)."""
    haiku = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": False,
                "score": 0.50,
                "rationale": "borderline",
            },
        ]
    )
    sonnet = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": False,
                "score": 0.30,
                "rationale": "no",
            },
        ]
    )
    client, _fake = _make_client(config_root, responses=[haiku, sonnet])
    out = client.classify_segment("text", ["cm_net_revenue_retention"])
    assert out[0].score == 0.30
    assert out[0].present is False  # 0.30 < 0.62 threshold


def test_classify_segment_clamps_score_to_unit_interval(config_root: Path) -> None:
    """Defensive: model returns score=1.5 (out of bounds); we clamp to [0, 1]."""
    response = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": True,
                "score": 1.5,
                "rationale": "x",
            },
        ]
    )
    client, _fake = _make_client(config_root, responses=[response])
    out = client.classify_segment("text", ["cm_net_revenue_retention"])
    assert out[0].score == 1.0


def test_classify_segment_sets_cache_control_on_system_block(config_root: Path) -> None:
    response = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": True,
                "score": 0.9,
                "rationale": "x",
            },
        ]
    )
    client, fake = _make_client(config_root, responses=[response])
    client.classify_segment("text", ["cm_net_revenue_retention"])
    system_arg = fake.calls[0]["system"]
    assert isinstance(system_arg, list) and len(system_arg) == 1
    assert system_arg[0]["cache_control"] == {"type": "ephemeral"}
    # Output schema is wired in
    assert "output_config" in fake.calls[0]
    assert fake.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_classify_segment_response_missing_metric_raises(config_root: Path) -> None:
    response = _fake_response(
        [
            {
                "metric_id": "cm_net_revenue_retention",
                "present": True,
                "score": 0.9,
                "rationale": "ok",
            },
        ]
    )
    client, _fake = _make_client(config_root, responses=[response])
    with pytest.raises(ValueError, match="missing metrics"):
        client.classify_segment(
            "text",
            ["cm_net_revenue_retention", "cm_revenue_concentration"],
        )


def test_classify_segment_invalid_json_raises(config_root: Path) -> None:
    bad = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="not json")],
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=10,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )
    client, _fake = _make_client(config_root, responses=[bad])
    with pytest.raises(ValueError, match="not valid JSON"):
        client.classify_segment("text", ["cm_net_revenue_retention"])


def test_classify_segment_returns_in_input_order(config_root: Path) -> None:
    """Output preserves the caller's metric_ids order even when the API
    returns them in a different order."""
    response = _fake_response(
        [
            # Reversed vs the input order
            {
                "metric_id": "cm_revenue_concentration",
                "present": False,
                "score": 0.10,
                "rationale": "no",
            },
            {
                "metric_id": "cm_net_revenue_retention",
                "present": True,
                "score": 0.90,
                "rationale": "yes",
            },
        ]
    )
    client, _fake = _make_client(config_root, responses=[response])
    out = client.classify_segment(
        "text",
        ["cm_net_revenue_retention", "cm_revenue_concentration"],
    )
    assert [c.metric_id for c in out] == ["cm_net_revenue_retention", "cm_revenue_concentration"]


# ---------------------------------------------------------------------------
# Determinism helpers
# ---------------------------------------------------------------------------


def test_build_system_text_is_order_invariant(config_root: Path) -> None:
    cfg = load_classifier_config(config_root=config_root)
    a_b = _build_system_text(
        [cfg.prompts["cm_net_revenue_retention"], cfg.prompts["cm_revenue_concentration"]]
    )
    b_a = _build_system_text(
        [cfg.prompts["cm_revenue_concentration"], cfg.prompts["cm_net_revenue_retention"]]
    )
    assert a_b == b_a, "system text must be order-invariant for cache hits"
    assert "cm_net_revenue_retention" in a_b
    assert "cm_revenue_concentration" in a_b


def test_metric_set_hash_is_order_invariant() -> None:
    assert _metric_set_hash(["a", "b", "c"]) == _metric_set_hash(["c", "a", "b"])
    assert _metric_set_hash(["a", "b"]) != _metric_set_hash(["a", "c"])
