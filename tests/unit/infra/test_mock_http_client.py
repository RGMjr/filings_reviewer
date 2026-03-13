"""
Tests for MockHTTPClient.
"""

import pytest
import requests

from src.infra.http_client import HTTPResponse
from tests.unit.infra.mock_http_client import MockHTTPClient


class TestMockHTTPClient:
    """Tests for MockHTTPClient functionality."""

    def test_predefined_response(self):
        """Test mock returns predefined response for URL."""
        response = HTTPResponse(status_code=200, content=b"test data", headers={}, url="https://example.com", elapsed_seconds=0.1)

        mock = MockHTTPClient(responses={"https://example.com": response})

        result = mock.get("https://example.com")

        assert result is response
        assert result.status_code == 200
        assert result.content == b"test data"

    def test_predefined_failure(self):
        """Test mock raises predefined exception for URL."""
        mock = MockHTTPClient(failures={"https://error.com": requests.HTTPError("500 Server Error")})

        with pytest.raises(requests.HTTPError, match="500"):
            mock.get("https://error.com")

    def test_request_history_tracking(self):
        """Test mock tracks request history."""
        mock = MockHTTPClient()
        mock.add_response("https://example.com/1", 200, b"ok")
        mock.add_response("https://example.com/2", 200, b"ok")

        mock.get("https://example.com/1")
        mock.get("https://example.com/2")
        mock.get("https://example.com/1")  # Duplicate

        assert mock.request_history == ["https://example.com/1", "https://example.com/2", "https://example.com/1"]
        assert mock.get_request_count() == 3
        assert mock.get_request_count("https://example.com/1") == 2
        assert mock.get_request_count("https://example.com/2") == 1

    def test_response_factory(self):
        """Test mock uses response factory for unmocked URLs."""

        def factory(url: str) -> HTTPResponse:
            return HTTPResponse(status_code=200, content=f"Dynamic: {url}".encode(), headers={}, url=url, elapsed_seconds=0.1)

        mock = MockHTTPClient(response_factory=factory)

        result = mock.get("https://dynamic.com/page")

        assert result.status_code == 200
        assert result.content == b"Dynamic: https://dynamic.com/page"
        assert result.url == "https://dynamic.com/page"

    def test_no_mock_raises_error(self):
        """Test mock raises HTTPError if no response configured."""
        mock = MockHTTPClient()

        with pytest.raises(requests.HTTPError, match="No mock response"):
            mock.get("https://unmocked.com")

    def test_add_response_helper(self):
        """Test add_response helper creates HTTPResponse."""
        mock = MockHTTPClient()
        mock.add_response("https://example.com/api", 201, b'{"created": true}', headers={"Content-Type": "application/json"})

        result = mock.get("https://example.com/api")

        assert result.status_code == 201
        assert result.content == b'{"created": true}'
        assert result.headers == {"Content-Type": "application/json"}

    def test_add_failure_helper(self):
        """Test add_failure helper configures exception."""
        mock = MockHTTPClient()
        mock.add_failure("https://timeout.com", TimeoutError("Connection timed out"))

        with pytest.raises(TimeoutError, match="timed out"):
            mock.get("https://timeout.com")

    def test_clear_history(self):
        """Test clear_history removes all tracked requests."""
        mock = MockHTTPClient()
        mock.add_response("https://example.com", 200, b"ok")

        mock.get("https://example.com")
        mock.get("https://example.com")

        assert len(mock.request_history) == 2

        mock.clear_history()

        assert len(mock.request_history) == 0
        assert mock.get_request_count() == 0
