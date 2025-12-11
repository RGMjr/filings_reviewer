"""
Infrastructure exceptions.

Custom exception hierarchy for infrastructure layer modules (pool, sec_client, etc.).
Provides specific exception types for better error handling and debugging.
"""

import traceback
from dataclasses import dataclass
from typing import Any, List, Optional


class InfrastructureError(Exception):
    """Base exception for infrastructure layer errors."""

    pass


class HTTPError(InfrastructureError):
    """HTTP request failures.

    Raised when HTTP requests fail for network or protocol reasons.
    """

    def __init__(self, message: str, status_code: Optional[int] = None, url: Optional[str] = None):
        """Initialize HTTP error.

        Args:
            message: Error description
            status_code: HTTP status code if available
            url: Request URL if available
        """
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class SECClientError(InfrastructureError):
    """SEC client errors.

    Base exception for SEC API client errors.
    """

    pass


class SECRateLimitError(SECClientError):
    """Raised when SEC rate limit is exceeded (429 response).

    The SEC EDGAR API enforces rate limits (10 requests/second).
    This exception indicates the rate limit was exceeded.
    """

    pass


class SECDataError(SECClientError):
    """Raised when SEC returns malformed or unexpected data.

    Examples:
    - Malformed JSON responses
    - Missing required fields in JSON
    - Invalid data types
    """

    def __init__(self, message: str, url: str, response_preview: str):
        """Initialize SEC data error.

        Args:
            message: Error description
            url: SEC API URL that returned bad data
            response_preview: First 200 chars of response for debugging
        """
        super().__init__(message)
        self.url = url
        self.response_preview = response_preview


@dataclass
class TaskFailure:
    """Details of a failed concurrent task.

    Attributes:
        task_index: Index of failed task in original list
        task_description: Human-readable task description
        exception: Exception that caused failure
        traceback_str: String representation of traceback
    """

    task_index: int
    task_description: str
    exception: Exception
    traceback_str: str


class PoolExecutionError(InfrastructureError):
    """Raised when pool execution fails.

    Contains detailed information about task failures during concurrent execution.

    Attributes:
        failures: List of TaskFailure objects with failure details
        completed_count: Number of tasks that completed successfully
        total_count: Total number of tasks attempted
        partial_results: Optional list of results from successful tasks (None if fail_fast=True)
    """

    def __init__(
        self,
        failures: List[TaskFailure],
        completed_count: int,
        total_count: int,
        partial_results: Optional[List[Any]] = None,
    ):
        """Initialize pool execution error.

        Args:
            failures: List of failed tasks with details
            completed_count: Number of successful tasks
            total_count: Total tasks attempted
            partial_results: Results from successful tasks (if fail_fast=False)
        """
        self.failures = failures
        self.completed_count = completed_count
        self.total_count = total_count
        self.partial_results = partial_results

        summary = f"{len(failures)} of {total_count} tasks failed ({completed_count} completed)"
        super().__init__(summary)

    def get_error_summary(self, max_errors: int = 5) -> str:
        """Generate human-readable error summary.

        Args:
            max_errors: Maximum number of errors to include in summary

        Returns:
            Multi-line string with error details
        """
        lines = [f"Pool execution failed: {len(self.failures)} errors out of {self.total_count} tasks"]

        for i, failure in enumerate(self.failures[:max_errors]):
            lines.append(
                f"  Task {failure.task_index} ({failure.task_description}): "
                f"{type(failure.exception).__name__}: {failure.exception}"
            )

        if len(self.failures) > max_errors:
            lines.append(f"  ... and {len(self.failures) - max_errors} more errors")

        return "\n".join(lines)


class PoolTimeoutError(PoolExecutionError):
    """Raised when pool execution exceeds timeout.

    Subclass of PoolExecutionError for timeout-specific failures.
    """

    pass
