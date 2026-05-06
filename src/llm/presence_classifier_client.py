"""LLM presence-classifier client.

Anthropic SDK wrapper for the per-(segment, metric) presence classifier
introduced in Phase 1 of the metric-identification redesign. Distinct from
``vision_client.py`` (image-modality, multi-provider) — this client is
text-only and Anthropic-only because the prompt-caching strategy below
is specific to Anthropic's cache-control semantics.

Caching has two layers:

1. **Server-side prompt cache (Anthropic)** — the per-metric definition
   + few-shot block is sent with ``cache_control={"type": "ephemeral"}``
   so the model server caches the prefix. Cache key (server-side) is the
   full prefix bytes; we make the prefix stable by sorting metric blocks
   deterministically and writing prompt YAML with stable key order.
   Target ≥85% cache hit rate across a validator run.

2. **Local response cache (LLMCache)** — full (model, prompt, segment)
   responses memoized to the on-disk SQLite cache shared with
   ``vision_client.py``. Cache key includes ``prompt_version`` so
   versioned prompt changes invalidate cleanly.

This module currently exposes the public API and config loaders only.
Wire-level model calls land in PR3 alongside the
``LLMPresenceClassifierStage`` extraction stage.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_SONNET_MODEL = "claude-sonnet-4-6"

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config" / "llm_classifier"


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricPrompt:
    """Per-metric classifier prompt — versioned, hand-edited definition + signals."""

    metric_id: str
    prompt_version: str
    definition: str
    positive_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    few_shot_examples: tuple[dict[str, Any], ...]
    decision_format: str


@dataclass(frozen=True)
class MetricThreshold:
    """Calibrated decision threshold + Sonnet-fallback band for one metric."""

    metric_id: str
    threshold: float
    sonnet_band: tuple[float, float]


@dataclass(frozen=True)
class RecallAugmentationConfig:
    """Paraphrase-recall path enrollment — which metrics get the
    definition-anchored scan independent of keyword candidate_generation."""

    enrolled_metrics: frozenset[str]
    section_whitelist: frozenset[str]


@dataclass
class ClassifierClientConfig:
    """Aggregated config for one classifier run."""

    haiku_model: str = DEFAULT_HAIKU_MODEL
    sonnet_model: str = DEFAULT_SONNET_MODEL
    api_key: str | None = None
    recall_augmentation: RecallAugmentationConfig | None = None
    prompts: dict[str, MetricPrompt] = field(default_factory=dict)
    thresholds: dict[str, MetricThreshold] = field(default_factory=dict)
    default_threshold: float = 0.50
    default_sonnet_band: tuple[float, float] = (0.35, 0.65)


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------


def load_recall_augmentation(path: Path | None = None) -> RecallAugmentationConfig:
    src = path or (CONFIG_ROOT / "recall_augmentation.yaml")
    with src.open() as f:
        raw = yaml.safe_load(f)
    return RecallAugmentationConfig(
        enrolled_metrics=frozenset(raw["enrolled_metrics"]),
        section_whitelist=frozenset(raw["section_whitelist"]),
    )


def load_thresholds(path: Path | None = None) -> tuple[dict[str, MetricThreshold], float, tuple[float, float]]:
    src = path or (CONFIG_ROOT / "thresholds.yaml")
    with src.open() as f:
        raw = yaml.safe_load(f)
    defaults = raw.get("defaults", {})
    default_threshold = float(defaults.get("threshold", 0.50))
    band = defaults.get("sonnet_band", [0.35, 0.65])
    default_band = (float(band[0]), float(band[1]))
    out: dict[str, MetricThreshold] = {}
    for metric_id, entry in (raw.get("thresholds") or {}).items():
        entry_band = entry.get("sonnet_band", band)
        out[metric_id] = MetricThreshold(
            metric_id=metric_id,
            threshold=float(entry["threshold"]),
            sonnet_band=(float(entry_band[0]), float(entry_band[1])),
        )
    return out, default_threshold, default_band


def load_metric_prompt(metric_id: str, prompts_dir: Path | None = None) -> MetricPrompt:
    """Load a metric prompt, merging an optional sidecar few-shots file.

    The main file ``<metric_id>.yaml`` is human-authored: definition, signals,
    decision_format, prompt_version. The sidecar ``<metric_id>.few_shots.yaml``
    is automation-owned (written by ``scripts/calibrate_llm_thresholds.py``).
    Splitting them avoids the calibration script clobbering hand-authored
    content. If the main file carries a ``few_shot_examples`` key (legacy or
    inline overrides), the sidecar takes precedence when present.
    """
    base_dir = prompts_dir or (CONFIG_ROOT / "prompts")
    main_path = base_dir / f"{metric_id}.yaml"
    with main_path.open() as f:
        raw = yaml.safe_load(f)
    few_shots = raw.get("few_shot_examples", []) or []
    sidecar_path = base_dir / f"{metric_id}.few_shots.yaml"
    if sidecar_path.exists():
        with sidecar_path.open() as f:
            sidecar = yaml.safe_load(f) or {}
        few_shots = sidecar.get("few_shot_examples", []) or []
    return MetricPrompt(
        metric_id=raw["metric_id"],
        prompt_version=raw["prompt_version"],
        definition=raw["definition"].strip(),
        positive_signals=tuple(raw.get("positive_signals", [])),
        negative_signals=tuple(raw.get("negative_signals", [])),
        few_shot_examples=tuple(few_shots),
        decision_format=raw.get("decision_format", "").strip(),
    )


def load_all_prompts(prompts_dir: Path | None = None) -> dict[str, MetricPrompt]:
    src = prompts_dir or (CONFIG_ROOT / "prompts")
    out: dict[str, MetricPrompt] = {}
    if not src.exists():
        return out
    for yaml_path in sorted(src.glob("*.yaml")):
        # Skip sidecar files; they are loaded by load_metric_prompt itself.
        if yaml_path.name.endswith(".few_shots.yaml"):
            continue
        metric_id = yaml_path.stem
        out[metric_id] = load_metric_prompt(metric_id, prompts_dir=src)
    return out


def load_classifier_config(config_root: Path | None = None) -> ClassifierClientConfig:
    """Load all three config files into a single ClassifierClientConfig.

    API key resolution: ``ANTHROPIC_API_KEY`` env var; left ``None`` if absent
    so config can be inspected (eg. tests, calibration dry-runs) without
    requiring a live key.
    """
    root = config_root or CONFIG_ROOT
    recall = load_recall_augmentation(root / "recall_augmentation.yaml")
    thresholds, default_thr, default_band = load_thresholds(root / "thresholds.yaml")
    prompts = load_all_prompts(root / "prompts")
    return ClassifierClientConfig(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        recall_augmentation=recall,
        prompts=prompts,
        thresholds=thresholds,
        default_threshold=default_thr,
        default_sonnet_band=default_band,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentClassification:
    """Output of one classifier call for one (segment, metric) pair."""

    metric_id: str
    score: float
    present: bool
    rationale: str
    model: str
    sonnet_fallback: bool
    prompt_version: str


class PresenceClassifierClient:
    """Anthropic-backed classifier for per-(segment, metric) presence.

    The classification entrypoint (``classify_segment``) is intentionally
    not implemented in this PR — the foundation lands the config + client
    skeleton so subsequent PRs can wire the calibration script and
    extraction stage without churn on this interface.
    """

    def __init__(self, config: ClassifierClientConfig | None = None) -> None:
        self.config = config or load_classifier_config()

    def threshold_for(self, metric_id: str) -> tuple[float, tuple[float, float]]:
        """Return (threshold, sonnet_band) for a metric, falling back to defaults."""
        cfg = self.config.thresholds.get(metric_id)
        if cfg is not None:
            return cfg.threshold, cfg.sonnet_band
        return self.config.default_threshold, self.config.default_sonnet_band

    def is_paraphrase_enrolled(self, metric_id: str) -> bool:
        recall = self.config.recall_augmentation
        if recall is None:
            return False
        return metric_id in recall.enrolled_metrics

    def classify_segment(
        self,
        segment_text: str,
        metric_ids: list[str],
        section_type: str | None = None,
    ) -> list[SegmentClassification]:
        """Score a segment against multiple metrics in a single batched call.

        Implementation lands in PR3 with the LLMPresenceClassifierStage.
        """
        raise NotImplementedError(
            "classify_segment is wired in PR3 (LLMPresenceClassifierStage). "
            "Foundation PR ships config + skeleton only."
        )
