#!/usr/bin/env python3
"""Vision benchmark harness.

Two modes:

  --build-corpus   Export a stratified manifest from v2_image_review_decisions.
                   Writes to tests/fixtures/image_benchmark/manifest.json.
                   DB-read-only; never mutates any rows.

  --provider       Run the chart/table extraction pipeline against each image
                   in the corpus manifest and produce a benchmark report.
                   Saves to data/image_benchmarks/baseline_<date>.json.

Usage examples::

    # Build / refresh the frozen corpus manifest (requires DB access)
    python3 scripts/benchmark_vision.py --build-corpus \\
        --database-url "$TEST_DATABASE_URL"

    # Run the benchmark against the current prod GPT-4o path (limit 10 for smoke)
    python3 scripts/benchmark_vision.py --provider current --limit 10 \\
        --database-url "$TEST_DATABASE_URL"

    # Full baseline run (writes to data/image_benchmarks/baseline_<date>.json)
    python3 scripts/benchmark_vision.py --provider current \\
        --database-url "$TEST_DATABASE_URL"

Scope boundaries
----------------
- Does NOT modify vision_client.py (Wave B2 territory).
- Does NOT re-persist facts for reviewed filings (respects reviewed-filing guard).
- DB writes: none.  All DB access is read-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "image_benchmark" / "manifest.json"
BENCHMARK_OUTPUT_DIR = REPO_ROOT / "data" / "image_benchmarks"

# Stratification targets: minimum images per stratum.
# If the DB has fewer than MIN_PER_STRATUM for a given stratum, we take all.
MIN_PER_STRATUM = 5
MAX_PER_STRATUM = 30

# Tier-1 heavy subset: ensure at least this many tier-1 images in the corpus.
TIER1_TARGET = 40

# Hard-OCR subset: ensure at least this many hard-OCR images.
HARD_OCR_TARGET = 20

# ---- Provider configurations (Wave B5) ---------------------------------------
# Each entry maps a --provider value to the env-var settings that the B2
# VisionClient honors. "current" preserves the legacy single-call prod path;
# others exercise one of the B2 provider adapters, with "two-stage" using
# B4's task-aware routing (fast OCR -> premium reader).
#
# Env vars referenced: VISION_PROVIDER, VISION_MODEL_OCR, VISION_MODEL_CHART,
# VISION_ROUTING_MODE (see src/llm/vision_client.py).
PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "current": {
        "VISION_PROVIDER": "openai",
        "VISION_MODEL_OCR": "gpt-4o",
        "VISION_MODEL_CHART": "gpt-4o",
        "VISION_ROUTING_MODE": "legacy",
    },
    "openai-vnext": {
        "VISION_PROVIDER": "openai",
        "VISION_MODEL_OCR": "gpt-4o-2024-11-20",
        "VISION_MODEL_CHART": "gpt-4o-2024-11-20",
        "VISION_ROUTING_MODE": "legacy",
    },
    "gemini-flash": {
        "VISION_PROVIDER": "gemini",
        "VISION_MODEL_OCR": "gemini-2.5-flash-lite",
        "VISION_MODEL_CHART": "gemini-2.5-flash-lite",
        "VISION_ROUTING_MODE": "legacy",
    },
    "gemini-pro": {
        "VISION_PROVIDER": "gemini",
        "VISION_MODEL_OCR": "gemini-2.5-pro",
        "VISION_MODEL_CHART": "gemini-2.5-pro",
        "VISION_ROUTING_MODE": "legacy",
    },
    "anthropic": {
        "VISION_PROVIDER": "anthropic",
        "VISION_MODEL_OCR": "claude-sonnet-4-6",
        "VISION_MODEL_CHART": "claude-sonnet-4-6",
        "VISION_ROUTING_MODE": "legacy",
    },
    "two-stage": {
        # Hybrid: fast Gemini Flash OCR -> Claude Sonnet chart-read, with
        # OCR grounding blob passed to the premium reader (see B4).
        "VISION_PROVIDER": "openai",  # base client; routing vars override per-call
        "VISION_MODEL_OCR": "gemini-2.5-flash-lite",
        "VISION_MODEL_CHART": "claude-sonnet-4-6",
        "VISION_PROVIDER_OCR": "gemini",
        "VISION_PROVIDER_CHART": "anthropic",
        "VISION_ROUTING_MODE": "two_stage",
    },
}

BAKEOFF_PROVIDER_ORDER: list[str] = [
    "current",
    "openai-vnext",
    "gemini-flash",
    "gemini-pro",
    "anthropic",
    # NOTE: "two-stage" is intentionally excluded from the DETECT bake-off.
    # analyze_image_for_text() ignores VISION_ROUTING_MODE, so running a
    # two-stage provider in detect mode would burn spend without
    # exercising B4. The chart-read bake-off uses
    # BAKEOFF_PROVIDER_ORDER_CHART_READ below, which DOES include
    # "two-stage" because analyze_image_targeted() honors routing.
]

# Wave B5.x — chart-read bake-off order. Adds "two-stage" because
# analyze_image_targeted(task_type="chart_read") is the call site where
# VISION_ROUTING_MODE=two_stage actually fires (see
# src/llm/vision_client.py:527 and src/extraction_v2/stages/ocr_extraction.py:826).
BAKEOFF_PROVIDER_ORDER_CHART_READ: list[str] = [
    "current",
    "openai-vnext",
    "gemini-flash",
    "gemini-pro",
    "anthropic",
    "two-stage",
]

# metric-classify bake-off order. No "two-stage" — the premium-reader's
# edge is numeric fidelity (chart-read), not presence classification.
BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY: list[str] = [
    "current",
    "openai-vnext",
    "gemini-flash",
    "gemini-pro",
    "anthropic",
]

# Spend cap for the full bake-off sweep. Override via $MAX_BAKEOFF_USD.
DEFAULT_MAX_BAKEOFF_USD = 15.0

# Available harness modes. ``detect`` is the PR #142 path (chart detection
# only); ``chart-read`` is the B5.x extension that calls
# VisionClient.analyze_image_targeted(task_type="chart_read") with the prod
# chart-extraction prompt and scores per-point data fidelity against the
# gold-standard ``extracted_values.csv`` rows. ``metric-classify`` calls
# VisionClient.analyze_image directly with a short metric-enumeration prompt
# and scores per-image reviewer-disposition (accept/reject/correct/add).
BENCHMARK_MODES: tuple[str, ...] = ("detect", "chart-read", "metric-classify")

# metric-classify — reviewer rejection-reason enum, matching the
# ``v2_image_review_decisions.rejection_reason`` column (migration 29).
# Table-in-image cases map to ``"other"`` until the enum is extended; the
# detail is carried in ``reasoning``.
CLASSIFY_REJECTION_REASONS: frozenset[str] = frozenset(
    {"decorative", "not_a_chart", "wrong_subject", "duplicate", "unreadable", "other"}
)

# metric-classify — default confidence threshold for the derived
# ``predicted_relevant`` flag. Held at 0.5 so zero-metric outputs stay
# "not relevant" and low-confidence positives stay flagged for review.
CLASSIFY_RELEVANCE_THRESHOLD: float = 0.5


# ---- DB query -----------------------------------------------------------------

_CORPUS_QUERY = """
SELECT
    d.img_id::text                               AS img_id,
    f.accession_number                           AS filing_key,
    v.filename                                   AS filename,
    d.decision                                   AS decision,
    d.chart_type                                 AS chart_type,
    d.rejection_reason                           AS rejection_reason,
    d.reviewer_notes                             AS reviewer_notes,
    v.file_path                                  AS storage_key,
    f.accession_number                           AS accession_number,
    c.cik                                        AS cik,
    c.company_name                               AS company_name,
    v.relevance_score                            AS relevance_score
FROM v2_image_review_decisions d
JOIN v2_image_assets           v ON v.img_id = d.img_id
JOIN filings                   f ON v.doc_id = f.filing_id
JOIN companies                 c ON f.company_id = c.company_id
ORDER BY d.created_at
"""

_TIER1_FACTS_QUERY = """
SELECT
    ia.img_id::text  AS img_id,
    COUNT(*)         AS tier1_count
FROM v2_metric_facts mf
JOIN v2_image_assets ia ON ia.img_id = mf.image_asset_id
WHERE mf.metric_id IN (
    'cm_customer_retention_rate',
    'cm_net_revenue_retention',
    'cm_gross_revenue_retention',
    'cm_revenue_by_cohort',
    'cm_transactions_by_cohort',
    'cm_balance_by_cohort',
    'cm_gross_margin_by_cohort',
    'cm_revenue_concentration',
    'cm_lifetime_value_per_customer',
    'cm_customer_acquisition_cost',
    'cm_ltv_to_cac_ratio',
    'cm_ltv_to_cac_ratio_by_cohort',
    'cm_large_customers_period_end',
    'cm_new_customers_acquired',
    'cm_customers_period_end_by_tenure'
)
GROUP BY ia.img_id
"""


# ---- Stratification -----------------------------------------------------------

from src.gold_standard.image_eval import (  # noqa: E402 — after sys.path hack above
    is_hard_ocr_image,
    is_tier1_image,
    stratum_label,
)


def _stratify_corpus(
    rows: list[dict[str, Any]],
    tier1_facts: dict[str, int],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Build a stratified corpus from DB rows.

    Strategy:
    1. Bin rows by stratum label.
    2. From each stratum take MIN_PER_STRATUM..MAX_PER_STRATUM rows (random sample).
    3. Top-up tier-1 images to TIER1_TARGET.
    4. Top-up hard-OCR images to HARD_OCR_TARGET.
    5. Annotate each entry with tier/subset flags.
    """
    # Build stratum buckets
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = stratum_label(row["decision"], row.get("chart_type"), row.get("rejection_reason"))
        buckets.setdefault(label, []).append(row)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    # Phase 1: per-stratum sampling
    for _label, bucket in sorted(buckets.items()):
        rng.shuffle(bucket)
        take = min(MAX_PER_STRATUM, max(MIN_PER_STRATUM, len(bucket)))
        for row in bucket[:take]:
            if row["img_id"] not in selected_ids:
                selected_ids.add(row["img_id"])
                selected.append(row)

    # Phase 2: top-up tier-1 heavy subset
    tier1_selected = sum(1 for r in selected if is_tier1_image(r.get("chart_type")))
    if tier1_selected < TIER1_TARGET:
        tier1_candidates = [
            r
            for r in rows
            if r["img_id"] not in selected_ids and is_tier1_image(r.get("chart_type"))
        ]
        rng.shuffle(tier1_candidates)
        for row in tier1_candidates[: TIER1_TARGET - tier1_selected]:
            selected_ids.add(row["img_id"])
            selected.append(row)

    # Phase 3: top-up hard-OCR subset
    hard_ocr_selected = sum(1 for r in selected if is_hard_ocr_image(r.get("chart_type")))
    if hard_ocr_selected < HARD_OCR_TARGET:
        hard_ocr_candidates = [
            r
            for r in rows
            if r["img_id"] not in selected_ids and is_hard_ocr_image(r.get("chart_type"))
        ]
        rng.shuffle(hard_ocr_candidates)
        for row in hard_ocr_candidates[: HARD_OCR_TARGET - hard_ocr_selected]:
            selected_ids.add(row["img_id"])
            selected.append(row)

    # Annotate
    result = []
    for row in selected:
        entry: dict[str, Any] = {
            "img_id": row["img_id"],
            "filing_key": row["filing_key"],
            "filename": row["filename"],
            "decision": row["decision"],
            "chart_type": row.get("chart_type"),
            "rejection_reason": row.get("rejection_reason"),
            "reviewer_notes": row.get("reviewer_notes") or "",
            "storage_key": row["storage_key"],
            "company_name": row.get("company_name", ""),
            "cik": row.get("cik", ""),
            "relevance_score": row.get("relevance_score"),
            "stratum": stratum_label(
                row["decision"], row.get("chart_type"), row.get("rejection_reason")
            ),
            "is_tier1": is_tier1_image(row.get("chart_type")),
            "is_hard_ocr": is_hard_ocr_image(row.get("chart_type")),
            "tier1_facts_in_db": tier1_facts.get(row["img_id"], 0),
        }
        result.append(entry)

    return result


def _stratum_table(corpus: list[dict[str, Any]]) -> str:
    """Format a text table showing corpus size per stratum."""
    counts: dict[str, int] = {}
    for entry in corpus:
        counts[entry["stratum"]] = counts.get(entry["stratum"], 0) + 1
    lines = [f"{'Stratum':<35} {'Count':>6}"]
    lines.append("-" * 42)
    for stratum in sorted(counts):
        lines.append(f"{stratum:<35} {counts[stratum]:>6}")
    lines.append("-" * 42)
    lines.append(f"{'TOTAL':<35} {sum(counts.values()):>6}")
    tier1_count = sum(1 for e in corpus if e.get("is_tier1"))
    hard_ocr_count = sum(1 for e in corpus if e.get("is_hard_ocr"))
    lines.append(f"\n  Tier-1 images   : {tier1_count}")
    lines.append(f"  Hard-OCR images : {hard_ocr_count}")
    return "\n".join(lines)


# ---- Benchmark runner ---------------------------------------------------------


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load corpus entries from manifest JSON."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    corpus: list[dict[str, Any]] = data.get("corpus", [])
    if not corpus:
        raise ValueError(f"Corpus in {path} is empty.  Run with --build-corpus first.")
    return corpus


class _ProviderEnv:
    """Context manager that applies PROVIDER_CONFIGS[provider] to os.environ.

    Restores the prior values on exit (unset keys stay unset). Scoped so each
    call is independent and the process env is never permanently mutated.
    """

    def __init__(self, provider: str) -> None:
        if provider not in PROVIDER_CONFIGS:
            raise ValueError(
                f"Unknown provider {provider!r}. Known: {sorted(PROVIDER_CONFIGS.keys())}"
            )
        self._overrides = PROVIDER_CONFIGS[provider]
        self._prior: dict[str, str | None] = {}

    def __enter__(self) -> _ProviderEnv:
        for key, value in self._overrides.items():
            self._prior[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *_exc: Any) -> None:
        for key, prior in self._prior.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


def _force_local_storage_for_fixtures() -> None:
    """Point the image-storage abstraction at the local fixture tree.

    The bake-off corpus manifest references paths like
    ``Farfetch_Limited/g607688g09d00.jpg`` that only exist under
    ``data/gold_standard/`` on the local filesystem — they are not R2 keys.
    If ``.env`` has R2 credentials set (which is common on dev machines that
    share prod config), ``get_image_storage()`` would otherwise return
    ``R2Storage`` and every fixture read would 404.

    Clears the R2 env vars, points ``IMAGE_CACHE_DIR`` at
    ``data/gold_standard`` unless the caller set it explicitly, and resets
    the module-level caches so the change is observed immediately.

    Called at the top of benchmark modes (never from ``--build-corpus``,
    which genuinely needs the configured prod storage).
    """
    for var in ("R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT_URL"):
        os.environ.pop(var, None)
    if not os.environ.get("IMAGE_CACHE_DIR"):
        os.environ["IMAGE_CACHE_DIR"] = str(REPO_ROOT / "data" / "gold_standard")
    # Invalidate the cached resolver so the next call sees the new env.
    from src.infra.image_storage import get_image_storage
    from src.infra.paths import image_cache_dir

    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()
    logger.info("Benchmark storage: %s", os.environ["IMAGE_CACHE_DIR"])


def _run_provider(entry: dict[str, Any], provider: str, mode: str = "detect") -> dict[str, Any]:
    """Run one vision provider against one corpus image.

    Returns a dict with benchmark fields compatible with ImageRunRecord.
    Does NOT re-persist any facts (read-only).

    ``mode="detect"`` calls ``VisionClient.analyze_image_for_text`` — the
    PR #142 path that measures chart DETECTION. ``mode="chart-read"``
    calls ``VisionClient.analyze_image_targeted(task_type="chart_read")``
    with the prod chart-extraction prompt (Wave B5.x). For the
    ``two-stage`` provider under chart-read mode, the harness replicates
    the double-call (``chart_ocr`` grounding pass then ``chart_read``
    premium reader) that ``src/extraction_v2/stages/ocr_extraction.py``
    makes in production so costs and outputs match the real routing.

    In either mode ``PROVIDER_CONFIGS[provider]`` is applied to the
    process env for the duration of the call so the B2 ``VisionClient``
    picks the right adapter + model.
    """
    if mode not in BENCHMARK_MODES:
        raise ValueError(f"Unknown mode {mode!r}. Known: {BENCHMARK_MODES}")

    from src.infra.image_storage import get_image_storage

    storage = get_image_storage()
    storage_key = entry.get("storage_key", "")

    skeleton = {
        "img_id": entry["img_id"],
        "predicted_relevant": False,
        "predicted_chart_type": None,
        "parse_failed": False,
        "cost_usd": 0.0,
        "latency_ms": 0,
        "raw_output": "",
        "title_extracted": "",
        "legend_extracted": "",
        "ocr_cells_extracted": [],
        "axis_labels_extracted": [],
        "tier1_facts_extracted": 0,
        "extracted_points": [],
        "predicted_metrics": [],
        "classification_confidence": 0.0,
        "rejection_reason": None,
        "classification_reasoning": "",
        "skipped": False,
        "skip_reason": None,
    }

    t0 = time.perf_counter()
    try:
        image_bytes = storage.get_bytes(storage_key)
    except FileNotFoundError:
        logger.warning("Image not found in storage: %s (img_id=%s)", storage_key, entry["img_id"])
        return {**skeleton, "skipped": True, "skip_reason": "missing_bytes"}

    if mode == "detect":
        return _run_provider_detect(entry, provider, image_bytes, skeleton, t0)
    if mode == "metric-classify":
        return _run_provider_metric_classify(entry, provider, image_bytes, skeleton, t0)
    return _run_provider_chart_read(entry, provider, image_bytes, skeleton, t0)


def _run_provider_detect(
    entry: dict[str, Any],
    provider: str,
    image_bytes: bytes,
    skeleton: dict[str, Any],
    t0: float,
) -> dict[str, Any]:
    """Detect-mode path: the PR #142 ``analyze_image_for_text`` call."""
    from src.llm.vision_client import VisionClient

    try:
        with _ProviderEnv(provider):
            client = VisionClient()
            result = client.analyze_image_for_text(image_bytes)
    except Exception as exc:
        logger.warning(
            "Vision API error (detect) for provider=%s img_id=%s: %s",
            provider,
            entry["img_id"],
            exc,
        )
        return {
            **skeleton,
            "parse_failed": True,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "raw_output": str(exc),
        }

    return {
        **skeleton,
        "predicted_relevant": result.contains_chart,
        "predicted_chart_type": result.chart_hint if result.contains_chart else None,
        "cost_usd": result.cost_usd,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "raw_output": result.raw_response,
    }


def _run_provider_metric_classify(
    entry: dict[str, Any],
    provider: str,
    image_bytes: bytes,
    skeleton: dict[str, Any],
    t0: float,
) -> dict[str, Any]:
    """metric-classify mode: short prompt, JSON output, per-image metric set.

    Calls ``VisionClient.analyze_image`` directly (no routing) with the
    tier-enumerating ``CLASSIFY_PROMPT`` and ``response_format=json_object``.
    Returns the skeleton shape augmented with ``predicted_metrics``,
    ``classification_confidence``, ``rejection_reason``, and
    ``classification_reasoning``. ``predicted_relevant`` is derived from
    the confidence threshold so the chart-detection view still has signal.
    """
    from src.llm.vision_client import VisionClient

    try:
        with _ProviderEnv(provider):
            client = VisionClient()
            response = client.analyze_image(
                image_bytes=image_bytes,
                prompt=CLASSIFY_PROMPT,
                detail="high",
                max_tokens=400,
                response_format={"type": "json_object"},
            )
    except Exception as exc:
        logger.warning(
            "Vision API error (metric-classify) for provider=%s img_id=%s: %s",
            provider,
            entry["img_id"],
            exc,
        )
        return {
            **skeleton,
            "parse_failed": True,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "raw_output": str(exc),
        }

    raw_content = getattr(response, "content", "") or ""
    cost = float(getattr(response, "cost_usd", 0.0))
    latency_ms = int((time.perf_counter() - t0) * 1000)

    parsed = _parse_classify_response(raw_content)
    if parsed is None:
        return {
            **skeleton,
            "parse_failed": True,
            "cost_usd": cost,
            "latency_ms": latency_ms,
            "raw_output": raw_content[:4000],
        }

    metrics = parsed["predicted_metrics"]
    confidence = parsed["confidence"]
    predicted_relevant = bool(metrics) and confidence >= CLASSIFY_RELEVANCE_THRESHOLD

    return {
        **skeleton,
        "predicted_relevant": predicted_relevant,
        "cost_usd": cost,
        "latency_ms": latency_ms,
        "raw_output": raw_content[:4000],
        "predicted_metrics": metrics,
        "classification_confidence": confidence,
        "rejection_reason": parsed["rejection_reason"],
        "classification_reasoning": parsed["reasoning"],
    }


def _run_provider_chart_read(
    entry: dict[str, Any],
    provider: str,
    image_bytes: bytes,
    skeleton: dict[str, Any],
    t0: float,
) -> dict[str, Any]:
    """Chart-read mode: call ``analyze_image_targeted(task_type='chart_read')``.

    For the ``two-stage`` provider this fires the OCR grounding pass
    first (``chart_ocr``) then the premium reader (``chart_read``), with
    the OCR blob injected into the chart-read prompt. Prompt text is
    pulled from the prod stage so the benchmark can't drift from prod.
    """
    from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
    from src.llm.vision_client import VisionClient

    stage = OCRExtractionStage()  # no-arg init; just for prompt methods
    cost = 0.0
    ocr_blob = ""
    raw_ocr = ""
    raw_chart = ""

    try:
        with _ProviderEnv(provider):
            client = VisionClient()
            two_stage = os.environ.get("VISION_ROUTING_MODE", "").strip().lower() == "two_stage"

            if two_stage:
                ocr_resp = client.analyze_image_targeted(
                    image_bytes=image_bytes,
                    prompt=stage._get_chart_ocr_prompt(),
                    task_type="chart_ocr",
                    detail="high",
                    max_tokens=1500,
                    response_format={"type": "json_object"},
                )
                cost += float(getattr(ocr_resp, "cost_usd", 0.0))
                raw_ocr = getattr(ocr_resp, "content", "") or ""
                parsed_ocr = OCRExtractionStage._parse_chart_json(raw_ocr) or {}
                ocr_blob = str(parsed_ocr.get("text", "") or "")

            chart_resp = client.analyze_image_targeted(
                image_bytes=image_bytes,
                prompt=stage._get_chart_extraction_prompt(ocr_text=ocr_blob),
                task_type="chart_read",
                detail="high",
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            cost += float(getattr(chart_resp, "cost_usd", 0.0))
            raw_chart = getattr(chart_resp, "content", "") or ""
    except Exception as exc:
        logger.warning(
            "Vision API error (chart-read) for provider=%s img_id=%s: %s",
            provider,
            entry["img_id"],
            exc,
        )
        return {
            **skeleton,
            "parse_failed": True,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "cost_usd": cost,
            "raw_output": str(exc),
        }

    parsed = OCRExtractionStage._parse_chart_json(raw_chart)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    if parsed is None:
        return {
            **skeleton,
            "parse_failed": True,
            "cost_usd": cost,
            "latency_ms": latency_ms,
            "raw_output": raw_chart[:4000],
        }

    title = str(parsed.get("title", "") or "")
    x_axis = str(parsed.get("x_axis_label", "") or "")
    y_axis = str(parsed.get("y_axis_label", "") or "")
    series = parsed.get("series", []) or []
    annotations = parsed.get("annotations", []) or []

    axis_labels: list[str] = []
    if x_axis:
        axis_labels.append(x_axis)
    if y_axis:
        axis_labels.append(y_axis)

    legend_parts = [str(s.get("name", "") or "") for s in series]
    legend = "\n".join(p for p in legend_parts if p)

    predicted_chart_type = str(parsed.get("chart_type", "") or "") or None
    # If the model returns a chart_type + any structured output, count it
    # as "relevant" for detection purposes in chart-read mode too.
    predicted_relevant = bool(predicted_chart_type) or bool(series) or bool(annotations)

    extracted_points = _flatten_chart_points(series, annotations)

    return {
        **skeleton,
        "predicted_relevant": predicted_relevant,
        "predicted_chart_type": predicted_chart_type,
        "cost_usd": cost,
        "latency_ms": latency_ms,
        "raw_output": raw_chart[:4000],
        "title_extracted": title,
        "legend_extracted": legend,
        "axis_labels_extracted": axis_labels,
        "extracted_points": extracted_points,
    }


def _flatten_chart_points(
    series: list[dict[str, Any]], annotations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten model output into ``[{"value": float, "period": str|None, "source": str}, ...]``.

    Used by the chart-read scorer. Non-numeric values are dropped (a
    missing ``y`` or ``value`` can't contribute to a value match).
    """
    out: list[dict[str, Any]] = []
    for s in series:
        name = s.get("name")
        for p in s.get("points", []) or []:
            y = p.get("y")
            try:
                y_float = float(y)
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "value": y_float,
                    "period": p.get("x"),
                    "source": "series",
                    "series_name": name,
                    "label": p.get("label"),
                }
            )
    for a in annotations:
        v = a.get("value")
        if v is None:
            continue
        try:
            v_float = float(v)
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "value": v_float,
                "period": a.get("period"),
                "source": "annotation",
                "category": a.get("category"),
                "text": a.get("text"),
            }
        )
    return out


def _load_tier_metric_ids() -> tuple[list[str], list[str]]:
    """Return ``(tier1_ids, tier2_ids)`` from config/metric_keywords.yaml.

    Pulled from yaml at call time so the prompt can never drift from the
    authoritative tier assignment in CLAUDE.md. Returns deterministically
    sorted ids (alphabetical) so the prompt is stable across runs.
    """
    import yaml

    yaml_path = REPO_ROOT / "config" / "metric_keywords.yaml"
    with yaml_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    tier1: list[str] = []
    tier2: list[str] = []
    for metric_id, body in cfg.items():
        if not isinstance(body, dict):
            continue
        tier = body.get("tier")
        if tier == 1:
            tier1.append(metric_id)
        elif tier == 2:
            tier2.append(metric_id)
    return sorted(tier1), sorted(tier2)


# metric-classify — short classification prompt, built from metric_keywords.yaml
# at import time so the tier lists in CLAUDE.md are the single source of truth.
# TODO: when prod adopts this, move the constant into
# ``src/llm/vision_client.analyze_image_for_metric_classification`` and have
# the harness import it from there (keeps prompt-parity across benchmark and
# prod; see plan-doc "Prompt-parity risk").
_TIER1_METRIC_IDS, _TIER2_METRIC_IDS = _load_tier_metric_ids()


def _build_classify_prompt(tier1: list[str], tier2: list[str]) -> str:
    """Assemble the metric-classification prompt.

    Inlined in the harness rather than ``vision_client.py`` so prod routing
    isn't affected while we validate the approach. Returns JSON-only; paired
    with ``response_format={"type": "json_object"}`` on the API call.
    """
    tier1_block = "\n".join(f"  - {m}" for m in tier1)
    tier2_block = "\n".join(f"  - {m}" for m in tier2)
    reasons = sorted(CLASSIFY_REJECTION_REASONS)
    reasons_block = ", ".join(reasons)
    return (
        "You are classifying a customer-metrics disclosure image from an SEC "
        "filing.\n\n"
        f"TIER-1 metrics (must-not-miss; {len(tier1)}):\n{tier1_block}\n\n"
        f"TIER-2 metrics (nice-to-have; {len(tier2)}):\n{tier2_block}\n\n"
        "A metric is DISCLOSED in this image if the image depicts meaningful "
        "chart data for that metric — even if data points are unlabeled, axes "
        "are missing, or numeric values aren't visible. Base your judgment on "
        "the chart SHAPE (cohort parfait / layer cake / stacked-area-by-cohort "
        "/ triangle / retention curve / bar-by-cohort), the title, the legend, "
        "and any surrounding text. Labeled values are sufficient evidence; "
        "they are NOT required. Unlabeled cohort-waterfall / layer-cake "
        "visuals are valid disclosures when the shape depicts per-cohort data.\n\n"
        "Images that are TABLES of numbers should be returned with "
        'predicted_metrics=[] and rejection_reason="other" (tables are handled '
        "by a different pipeline).\n\n"
        "Return JSON exactly:\n"
        "{\n"
        '  "predicted_metrics": [metric_ids from the lists above; [] if none],\n'
        '  "confidence": float in 0.0 to 1.0 over the predicted set,\n'
        f'  "rejection_reason": one of {{{reasons_block}}} when '
        "predicted_metrics is empty, else null,\n"
        '  "reasoning": one sentence explaining the call (for audit)\n'
        "}\n\n"
        "Only emit metric_ids exactly as listed above."
    )


CLASSIFY_PROMPT: str = _build_classify_prompt(_TIER1_METRIC_IDS, _TIER2_METRIC_IDS)


def _strip_markdown_fences(raw: str) -> str:
    """Strip ```json … ``` fences that Gemini often wraps JSON responses in.

    Returns the stripped payload when the full content is a single fenced
    block; otherwise returns ``raw`` unchanged. Conservative: only triggers
    when the text starts with \"```\" so clean JSON is left alone.
    """
    if not raw:
        return raw
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return raw
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return raw
    body = stripped[first_newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body


def _parse_classify_response(raw: str) -> dict[str, Any] | None:
    """Parse and lightly normalise the metric-classify JSON response.

    Returns ``None`` if JSON parsing fails. Accepts missing optional fields
    and coerces common shape bugs (e.g. ``null`` confidence → 0.0, string
    metric list → wrapped in list, unknown rejection_reason → ``"other"``)
    so minor provider drift doesn't bubble up as a parse failure.
    """
    try:
        obj = json.loads(_strip_markdown_fences(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    raw_metrics = obj.get("predicted_metrics", []) or []
    if isinstance(raw_metrics, str):
        raw_metrics = [raw_metrics]
    known_ids = set(_TIER1_METRIC_IDS) | set(_TIER2_METRIC_IDS)
    metrics = [str(m).strip() for m in raw_metrics if str(m).strip() in known_ids]

    try:
        confidence = float(obj.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = obj.get("rejection_reason")
    if reason is not None:
        reason = str(reason).strip()
        if reason not in CLASSIFY_REJECTION_REASONS:
            reason = "other"
        if metrics:
            # Classifier emitted metrics AND a reason; the schema says the
            # reason only applies when metrics is empty. Drop it to keep
            # downstream scoring unambiguous.
            reason = None
    reasoning = str(obj.get("reasoning") or "")

    return {
        "predicted_metrics": metrics,
        "confidence": confidence,
        "rejection_reason": reason,
        "reasoning": reasoning,
    }


def _load_manifest_metric_tags(entry: dict[str, Any]) -> list[str]:
    """Return the manifest-provided ``ground_truth_metric_ids`` for an entry.

    Primary truth for the metric-classify scorer. Stable filter against the
    known tier-1/2 metric-id universe so a typo in the manifest doesn't
    quietly become a false negative elsewhere.
    """
    raw = entry.get("ground_truth_metric_ids") or []
    if not isinstance(raw, list):
        return []
    known_ids = set(_TIER1_METRIC_IDS) | set(_TIER2_METRIC_IDS)
    return [str(m).strip() for m in raw if str(m).strip() in known_ids]


def _load_chart_ground_truth(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Load ground-truth chart rows for a manifest entry, if mapped.

    Honors the optional ``ground_truth_value_ids`` field on each manifest
    entry. The scorer derives the gold-standard company directory from
    the ``storage_key`` prefix (e.g. ``Farfetch_Limited/foo.jpg`` →
    ``data/gold_standard/Farfetch_Limited/extracted_values.csv``) and
    returns the CSV rows whose ``metric_value_id`` appears in
    ``ground_truth_value_ids`` AND whose ``source_type == "chart"``.

    Returns an empty list if the entry has no mapping or the CSV is
    missing; callers should treat that as "structural fidelity only, no
    data-value scoring for this image".
    """
    ids = entry.get("ground_truth_value_ids")
    if not ids:
        return []
    storage_key = entry.get("storage_key", "") or ""
    if "/" not in storage_key:
        return []
    company_dir = storage_key.split("/", 1)[0]
    csv_path = REPO_ROOT / "data" / "gold_standard" / company_dir / "extracted_values.csv"
    if not csv_path.exists():
        logger.warning("ground_truth CSV not found for %s (expected %s)", entry["img_id"], csv_path)
        return []

    id_set = {str(i) for i in ids}
    import csv as _csv

    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8") as fh:
        for row in _csv.DictReader(fh):
            if row.get("source_type") != "chart":
                continue
            if str(row.get("metric_value_id", "")).strip() not in id_set:
                continue
            try:
                value = float(row["value_numeric"])
            except (TypeError, ValueError, KeyError):
                continue
            rows.append(
                {
                    "metric_value_id": row.get("metric_value_id"),
                    "metric_id": row.get("metric_id"),
                    "value": value,
                    "unit": row.get("unit"),
                    "period_start": row.get("period_start") or None,
                    "period_end": row.get("period_end") or None,
                }
            )
    return rows


def _run_current_provider(entry: dict[str, Any]) -> dict[str, Any]:
    """Legacy shim — kept for back-compat with external callers / tests."""
    return _run_provider(entry, "current")


def _run_benchmark(
    corpus: list[dict[str, Any]],
    provider: str,
    limit: int | None,
    mode: str = "detect",
) -> list[dict[str, Any]]:
    """Run the benchmark harness against the corpus and return raw run records.

    ``mode`` is forwarded to ``_run_provider``. In ``chart-read`` mode,
    each result is augmented with per-image data-value TP/FP/FN scored
    against any ground-truth CSV rows mapped by the manifest entry.
    """
    if mode not in BENCHMARK_MODES:
        raise ValueError(f"Unknown mode {mode!r}. Known: {BENCHMARK_MODES}")
    if limit is not None:
        corpus = corpus[:limit]

    run_records = []
    n = len(corpus)
    for i, entry in enumerate(corpus):
        logger.info(
            "  [%d/%d] img_id=%s  stratum=%s", i + 1, n, entry["img_id"], entry.get("stratum", "?")
        )

        if provider not in PROVIDER_CONFIGS:
            raise ValueError(
                f"Unknown provider {provider!r}. Known: {sorted(PROVIDER_CONFIGS.keys())}"
            )
        result = _run_provider(entry, provider, mode=mode)

        result["reviewer_decision"] = entry["decision"]
        result["reviewer_chart_type"] = entry.get("chart_type")
        result["reviewer_notes"] = entry.get("reviewer_notes", "")
        result["tier1_facts_in_db"] = entry.get("tier1_facts_in_db", 0)
        result["stratum"] = entry.get("stratum", "unknown")
        result["is_tier1"] = entry.get("is_tier1", False)
        result["provider"] = provider
        result["mode"] = mode

        if mode == "chart-read" and not result.get("skipped"):
            reference = _load_chart_ground_truth(entry)
            from src.gold_standard.image_eval import data_value_match

            tp, fp, fn = data_value_match(result.get("extracted_points", []), reference)
            result["reference_points"] = reference
            result["data_value_tp"] = tp
            result["data_value_fp"] = fp
            result["data_value_fn"] = fn
        else:
            result.setdefault("reference_points", [])
            result.setdefault("data_value_tp", 0)
            result.setdefault("data_value_fp", 0)
            result.setdefault("data_value_fn", 0)

        if mode == "metric-classify" and not result.get("skipped"):
            reference_metrics = _load_manifest_metric_tags(entry)
            from src.gold_standard.image_eval import reviewer_action

            result["reference_metrics"] = reference_metrics
            result["reviewer_action"] = reviewer_action(
                result.get("predicted_metrics", []), reference_metrics
            )
        else:
            result.setdefault("reference_metrics", [])
            result.setdefault("reviewer_action", "")

        run_records.append(result)

    return run_records


def _build_eval_results(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert raw run records to ImageRunRecord objects and aggregate metrics."""
    from src.gold_standard.image_eval import ImageRunRecord, aggregate_results

    records = []
    for r in run_records:
        if r.get("skipped"):
            continue
        records.append(
            ImageRunRecord(
                img_id=r["img_id"],
                reviewer_decision=r["reviewer_decision"],
                reviewer_chart_type=r.get("reviewer_chart_type"),
                reviewer_notes=r.get("reviewer_notes", ""),
                tier1_facts_in_db=r.get("tier1_facts_in_db", 0),
                predicted_chart_type=r.get("predicted_chart_type"),
                predicted_relevant=bool(r.get("predicted_relevant", False)),
                ocr_cells_extracted=r.get("ocr_cells_extracted", []),
                ocr_cells_reference=[],
                axis_labels_extracted=r.get("axis_labels_extracted", []),
                axis_labels_reference=[],
                title_extracted=r.get("title_extracted", ""),
                legend_extracted=r.get("legend_extracted", ""),
                tier1_facts_extracted=r.get("tier1_facts_extracted", 0),
                parse_failed=bool(r.get("parse_failed", False)),
                cost_usd=float(r.get("cost_usd", 0.0)),
                latency_ms=int(r.get("latency_ms", 0)),
                raw_output=r.get("raw_output", ""),
                provider=r.get("provider", "unknown"),
                extracted_points=r.get("extracted_points", []),
                reference_points=r.get("reference_points", []),
                data_value_tp=int(r.get("data_value_tp", 0)),
                data_value_fp=int(r.get("data_value_fp", 0)),
                data_value_fn=int(r.get("data_value_fn", 0)),
                predicted_metrics=r.get("predicted_metrics", []),
                reference_metrics=r.get("reference_metrics", []),
                classification_confidence=float(r.get("classification_confidence", 0.0)),
                rejection_reason=r.get("rejection_reason"),
                reviewer_action=r.get("reviewer_action", ""),
            )
        )

    agg = aggregate_results(records)
    return {
        "chart_detection_precision": agg.chart_detection_precision,
        "chart_detection_recall": agg.chart_detection_recall,
        "chart_detection_f1": agg.chart_detection_f1,
        "ocr_cell_accuracy": agg.ocr_cell_accuracy,
        "ocr_axis_label_accuracy": agg.ocr_axis_label_accuracy,
        "title_match_score": agg.title_match_score,
        "legend_match_score": agg.legend_match_score,
        "tier1_fact_recall": agg.tier1_fact_recall,
        "parse_failure_rate": agg.parse_failure_rate,
        "mean_cost_usd": agg.mean_cost_usd,
        "mean_latency_ms": agg.mean_latency_ms,
        "n_images": agg.n_images,
        "n_relevant": agg.n_relevant,
        "n_not_relevant": agg.n_not_relevant,
        "data_value_precision": agg.data_value_precision,
        "data_value_recall": agg.data_value_recall,
        "data_value_f1": agg.data_value_f1,
        "n_images_scored_on_data": agg.n_images_scored_on_data,
        "accept_rate": agg.accept_rate,
        "reject_rate": agg.reject_rate,
        "correct_rate": agg.correct_rate,
        "add_rate": agg.add_rate,
        "partial_rate": agg.partial_rate,
        "skip_rate": agg.skip_rate,
        "auto_disposition_rate": agg.auto_disposition_rate,
        "metric_tag_precision": agg.metric_tag_precision,
        "metric_tag_recall": agg.metric_tag_recall,
        "metric_tag_f1": agg.metric_tag_f1,
        "calibration_ece": agg.calibration_ece,
        "n_images_scored_on_metric_tags": agg.n_images_scored_on_metric_tags,
        "n_skipped": sum(1 for r in run_records if r.get("skipped")),
        "n_missing_bytes": sum(1 for r in run_records if r.get("skip_reason") == "missing_bytes"),
    }


# ---- CLI ---------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vision benchmark harness — build corpus or run evaluations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build corpus manifest from DB
  python3 scripts/benchmark_vision.py --build-corpus \\
      --database-url "$TEST_DATABASE_URL"

  # Smoke test (10 images)
  python3 scripts/benchmark_vision.py --provider current --limit 10 \\
      --database-url "$TEST_DATABASE_URL"

  # Full baseline run
  python3 scripts/benchmark_vision.py --provider current \\
      --database-url "$TEST_DATABASE_URL"
        """,
    )
    parser.add_argument(
        "--build-corpus",
        action="store_true",
        help="Export a stratified corpus manifest from v2_image_review_decisions.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="current",
        choices=sorted(PROVIDER_CONFIGS.keys()),
        help=(
            "Vision provider to benchmark.  'current' = prod GPT-4o path; "
            "'openai-vnext', 'gemini-flash', 'gemini-pro', 'anthropic', "
            "'two-stage' exercise the Wave B2 / B4 provider adapters."
        ),
    )
    parser.add_argument(
        "--bakeoff",
        action="store_true",
        help=(
            "Run the full Wave B5 sweep: every provider in PROVIDER_CONFIGS, "
            "sequentially, with a cumulative spend cap ($MAX_BAKEOFF_USD, "
            f"default ${DEFAULT_MAX_BAKEOFF_USD:.0f}). Writes per-provider "
            "reports to data/image_benchmarks/bakeoff_<date>/ plus a summary. "
            "In chart-read mode the order also includes 'two-stage'."
        ),
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="detect",
        choices=sorted(BENCHMARK_MODES),
        help=(
            "Benchmark mode. 'detect' = PR #142 chart-detection path "
            "(analyze_image_for_text). 'chart-read' = Wave B5.x per-point "
            "data-fidelity path (analyze_image_targeted, exercises B4 "
            "two-stage routing for provider=two-stage). 'metric-classify' "
            "= presence-first per-image metric classification "
            "(analyze_image + short JSON prompt); scored on reviewer "
            "accept/reject/correct/add dispositions."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of corpus images evaluated (for smoke testing).",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default=str(MANIFEST_PATH),
        help="Path to the corpus manifest JSON (default: tests/fixtures/image_benchmark/manifest.json).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Path to write the benchmark report JSON.  "
            "Defaults to data/image_benchmarks/baseline_<date>.json."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for stratified sampling (default: 42).",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="PostgreSQL connection string (defaults to DATABASE_URL from .env).",
    )
    return parser.parse_args()


def _run_single_provider_report(
    corpus: list[dict[str, Any]],
    provider: str,
    limit: int | None,
    manifest_path: Path,
    output_path: Path,
    mode: str = "detect",
) -> dict[str, Any]:
    """Run one provider, aggregate metrics, write the JSON report, return it."""
    logger.info("Running benchmark with provider=%r mode=%r ...", provider, mode)
    run_records = _run_benchmark(corpus, provider, limit, mode=mode)

    logger.info("Computing metrics ...")
    eval_metrics = _build_eval_results(run_records)

    report = {
        "provider": provider,
        "mode": mode,
        "run_date": date.today().isoformat(),
        "manifest_path": str(manifest_path),
        "limit": limit,
        "metrics": eval_metrics,
        "run_records": run_records,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    logger.info("\n=== Provider: %s (mode=%s) ===", provider, mode)
    m = eval_metrics
    logger.info(
        "  Chart detection  P=%.3f  R=%.3f  F1=%.3f",
        m["chart_detection_precision"],
        m["chart_detection_recall"],
        m["chart_detection_f1"],
    )
    logger.info("  Tier-1 fact recall     : %.3f", m["tier1_fact_recall"])
    logger.info("  Parse failure rate     : %.3f", m["parse_failure_rate"])
    if mode == "chart-read":
        logger.info(
            "  Data-value P/R/F1      : %.3f / %.3f / %.3f  (scored on %d img)",
            m["data_value_precision"],
            m["data_value_recall"],
            m["data_value_f1"],
            m["n_images_scored_on_data"],
        )
    if mode == "metric-classify":
        logger.info(
            "  Metric-tag P/R/F1      : %.3f / %.3f / %.3f  (scored on %d img)",
            m["metric_tag_precision"],
            m["metric_tag_recall"],
            m["metric_tag_f1"],
            m["n_images_scored_on_metric_tags"],
        )
        logger.info(
            "  Reviewer actions       : accept=%.2f reject=%.2f correct=%.2f "
            "add=%.2f partial=%.2f skip=%.2f",
            m["accept_rate"],
            m["reject_rate"],
            m["correct_rate"],
            m["add_rate"],
            m["partial_rate"],
            m["skip_rate"],
        )
        logger.info(
            "  Auto-disposition       : %.3f   Calibration ECE: %.3f",
            m["auto_disposition_rate"],
            m["calibration_ece"],
        )
    logger.info(
        "  Cost / image           : $%.5f  |  Latency: %dms",
        m["mean_cost_usd"],
        int(m["mean_latency_ms"]),
    )
    logger.info("  Report written to %s", output_path)
    return report


def _cumulative_cost(report: dict[str, Any]) -> float:
    """Sum the per-image cost across the run records in one provider report."""
    return sum(float(r.get("cost_usd", 0.0)) for r in report.get("run_records", []))


def _bakeoff_order_for(mode: str) -> list[str]:
    """Return the provider order for the bake-off given the benchmark mode."""
    if mode == "chart-read":
        return list(BAKEOFF_PROVIDER_ORDER_CHART_READ)
    if mode == "metric-classify":
        return list(BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY)
    return list(BAKEOFF_PROVIDER_ORDER)


def _run_bakeoff(
    corpus: list[dict[str, Any]],
    limit: int | None,
    manifest_path: Path,
    output_root: Path,
    max_usd: float,
    mode: str = "detect",
) -> dict[str, Any]:
    """Run every provider for ``mode`` sequentially with a spend cap.

    Aborts mid-sweep if cumulative cost crosses ``max_usd``. Writes a
    per-provider JSON to ``output_root / <provider>.json`` plus a
    ``summary.json`` comparing metrics across providers.

    Provider order is mode-dependent:
    - ``detect`` → ``BAKEOFF_PROVIDER_ORDER`` (excludes two-stage).
    - ``chart-read`` → ``BAKEOFF_PROVIDER_ORDER_CHART_READ`` (includes two-stage).
    """
    output_root.mkdir(parents=True, exist_ok=True)

    per_provider: dict[str, dict[str, Any]] = {}
    cumulative = 0.0
    aborted_at: str | None = None
    order = _bakeoff_order_for(mode)

    for provider in order:
        logger.info(
            "\n--- Bake-off provider %s (mode=%s, cumulative spend: $%.4f / $%.2f cap) ---",
            provider,
            mode,
            cumulative,
            max_usd,
        )
        if cumulative >= max_usd:
            logger.error(
                "Spend cap $%.2f reached before provider=%s — aborting sweep.",
                max_usd,
                provider,
            )
            aborted_at = provider
            break

        provider_output = output_root / f"{provider}.json"
        report = _run_single_provider_report(
            corpus=corpus,
            provider=provider,
            limit=limit,
            manifest_path=manifest_path,
            output_path=provider_output,
            mode=mode,
        )
        per_provider[provider] = report
        cumulative += _cumulative_cost(report)

    summary = {
        "run_date": date.today().isoformat(),
        "mode": mode,
        "manifest_path": str(manifest_path),
        "providers_run": list(per_provider.keys()),
        "aborted_at": aborted_at,
        "spend_cap_usd": max_usd,
        "total_cost_usd": round(cumulative, 6),
        "by_provider": {
            provider: {
                "metrics": report["metrics"],
                "report_path": str(output_root / f"{provider}.json"),
            }
            for provider, report in per_provider.items()
        },
    }
    summary_path = output_root / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    logger.info("\n=== Bake-off summary (mode=%s) ===", mode)
    logger.info("  Providers run: %s", ", ".join(per_provider.keys()))
    logger.info("  Total spend  : $%.4f (cap $%.2f)", cumulative, max_usd)
    logger.info("  Summary JSON : %s", summary_path)
    if aborted_at:
        logger.warning("  Aborted before: %s", aborted_at)

    return summary


def main() -> None:
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args()

    # ------------------------------------------------------------------ #
    # Mode 1: build corpus manifest (DB required)
    # ------------------------------------------------------------------ #
    if args.build_corpus:
        db_url = (
            args.database_url
            or os.environ.get("TEST_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
        )
        if not db_url:
            logger.error("No database URL found.  Pass --database-url or set TEST_DATABASE_URL.")
            sys.exit(1)

        from src.infra.db import DatabaseAdapter

        db = DatabaseAdapter(db_url)

        logger.info("Querying v2_image_review_decisions for corpus...")
        rows = db.query(_CORPUS_QUERY, {})
        logger.info("  %d labeled images in DB", len(rows))

        # Fetch tier-1 fact counts per image
        logger.info("Fetching Tier-1 fact counts per image...")
        try:
            fact_rows = db.query(_TIER1_FACTS_QUERY, {})
            tier1_facts: dict[str, int] = {r["img_id"]: r["tier1_count"] for r in fact_rows}
        except Exception as exc:
            logger.warning("Could not fetch tier-1 fact counts: %s.  Defaulting to 0.", exc)
            tier1_facts = {}

        rng = random.Random(args.seed)
        corpus = _stratify_corpus(rows, tier1_facts, rng)

        logger.info("\nCorpus summary:\n%s", _stratum_table(corpus))

        manifest = {
            "_schema": "image_benchmark_manifest_v1",
            "_generated_by": "scripts/benchmark_vision.py --build-corpus",
            "_generated_date": date.today().isoformat(),
            "_seed": args.seed,
            "_total_labeled_in_db": len(rows),
            "corpus": corpus,
        }

        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)
        logger.info("Manifest written to %s  (%d entries)", manifest_path, len(corpus))
        return

    # ------------------------------------------------------------------ #
    # Mode 2: run benchmark — single provider or full Wave B5 bake-off
    # ------------------------------------------------------------------ #
    _force_local_storage_for_fixtures()

    manifest_path = Path(args.manifest)
    logger.info("Loading corpus manifest from %s ...", manifest_path)
    corpus = _load_manifest(manifest_path)
    logger.info("  Corpus: %d images", len(corpus))

    if args.limit:
        logger.info("  Limiting to %d images (--limit)", args.limit)

    mode = args.mode
    if mode == "chart-read":
        mode_prefix = "bakeoff_chart_read"
        single_prefix = "chart-read"
    elif mode == "metric-classify":
        mode_prefix = "bakeoff_metric_classify"
        single_prefix = "metric-classify"
    else:
        mode_prefix = "bakeoff"
        single_prefix = args.provider

    if args.bakeoff:
        max_usd_raw = os.environ.get("MAX_BAKEOFF_USD", "").strip()
        max_usd = float(max_usd_raw) if max_usd_raw else DEFAULT_MAX_BAKEOFF_USD
        output_root = (
            Path(args.output)
            if args.output
            else BENCHMARK_OUTPUT_DIR / f"{mode_prefix}_{date.today().isoformat()}"
        )
        _run_bakeoff(
            corpus=corpus,
            limit=args.limit,
            manifest_path=manifest_path,
            output_root=output_root,
            max_usd=max_usd,
            mode=mode,
        )
        return

    if args.output:
        output_path = Path(args.output)
    else:
        BENCHMARK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if mode in {"chart-read", "metric-classify"}:
            filename = f"{single_prefix}_{args.provider}_{date.today().isoformat()}.json"
        else:
            filename = f"{args.provider}_{date.today().isoformat()}.json"
        output_path = BENCHMARK_OUTPUT_DIR / filename

    _run_single_provider_report(
        corpus=corpus,
        provider=args.provider,
        limit=args.limit,
        manifest_path=manifest_path,
        output_path=output_path,
        mode=mode,
    )


if __name__ == "__main__":
    main()
