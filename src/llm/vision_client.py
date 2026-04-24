"""LLM Vision API client — provider-agnostic dispatcher.

``VisionClient`` is the single public entry point for all vision calls.
It handles:
  - Input validation
  - LLMCache integration (lookup before call, write after)
  - Retry + exponential backoff (RateLimitError, connection errors, 5xx)
  - Provider dispatch (OpenAI by default; Gemini / Anthropic via env var)

Provider selection is controlled by:
  ``VISION_PROVIDER``      — ``openai`` (default) | ``gemini`` | ``anthropic``
  ``VISION_MODEL_OCR``     — override per-provider default model for OCR calls
  ``VISION_MODEL_CHART``   — override per-provider default model for chart calls
  ``VISION_ROUTING_MODE``  — ``legacy`` (default) | ``two_stage`` (Wave B4)

Wave B4 two-stage routing:
  When ``VISION_ROUTING_MODE=two_stage``:
  - TABLE_IMAGE calls use the fast provider resolved by ``VISION_MODEL_OCR``
    (default ``gemini-2.5-flash-lite``).
  - CHART calls make *two* sequential calls:
    1. Fast OCR pass (same fast provider) to extract axis labels / legends /
       annotation strings as a text blob.
    2. Premium reader (``VISION_MODEL_CHART``, default ``claude-sonnet-4-6``)
       with the standard chart-extraction prompt augmented by the OCR blob as
       grounding context.  The premium prompt still enforces "labeled values
       only — no interpolation".
  Both calls' costs accumulate into the caller's ``_chart_vision_spend``.
  When ``VISION_ROUTING_MODE=legacy`` (default), behavior is unchanged.

Default behavior (all env vars unset) is **identical** to the pre-refactor
implementation — the OpenAI adapter executes the same code path.

Design notes:
  1. Timing: uses ``time.time()`` for consistency with the original (see
     docstring in the original for the perf_counter improvement note).
  2. Prompts are unchanged — adapters receive exactly the prompt string
     that callers pass.  Any prompt modifications live in the adapters
     (e.g. appending JSON mode hints for Gemini/Anthropic).
  3. Cache key includes ``model`` as a top-level field via ``LLMCache._compute_key``.
     ``LLM_CACHE_VERSION`` is bumped to ``v2`` in this PR to prevent old GPT-4o
     cached responses from appearing as hits under a new provider default.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIError, RateLimitError

from src.llm.cache import CacheConfig, LLMCache
from src.llm.providers.retry_shim import (
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderServerError,
)

logger = logging.getLogger(__name__)


# Supported image formats with their magic bytes
# WebP files start with "RIFF" followed by file size (4 bytes) then "WEBP"
IMAGE_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}

# WebP requires special handling - check for RIFF header + WEBP at offset 8
WEBP_RIFF_HEADER = b"RIFF"
WEBP_MAGIC = b"WEBP"


def detect_mime_type(image_bytes: bytes) -> str:
    """Detect MIME type from image magic bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        MIME type string (defaults to "image/png" if unknown)
    """
    # Check standard signatures first
    for signature, mime_type in IMAGE_SIGNATURES.items():
        if image_bytes.startswith(signature):
            return mime_type

    # Check for WebP: RIFF header + "WEBP" at offset 8
    if (
        len(image_bytes) >= 12
        and image_bytes.startswith(WEBP_RIFF_HEADER)
        and image_bytes[8:12] == WEBP_MAGIC
    ):
        return "image/webp"

    # Default to PNG for unknown formats
    return "image/png"


@dataclass
class VisionResponse:
    """Response from Vision LLM.

    Attributes:
        content: The text content of the LLM response
        model: The model identifier used
        prompt_tokens: Number of tokens in the prompt (including image)
        completion_tokens: Number of tokens in the completion
        cost_usd: Estimated cost in USD for this request
        latency_ms: Request latency in milliseconds
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


@dataclass
class PageTextExtraction:
    """Parsed output of ``VisionClient.analyze_image_for_text``.

    Attributes:
        text: Paragraph / table-cell text in reading order (may be empty).
        contains_chart: True iff a chart/graph is visually present on the page.
        chart_hint: Best-guess chart type; one of the ``ChartType`` values or
            ``"none"`` if no chart present.
        cost_usd: Cost of the underlying vision call (0.0 for cache hits).
        raw_response: The unparsed content string (for audit / debugging).
    """

    text: str
    contains_chart: bool
    chart_hint: str
    cost_usd: float
    raw_response: str


# Prompt for text-mode OCR of a full page image.
# The word "JSON" is required by OpenAI's response_format=json_object mode.
_PAGE_TEXT_PROMPT = """\
You are extracting content from a single page of a company's SEC filing. \
The page is supplied as an image.

Extract:
1. All paragraph text and table-cell text visible on the page, in reading order, \
joined with single newline characters between blocks. Preserve numeric values, dates, \
percentages, and cell text exactly as shown. Skip page numbers, headers, footers, \
watermarks, and legal boilerplate unless that is the entire page.
2. Whether the page contains a chart or graph (bar, line, pie, area, stacked bar, \
scatter), as distinct from a text-only page or a table-only page.
3. If a chart is present, the best-guess chart type.

Return ONLY a valid JSON object with exactly this schema:
{
  "text": "...",
  "contains_chart": true|false,
  "chart_hint": "bar" | "line" | "pie" | "area" | "stacked_bar" | "scatter" | "none"
}

Do not include any commentary outside the JSON."""


_VALID_CHART_HINTS = frozenset({"bar", "line", "pie", "area", "stacked_bar", "scatter", "none"})

# Per-provider default models
_PROVIDER_DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "openai": {"ocr": "gpt-4o", "chart": "gpt-4o"},
    "gemini": {"ocr": "gemini-2.0-flash", "chart": "gemini-2.5-pro-preview-05-06"},
    "anthropic": {"ocr": "claude-sonnet-4-6", "chart": "claude-sonnet-4-6"},
}


def _get_provider_and_model(
    model: str | None,
) -> tuple[str, str]:
    """Resolve provider name and model string from env vars + argument.

    Priority (highest to lowest):
      1. ``model`` argument passed directly to ``VisionClient.__init__``
         (when non-None, uses ``openai`` provider regardless of VISION_PROVIDER)
      2. ``VISION_PROVIDER`` env var + ``VISION_MODEL_OCR`` / ``VISION_MODEL_CHART``
      3. Provider defaults from ``_PROVIDER_DEFAULT_MODELS``

    Returns:
        (provider_name, model_string)
    """
    provider = os.environ.get("VISION_PROVIDER", "openai").lower().strip()
    if provider not in _PROVIDER_DEFAULT_MODELS:
        logger.warning("Unknown VISION_PROVIDER=%r; falling back to 'openai'", provider)
        provider = "openai"

    if model is not None:
        # Explicit model passed → force openai provider (back-compat with
        # call sites that do VisionClient(model="gpt-4o-mini"))
        return "openai", model

    # Use VISION_MODEL_OCR as the default model for the client.  Callers that
    # need chart-specific models will be handled in Wave B4.
    env_model = os.environ.get("VISION_MODEL_OCR", "").strip()
    if env_model:
        return provider, env_model

    return provider, _PROVIDER_DEFAULT_MODELS[provider]["ocr"]


def _build_provider(provider_name: str, model: str) -> object:
    """Instantiate the appropriate provider adapter.

    Returns an instance of ``VisionProvider`` for the given provider name.
    """
    if provider_name == "openai":
        from src.llm.providers.openai import OpenAIVisionProvider

        return OpenAIVisionProvider(model=model)
    elif provider_name == "gemini":
        from src.llm.providers.gemini import GeminiVisionProvider

        return GeminiVisionProvider(model=model)
    elif provider_name == "anthropic":
        from src.llm.providers.anthropic import AnthropicVisionProvider

        return AnthropicVisionProvider(model=model)
    else:
        raise ValueError(f"Unknown provider: {provider_name!r}")


# Default models for two-stage routing (Wave B4).
# These are read at stage init; operators can override via env vars.
_TWO_STAGE_DEFAULT_OCR_MODEL = "gemini-2.5-flash-lite"
_TWO_STAGE_DEFAULT_CHART_MODEL = "claude-sonnet-4-6"
_TWO_STAGE_DEFAULT_OCR_PROVIDER = "gemini"
_TWO_STAGE_DEFAULT_CHART_PROVIDER = "anthropic"


def _resolve_two_stage_providers() -> tuple[tuple[str, str], tuple[str, str]]:
    """Resolve (provider, model) pairs for the two-stage routing path.

    Returns:
        ((ocr_provider, ocr_model), (chart_provider, chart_model))

    OCR model is controlled by ``VISION_MODEL_OCR`` env var (default:
    ``gemini-2.5-flash-lite`` via Gemini).  Chart model is controlled by
    ``VISION_MODEL_CHART`` env var (default: ``claude-sonnet-4-6`` via
    Anthropic).  When an env-var override specifies a model that belongs to a
    different provider, we make a best-effort guess based on model name
    prefixes; callers can also set ``VISION_PROVIDER_OCR`` /
    ``VISION_PROVIDER_CHART`` to force the provider explicitly.
    """
    ocr_model = os.environ.get("VISION_MODEL_OCR", "").strip() or _TWO_STAGE_DEFAULT_OCR_MODEL
    chart_model = os.environ.get("VISION_MODEL_CHART", "").strip() or _TWO_STAGE_DEFAULT_CHART_MODEL

    ocr_provider = _infer_provider_from_model(
        os.environ.get("VISION_PROVIDER_OCR", "").strip(),
        ocr_model,
        _TWO_STAGE_DEFAULT_OCR_PROVIDER,
    )
    chart_provider = _infer_provider_from_model(
        os.environ.get("VISION_PROVIDER_CHART", "").strip(),
        chart_model,
        _TWO_STAGE_DEFAULT_CHART_PROVIDER,
    )

    return (ocr_provider, ocr_model), (chart_provider, chart_model)


def _infer_provider_from_model(explicit_provider: str, model: str, default: str) -> str:
    """Return provider name, using explicit override or model-prefix heuristic.

    Args:
        explicit_provider: Value from VISION_PROVIDER_OCR / _CHART env vars.
            Empty string means "no explicit override".
        model: Model identifier string.
        default: Fallback when neither explicit nor heuristic applies.
    """
    if explicit_provider and explicit_provider in _PROVIDER_DEFAULT_MODELS:
        return explicit_provider
    # Heuristic: model name prefix
    m = model.lower()
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("claude"):
        return "anthropic"
    return default


class VisionClient:
    """Provider-agnostic vision client.

    Routes image analysis calls to the configured provider (default: OpenAI
    GPT-4o).  Provider is selected via ``VISION_PROVIDER`` env var.  When
    ``VISION_PROVIDER`` is unset or ``"openai"``, behavior is **identical** to
    the pre-refactor implementation.

    Public interface is unchanged from the original:
        client = VisionClient()
        response = client.analyze_image(
            image_bytes=open("chart.jpg", "rb").read(),
            prompt="Extract data from this chart...",
        )
        print(response.content)

    Cache, retry, and cost-tracking semantics are preserved across all
    providers.
    """

    # GPT-4o pricing per 1M tokens (as of 2025-01) — kept as class attrs for
    # test back-compat (tests reference VisionClient.COST_PER_1M_INPUT_TOKENS).
    COST_PER_1M_INPUT_TOKENS: float = 2.50  # $2.50/1M input
    COST_PER_1M_OUTPUT_TOKENS: float = 10.00  # $10.00/1M output

    # Retry configuration
    DEFAULT_MAX_RETRIES: int = 3
    BASE_BACKOFF_SECONDS: float = 1.0

    def __init__(self, model: str | None = None, cache_config: CacheConfig | None = None) -> None:
        """Initialize VisionClient.

        Args:
            model: Optional model override. When set, forces the OpenAI
                provider with the specified model (back-compat). When None,
                provider and model are resolved from env vars.
            cache_config: Optional cache configuration. If None, uses defaults
                from environment. Cache is disabled automatically when
                DATABASE_URL is unset.
        """
        # Accept model="gpt-4o" for back-compat (original signature)
        _model_arg: str | None = model if model is not None else None

        provider_name, resolved_model = _get_provider_and_model(_model_arg)
        self.model = resolved_model
        self._provider = _build_provider(provider_name, resolved_model)
        self._cache = LLMCache(cache_config)

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "high",
        max_tokens: int = 2000,
        max_retries: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> VisionResponse:
        """Send image to Vision LLM for analysis.

        Args:
            image_bytes: Raw image bytes (JPEG, PNG, GIF, or WebP)
            prompt: Text prompt describing what to extract
            detail: Image detail level ("high" for accuracy, "low" for speed/cost)
            max_tokens: Maximum response tokens
            max_retries: Maximum retry attempts (default: 3)
            response_format: Optional response_format, e.g.
                ``{"type": "json_object"}`` to force valid JSON output. Requires
                the word "JSON" to appear in the prompt (OpenAI requirement;
                other providers use a prompt injection instead). Included in
                the cache key.

        Returns:
            VisionResponse with content and metadata

        Raises:
            ValueError: On invalid inputs (empty image or prompt)
            Exception: Provider-specific API error after retries exhausted
        """
        # Input validation - fail fast before API call
        if not image_bytes:
            raise ValueError("image_bytes cannot be empty")
        if not prompt or not prompt.strip():
            raise ValueError("prompt cannot be empty")

        if max_retries is None:
            max_retries = self.DEFAULT_MAX_RETRIES

        # Compute SHA-256 of image bytes once; used as part of the cache key
        image_sha256 = hashlib.sha256(image_bytes).hexdigest()

        # Serialize response_format for cache key
        response_format_key = response_format.get("type", "none") if response_format else "none"

        # Cache lookup
        cached = self._cache.get(
            model=self.model,
            system_message="",
            prompt=prompt,
            temperature=0.0,
            max_tokens=max_tokens,
            image_sha256=image_sha256,
            detail=detail,
            response_format=response_format_key,
        )
        if cached:
            return VisionResponse(
                content=cached.content,
                model=self.model,
                prompt_tokens=cached.input_tokens,
                completion_tokens=cached.output_tokens,
                cost_usd=0.0,
                latency_ms=0,
            )

        # Detect MIME type from magic bytes (done here, not in adapter,
        # so it's part of the common path and available for logging)
        mime_type = detect_mime_type(image_bytes)

        # Retry loop with exponential backoff
        last_exception: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._provider.call_api(  # type: ignore[attr-defined]
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    prompt=prompt,
                    detail=detail,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )

                # Store result in cache
                self._cache.set(
                    model=self.model,
                    system_message="",
                    prompt=prompt,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    response_content=response.content,
                    input_tokens=response.prompt_tokens,
                    output_tokens=response.completion_tokens,
                    image_sha256=image_sha256,
                    detail=detail,
                    response_format=response_format_key,
                )

                return response

            except (RateLimitError, ProviderRateLimitError) as e:
                last_exception = e
                if attempt < max_retries:
                    backoff = self.BASE_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        f"Rate limit hit, retrying in {backoff}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(f"Rate limit exceeded after {max_retries} retries")

            except (APIConnectionError, ProviderConnectionError) as e:
                last_exception = e
                if attempt < max_retries:
                    backoff = self.BASE_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        f"Connection error, retrying in {backoff}s "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(f"Connection failed after {max_retries} retries: {e}")

            except ProviderServerError as e:
                # Provider-neutral 5xx shim
                last_exception = e
                if attempt < max_retries:
                    backoff = self.BASE_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        f"Server error {e.status_code}, retrying in {backoff}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(f"Server error after {max_retries} retries: {e}")
                    raise

            except APIError as e:
                # OpenAI server error (5xx) - retry; client error (4xx) - don't retry
                last_exception = e
                status_code = getattr(e, "status_code", None)
                if status_code and 500 <= status_code < 600 and attempt < max_retries:
                    backoff = self.BASE_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        f"Server error {status_code}, retrying in {backoff}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(backoff)
                else:
                    logger.error(f"API error (status={status_code}): {e}")
                    raise

        # All retries exhausted
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected state: no response and no exception")

    def analyze_image_targeted(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        task_type: str,
        detail: str = "high",
        max_tokens: int = 2000,
        max_retries: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> VisionResponse:
        """Route an image analysis call to the task-specific provider (Wave B4).

        When ``VISION_ROUTING_MODE=two_stage``:
        - ``task_type='table_ocr'`` or ``'chart_ocr'`` → fast provider
          (``VISION_MODEL_OCR``, default ``gemini-2.5-flash-lite``).
        - ``task_type='chart_read'`` → premium reader (``VISION_MODEL_CHART``,
          default ``claude-sonnet-4-6``).

        When ``VISION_ROUTING_MODE=legacy`` (default), all task types route
        through the single provider configured at init — behavior is
        identical to ``analyze_image``.
        """
        mode = os.environ.get("VISION_ROUTING_MODE", "legacy").strip().lower()
        if mode != "two_stage":
            return self.analyze_image(
                image_bytes,
                prompt,
                detail=detail,
                max_tokens=max_tokens,
                max_retries=max_retries,
                response_format=response_format,
            )

        (ocr_p, ocr_m), (chart_p, chart_m) = _resolve_two_stage_providers()
        if task_type in ("table_ocr", "chart_ocr"):
            provider_name, model = ocr_p, ocr_m
        elif task_type == "chart_read":
            provider_name, model = chart_p, chart_m
        else:
            raise ValueError(
                f"Unknown task_type: {task_type!r} "
                "(expected 'table_ocr', 'chart_ocr', or 'chart_read')"
            )

        # Swap provider + model for this call only. Cache keying depends on
        # self.model, so both the lookup and store use the correct model.
        orig_provider = self._provider
        orig_model = self.model
        self._provider = _build_provider(provider_name, model)
        self.model = model
        try:
            return self.analyze_image(
                image_bytes,
                prompt,
                detail=detail,
                max_tokens=max_tokens,
                max_retries=max_retries,
                response_format=response_format,
            )
        finally:
            self._provider = orig_provider
            self.model = orig_model

    def analyze_image_for_text(
        self,
        image_bytes: bytes,
        *,
        max_tokens: int = 3000,
    ) -> PageTextExtraction:
        """Extract paragraph text from a page-sized image and flag chart presence.

        Targets the full-page-scan and ambiguous-image-pre-scan use cases:
        returns OCR'd paragraph text plus a flag indicating whether the same
        page also contains a chart (so callers can decide whether to run a
        second, chart-specific vision call on the same asset).

        Args:
            image_bytes: Raw JPEG/PNG/GIF/WebP bytes.
            max_tokens: Ceiling on output tokens. Default 3000 comfortably fits
                a dense slide; bump only if truncation becomes a problem.

        Returns:
            PageTextExtraction with parsed ``text``, ``contains_chart``,
            ``chart_hint``, and the underlying cost.

        Notes:
            - Uses ``response_format={"type": "json_object"}`` to force valid
              JSON where the provider supports it; other providers receive a
              prompt injection.
            - Cache key includes the prompt, so this call never collides with
              cached chart/table responses.
        """
        response = self.analyze_image(
            image_bytes=image_bytes,
            prompt=_PAGE_TEXT_PROMPT,
            detail="high",
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        parsed = self._parse_text_ocr_json(response.content)
        if parsed is None:
            logger.warning(
                "analyze_image_for_text: failed to parse JSON response (len=%d, first_80=%r)",
                len(response.content),
                response.content[:80],
            )
            return PageTextExtraction(
                text="",
                contains_chart=False,
                chart_hint="none",
                cost_usd=response.cost_usd,
                raw_response=response.content,
            )

        text = str(parsed.get("text", "") or "")
        contains_chart = bool(parsed.get("contains_chart", False))
        chart_hint_raw = str(parsed.get("chart_hint", "none") or "none").lower()
        chart_hint = chart_hint_raw if chart_hint_raw in _VALID_CHART_HINTS else "none"

        if not contains_chart:
            chart_hint = "none"

        return PageTextExtraction(
            text=text,
            contains_chart=contains_chart,
            chart_hint=chart_hint,
            cost_usd=response.cost_usd,
            raw_response=response.content,
        )

    def analyze_image_for_metric_classification(
        self,
        image_bytes: bytes,
        *,
        detail: str = "high",
        max_tokens: int = 400,
    ) -> dict[str, Any] | None:
        """Classify which customer metrics are disclosed in a chart image.

        Sends the image to the Vision LLM using ``CLASSIFY_PROMPT`` and
        ``response_format={"type": "json_object"}``, then parses and
        normalises the response via ``_parse_classify_response``.

        Args:
            image_bytes: Raw JPEG/PNG/GIF/WebP bytes.
            detail: Image detail level passed to ``analyze_image``.
                Default ``"high"`` — metric-classify needs full resolution.
            max_tokens: Ceiling on output tokens. 400 comfortably fits the
                compact JSON response schema.

        Returns:
            Parsed dict with keys ``predicted_metrics``, ``confidence``,
            ``rejection_reason``, and ``reasoning``; or ``None`` on API
            failure or unparseable response.

        Notes:
            - Uses the module-level ``CLASSIFY_PROMPT`` constant (built from
              ``config/metric_keywords.yaml`` at import time).
            - No prod pipeline stage wires this yet — Leg B adds that.
        """
        try:
            response = self.analyze_image(
                image_bytes=image_bytes,
                prompt=CLASSIFY_PROMPT,
                detail=detail,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception:
            logger.exception("analyze_image_for_metric_classification: API call failed")
            return None

        parsed = _parse_classify_response(response.content)
        if parsed is None:
            logger.warning(
                "analyze_image_for_metric_classification: failed to parse response "
                "(len=%d, first_80=%r)",
                len(response.content),
                response.content[:80],
            )
        return parsed

    @staticmethod
    def _parse_text_ocr_json(content: str) -> dict | None:
        """Parse the JSON body of an ``analyze_image_for_text`` response.

        Strips markdown code fences (rarely present under json_object mode but
        cheap to handle) and attempts a single balanced-brace repair if the
        raw content is truncated. Returns None if no balanced object is found.
        """
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", content.strip(), flags=re.MULTILINE)
        stripped = stripped.rstrip("`").strip()
        if not stripped:
            return None

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        repaired = _repair_truncated_json_object(stripped)
        if repaired is None:
            return None
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# Metric-classify helpers — ported from metric-classify-harness
# ---------------------------------------------------------------------------

# Repo root: two levels up from src/llm/vision_client.py
_REPO_ROOT = Path(__file__).parent.parent.parent


def _load_tier_metric_ids() -> tuple[list[str], list[str]]:
    """Return ``(tier1_ids, tier2_ids)`` from config/metric_keywords.yaml.

    Reads yaml at call time so the prompt can never drift from the
    authoritative tier assignment in CLAUDE.md. Returns deterministically
    sorted ids (alphabetical) so the prompt is stable across runs.
    """
    import yaml

    yaml_path = _REPO_ROOT / "config" / "metric_keywords.yaml"
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


#: Allowed ``rejection_reason`` values in a metric-classify response.
#: ``table_handled_elsewhere`` is added here (preemptive #93 fix) so this
#: frozenset is the single-source of truth; ``v2_image_review_decisions``
#: CHECK constraint will reference it once Leg B lands.
CLASSIFY_REJECTION_REASONS: frozenset[str] = frozenset(
    {
        "decorative",
        "not_a_chart",
        "wrong_subject",
        "duplicate",
        "unreadable",
        "other",
        "table_handled_elsewhere",
    }
)


def _build_classify_prompt(tier1: list[str], tier2: list[str]) -> str:
    """Assemble the metric-classification prompt.

    Returns JSON-only; paired with ``response_format={"type": "json_object"}``
    on the API call. Tier lists are injected from ``metric_keywords.yaml``
    at import time so tier assignments are always in sync with CLAUDE.md.
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


_TIER1_METRIC_IDS, _TIER2_METRIC_IDS = _load_tier_metric_ids()

#: Pre-built classification prompt (stable across runs; built from yaml at import).
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


def _repair_truncated_json_object(text: str) -> str | None:
    """Return the shortest prefix forming a balanced top-level JSON object.

    Mirrors ``OCRExtractionStage._repair_truncated_json`` so we do not take
    a cross-module dependency from ``vision_client`` into the extraction stage.
    """
    if not text or not text.lstrip().startswith("{"):
        return None
    depth = 0
    in_string = False
    escape = False
    last_balanced = -1
    start = text.find("{")
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_balanced = i
                break
    if last_balanced < 0:
        return None
    return text[start : last_balanced + 1]
