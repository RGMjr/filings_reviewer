"""
Tests for HTTP client abstraction.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from src.infra.http_client import HTTPResponse, RequestsHTTPClient


class TestHTTPResponse:
    """Tests for HTTPResponse dataclass."""

    def test_http_response_creation(self):
        """Test HTTPResponse stores all fields correctly."""
        response = HTTPResponse(
            status_code=200,
            content=b'{"key": "value"}',
            headers={"Content-Type": "application/json"},
            url="https://example.com/api",
            elapsed_seconds=0.123,
        )

        assert response.status_code == 200
        assert response.content == b'{"key": "value"}'
        assert response.headers == {"Content-Type": "application/json"}
        assert response.url == "https://example.com/api"
        assert response.elapsed_seconds == 0.123


class TestRequestsHTTPClient:
    """Tests for RequestsHTTPClient implementation."""

    def test_initialization_sets_user_agent(self):
        """Test client sets User-Agent header on session."""
        client = RequestsHTTPClient(user_agent="TestBot/1.0 test@example.com")

        assert "User-Agent" in client._session.headers
        assert client._session.headers["User-Agent"] == "TestBot/1.0 test@example.com"

    @patch("requests.Session.get")
    def test_successful_get_request(self, mock_get):
        """Test successful GET request returns HTTPResponse."""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"response body"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.url = "https://example.com/page"
        mock_get.return_value = mock_response

        client = RequestsHTTPClient(user_agent="TestBot/1.0")
        result = client.get("https://example.com/page")

        # Verify request made
        mock_get.assert_called_once_with(
            "https://example.com/page", headers=None, timeout=10.0, allow_redirects=True
        )

        # Verify response
        assert isinstance(result, HTTPResponse)
        assert result.status_code == 200
        assert result.content == b"response body"
        assert result.headers == {"Content-Type": "text/html"}
        assert result.url == "https://example.com/page"
        assert result.elapsed_seconds >= 0

    @patch("requests.Session.get")
    def test_get_with_custom_headers_and_timeout(self, mock_get):
        """Test GET request with custom headers and timeout."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"ok"
        mock_response.headers = {}
        mock_response.url = "https://api.example.com"
        mock_get.return_value = mock_response

        client = RequestsHTTPClient(user_agent="TestBot/1.0")
        custom_headers = {"Authorization": "Bearer token123"}
        result = client.get("https://api.example.com", headers=custom_headers, timeout=30.0)

        # Verify headers and timeout passed
        mock_get.assert_called_once_with(
            "https://api.example.com", headers=custom_headers, timeout=30.0, allow_redirects=True
        )

        assert result.status_code == 200

    @patch("requests.Session.get")
    def test_4xx_error_raises_http_error(self, mock_get):
        """Test 4xx response raises requests.HTTPError."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        client = RequestsHTTPClient(user_agent="TestBot/1.0")

        with pytest.raises(requests.HTTPError, match="404"):
            client.get("https://example.com/missing")

    @patch("requests.Session.get")
    def test_5xx_error_raises_http_error(self, mock_get):
        """Test 5xx response raises requests.HTTPError."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Internal Server Error")
        mock_get.return_value = mock_response

        client = RequestsHTTPClient(user_agent="TestBot/1.0")

        with pytest.raises(requests.HTTPError, match="500"):
            client.get("https://example.com/error")

    @patch("requests.Session.get")
    def test_timeout_raises_timeout_error(self, mock_get):
        """Test request timeout raises TimeoutError."""
        mock_get.side_effect = requests.Timeout("Connection timed out")

        client = RequestsHTTPClient(user_agent="TestBot/1.0")

        with pytest.raises(TimeoutError, match="timed out after 10.0s"):
            client.get("https://slow.example.com")

    @patch("requests.Session.get")
    def test_network_error_raises_io_error(self, mock_get):
        """Test network errors raise IOError."""
        mock_get.side_effect = requests.ConnectionError("Connection refused")

        client = RequestsHTTPClient(user_agent="TestBot/1.0")

        with pytest.raises(IOError, match="Network error"):
            client.get("https://unreachable.example.com")

    @patch("requests.Session.get")
    def test_elapsed_time_measured(self, mock_get):
        """Test elapsed time is measured accurately."""
        import time

        def slow_response(*args, **kwargs):
            time.sleep(0.05)  # 50ms delay
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.content = b"ok"
            mock_response.headers = {}
            mock_response.url = args[0]
            return mock_response

        mock_get.side_effect = slow_response

        client = RequestsHTTPClient(user_agent="TestBot/1.0")
        result = client.get("https://example.com")

        # Should have taken at least 50ms
        assert result.elapsed_seconds >= 0.05
        assert result.elapsed_seconds < 1.0  # But less than 1 second
