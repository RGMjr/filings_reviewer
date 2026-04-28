"""Gemini vision provider adapter.

Uses the ``google-genai`` SDK (``google.genai``) with ``GOOGLE_API_KEY``
environment variable authentication.  No GCP project or Vertex AI dependency.

Default models:
  OCR  : ``gemini-2.0-flash`` (fast, cheap)
  Chart: ``gemini-2.5-pro-preview-05-06`` (high-quality reasoning)

The ``VISION_MODEL_OCR`` / ``VISION_MODEL_CHART`` env vars override these
via the dispatcher in ``VisionClient``.  This adapter is model-agnostic;
pass the desired model string to ``__init__``.

Retry-eligible exceptions re-raised as-is so ``VisionClient``'s retry loop
can catch them.  The ``google.genai`` SDK raises:
  - ``google.api_core.exceptions.ResourceExhausted`` — maps to rate-limit
  - ``google.api_core.exceptions.ServiceUnavailable`` — maps to 5xx
  - ``google.api_core.exceptions.GoogleAPICallError`` — general API error

Since ``VisionClient`` retries on ``RateLimitError`` / ``APIConnectionError``
/ ``APIError``, and those are OpenAI types, the Gemini adapter converts the
Gemini exceptions to a parallel hierarchy using the shim at the bottom of
this module.  This keeps retry logic in one place.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

from src.llm.vision_client import VisionResponse

from .base import VisionProvider
from .retry_shim import ProviderRateLimitError, ProviderServerError

logger = logging.getLogger(__name__)

# Pricing (as of 2025-Q1 preview pricing — update when GA pricing is announced)
# Gemini 2.5 Pro: $1.25/1M input (<=200K tokens), $10.00/1M output
# Gemini 2.0 Flash: $0.10/1M input, $0.40/1M output
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro-preview-05-06": (1.25, 10.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}
_DEFAULT_PRICING = (1.25, 10.00)  # conservative fallback

# Model name substrings that indicate extended-thinking capability (Gemini 2.5 Pro).
# These models run a thinking phase before emitting output; when max_output_tokens is
# low (e.g. 400 for metric-classify), the thinking phase can consume the entire budget
# and leave an empty text response.  We disable thinking for vision calls so the full
# token budget is available for the actual JSON response.
_THINKING_MODEL_SUBSTRINGS: tuple[str, ...] = ("gemini-2.5-pro",)


def _is_thinking_model(model: str) -> bool:
    """Return True if ``model`` is a Gemini thinking model (e.g. Gemini 2.5 Pro).

    Uses substring matching so preview suffixes like ``-preview-05-06`` are
    recognised automatically.
    """
    m = model.lower()
    return any(sub in m for sub in _THINKING_MODEL_SUBSTRINGS)


class GeminiVisionProvider(VisionProvider):
    """Vision provider backed by Google Gemini (google-genai SDK).

    Authentication: set ``GOOGLE_API_KEY`` in the environment.
    No GCP project / Application Default Credentials required.
    """

    def __init__(self, model: str = "gemini-2.0-flash") -> None:
        """Initialize the Gemini vision provider.

        Args:
            model: Gemini model identifier. Defaults to ``gemini-2.0-flash``
                for cost-effective OCR work.
        """
        self.model = model
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("GOOGLE_API_KEY is not set; Gemini calls will fail at runtime.")
        # Lazy import: google-genai is an optional dependency
        try:
            import google.genai as genai  # type: ignore[import-untyped]

            self._genai = genai
            self._client = genai.Client(api_key=api_key or "MISSING")
        except ImportError as exc:
            raise ImportError(
                "google-genai is required for the Gemini provider. "
                "Install it with: pip install google-genai"
            ) from exc

        pricing = _MODEL_PRICING.get(model, _DEFAULT_PRICING)
        self._cost_in, self._cost_out = pricing

    def call_api(
        self,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        *,
        detail: str = "high",  # noqa: ARG002 — not used by Gemini
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
    ) -> VisionResponse:
        """Call the Gemini GenerateContent API with an image payload.

        ``detail`` is accepted for interface compatibility but has no effect
        (Gemini does not expose a per-request image-quality parameter).

        ``response_format={"type": "json_object"}`` is handled two ways:
        1. ``response_mime_type="application/json"`` is set in the generation
           config so the API enforces valid JSON at the protocol level.
        2. ``"Return ONLY valid JSON."`` is appended to the prompt when
           "JSON" does not already appear, as a belt-and-suspenders hint.

        For thinking-capable models (Gemini 2.5 Pro), extended thinking is
        disabled via ``thinking_config`` with ``thinking_budget=0``.  Without
        this, the thinking phase can silently consume the entire
        ``max_output_tokens`` budget and leave an empty text response — the
        root cause of legacy-091.
        """
        # Build the image Part
        b64_data = base64.standard_b64encode(image_bytes).decode("utf-8")

        wants_json = response_format and response_format.get("type") == "json_object"

        effective_prompt = prompt
        if wants_json and "JSON" not in prompt:
            effective_prompt = prompt + "\n\nReturn ONLY valid JSON."

        try:
            import google.genai.types as genai_types  # type: ignore[import-untyped]

            image_part = genai_types.Part.from_bytes(
                data=base64.standard_b64decode(b64_data),
                mime_type=mime_type,
            )
            contents = [image_part, effective_prompt]

            config_kwargs: dict[str, Any] = {
                "max_output_tokens": max_tokens,
                "temperature": 0.0,
            }
            if wants_json:
                config_kwargs["response_mime_type"] = "application/json"
            if _is_thinking_model(self.model):
                # Disable extended thinking so the full token budget is
                # available for the JSON response (fixes legacy-091).
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                    thinking_budget=0
                )
            generation_config = genai_types.GenerateContentConfig(**config_kwargs)
        except ImportError:
            # Older google-genai API (pre-1.0) uses dict-based parts
            contents = _build_legacy_contents(b64_data, mime_type, effective_prompt)
            generation_config = {"maxOutputTokens": max_tokens, "temperature": 0.0}

        start_ms = int(time.time() * 1000)
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=generation_config,
            )
        except Exception as exc:
            _translate_gemini_exception(exc)
            raise  # unreachable; _translate raises
        latency_ms = int(time.time() * 1000) - start_ms

        content = ""
        prompt_tokens = 0
        completion_tokens = 0

        if response.text:
            content = response.text
        if response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            completion_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        cost_usd = (prompt_tokens / 1_000_000) * self._cost_in + (
            completion_tokens / 1_000_000
        ) * self._cost_out

        return VisionResponse(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )


def _build_legacy_contents(b64_data: str, mime_type: str, prompt: str) -> list[Any]:
    """Build contents list for older google-genai SDK versions."""
    return [
        {
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                {"text": prompt},
            ]
        }
    ]


def _translate_gemini_exception(exc: Exception) -> None:
    """Convert google-api-core exceptions to provider-neutral shims.

    Raises the appropriate shim exception so ``VisionClient``'s retry
    loop handles it correctly.
    """
    exc_type_name = type(exc).__name__
    exc_module = getattr(type(exc), "__module__", "")

    if "google" in exc_module:
        if exc_type_name == "ResourceExhausted":
            raise ProviderRateLimitError(str(exc)) from exc
        if exc_type_name in ("ServiceUnavailable", "InternalServerError", "DeadlineExceeded"):
            raise ProviderServerError(str(exc)) from exc
