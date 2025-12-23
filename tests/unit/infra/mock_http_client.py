"""
Mock HTTP client for testing.

Provides a configurable mock implementation of the HTTPClient protocol
for use in tests. Supports predefined responses, simulated failures,
and request history tracking.
"""

from dataclasses import dataclass, field
from collections.abc import Callable

import requests

from src.infra.http_client import HTTPResponse


@dataclass
class MockHTTPClient:
    """Mock HTTP client for testing.

    This class implements the HTTPClient protocol and can be used as a drop-in
    replacement for RequestsHTTPClient in tests.

    Features:
    - Predefined responses by URL
    - Simulated failures (timeout, network error, 4xx/5xx)
    - Request history tracking
    - Response factory for dynamic responses

    Example:
        >>> mock = MockHTTPClient(responses={
        ...     "https://api.example.com/data": HTTPResponse(
        ...         status_code=200,
        ...         content=b'{"result": "ok"}',
        ...         headers={},
        ...         url="https://api.example.com/data",
        ...         elapsed_seconds=0.1
        ...     )
        ... })
        >>> response = mock.get("https://api.example.com/data")
        >>> assert response.status_code == 200
    """

    responses: dict[str, HTTPResponse] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    request_history: list[str] = field(default_factory=list)
    response_factory: Callable[[str], HTTPResponse] | None = None

    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> HTTPResponse:
        """Mock GET request.

        Args:
            url: URL to request
            headers: Optional headers (tracked but not used)
            timeout: Timeout value (tracked but not used)

        Returns:
            HTTPResponse from predefined responses or response factory

        Raises:
            Exception from failures dict, or requests.HTTPError if no mock found
        """
        # Track request
        self.request_history.append(url)

        # Check for configured failure
        if url in self.failures:
            raise self.failures[url]

        # Check for predefined response
        if url in self.responses:
            return self.responses[url]

        # Use factory if available
        if self.response_factory:
            return self.response_factory(url)

        # Default: raise 404
        raise requests.HTTPError(f"No mock response configured for {url}")

    def add_response(self, url: str, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> None:
        """Helper to add a response.

        Args:
            url: URL to match
            status_code: HTTP status code
            content: Response body
            headers: Response headers (defaults to empty dict)
        """
        self.responses[url] = HTTPResponse(
            status_code=status_code, content=content, headers=headers or {}, url=url, elapsed_seconds=0.1
        )

    def add_failure(self, url: str, exception: Exception) -> None:
        """Helper to add a failure.

        Args:
            url: URL to match
            exception: Exception to raise when URL is requested
        """
        self.failures[url] = exception

    def clear_history(self) -> None:
        """Clear request history."""
        self.request_history.clear()

    def get_request_count(self, url: str | None = None) -> int:
        """Get count of requests.

        Args:
            url: If provided, count requests to this URL only.
                If None, count all requests.

        Returns:
            Number of matching requests
        """
        if url is None:
            return len(self.request_history)
        return self.request_history.count(url)
