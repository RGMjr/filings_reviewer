"""LLM presence-classifier client.

Anthropic SDK wrapper for the per-(segment, metric) presence classifier
introduced in Phase 1 of the metric-identification redesign. Distinct from
``vision_client.py`` (image-modality, multi-provider) — this client is
text-only and Anthropic-only because the prompt-caching strategy below
is specific to Anthropic's cache-control semantics.

The classifier is multi-label per call: one Anthropic request scores all
requested metrics for a segment. The per-metric definition + few-shot
block is sent with ``cache_control={"type": "ephemeral"}`` so the model
server caches the prefix; the prefix is made stable by sorting metric
blocks by ``metric_id`` and rendering them deterministically. Any byte
change anywhere in the prefix invalidates the entire cache.

Two-pass model strategy:
- Default: Haiku 4.5 (cheap; ~$0.20-0.40 per filing target).
- Sonnet 4.6 fallback: any metric whose Haiku score lands in that
  metric's calibrated ``sonnet_band`` is re-scored on Sonnet for that
  segment. The Sonnet score replaces the Haiku score in the final result.

The ``LLMPresenceClassifierStage`` (PR3 Part D) wires this client into
the V2 extraction pipeline; calibrated thresholds come from
``config/llm_classifier/thresholds.yaml`` (PR3 Part G).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
# Sonnet 4.6's canonical alias is the un-dated form per Anthropic's model
# catalog; unlike Haiku 4.5 there is no stable date-suffixed alias yet.
# Pin shape kept consistent: any future change to a date-suffixed Sonnet
# alias should follow the Haiku pattern.
DEFAULT_SONNET_MODEL = "claude-sonnet-4-6"

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config" / "llm_classifier"

# Per-1M-token pricing in USD, used by classify_segment to log a cost
# estimate per call. Updated when Anthropic publishes new rates; pinned here
# rather than hit a live pricing API on every classifier call.
_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}
_DEFAULT_PRICING: tuple[float, float] = (3.00, 15.00)
# Anthropic prompt-caching: cache reads cost ~0.1x base input price; 5-minute
# ephemeral cache writes cost ~1.25x base input. See claude-api skill
# (shared/prompt-caching.md) for current multipliers.
_CACHE_READ_MULTIPLIER = 0.10
_CACHE_WRITE_MULTIPLIER = 1.25
# Output JSON schema for the multi-label classifier call. Numeric range
# constraints (minimum/maximum on score) are not honored by structured
# outputs; classify_segment clamps client-side.
_CLASSIFY_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric_id": {"type": "string"},
                    "present": {"type": "boolean"},
                    "score": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["metric_id", "present", "score", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["metrics"],
    "additionalProperties": False,
}
# Max tokens per classifier response — enough headroom for ~8 metrics each
# with a one-sentence rationale. Bumped if multi-label output starts hitting
# the cap.
_CLASSIFY_MAX_TOKENS = 2048


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
class ThresholdsConfig:
    """Parsed contents of ``config/llm_classifier/thresholds.yaml``."""

    per_metric: dict[str, MetricThreshold]
    default_threshold: float
    default_sonnet_band: tuple[float, float]


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


def _validated_band(band: list[float] | tuple[float, float], *, where: str) -> tuple[float, float]:
    lo, hi = float(band[0]), float(band[1])
    assert lo < hi, f"sonnet_band must satisfy lo < hi (got [{lo}, {hi}] in {where})"
    return lo, hi


def load_thresholds(path: Path | None = None) -> ThresholdsConfig:
    src = path or (CONFIG_ROOT / "thresholds.yaml")
    with src.open() as f:
        raw = yaml.safe_load(f)
    defaults = raw.get("defaults", {})
    default_threshold = float(defaults.get("threshold", 0.50))
    default_band = _validated_band(
        defaults.get("sonnet_band", [0.35, 0.65]),
        where=f"{src} defaults",
    )
    out: dict[str, MetricThreshold] = {}
    for metric_id, entry in (raw.get("thresholds") or {}).items():
        entry_band = _validated_band(
            entry.get("sonnet_band", list(default_band)),
            where=f"{src} thresholds.{metric_id}",
        )
        out[metric_id] = MetricThreshold(
            metric_id=metric_id,
            threshold=float(entry["threshold"]),
            sonnet_band=entry_band,
        )
    return ThresholdsConfig(
        per_metric=out,
        default_threshold=default_threshold,
        default_sonnet_band=default_band,
    )


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
    assert raw["metric_id"] == metric_id, (
        f"prompt YAML at {main_path} declares metric_id={raw['metric_id']!r} "
        f"but filename stem is {metric_id!r}; rename the file or fix the YAML"
    )
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
    thresholds = load_thresholds(root / "thresholds.yaml")
    prompts = load_all_prompts(root / "prompts")
    return ClassifierClientConfig(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        recall_augmentation=recall,
        prompts=prompts,
        thresholds=thresholds.per_metric,
        default_threshold=thresholds.default_threshold,
        default_sonnet_band=thresholds.default_sonnet_band,
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


# ---------------------------------------------------------------------------
# Prompt construction (deterministic — every byte feeds the cache key)
# ---------------------------------------------------------------------------


_SYSTEM_HEADER = (
    "You are a metric-presence classifier for SEC S-1 / F-1 filings.\n"
    "For each metric below, score whether the user-provided segment of\n"
    "filing prose discusses that metric (regardless of whether a numeric\n"
    "value is present). Use the metric definition, positive/negative\n"
    "signals, and few-shot examples as your guide.\n\n"
    "Return a single JSON object matching the response schema. Include one\n"
    "entry in 'metrics' for EVERY metric listed below. 'score' is your\n"
    "calibrated [0..1] confidence that the metric is being discussed.\n"
    "'present' is your boolean call at the deployment threshold; the\n"
    "downstream pipeline may override it using a calibrated threshold.\n"
    "'rationale' is one short sentence quoting the most decisive evidence.\n"
)


def _format_few_shot(example: dict[str, Any]) -> str:
    label = "PRESENT" if example.get("label") else "NOT PRESENT"
    text = (example.get("text") or "").strip()
    extra = ""
    rej = example.get("rejection_category")
    if rej:
        extra = f" [reviewer rejection_category={rej}]"
    return f"  - [{label}]{extra} {text}"


def _format_metric_block(prompt: MetricPrompt) -> str:
    parts = [
        f"### metric_id: {prompt.metric_id}",
        f"prompt_version: {prompt.prompt_version}",
        "",
        "Definition:",
        prompt.definition.strip(),
    ]
    if prompt.positive_signals:
        parts.append("\nPositive signals:")
        parts.extend(f"  - {s}" for s in prompt.positive_signals)
    if prompt.negative_signals:
        parts.append("\nNegative signals:")
        parts.extend(f"  - {s}" for s in prompt.negative_signals)
    if prompt.few_shot_examples:
        parts.append("\nFew-shot examples:")
        parts.extend(_format_few_shot(ex) for ex in prompt.few_shot_examples)
    return "\n".join(parts)


def _build_system_text(prompts: list[MetricPrompt]) -> str:
    """Concatenate header + per-metric blocks.

    Sorted by metric_id so the prefix bytes are deterministic — same input
    set must produce the same prefix bytes for the Anthropic prompt cache
    to hit. Any byte change anywhere in the prefix invalidates the cache.
    """
    sorted_prompts = sorted(prompts, key=lambda p: p.metric_id)
    blocks = [_format_metric_block(p) for p in sorted_prompts]
    return _SYSTEM_HEADER + "\n" + "\n\n".join(blocks)


def _metric_set_hash(metric_ids: Iterable[str]) -> str:
    """Stable telemetry hash for the (sorted) metric set sent in one call."""
    payload = ",".join(sorted(metric_ids)).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def _estimate_cost_usd(usage: Any, model: str) -> float:
    """Estimate $ cost from an Anthropic Usage object, accounting for cache."""
    in_rate, out_rate = _PRICING_PER_MTOK.get(model, _DEFAULT_PRICING)
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return (
        input_tokens * in_rate
        + cache_read * in_rate * _CACHE_READ_MULTIPLIER
        + cache_create * in_rate * _CACHE_WRITE_MULTIPLIER
        + output_tokens * out_rate
    ) / 1_000_000


def estimate_cost_usd_from_counts(
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_create: int,
    model: str = DEFAULT_HAIKU_MODEL,
) -> float:
    """Estimate cost from raw token counts rather than a Usage object.

    Defaults to Haiku pricing — the dominant model in a corpus validation
    run. For aggregate totals that mix Haiku + Sonnet calls the cost is an
    underestimate; accurate for Haiku-only runs.
    """
    in_rate, out_rate = _PRICING_PER_MTOK.get(model, _DEFAULT_PRICING)
    return (
        input_tokens * in_rate
        + cache_read * in_rate * _CACHE_READ_MULTIPLIER
        + cache_create * in_rate * _CACHE_WRITE_MULTIPLIER
        + output_tokens * out_rate
    ) / 1_000_000


def _extract_json_text(response: Any) -> str:
    """Pull the JSON-bearing text block out of an Anthropic Message response."""
    content = getattr(response, "content", None) or []
    for block in content:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", "") or ""
    return ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class PresenceClassifierClient:
    """Anthropic-backed classifier for per-(segment, metric) presence.

    Two-pass model strategy:
    - Default model: Haiku (cheap; multi-label per call).
    - Sonnet fallback: any metric whose Haiku score lands inside that
      metric's calibrated ``sonnet_band`` is re-scored on Sonnet for that
      one segment, then the Sonnet score replaces the Haiku score in the
      returned `SegmentClassification`.

    Caching: the per-metric system prefix is sent with
    ``cache_control={"type": "ephemeral"}`` so Anthropic caches the
    rendered system text. Determinism is enforced by sorting metric blocks
    by ``metric_id`` and rendering them with stable formatting; any byte
    change anywhere in the prefix invalidates the entire cache (see
    claude-api skill / shared/prompt-caching.md).

    Dependency injection: pass ``anthropic_client=...`` to the constructor
    to substitute a mock or pre-configured Anthropic client. The default
    constructs ``anthropic.Anthropic(api_key=config.api_key)`` lazily on
    first call so importing this module does not require the SDK or a key.
    """

    def __init__(
        self,
        config: ClassifierClientConfig | None = None,
        *,
        anthropic_client: Any | None = None,
    ) -> None:
        self.config = config or load_classifier_config()
        self._anthropic_client: Any | None = anthropic_client

    # ----- public API -----

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
        section_type: str | None = None,  # noqa: ARG002 — caller-side filter
    ) -> tuple[list[SegmentClassification], dict[str, int]]:
        """Score a segment against multiple metrics in a single batched call.

        Returns ``(classifications, token_counts)`` where ``classifications``
        has one ``SegmentClassification`` per requested metric_id (in input
        order) and ``token_counts`` is the sum of tokens across the Haiku call
        and any Sonnet fallback call.  Raises ``ValueError`` if any requested
        metric_id has no prompt YAML loaded, or if the API response is missing
        a metric we asked about.  Raises whatever the Anthropic SDK raises
        (rate limit, server errors) — callers wrap the call in their own
        retry policy.
        """
        if not metric_ids:
            return [], {}
        missing = [m for m in metric_ids if m not in self.config.prompts]
        if missing:
            raise ValueError(
                f"No classifier prompt loaded for metric_ids={missing}. "
                f"Author config/llm_classifier/prompts/<metric_id>.yaml "
                f"and re-load the config."
            )

        haiku_scores, haiku_tokens = self._call_model(
            model=self.config.haiku_model,
            metric_ids=metric_ids,
            segment_text=segment_text,
        )

        # Identify metrics whose Haiku score is borderline → re-score with
        # Sonnet. Each metric has its own band; default band applies when a
        # metric has no calibrated entry yet.
        borderline: list[str] = []
        for mid in metric_ids:
            _thr, band = self.threshold_for(mid)
            score = float(haiku_scores[mid].get("score", 0.0))
            if band[0] <= score <= band[1]:
                borderline.append(mid)

        sonnet_scores: dict[str, dict[str, Any]] = {}
        sonnet_tokens: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read": 0,
            "cache_create": 0,
        }
        if borderline:
            sonnet_scores, sonnet_tokens = self._call_model(
                model=self.config.sonnet_model,
                metric_ids=borderline,
                segment_text=segment_text,
            )

        out: list[SegmentClassification] = []
        for mid in metric_ids:
            threshold, _band = self.threshold_for(mid)
            if mid in sonnet_scores:
                raw = sonnet_scores[mid]
                model = self.config.sonnet_model
                fallback = True
            else:
                raw = haiku_scores[mid]
                model = self.config.haiku_model
                fallback = False
            score = max(0.0, min(1.0, float(raw.get("score", 0.0))))
            out.append(
                SegmentClassification(
                    metric_id=mid,
                    score=score,
                    present=score >= threshold,
                    rationale=str(raw.get("rationale", "")).strip(),
                    model=model,
                    sonnet_fallback=fallback,
                    prompt_version=self.config.prompts[mid].prompt_version,
                )
            )
        total_tokens = {k: haiku_tokens[k] + sonnet_tokens[k] for k in haiku_tokens}
        return out, total_tokens

    # ----- internals -----

    def _get_client(self) -> Any:
        if self._anthropic_client is not None:
            return self._anthropic_client
        if not self.config.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set; PresenceClassifierClient cannot "
                "call Anthropic. Set the env var or pass anthropic_client=...."
            )
        try:
            import anthropic as anthropic_sdk  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover — dep is in requirements
            raise ImportError(
                "anthropic SDK is required for PresenceClassifierClient. "
                "Install via: uv pip install -r requirements.txt"
            ) from exc
        self._anthropic_client = anthropic_sdk.Anthropic(api_key=self.config.api_key)
        return self._anthropic_client

    def _call_model(
        self,
        *,
        model: str,
        metric_ids: list[str],
        segment_text: str,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
        """Run one Anthropic call and return ({metric_id: response_entry}, token_counts).

        Validates that every requested metric appears in the response and
        logs token usage + cost + cache hit rate.
        """
        prompts = [self.config.prompts[m] for m in metric_ids]
        system_text = _build_system_text(prompts)
        system_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        client = self._get_client()
        response = client.messages.create(
            model=model,
            max_tokens=_CLASSIFY_MAX_TOKENS,
            system=system_blocks,
            messages=[{"role": "user", "content": segment_text}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _CLASSIFY_OUTPUT_SCHEMA,
                }
            },
        )

        # Telemetry — log even if parsing fails so we still see the cost.
        token_counts: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read": 0,
            "cache_create": 0,
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            token_counts = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read": cache_read,
                "cache_create": cache_create,
            }
            cacheable = cache_read + cache_create + input_tokens
            hit_rate = (cache_read / cacheable) if cacheable > 0 else 0.0
            logger.info(
                "classify_segment model=%s metrics=%d set_hash=%s "
                "tokens=in:%d/out:%d cache=read:%d/write:%d hit_rate=%.2f "
                "cost=$%.5f",
                model,
                len(metric_ids),
                _metric_set_hash(metric_ids),
                input_tokens,
                output_tokens,
                cache_read,
                cache_create,
                hit_rate,
                _estimate_cost_usd(usage, model),
            )

        text = _extract_json_text(response)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Classifier response was not valid JSON (model={model}): {exc}; raw={text[:500]!r}"
            ) from exc

        by_metric: dict[str, dict[str, Any]] = {}
        for entry in payload.get("metrics", []) or []:
            mid = entry.get("metric_id")
            if mid in metric_ids:
                by_metric[mid] = entry
        missing_in_response = [m for m in metric_ids if m not in by_metric]
        if missing_in_response:
            raise ValueError(
                f"Classifier response missing metrics={missing_in_response} "
                f"(model={model}); got={list(by_metric)}"
            )
        return by_metric, token_counts
