"""Unit tests for src/llm/presence_classifier_client.py.

Foundation-PR scope: config loading + threshold resolution + paraphrase-recall
enrollment lookup. The classify_segment wire path is exercised in PR3.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.llm.presence_classifier_client import (
    PresenceClassifierClient,
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
    return tmp_path


def test_load_recall_augmentation(config_root: Path) -> None:
    cfg = load_recall_augmentation(config_root / "recall_augmentation.yaml")
    assert "cm_net_revenue_retention" in cfg.enrolled_metrics
    assert "cm_revenue_concentration" in cfg.enrolled_metrics
    assert cfg.section_whitelist == frozenset({"mda", "business"})


def test_load_thresholds_with_defaults(config_root: Path) -> None:
    thresholds, default_thr, default_band = load_thresholds(config_root / "thresholds.yaml")
    assert thresholds["cm_net_revenue_retention"].threshold == 0.62
    assert thresholds["cm_net_revenue_retention"].sonnet_band == (0.40, 0.70)
    assert default_thr == 0.50
    assert default_band == (0.35, 0.65)


def test_load_metric_prompt(config_root: Path) -> None:
    prompt = load_metric_prompt("cm_net_revenue_retention", prompts_dir=config_root / "prompts")
    assert prompt.metric_id == "cm_net_revenue_retention"
    assert prompt.prompt_version == "0.1.0-test"
    assert "dollar-based" in prompt.definition
    assert prompt.positive_signals == ('explicit "net revenue retention"',)
    assert prompt.negative_signals == ("customer-count retention only",)
    assert prompt.few_shot_examples == ()
    assert prompt.decision_format.startswith('{"present"')


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


def test_classify_segment_not_implemented_in_foundation(config_root: Path) -> None:
    client = PresenceClassifierClient(load_classifier_config(config_root=config_root))
    with pytest.raises(NotImplementedError):
        client.classify_segment("some text", ["cm_net_revenue_retention"])


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
