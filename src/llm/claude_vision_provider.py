"""Claude Vision provider using the Anthropic SDK.

Implements the VisionProvider protocol for Claude models, enabling
A/B comparison with OpenAI GPT-4o for chart extraction quality.
"""

from __future__ import annotations

import base64
import logging
import time

from src.llm.vision_client import VisionResponse, detect_mime_type

logger = logging.getLogger(__name__)


class ClaudeVisionProvider:
    """Anthropic Claude Vision provider.

    Uses the Anthropic SDK to send images to Claude for analysis.
    Implements the VisionProvider protocol.

    Example:
        provider = ClaudeVisionProvider()
        response = provider.analyze_image(
            image_bytes=open("chart.jpg", "rb").read(),
            prompt="Extract data from this chart...",
        )
        print(response.content)
    """

    # Claude claude-opus-4-5 pricing per 1M tokens (as of 2025-01)
    COST_PER_1M_INPUT_TOKENS: float = 15.00   # $15.00/1M input
    COST_PER_1M_OUTPUT_TOKENS: float = 75.00  # $75.00/1M output

    def __init__(self, model: str = "claude-opus-4-5") -> None:
        """Initialize ClaudeVisionProvider.

        Args:
            model: Anthropic model to use (default: claude-opus-4-5)
        """
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY from env

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "high",
        max_tokens: int = 2000,
    ) -> VisionResponse:
        """Send image to Claude for analysis.

        Args:
            image_bytes: Raw image bytes (JPEG, PNG, GIF, WebP)
            prompt: Text prompt describing what to extract
            detail: Ignored for Claude (included for protocol compatibility)
            max_tokens: Maximum response tokens

        Returns:
            VisionResponse with content and metadata

        Raises:
            ValueError: On invalid inputs
            anthropic.APIError: On API failures
        """
        import anthropic

        if not image_bytes:
            raise ValueError("image_bytes cannot be empty")
        if not prompt or not prompt.strip():
            raise ValueError("prompt cannot be empty")

        mime_type = detect_mime_type(image_bytes)
        b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        try:
            t0 = time.monotonic()
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": b64_image,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            latency_ms = int((time.monotonic() - t0) * 1000)

            content = response.content[0].text if response.content else ""
            prompt_tokens = response.usage.input_tokens if response.usage else 0
            completion_tokens = response.usage.output_tokens if response.usage else 0
            cost_usd = (
                (prompt_tokens / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS
                + (completion_tokens / 1_000_000) * self.COST_PER_1M_OUTPUT_TOKENS
            )

            return VisionResponse(
                content=content,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )

        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            raise
