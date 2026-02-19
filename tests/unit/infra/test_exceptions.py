"""
Tests for infrastructure exceptions.
"""

from src.infra.exceptions import (
    HTTPError,
    InfrastructureError,
    PoolExecutionError,
    PoolTimeoutError,
    SECClientError,
    SECDataError,
    SECRateLimitError,
    TaskFailure,
)


class TestHTTPError:
    """Tests for HTTPError exception."""

    def test_http_error_with_status_and_url(self):
        """Test HTTPError stores status code and URL."""
        error = HTTPError("Request failed", status_code=500, url="https://example.com/api")

        assert str(error) == "Request failed"
        assert error.status_code == 500
        assert error.url == "https://example.com/api"
        assert isinstance(error, InfrastructureError)

    def test_http_error_without_optional_fields(self):
        """Test HTTPError works without status/URL."""
        error = HTTPError("Network error")

        assert str(error) == "Network error"
        assert error.status_code is None
        assert error.url is None


class TestSECClientErrors:
    """Tests for SEC client exceptions."""

    def test_sec_rate_limit_error(self):
        """Test SECRateLimitError is subclass of SECClientError."""
        error = SECRateLimitError("Rate limit exceeded")

        assert str(error) == "Rate limit exceeded"
        assert isinstance(error, SECClientError)
        assert isinstance(error, InfrastructureError)

    def test_sec_data_error_with_context(self):
        """Test SECDataError stores URL and response preview."""
        error = SECDataError(
            "Invalid JSON",
            url="https://data.sec.gov/submissions/CIK0001234567.json",
            response_preview="not valid json{",
        )

        assert str(error) == "Invalid JSON"
        assert error.url == "https://data.sec.gov/submissions/CIK0001234567.json"
        assert error.response_preview == "not valid json{"
        assert isinstance(error, SECClientError)


class TestPoolExecutionError:
    """Tests for pool execution exceptions."""

    def test_task_failure_dataclass(self):
        """Test TaskFailure stores failure details."""
        exc = ValueError("Invalid input")
        failure = TaskFailure(
            task_index=3,
            task_description="Process filing 1234",
            exception=exc,
            traceback_str="Traceback...",
        )

        assert failure.task_index == 3
        assert failure.task_description == "Process filing 1234"
        assert failure.exception is exc
        assert failure.traceback_str == "Traceback..."

    def test_pool_execution_error_summary(self):
        """Test PoolExecutionError generates readable error message."""
        failures = [
            TaskFailure(0, "Task 0", ValueError("Error 0"), ""),
            TaskFailure(2, "Task 2", TypeError("Error 2"), ""),
        ]
        error = PoolExecutionError(failures=failures, completed_count=8, total_count=10)

        assert "2 of 10 tasks failed" in str(error)
        assert error.failures == failures
        assert error.completed_count == 8
        assert error.total_count == 10
        assert error.partial_results is None

    def test_pool_execution_error_summary_output(self):
        """Test PoolExecutionError.get_error_summary() format."""
        failures = [
            TaskFailure(0, "Extract filing 1", ValueError("Invalid CIK"), ""),
            TaskFailure(5, "Extract filing 6", OSError("File not found"), ""),
            TaskFailure(7, "Extract filing 8", KeyError("Missing field"), ""),
        ]
        error = PoolExecutionError(
            failures=failures,
            completed_count=7,
            total_count=10,
            partial_results=[1, 2, None, 4, 5, None, 7, None, 9, 10],
        )

        summary = error.get_error_summary(max_errors=2)

        assert "Pool execution failed: 3 errors" in summary
        assert "Task 0 (Extract filing 1): ValueError: Invalid CIK" in summary
        assert "Task 5 (Extract filing 6): OSError: File not found" in summary
        assert "... and 1 more errors" in summary

    def test_pool_timeout_error_is_subclass(self):
        """Test PoolTimeoutError is subclass of PoolExecutionError."""
        failure = TaskFailure(-1, "Timeout", TimeoutError("Exceeded 60s"), "")
        error = PoolTimeoutError(failures=[failure], completed_count=5, total_count=10)

        assert isinstance(error, PoolExecutionError)
        assert isinstance(error, InfrastructureError)
        assert len(error.failures) == 1


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_all_infrastructure_errors_inherit_from_base(self):
        """Test all custom exceptions inherit from InfrastructureError."""
        exceptions = [
            HTTPError("test"),
            SECClientError("test"),
            SECRateLimitError("test"),
            SECDataError("test", "url", "preview"),
            PoolExecutionError([], 0, 0),
            PoolTimeoutError([], 0, 0),
        ]

        for exc in exceptions:
            assert isinstance(exc, InfrastructureError)
            assert isinstance(exc, Exception)
