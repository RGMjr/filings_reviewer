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
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIError, OpenAI, RateLimitError

from src.llm.cache import CacheConfig, LLMCache

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


class VisionClient:
    """Client for OpenAI GPT-4o Vision API.

    Provides a simple interface for sending images to GPT-4o Vision
    and receiving structured responses. Includes cost tracking,
    MIME type detection, and retry logic with exponential backoff.

    Example:
        client = VisionClient()
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

    def __init__(self, model: str = "gpt-4o", cache_config: CacheConfig | None = None) -> None:
        """Initialize VisionClient.

        Args:
            model: OpenAI model to use (default: gpt-4o)
            cache_config: Optional cache configuration. If None, uses defaults from
                environment. Cache is disabled automatically when DATABASE_URL is unset.
        """
        self.model = model
        self._client = OpenAI()  # Uses OPENAI_API_KEY from env
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
            image_bytes: Raw image bytes (JPEG, PNG, or GIF)
            prompt: Text prompt describing what to extract
            detail: Image detail level ("high" for accuracy, "low" for speed/cost)
            max_tokens: Maximum response tokens
            max_retries: Maximum retry attempts (default: 3)
            response_format: Optional OpenAI response_format, e.g.
                ``{"type": "json_object"}`` to force valid JSON output. Requires
                the word "JSON" to appear in the prompt. Included in the cache key.

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

        # Compute SHA-256 of image bytes once; used as part of the cache key
        # so that different images with identical prompts produce distinct keys.
        image_sha256 = hashlib.sha256(image_bytes).hexdigest()

        # Serialize response_format for cache key (None and json_object must produce distinct keys)
        response_format_key = response_format.get("type", "none") if response_format else "none"

        # Cache lookup — returns immediately with zero cost if entry exists
        cached = self._cache.get(
            model=self.model,
            system_message="",
            prompt=prompt,
            temperature=0.0,  # placeholder for key stability; not passed to API
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

                create_kwargs: dict = {
                    "model": self.model,
                    "messages": [user_message],
                    "max_tokens": max_tokens,
                }
                if response_format is not None:
                    create_kwargs["response_format"] = response_format

                response = self._client.chat.completions.create(**create_kwargs)

                latency_ms = int(time.time() * 1000) - start_ms

                # Extract usage stats
                usage = response.usage
                prompt_tokens = usage.prompt_tokens if usage else 0
                completion_tokens = usage.completion_tokens if usage else 0

                # Calculate cost (per 1M tokens)
                cost_usd = (prompt_tokens / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS + (
                    completion_tokens / 1_000_000
                ) * self.COST_PER_1M_OUTPUT_TOKENS

                # Store result in cache for future calls on same image/prompt
                self._cache.set(
                    model=self.model,
                    system_message="",
                    prompt=prompt,
                    temperature=0.0,  # placeholder for key stability; not passed to API
                    max_tokens=max_tokens,
                    response_content=response.choices[0].message.content or "",
                    input_tokens=prompt_tokens,
                    output_tokens=completion_tokens,
                    image_sha256=image_sha256,
                    detail=detail,
                    response_format=response_format_key,
                )

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
              JSON out of gpt-4o. ``_parse_text_ocr_json`` repairs the rare
              truncated response (mirrors ``OCRExtractionStage._parse_chart_json``).
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

        # If the model said no chart, normalize the hint so callers don't see
        # stale hints from a flipped-flag response.
        if not contains_chart:
            chart_hint = "none"

        return PageTextExtraction(
            text=text,
            contains_chart=contains_chart,
            chart_hint=chart_hint,
            cost_usd=response.cost_usd,
            raw_response=response.content,
        )

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
