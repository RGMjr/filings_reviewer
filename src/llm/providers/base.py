"""Abstract base for vision provider adapters.

Every provider adapter must implement ``call_api``, which performs the raw
network call and returns a ``VisionResponse``. The retry + cache wrapping
is handled once in ``VisionClient.analyze_image`` — adapters only deal with
the network boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.llm.vision_client import VisionResponse


class VisionProvider(ABC):
    """Abstract vision provider.

    Adapters implement ``call_api`` which maps the common call contract to
    the underlying SDK.  Retry logic and LLMCache integration live in
    ``VisionClient``; providers are responsible only for the single
    network call and cost accounting.
    """

    @abstractmethod
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
        """Perform a single (non-retried) vision API call.

        Args:
            image_bytes: Raw image bytes (already validated non-empty by caller).
            mime_type: MIME type string, e.g. ``"image/png"``.
            prompt: User prompt (already validated non-empty by caller).
            detail: Provider-specific detail hint (``"high"`` / ``"low"``).
            max_tokens: Maximum response tokens.
            response_format: Optional structured-output hint.  Providers that
                do not support this parameter should ignore it gracefully.

        Returns:
            ``VisionResponse`` with ``content``, ``model``, ``prompt_tokens``,
            ``completion_tokens``, ``cost_usd``, and ``latency_ms`` populated.

        Raises:
            Any provider-specific exception on unrecoverable error.  Retryable
            errors (rate-limit, transient 5xx, connection) should bubble up as
            their native exception types so ``VisionClient``'s retry logic can
            handle them uniformly.
        """
        ...
