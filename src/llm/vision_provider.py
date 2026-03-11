"""Vision provider protocol and shared response type.

Defines the VisionProvider Protocol that all vision implementations must satisfy,
enabling easy swapping between OpenAI GPT-4o, Claude Vision, and future providers.
"""

from __future__ import annotations

from typing import Protocol

from src.llm.vision_client import VisionResponse

__all__ = ["VisionProvider", "VisionResponse"]


class VisionProvider(Protocol):
    """Protocol for vision LLM providers.

    Any class implementing this protocol can be used interchangeably as a
    vision backend in the extraction pipeline.
    """

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "high",
        max_tokens: int = 2000,
    ) -> VisionResponse:
        """Send image to vision LLM for analysis.

        Args:
            image_bytes: Raw image bytes (JPEG, PNG, GIF, WebP)
            prompt: Text prompt describing what to extract
            detail: Image detail level ("high" for accuracy, "low" for speed/cost)
            max_tokens: Maximum response tokens

        Returns:
            VisionResponse with content and metadata
        """
        ...
