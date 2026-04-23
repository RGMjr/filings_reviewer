"""OpenAI vision provider adapter.

Wraps the ``openai`` SDK.  This is the default provider (``VISION_PROVIDER=openai``)
and is behaviorally identical to the original ``VisionClient`` implementation.

Retry logic (RateLimitError, APIConnectionError, 5xx APIError) is handled by
``VisionClient.analyze_image``; this adapter only performs a single call.
"""

from __future__ import annotations

import base64
import time

from openai import OpenAI
from openai.types.chat import ChatCompletionUserMessageParam

from src.llm.vision_client import VisionResponse

from .base import VisionProvider


class OpenAIVisionProvider(VisionProvider):
    """Vision provider backed by OpenAI's Chat Completions API.

    Pricing defaults match GPT-4o as of 2025-01.  Pass a different
    ``model`` and cost constants when using other OpenAI vision models.
    """

    # GPT-4o pricing per 1M tokens (as of 2025-01)
    COST_PER_1M_INPUT_TOKENS: float = 2.50
    COST_PER_1M_OUTPUT_TOKENS: float = 10.00

    def __init__(
        self,
        model: str = "gpt-4o",
        cost_per_1m_input: float | None = None,
        cost_per_1m_output: float | None = None,
    ) -> None:
        """Initialize the OpenAI vision provider.

        Args:
            model: OpenAI model identifier.
            cost_per_1m_input: Override input token cost ($/1M). Defaults to
                ``COST_PER_1M_INPUT_TOKENS``.
            cost_per_1m_output: Override output token cost ($/1M). Defaults to
                ``COST_PER_1M_OUTPUT_TOKENS``.
        """
        self.model = model
        self._cost_in = (
            cost_per_1m_input if cost_per_1m_input is not None else self.COST_PER_1M_INPUT_TOKENS
        )
        self._cost_out = (
            cost_per_1m_output if cost_per_1m_output is not None else self.COST_PER_1M_OUTPUT_TOKENS
        )
        self._client = OpenAI()  # uses OPENAI_API_KEY from env

    def call_api(
        self,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        *,
        detail: str = "high",
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
    ) -> VisionResponse:
        """Call the OpenAI Chat Completions API with an image payload."""
        b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64_image}",
                        "detail": detail,  # type: ignore[typeddict-item]
                    },
                },
            ],
        }

        create_kwargs: dict = {
            "model": self.model,
            "messages": [user_message],
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            create_kwargs["response_format"] = response_format

        start_ms = int(time.time() * 1000)
        response = self._client.chat.completions.create(**create_kwargs)
        latency_ms = int(time.time() * 1000) - start_ms

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        cost_usd = (prompt_tokens / 1_000_000) * self._cost_in + (
            completion_tokens / 1_000_000
        ) * self._cost_out

        return VisionResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
