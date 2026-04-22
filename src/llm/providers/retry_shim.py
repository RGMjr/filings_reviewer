"""Provider-neutral exception shims for the retry layer in VisionClient.

VisionClient's retry loop was originally written against OpenAI exception
types (``RateLimitError``, ``APIConnectionError``, ``APIError``).  Rather
than adding provider-specific exception handling to the core retry loop,
non-OpenAI adapters translate their SDK exceptions into these lightweight
shims at the adapter boundary.

``VisionClient`` catches ``ProviderRateLimitError``, ``ProviderServerError``,
and ``ProviderConnectionError`` in addition to the original OpenAI types.
"""


class ProviderRateLimitError(Exception):
    """Rate limit exceeded — should be retried with exponential backoff."""


class ProviderServerError(Exception):
    """Transient 5xx server error — should be retried with exponential backoff."""

    # Mirror the OpenAI APIError interface so retry code can read status_code
    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderConnectionError(Exception):
    """Network connection error — should be retried with exponential backoff."""
