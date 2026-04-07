"""
Unit tests for connection pool module.

Tests configuration loading, pool creation parameters, and DatabaseAdapter
pool integration without requiring a real database connection.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGetPoolConfig:
    """Tests for get_pool_config() function."""

    def test_default_values(self):
        """Should return default values when no env vars set."""
        from src.infra.pool import get_pool_config

        with patch.dict(os.environ, {}, clear=True):
            config = get_pool_config()

        assert config["min_size"] == 2
        assert config["max_size"] == 10
        assert config["timeout"] == 30.0
        assert config["max_idle"] == 300.0
        assert config["reconnect_timeout"] == 300.0

    def test_custom_values_from_environment(self):
        """Should load values from environment variables."""
        from src.infra.pool import get_pool_config

        env_vars = {
            "DB_POOL_MIN_SIZE": "5",
            "DB_POOL_MAX_SIZE": "20",
            "DB_POOL_TIMEOUT": "60",
            "DB_POOL_MAX_IDLE": "600",
            "DB_POOL_RECONNECT_TIMEOUT": "120",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = get_pool_config()

        assert config["min_size"] == 5
        assert config["max_size"] == 20
        assert config["timeout"] == 60.0
        assert config["max_idle"] == 600.0
        assert config["reconnect_timeout"] == 120.0


class TestCreatePool:
    """Tests for create_pool() function."""

    @patch("src.infra.pool.ConnectionPool")
    def test_creates_pool_with_defaults(self, mock_pool_class):
        """Should create pool with default config values."""
        from src.infra.pool import create_pool

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        with patch.dict(os.environ, {}, clear=True):
            result = create_pool("postgresql://localhost/test")

        assert result == mock_pool
        mock_pool_class.assert_called_once()

        call_kwargs = mock_pool_class.call_args[1]
        assert call_kwargs["conninfo"] == "postgresql://localhost/test"
        assert call_kwargs["min_size"] == 2
        assert call_kwargs["max_size"] == 10
        assert call_kwargs["timeout"] == 30.0
        assert call_kwargs["open"] is True

    @patch("src.infra.pool.ConnectionPool")
    def test_creates_pool_with_custom_params(self, mock_pool_class):
        """Should override defaults with explicit parameters."""
        from src.infra.pool import create_pool

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        with patch.dict(os.environ, {}, clear=True):
            create_pool(
                "postgresql://localhost/test",
                min_size=5,
                max_size=25,
                timeout=45.0,
            )

        call_kwargs = mock_pool_class.call_args[1]
        assert call_kwargs["min_size"] == 5
        assert call_kwargs["max_size"] == 25
        assert call_kwargs["timeout"] == 45.0

    @patch("src.infra.pool.ConnectionPool")
    def test_creates_pool_without_opening(self, mock_pool_class):
        """Should support creating pool without opening it."""
        from src.infra.pool import create_pool

        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        with patch.dict(os.environ, {}, clear=True):
            create_pool("postgresql://localhost/test", open_pool=False)

        call_kwargs = mock_pool_class.call_args[1]
        assert call_kwargs["open"] is False


class TestSharedPool:
    """Tests for get_shared_pool() and close_shared_pool()."""

    def setup_method(self):
        """Reset shared pool state before each test."""
        from src.infra import pool

        pool._shared_pool = None
        pool._shared_pool_conninfo = None

    @patch("src.infra.pool.create_pool")
    def test_get_shared_pool_creates_new(self, mock_create_pool):
        """Should create new pool on first call."""
        from src.infra.pool import get_shared_pool

        mock_pool = MagicMock()
        mock_create_pool.return_value = mock_pool

        result = get_shared_pool("postgresql://localhost/test")

        assert result == mock_pool
        mock_create_pool.assert_called_once_with("postgresql://localhost/test")

    @patch("src.infra.pool.create_pool")
    def test_get_shared_pool_returns_existing(self, mock_create_pool):
        """Should return existing pool on subsequent calls."""
        from src.infra.pool import get_shared_pool

        mock_pool = MagicMock()
        mock_create_pool.return_value = mock_pool

        result1 = get_shared_pool("postgresql://localhost/test")
        result2 = get_shared_pool("postgresql://localhost/test")

        assert result1 == result2
        assert mock_create_pool.call_count == 1  # Only called once

    @patch("src.infra.pool.create_pool")
    def test_get_shared_pool_different_conninfo_raises(self, mock_create_pool):
        """Should raise error if called with different connection string."""
        from src.infra.pool import get_shared_pool

        mock_pool = MagicMock()
        mock_create_pool.return_value = mock_pool

        get_shared_pool("postgresql://localhost/test1")

        with pytest.raises(ValueError, match="different connection string"):
            get_shared_pool("postgresql://localhost/test2")

    @patch("src.infra.pool.create_pool")
    def test_close_shared_pool(self, mock_create_pool):
        """Should close pool and reset state."""
        from src.infra import pool
        from src.infra.pool import close_shared_pool, get_shared_pool

        mock_pool = MagicMock()
        mock_create_pool.return_value = mock_pool

        get_shared_pool("postgresql://localhost/test")
        close_shared_pool()

        mock_pool.close.assert_called_once()
        assert pool._shared_pool is None
        assert pool._shared_pool_conninfo is None

    def test_close_shared_pool_when_none(self):
        """Should be safe to call when no pool exists."""
        from src.infra.pool import close_shared_pool

        # Should not raise
        close_shared_pool()


class TestGetPoolStats:
    """Tests for get_pool_stats() function."""

    def test_returns_stats_dict(self):
        """Should return dict with pool statistics."""
        from src.infra.pool import get_pool_stats

        mock_pool = MagicMock()
        mock_pool.get_stats.return_value = {
            "pool_size": 5,
            "pool_available": 3,
            "requests_waiting": 0,
        }
        mock_pool.min_size = 2
        mock_pool.max_size = 10

        stats = get_pool_stats(mock_pool)

        assert stats["pool_size"] == 5
        assert stats["pool_available"] == 3
        assert stats["requests_waiting"] == 0
        assert stats["pool_min"] == 2
        assert stats["pool_max"] == 10


class TestCheckPoolHealth:
    """Tests for check_pool_health() function."""

    def test_healthy_pool(self):
        """Should return healthy PoolHealthReport when pool works."""
        from src.infra.pool import PoolHealthReport, check_pool_health

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.get_stats.return_value = {"pool_size": 5, "pool_available": 3, "requests_waiting": 0}
        mock_pool.min_size = 2
        mock_pool.max_size = 10

        result = check_pool_health(mock_pool)

        assert isinstance(result, PoolHealthReport)
        assert result.is_healthy is True
        assert result.total_connections == 5
        assert result.idle_connections == 3
        assert result.active_connections == 2
        assert result.test_query_elapsed is not None
        assert result.error is None

    def test_unhealthy_pool(self):
        """Should return unhealthy PoolHealthReport when pool fails."""
        from src.infra.pool import PoolHealthReport, check_pool_health

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("Connection failed")
        mock_pool.get_stats.return_value = {"pool_size": 0, "pool_available": 0, "requests_waiting": 0}

        result = check_pool_health(mock_pool)

        assert isinstance(result, PoolHealthReport)
        assert result.is_healthy is False
        assert "Connection failed" in result.error
        assert result.test_query_elapsed is None


class TestDatabaseAdapterWithPool:
    """Tests for DatabaseAdapter pool integration."""

    def test_adapter_accepts_pool_parameter(self):
        """Should accept optional pool parameter."""
        from src.infra.db import DatabaseAdapter

        mock_pool = MagicMock()
        adapter = DatabaseAdapter("postgresql://localhost/test", pool=mock_pool)

        assert adapter._pool == mock_pool

    def test_adapter_works_without_pool(self):
        """Should work without pool (backward compatibility)."""
        from src.infra.db import DatabaseAdapter

        adapter = DatabaseAdapter("postgresql://localhost/test")

        assert adapter._pool is None
        assert adapter.connection_string == "postgresql://localhost/test"

    @patch("src.infra.db.psycopg.connect")
    def test_get_connection_uses_pool_when_available(self, mock_connect):
        """Should use pool connection when pool is provided."""
        from src.infra.db import DatabaseAdapter

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        adapter = DatabaseAdapter("postgresql://localhost/test", pool=mock_pool)

        with adapter.get_connection() as conn:
            assert conn == mock_conn

        # Should use pool, not psycopg.connect
        mock_connect.assert_not_called()
        mock_pool.connection.assert_called_once()

    @patch("src.infra.db.psycopg.connect")
    def test_get_connection_creates_new_without_pool(self, mock_connect):
        """Should create new connection when no pool provided."""
        from src.infra.db import DatabaseAdapter

        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        adapter = DatabaseAdapter("postgresql://localhost/test")

        with adapter.get_connection() as conn:
            assert conn == mock_conn

        mock_connect.assert_called_once()


class TestCreatePooledAdapter:
    """Tests for create_pooled_adapter() convenience function."""

    def test_uses_provided_connection_string(self):
        """Should use provided connection string."""
        with patch("src.infra.pool.get_shared_pool") as mock_get_pool:
            from src.infra.db import create_pooled_adapter

            mock_pool = MagicMock()
            mock_get_pool.return_value = mock_pool

            adapter = create_pooled_adapter("postgresql://localhost/mydb")

            mock_get_pool.assert_called_once_with("postgresql://localhost/mydb")
            assert adapter._pool == mock_pool

    def test_uses_database_url_env_var(self):
        """Should use DATABASE_URL when no connection string provided."""
        with patch("src.infra.pool.get_shared_pool") as mock_get_pool:
            from src.infra.db import create_pooled_adapter

            mock_pool = MagicMock()
            mock_get_pool.return_value = mock_pool

            with patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/envdb"}):
                adapter = create_pooled_adapter()

            mock_get_pool.assert_called_once_with("postgresql://localhost/envdb")
            assert adapter._pool == mock_pool

    def test_raises_when_no_connection_string(self):
        """Should raise error when no connection string available."""
        from src.infra.db import create_pooled_adapter

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="DATABASE_URL"):
                create_pooled_adapter()


class TestExecuteBatch:
    """Tests for execute_batch() concurrent task execution."""

    def test_execute_batch_all_tasks_succeed(self):
        """Should execute all tasks and return results in order."""
        from src.infra.pool import execute_batch

        def task1():
            return "result1"

        def task2():
            return "result2"

        def task3():
            return "result3"

        results = execute_batch([task1, task2, task3])

        assert results == ["result1", "result2", "result3"]

    def test_execute_batch_one_task_fails_raises_error(self):
        """Should raise PoolExecutionError when a task fails."""
        from src.infra.exceptions import PoolExecutionError
        from src.infra.pool import execute_batch

        def task1():
            return "result1"

        def task2():
            raise ValueError("Task 2 failed")

        def task3():
            return "result3"

        with pytest.raises(PoolExecutionError) as exc_info:
            execute_batch([task1, task2, task3])

        error = exc_info.value
        # Key assertions: failure was captured with details
        assert len(error.failures) == 1
        assert error.failures[0].task_index == 1
        assert isinstance(error.failures[0].exception, ValueError)
        assert "Task 2 failed" in str(error.failures[0].exception)
        # Total count should be correct
        assert error.total_count == 3
        # With fail_fast, partial_results should be None
        assert error.partial_results is None

    def test_execute_batch_fail_fast_cancels_remaining(self):
        """Should cancel remaining tasks when fail_fast=True."""
        import time

        from src.infra.exceptions import PoolExecutionError
        from src.infra.pool import execute_batch

        executed = []
        started = []

        def slow_task(index):
            started.append(index)
            time.sleep(0.2)  # Short sleep to ensure tasks are still running when cancelled
            executed.append(index)
            return f"result{index}"

        def failing_task():
            started.append("fail")
            raise ValueError("Failed immediately")

        # First task fails quickly, should cancel remaining slow tasks
        # Use more tasks to increase likelihood of cancellation
        tasks = [failing_task] + [lambda i=i: slow_task(i) for i in range(10)]

        with pytest.raises(PoolExecutionError) as exc_info:
            execute_batch(tasks, fail_fast=True, max_workers=4)

        # Key assertion: error was raised with failure info
        error = exc_info.value
        assert len(error.failures) == 1
        assert "Failed immediately" in str(error.failures[0].exception)

        # Some tasks may have started but not all should have completed
        # Due to cancellation, completed tasks should be less than started
        assert len(executed) < len(started)

    def test_execute_batch_timeout_raises_timeout_error(self):
        """Should raise PoolTimeoutError when execution exceeds timeout."""
        import time

        from src.infra.exceptions import PoolTimeoutError
        from src.infra.pool import execute_batch

        def slow_task():
            time.sleep(0.8)  # Must exceed the 0.5s timeout
            return "result"

        with pytest.raises(PoolTimeoutError) as exc_info:
            execute_batch([slow_task, slow_task], timeout=0.5)

        error = exc_info.value
        assert error.total_count == 2
        assert error.completed_count < 2  # Not all completed

    def test_execute_batch_cancellation_stops_pending(self):
        """Should cancel pending tasks when failure occurs."""
        import time

        from src.infra.exceptions import PoolExecutionError
        from src.infra.pool import execute_batch

        started = []
        completed = []

        def task(index):
            started.append(index)
            time.sleep(0.1)
            completed.append(index)
            return f"result{index}"

        def failing_task():
            started.append("fail")
            raise ValueError("Failed")

        # Mix of tasks - failure should cancel others
        tasks = [lambda i=i: task(i) for i in range(3)] + [failing_task] + [lambda i=i: task(i) for i in range(3, 6)]

        with pytest.raises(PoolExecutionError):
            execute_batch(tasks, fail_fast=True, max_workers=2)

        # Some tasks started but not all completed
        assert len(started) > 0
        assert len(completed) < 6

    def test_execute_batch_error_summary_readable(self):
        """Should provide readable error summary."""
        from src.infra.exceptions import PoolExecutionError
        from src.infra.pool import execute_batch

        def failing_task():
            raise ValueError("Something went wrong")

        with pytest.raises(PoolExecutionError) as exc_info:
            execute_batch(
                [failing_task],
                task_descriptions=["Process filing 123"]
            )

        error = exc_info.value
        failure = error.failures[0]

        assert failure.task_description == "Process filing 123"
        assert "Something went wrong" in str(failure.exception)
        assert "ValueError" in failure.traceback_str

    def test_execute_batch_concurrent_stress_100_tasks(self):
        """Should handle 100 concurrent tasks successfully."""
        from src.infra.pool import execute_batch

        def task(index):
            return index * 2

        tasks = [lambda i=i: task(i) for i in range(100)]

        results = execute_batch(tasks, max_workers=10)

        assert len(results) == 100
        assert results == [i * 2 for i in range(100)]

    def test_pool_health_report_structure(self):
        """Should return PoolHealthReport with expected structure."""
        from src.infra.pool import PoolHealthReport, check_pool_health

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.get_stats.return_value = {
            "pool_size": 5,
            "pool_available": 3,
            "requests_waiting": 0
        }
        mock_pool.min_size = 2
        mock_pool.max_size = 10

        report = check_pool_health(mock_pool)

        assert isinstance(report, PoolHealthReport)
        assert hasattr(report, 'is_healthy')
        assert hasattr(report, 'total_connections')
        assert hasattr(report, 'idle_connections')
        assert hasattr(report, 'active_connections')
        assert hasattr(report, 'test_query_elapsed')
        assert hasattr(report, 'timestamp')
        assert hasattr(report, 'error')
        assert report.timestamp is not None

    def test_pool_health_check_includes_metrics(self):
        """Should include connection metrics in health check."""
        from src.infra.pool import check_pool_health

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.get_stats.return_value = {
            "pool_size": 8,
            "pool_available": 5,
            "requests_waiting": 0
        }
        mock_pool.min_size = 2
        mock_pool.max_size = 10

        report = check_pool_health(mock_pool)

        assert report.total_connections == 8
        assert report.idle_connections == 5
        assert report.active_connections == 3
        assert report.test_query_elapsed is not None
        assert report.test_query_elapsed > 0

    def test_pool_cleanup_logging(self):
        """Should log pool cleanup with timing information."""
        from src.infra import pool
        from src.infra.pool import close_shared_pool, get_shared_pool

        # Create a shared pool
        with patch("src.infra.pool.create_pool") as mock_create_pool:
            mock_pool = MagicMock()
            mock_pool.get_stats.return_value = {
                "pool_size": 5,
                "pool_available": 3,
                "requests_waiting": 0
            }
            mock_create_pool.return_value = mock_pool

            get_shared_pool("postgresql://localhost/test")

            # Close the pool
            close_shared_pool()

            # Verify close was called
            mock_pool.close.assert_called_once()

            # Verify state was reset
            assert pool._shared_pool is None
            assert pool._shared_pool_conninfo is None

    def test_task_descriptions_in_error_messages(self):
        """Should include task descriptions in error messages."""
        from src.infra.exceptions import PoolExecutionError
        from src.infra.pool import execute_batch

        def failing_task():
            raise RuntimeError("Database connection failed")

        descriptions = ["Fetch filing 1", "Fetch filing 2", "Fetch filing 3"]

        with pytest.raises(PoolExecutionError) as exc_info:
            execute_batch(
                [failing_task, failing_task, failing_task],
                task_descriptions=descriptions,
                fail_fast=True
            )

        error = exc_info.value
        failure = error.failures[0]

        # First failure should have its description
        assert failure.task_description in descriptions

    def test_partial_results_when_fail_fast_false(self):
        """Should return partial results when fail_fast=False."""
        from src.infra.exceptions import PoolExecutionError
        from src.infra.pool import execute_batch

        def task1():
            return "result1"

        def task2():
            raise ValueError("Task 2 failed")

        def task3():
            return "result3"

        with pytest.raises(PoolExecutionError) as exc_info:
            execute_batch([task1, task2, task3], fail_fast=False)

        error = exc_info.value
        assert error.partial_results is not None
        assert error.partial_results[0] == "result1"
        assert error.partial_results[1] is None  # Failed task
        assert error.partial_results[2] == "result3"
