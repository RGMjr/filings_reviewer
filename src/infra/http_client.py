"""
HTTP client abstraction for testability.

Provides a Protocol-based abstraction over HTTP requests to enable mocking and testing.
The production implementation uses the requests library.
"""

import time
from dataclasses import dataclass
from typing import Protocol

import requests


@dataclass
class HTTPResponse:
    """Standardized HTTP response.

    Attributes:
        status_code: HTTP status code (200, 404, 500, etc.)
        content: Response body as bytes
        headers: Response headers as dict
        url: Final URL (after redirects)
        elapsed_seconds: Time taken for request in seconds
    """

    status_code: int
    content: bytes
    headers: dict[str, str]
    url: str
    elapsed_seconds: float


class HTTPClient(Protocol):
    """Protocol for HTTP clients.

    This defines the interface that SEC client and other modules expect.
    Implementations must provide the get() method.

    This is a Protocol (PEP 544) - any class with a compatible get() method
    automatically satisfies this interface without explicit inheritance.
    """

    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> HTTPResponse:
        """Perform GET request.

        Args:
            url: Full URL to request
            headers: Optional HTTP headers to include
            timeout: Request timeout in seconds

        Returns:
            HTTPResponse with status, content, headers, URL, and timing

        Raises:
            requests.HTTPError: For 4xx/5xx HTTP error responses
            TimeoutError: For request timeout
            IOError: For network/connection errors
        """
        ...


class RequestsHTTPClient:
    """Production HTTP client implementation using requests library.

    This is the default HTTP client used in production. It wraps the requests
    library with our standardized HTTPResponse format.
    """

    def __init__(self, user_agent: str):
        """Initialize HTTP client with user agent.

        Args:
            user_agent: User-Agent header value for all requests
        """
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> HTTPResponse:
        """Perform GET request using requests library.

        Args:
            url: Full URL to request
            headers: Optional additional headers (merged with session headers)
            timeout: Request timeout in seconds

        Returns:
            HTTPResponse object

        Raises:
            requests.HTTPError: For 4xx/5xx responses
            TimeoutError: For timeout
            IOError: For network errors
        """
        start_time = time.time()

        try:
            response = self._session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            elapsed = time.time() - start_time

            # Raise for 4xx/5xx status codes
            response.raise_for_status()

            return HTTPResponse(
                status_code=response.status_code,
                content=response.content,
                headers=dict(response.headers),
                url=response.url,
                elapsed_seconds=elapsed,
            )

        except requests.Timeout as e:
            raise TimeoutError(f"Request timed out after {timeout}s: {url}") from e

        except requests.HTTPError:
            # Re-raise HTTP errors (4xx/5xx) without conversion
            raise

        except requests.RequestException as e:
            # Convert other requests exceptions to IOError for network issues
            raise IOError(f"Network error requesting {url}: {e}") from e
