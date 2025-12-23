"""
Connection pool management for PostgreSQL.

Provides connection pooling via psycopg_pool to reuse database connections
instead of creating new ones for each operation. This significantly reduces
connection overhead (~150ms/query to ~5ms/query).

Usage:
    # For Flask apps - pool is created at startup and passed to DatabaseAdapter
    pool = create_pool(DATABASE_URL)
    adapter = DatabaseAdapter(DATABASE_URL, pool=pool)

    # For scripts - use the shared singleton pool
    adapter = create_pooled_adapter()  # Uses get_shared_pool() internally

Configuration via environment variables:
    DB_POOL_MIN_SIZE: Minimum connections to keep open (default: 2)
    DB_POOL_MAX_SIZE: Maximum connections in pool (default: 10)
    DB_POOL_TIMEOUT: Seconds to wait for available connection (default: 30)
    DB_POOL_MAX_IDLE: Seconds before idle connection is closed (default: 300)
    DB_POOL_RECONNECT_TIMEOUT: Seconds to attempt reconnection (default: 300)
"""

import atexit
import logging
import os
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from collections.abc import Callable

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.infra.exceptions import PoolExecutionError, PoolTimeoutError, TaskFailure

logger = logging.getLogger(__name__)

# Module-level singleton pool with thread-safe access
_shared_pool: ConnectionPool | None = None
_shared_pool_conninfo: str | None = None
_shared_pool_lock = threading.Lock()


@dataclass
class PoolHealthReport:
    """Health check report for connection pool.

    Attributes:
        is_healthy: True if pool is working correctly
        total_connections: Total connections in pool
        idle_connections: Connections available for use
        active_connections: Connections currently in use
        test_query_elapsed: Time taken for test query (seconds)
        timestamp: When health check was performed
        error: Error message if health check failed
    """

    is_healthy: bool
    total_connections: int
    idle_connections: int
    active_connections: int
    test_query_elapsed: float | None = None
    timestamp: datetime = None
    error: str | None = None

    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()


def execute_batch(
    tasks: list[Callable],
    *,
    max_workers: int | None = None,
    timeout: float | None = None,
    task_descriptions: list[str] | None = None,
    fail_fast: bool = True,
) -> list[Any]:
    """Execute tasks concurrently using ThreadPoolExecutor with fail-fast error handling.

    This function provides structured error handling for concurrent task execution:
    - Tracks failures with detailed context (task index, description, exception, traceback)
    - Cancels remaining tasks on first failure when fail_fast=True
    - Raises PoolExecutionError with comprehensive error details
    - Supports timeout for overall execution

    Args:
        tasks: List of callables to execute (no arguments)
        max_workers: Maximum number of worker threads (default: min(32, len(tasks)))
        timeout: Optional timeout in seconds for all tasks to complete
        task_descriptions: Optional human-readable descriptions for each task
        fail_fast: If True, cancel remaining tasks on first failure (default: True)

    Returns:
        List of results in same order as input tasks

    Raises:
        PoolExecutionError: If any tasks fail (includes failure details)
        PoolTimeoutError: If execution exceeds timeout

    Example:
        def task1(): return "result1"
        def task2(): return "result2"

        results = execute_batch(
            [task1, task2],
            task_descriptions=["Process filing 1", "Process filing 2"],
            timeout=60.0
        )
    """
    if not tasks:
        return []

    if task_descriptions is None:
        task_descriptions = [f"Task {i}" for i in range(len(tasks))]

    if len(task_descriptions) != len(tasks):
        raise ValueError(
            f"task_descriptions length ({len(task_descriptions)}) must match tasks length ({len(tasks)})"
        )

    # Determine worker count
    if max_workers is None:
        max_workers = min(32, len(tasks))

    results: list[Any] = [None] * len(tasks)
    failures: list[TaskFailure] = []
    future_to_index: dict[Future, int] = {}

    start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            for i, task in enumerate(tasks):
                future = executor.submit(task)
                future_to_index[future] = i

            # Collect results as they complete
            completed_count = 0

            for future in as_completed(future_to_index.keys(), timeout=timeout):
                task_index = future_to_index[future]
                task_desc = task_descriptions[task_index]

                try:
                    result = future.result()
                    results[task_index] = result
                    completed_count += 1

                except Exception as e:
                    # Record failure
                    failure = TaskFailure(
                        task_index=task_index,
                        task_description=task_desc,
                        exception=e,
                        traceback_str=traceback.format_exc(),
                    )
                    failures.append(failure)

                    logger.error(
                        f"Task {task_index} ({task_desc}) failed: {type(e).__name__}: {e}"
                    )

                    if fail_fast:
                        # Cancel remaining futures
                        for remaining_future in future_to_index.keys():
                            if not remaining_future.done():
                                remaining_future.cancel()

                        # Raise immediately
                        raise PoolExecutionError(
                            failures=failures,
                            completed_count=completed_count,
                            total_count=len(tasks),
                            partial_results=None,  # Don't return partial results in fail-fast mode
                        )

            # If we reach here without fail_fast or all succeeded
            if failures:
                raise PoolExecutionError(
                    failures=failures,
                    completed_count=completed_count,
                    total_count=len(tasks),
                    partial_results=results,  # Return partial results when not fail-fast
                )

            return results

    except TimeoutError as e:
        # Timeout occurred - cancel remaining tasks
        elapsed = time.time() - start_time
        logger.error(f"Batch execution timed out after {elapsed:.1f}s (limit: {timeout}s)")

        for future in future_to_index.keys():
            if not future.done():
                future.cancel()

        # Create timeout failure
        timeout_failure = TaskFailure(
            task_index=-1,
            task_description="Batch timeout",
            exception=e,
            traceback_str=traceback.format_exc(),
        )
        failures.append(timeout_failure)

        raise PoolTimeoutError(
            failures=failures,
            completed_count=sum(1 for r in results if r is not None),
            total_count=len(tasks),
        )


def get_pool_config() -> dict[str, Any]:
    """
    Load pool configuration from environment variables.

    Returns:
        Dict with pool configuration parameters.
    """
    return {
        "min_size": int(os.environ.get("DB_POOL_MIN_SIZE", "2")),
        "max_size": int(os.environ.get("DB_POOL_MAX_SIZE", "10")),
        "timeout": float(os.environ.get("DB_POOL_TIMEOUT", "30")),
        "max_idle": float(os.environ.get("DB_POOL_MAX_IDLE", "300")),
        "reconnect_timeout": float(os.environ.get("DB_POOL_RECONNECT_TIMEOUT", "300")),
    }


def create_pool(
    connection_string: str,
    min_size: int | None = None,
    max_size: int | None = None,
    timeout: float | None = None,
    max_idle: float | None = None,
    reconnect_timeout: float | None = None,
    open_pool: bool = True,
) -> ConnectionPool:
    """
    Create a new connection pool.

    Args:
        connection_string: PostgreSQL connection string.
        min_size: Minimum connections to keep open (default from env).
        max_size: Maximum connections in pool (default from env).
        timeout: Seconds to wait for available connection (default from env).
        max_idle: Seconds before idle connection is closed (default from env).
        reconnect_timeout: Seconds to attempt reconnection (default from env).
        open_pool: If True, open the pool immediately (default True).

    Returns:
        Configured ConnectionPool instance.

    Example:
        pool = create_pool("postgresql://user:pass@localhost/db")
        with pool.connection() as conn:
            conn.execute("SELECT 1")
    """
    config = get_pool_config()

    # Override defaults with any explicitly provided values
    if min_size is not None:
        config["min_size"] = min_size
    if max_size is not None:
        config["max_size"] = max_size
    if timeout is not None:
        config["timeout"] = timeout
    if max_idle is not None:
        config["max_idle"] = max_idle
    if reconnect_timeout is not None:
        config["reconnect_timeout"] = reconnect_timeout

    pool = ConnectionPool(
        conninfo=connection_string,
        min_size=config["min_size"],
        max_size=config["max_size"],
        timeout=config["timeout"],
        max_idle=config["max_idle"],
        reconnect_timeout=config["reconnect_timeout"],
        kwargs={"row_factory": dict_row},  # Applied to all connections
        open=open_pool,
    )

    logger.info(
        f"Connection pool created: min_size={config['min_size']}, "
        f"max_size={config['max_size']}, timeout={config['timeout']}s"
    )

    return pool


def get_shared_pool(connection_string: str) -> ConnectionPool:
    """
    Get or create the shared singleton connection pool.

    The shared pool is intended for use by scripts that want connection
    pooling without managing pool lifecycle themselves. The pool is
    automatically closed at process exit via atexit handler.

    This function is thread-safe and can be called from multiple threads
    concurrently.

    Args:
        connection_string: PostgreSQL connection string.

    Returns:
        Shared ConnectionPool instance.

    Raises:
        ValueError: If called with different connection string than existing pool.

    Example:
        pool = get_shared_pool(os.environ["DATABASE_URL"])
        adapter = DatabaseAdapter(url, pool=pool)
    """
    global _shared_pool, _shared_pool_conninfo

    # Fast path: pool already exists (no lock needed for read)
    if _shared_pool is not None:
        if _shared_pool_conninfo != connection_string:
            raise ValueError(
                "Shared pool already exists with different connection string. "
                "Call close_shared_pool() first to create a new pool."
            )
        return _shared_pool

    # Slow path: need to create pool (with lock for thread safety)
    with _shared_pool_lock:
        # Double-check after acquiring lock (another thread may have created it)
        if _shared_pool is not None:
            if _shared_pool_conninfo != connection_string:
                raise ValueError(
                    "Shared pool already exists with different connection string. "
                    "Call close_shared_pool() first to create a new pool."
                )
            return _shared_pool

        # Create new shared pool
        _shared_pool = create_pool(connection_string)
        _shared_pool_conninfo = connection_string

        # Register cleanup at process exit
        atexit.register(close_shared_pool)

        logger.info("Shared connection pool created")
        return _shared_pool


def close_shared_pool() -> None:
    """
    Close the shared singleton connection pool with instrumented logging.

    Safe to call multiple times or when no pool exists.
    Called automatically at process exit if pool was created.
    This function is thread-safe.
    """
    global _shared_pool, _shared_pool_conninfo

    with _shared_pool_lock:
        if _shared_pool is not None:
            try:
                # Get final stats before closing
                try:
                    stats = get_pool_stats(_shared_pool)
                    logger.info(
                        f"Closing shared pool: {stats['pool_size']} connections "
                        f"({stats['pool_available']} idle, {stats['requests_waiting']} waiting)"
                    )
                except Exception:
                    logger.info("Closing shared connection pool")

                # Measure close time
                start_time = time.time()
                _shared_pool.close()
                elapsed = time.time() - start_time

                logger.info(f"Shared connection pool closed successfully in {elapsed:.3f}s")

            except Exception as e:
                logger.error(
                    f"Error closing shared pool: {type(e).__name__}: {e}. "
                    "Pool resources may not be fully released."
                )

            finally:
                _shared_pool = None
                _shared_pool_conninfo = None


def get_pool_stats(pool: ConnectionPool) -> dict[str, Any]:
    """
    Get statistics about a connection pool.

    Useful for monitoring and debugging pool behavior.

    Args:
        pool: ConnectionPool instance to get stats for.

    Returns:
        Dict with pool statistics including:
        - pool_size: Current number of connections
        - pool_available: Connections available for use
        - requests_waiting: Requests waiting for a connection
        - pool_min: Configured minimum size
        - pool_max: Configured maximum size
    """
    stats = pool.get_stats()
    return {
        "pool_size": stats.get("pool_size", 0),
        "pool_available": stats.get("pool_available", 0),
        "requests_waiting": stats.get("requests_waiting", 0),
        "pool_min": pool.min_size,
        "pool_max": pool.max_size,
    }


def check_pool_health(pool: ConnectionPool) -> PoolHealthReport:
    """
    Check the health of a connection pool.

    Attempts to get a connection from the pool and execute a simple query.

    Args:
        pool: ConnectionPool instance to check.

    Returns:
        PoolHealthReport with health status and pool statistics.
    """
    try:
        start_time = time.time()

        with pool.connection() as conn:
            conn.execute("SELECT 1")

        elapsed = time.time() - start_time

        stats = get_pool_stats(pool)

        return PoolHealthReport(
            is_healthy=True,
            total_connections=stats["pool_size"],
            idle_connections=stats["pool_available"],
            active_connections=stats["pool_size"] - stats["pool_available"],
            test_query_elapsed=elapsed,
            error=None,
        )

    except Exception as e:
        logger.error(f"Pool health check failed: {type(e).__name__}: {e}")

        # Try to get stats even if health check failed
        try:
            stats = get_pool_stats(pool)
            total = stats["pool_size"]
            idle = stats["pool_available"]
            active = total - idle
        except Exception:
            total = idle = active = 0

        return PoolHealthReport(
            is_healthy=False,
            total_connections=total,
            idle_connections=idle,
            active_connections=active,
            test_query_elapsed=None,
            error=str(e),
        )
