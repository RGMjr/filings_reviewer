"""LLM Vision API client for chart image analysis.

This module provides a client for the OpenAI GPT-4o Vision API, designed
specifically for extracting structured data from chart images in SEC filings.

Design: OpenAI-only for now. Can be extended to support Claude Vision
in the future via subclassing or protocol pattern.

Future Improvements:
    1. Timing precision: Consider using time.perf_counter() instead of time.time()
       for latency_ms measurement. time.perf_counter() provides monotonic,
       high-resolution timing better suited for measuring elapsed time.

    2. Pipeline integration: This client is standalone. To integrate with the
       extraction pipeline, orchestrate as:
       - CohortChartDetector.detect_charts_in_filing() -> list of image candidates
       - SECClient.fetch_image() -> download each image
       - ChartValueExtractor.extract() -> extract values from each image
       See VIS-2a for planned caching to avoid repeated SEC downloads.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIError, OpenAI, RateLimitError

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

    # Default to PNG for unknown formats (OpenAI will reject if invalid)
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


class OpenAIVisionProvider:
    """OpenAI GPT-4o Vision provider.

    Provides a simple interface for sending images to GPT-4o Vision
    and receiving structured responses. Includes cost tracking,
    MIME type detection, and retry logic with exponential backoff.

    Implements the VisionProvider protocol.

    Example:
        client = OpenAIVisionProvider()
        response = client.analyze_image(
            image_bytes=open("chart.jpg", "rb").read(),
            prompt="Extract data from this chart...",
        )
        print(response.content)
    """

    # GPT-4o pricing per 1M tokens (as of 2025-01)
    # Source: https://openai.com/pricing
    COST_PER_1M_INPUT_TOKENS: float = 2.50  # $2.50/1M input
    COST_PER_1M_OUTPUT_TOKENS: float = 10.00  # $10.00/1M output

    # Retry configuration
    DEFAULT_MAX_RETRIES: int = 3
    BASE_BACKOFF_SECONDS: float = 1.0

    def __init__(self, model: str = "gpt-4o") -> None:
        """Initialize OpenAIVisionProvider.

        Args:
            model: OpenAI model to use (default: gpt-4o)
        """
        self.model = model
        self._client = OpenAI()  # Uses OPENAI_API_KEY from env

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "high",
        max_tokens: int = 2000,
        max_retries: int | None = None,
    ) -> VisionResponse:
        """Send image to Vision LLM for analysis.

        Args:
            image_bytes: Raw image bytes (JPEG, PNG, or GIF)
            prompt: Text prompt describing what to extract
            detail: Image detail level ("high" for accuracy, "low" for speed/cost)
            max_tokens: Maximum response tokens
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            VisionResponse with content and metadata

        Raises:
            ValueError: On invalid inputs (empty image or prompt)
            openai.APIError: On API failures (after retries exhausted)
        """
        # Input validation - fail fast before API call
        if not image_bytes:
            raise ValueError("image_bytes cannot be empty")
        if not prompt or not prompt.strip():
            raise ValueError("prompt cannot be empty")

        if max_retries is None:
            max_retries = self.DEFAULT_MAX_RETRIES

        # Encode image as base64
        b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        # Detect MIME type from magic bytes
        mime_type = detect_mime_type(image_bytes)

        # Build message content for Vision API
        # Type assertion needed for OpenAI SDK's strict typing
        from openai.types.chat import ChatCompletionUserMessageParam

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

        # Retry loop with exponential backoff
        last_exception: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                start_ms = int(time.time() * 1000)

                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[user_message],
                    max_tokens=max_tokens,
                )

                latency_ms = int(time.time() * 1000) - start_ms

                # Extract usage stats
                usage = response.usage
                prompt_tokens = usage.prompt_tokens if usage else 0
                completion_tokens = usage.completion_tokens if usage else 0

                # Calculate cost (per 1M tokens)
                cost_usd = (prompt_tokens / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS + (
                    completion_tokens / 1_000_000
                ) * self.COST_PER_1M_OUTPUT_TOKENS

                return VisionResponse(
                    content=response.choices[0].message.content or "",
                    model=response.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                )

            except RateLimitError as e:
                # Rate limit - always retry with backoff
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

            except APIConnectionError as e:
                # Connection error - retry with backoff
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

            except APIError as e:
                # Server error (5xx) - retry; client error (4xx) - don't retry
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
                    # Client error or max retries exceeded - raise immediately
                    logger.error(f"API error (status={status_code}): {e}")
                    raise

        # All retries exhausted
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected state: no response and no exception")


# Backward-compatibility alias
VisionClient = OpenAIVisionProvider
