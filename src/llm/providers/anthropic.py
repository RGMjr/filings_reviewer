"""Anthropic vision provider adapter.

Uses the ``anthropic`` SDK with ``ANTHROPIC_API_KEY`` environment variable
authentication.

Default model: ``claude-sonnet-4-6`` (matches the bake-off target in the plan).

The ``VISION_MODEL_OCR`` / ``VISION_MODEL_CHART`` env vars override the model
via the dispatcher in ``VisionClient``.

Retry-eligible exceptions (``anthropic.RateLimitError``,
``anthropic.APIConnectionError``, ``anthropic.APIStatusError`` with 5xx) are
translated to provider-neutral shims so ``VisionClient``'s single retry loop
handles all providers uniformly.

``response_format={"type": "json_object"}`` is handled by appending a JSON
instruction to the prompt (Anthropic does not have a native ``response_format``
parameter equivalent to OpenAI's ``json_object`` mode).
"""

from __future__ import annotations

import base64
import logging
import os
import time

from src.llm.vision_client import VisionResponse

from .base import VisionProvider
from .retry_shim import ProviderRateLimitError, ProviderServerError

logger = logging.getLogger(__name__)

# Pricing (as of 2025-Q1)
# Claude Sonnet 4.6 / claude-sonnet-4-5: $3.00/1M input, $15.00/1M output
# Claude Haiku 3.5: $0.80/1M input, $4.00/1M output
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
}
_DEFAULT_PRICING = (3.00, 15.00)  # conservative fallback


class AnthropicVisionProvider(VisionProvider):
    """Vision provider backed by Anthropic Claude (anthropic SDK).

    Authentication: set ``ANTHROPIC_API_KEY`` in the environment.
    """

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        """Initialize the Anthropic vision provider.

        Args:
            model: Anthropic model identifier. Defaults to
                ``claude-sonnet-4-6`` which is the planned B5 bake-off target.
        """
        self.model = model
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY is not set; Anthropic calls will fail at runtime.")
        # Lazy import: anthropic may be installed as optional dep
        try:
            import anthropic as anthropic_sdk  # type: ignore[import-untyped]

            self._sdk = anthropic_sdk
            self._client = anthropic_sdk.Anthropic(api_key=api_key or "MISSING")
        except ImportError as exc:
            raise ImportError(
                "anthropic is required for the Anthropic provider. "
                "Install it with: pip install anthropic"
            ) from exc

        pricing = _MODEL_PRICING.get(model, _DEFAULT_PRICING)
        self._cost_in, self._cost_out = pricing

    def call_api(
        self,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        *,
        detail: str = "high",  # noqa: ARG002 — Anthropic does not expose detail level
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
    ) -> VisionResponse:
        """Call the Anthropic Messages API with an image payload.

        ``detail`` is accepted for interface compatibility but has no effect
        (Anthropic does not expose a per-request image-quality parameter).

        ``response_format={"type": "json_object"}`` is handled by appending
        a JSON instruction to the prompt, since the Anthropic API does not
        have a native JSON mode parameter.
        """
        b64_data = base64.standard_b64encode(image_bytes).decode("utf-8")

        effective_prompt = prompt
        if response_format and response_format.get("type") == "json_object":
            if "JSON" not in prompt:
                effective_prompt = prompt + "\n\nReturn ONLY valid JSON."

        # Validate mime_type for Anthropic (only JPEG, PNG, GIF, WebP supported)
        supported_mime = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if mime_type not in supported_mime:
            # Fall back to PNG if unrecognized
            logger.warning(
                "Anthropic does not support mime_type=%r; falling back to image/png",
                mime_type,
            )
            mime_type = "image/png"

        message_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": b64_data,
                },
            },
            {"type": "text", "text": effective_prompt},
        ]

        start_ms = int(time.time() * 1000)
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": message_content}],
            )
        except Exception as exc:
            _translate_anthropic_exception(exc, self._sdk)
            raise  # unreachable; _translate raises
        latency_ms = int(time.time() * 1000) - start_ms

        content = ""
        if response.content and len(response.content) > 0:
            first_block = response.content[0]
            if hasattr(first_block, "text"):
                content = first_block.text or ""

        usage = response.usage
        prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0

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


def _translate_anthropic_exception(exc: Exception, sdk: object) -> None:
    """Convert anthropic SDK exceptions to provider-neutral shims.

    Raises the appropriate shim exception so ``VisionClient``'s retry
    loop handles it correctly.
    """
    try:
        import anthropic as anthropic_sdk  # type: ignore[import-untyped]
    except ImportError:
        return

    if isinstance(exc, anthropic_sdk.RateLimitError):
        raise ProviderRateLimitError(str(exc)) from exc
    if isinstance(exc, anthropic_sdk.APIConnectionError):
        raise ProviderRateLimitError(str(exc)) from exc
    if isinstance(exc, anthropic_sdk.APIStatusError):
        if exc.status_code and 500 <= exc.status_code < 600:
            raise ProviderServerError(str(exc)) from exc
