"""
Integration tests for connection pool module.

Tests pool functionality with a real PostgreSQL database connection.
Requires TEST_DATABASE_URL environment variable to be set.
"""

import os

import pytest
from dotenv import load_dotenv

# Load environment
load_dotenv()


@pytest.fixture(scope="module")
def test_db_url():
    """Get test database URL from environment."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


class TestPoolCreation:
    """Tests for creating connection pools with real database."""

    def test_create_pool_connects_to_database(self, test_db_url):
        """Should successfully create pool and connect to database."""
        from src.infra.pool import create_pool

        pool = create_pool(test_db_url, min_size=1, max_size=3)
        try:
            # Verify pool can get a connection
            with pool.connection() as conn:
                result = conn.execute("SELECT 1 AS value").fetchone()
                assert result["value"] == 1
        finally:
            pool.close()

    def test_pool_reuses_connections(self, test_db_url):
        """Should reuse connections rather than creating new ones."""
        from src.infra.pool import create_pool

        pool = create_pool(test_db_url, min_size=1, max_size=3)
        try:
            # Get connection, use it, return it
            with pool.connection() as conn1:
                conn1.execute("SELECT 1")

            # Get another connection - should reuse
            with pool.connection() as conn2:
                conn2.execute("SELECT 1")

            # Pool should have used the same connection
            stats = pool.get_stats()
            # Pool size should not have grown beyond min_size for simple operations
            assert stats["pool_size"] <= 2
        finally:
            pool.close()

    def test_pool_respects_max_size(self, test_db_url):
        """Should respect max_size configuration."""
        from src.infra.pool import create_pool

        pool = create_pool(test_db_url, min_size=1, max_size=2)
        try:
            stats = pool.get_stats()
            assert pool.max_size == 2
            assert stats["pool_size"] <= 2
        finally:
            pool.close()


class TestPoolWithDatabaseAdapter:
    """Tests for DatabaseAdapter with connection pool."""

    def test_adapter_uses_pool_for_operations(self, test_db_url):
        """Should use pool connections for database operations."""
        from src.infra.db import DatabaseAdapter
        from src.infra.pool import create_pool

        pool = create_pool(test_db_url, min_size=1, max_size=3)
        try:
            adapter = DatabaseAdapter(test_db_url, pool=pool)

            # Execute a simple query
            with adapter.get_connection() as conn:
                result = conn.execute("SELECT 1 AS value").fetchone()
                assert result["value"] == 1

            # Pool should have been used (connection returned to pool)
            stats = pool.get_stats()
            assert stats["pool_available"] >= 1
        finally:
            pool.close()

    def test_adapter_operations_work_with_pool(self, test_db_url):
        """Should successfully perform multiple operations through pooled adapter."""
        from src.infra.db import DatabaseAdapter
        from src.infra.pool import create_pool

        pool = create_pool(test_db_url, min_size=1, max_size=5)
        try:
            adapter = DatabaseAdapter(test_db_url, pool=pool)

            # Multiple sequential operations
            for i in range(5):
                with adapter.get_connection() as conn:
                    result = conn.execute(
                        "SELECT %s AS iteration", (i,)
                    ).fetchone()
                    assert result["iteration"] == i

            # All connections should be back in pool
            stats = pool.get_stats()
            assert stats["requests_waiting"] == 0
        finally:
            pool.close()

    def test_adapter_without_pool_still_works(self, test_db_url):
        """Should work without pool (backward compatibility)."""
        from src.infra.db import DatabaseAdapter

        adapter = DatabaseAdapter(test_db_url)

        # Should create and close connection per operation
        with adapter.get_connection() as conn:
            result = conn.execute("SELECT 'hello' AS greeting").fetchone()
            assert result["greeting"] == "hello"


class TestPoolStats:
    """Tests for pool statistics with real connections."""

    def test_get_pool_stats_returns_valid_data(self, test_db_url):
        """Should return accurate statistics about pool state."""
        from src.infra.pool import create_pool, get_pool_stats

        pool = create_pool(test_db_url, min_size=2, max_size=5)
        try:
            stats = get_pool_stats(pool)

            assert "pool_size" in stats
            assert "pool_available" in stats
            assert "requests_waiting" in stats
            assert stats["pool_min"] == 2
            assert stats["pool_max"] == 5
        finally:
            pool.close()

    def test_stats_reflect_connection_usage(self, test_db_url):
        """Should reflect when connections are in use."""
        from src.infra.pool import create_pool, get_pool_stats

        pool = create_pool(test_db_url, min_size=1, max_size=3)
        try:
            # First, ensure pool has at least one connection available
            # by using and returning one
            with pool.connection() as conn:
                conn.execute("SELECT 1")

            # Now pool should have at least 1 available
            stats_before = get_pool_stats(pool)
            available_before = stats_before["pool_available"]
            assert available_before >= 1, "Pool should have at least 1 connection available"

            # While using connection
            with pool.connection():
                stats_during = get_pool_stats(pool)
                # Available should be less during usage
                assert stats_during["pool_available"] < available_before

            # After returning connection
            stats_after = get_pool_stats(pool)
            assert stats_after["pool_available"] >= stats_during["pool_available"]
        finally:
            pool.close()


class TestPoolHealth:
    """Tests for pool health checking with real database."""

    def test_healthy_pool_reports_healthy(self, test_db_url):
        """Should report healthy when pool can execute queries."""
        from src.infra.pool import check_pool_health, create_pool

        pool = create_pool(test_db_url, min_size=1, max_size=3)
        try:
            result = check_pool_health(pool)

            assert result.is_healthy is True
            assert result.error is None
            assert result.total_connections is not None
        finally:
            pool.close()


class TestSharedPool:
    """Tests for shared singleton pool."""

    def setup_method(self):
        """Reset shared pool state before each test."""
        from src.infra import pool

        pool._shared_pool = None
        pool._shared_pool_conninfo = None

    def teardown_method(self):
        """Clean up shared pool after each test."""
        from src.infra.pool import close_shared_pool

        close_shared_pool()

    def test_shared_pool_creates_real_connections(self, test_db_url):
        """Should create working pool via get_shared_pool."""
        from src.infra.pool import get_shared_pool

        pool = get_shared_pool(test_db_url)

        # Verify it works
        with pool.connection() as conn:
            result = conn.execute("SELECT 'shared' AS source").fetchone()
            assert result["source"] == "shared"

    def test_shared_pool_returns_same_instance(self, test_db_url):
        """Should return same pool instance on subsequent calls."""
        from src.infra.pool import get_shared_pool

        pool1 = get_shared_pool(test_db_url)
        pool2 = get_shared_pool(test_db_url)

        assert pool1 is pool2

    def test_close_shared_pool_allows_new_creation(self, test_db_url):
        """Should allow creating new pool after closing."""
        from src.infra.pool import close_shared_pool, get_shared_pool

        pool1 = get_shared_pool(test_db_url)
        close_shared_pool()

        pool2 = get_shared_pool(test_db_url)

        # Should be different instances
        assert pool1 is not pool2

        # New pool should work
        with pool2.connection() as conn:
            result = conn.execute("SELECT 1 AS value").fetchone()
            assert result["value"] == 1


class TestCreatePooledAdapter:
    """Tests for create_pooled_adapter convenience function."""

    def setup_method(self):
        """Reset shared pool state before each test."""
        from src.infra import pool

        pool._shared_pool = None
        pool._shared_pool_conninfo = None

    def teardown_method(self):
        """Clean up shared pool after each test."""
        from src.infra.pool import close_shared_pool

        close_shared_pool()

    def test_creates_working_adapter(self, test_db_url):
        """Should create adapter backed by real pool."""
        from src.infra.db import create_pooled_adapter

        adapter = create_pooled_adapter(test_db_url)

        # Should work
        with adapter.get_connection() as conn:
            result = conn.execute("SELECT 'pooled' AS type").fetchone()
            assert result["type"] == "pooled"

    def test_uses_database_url_env_var(self, test_db_url):
        """Should use DATABASE_URL when no argument provided."""
        import os
        from unittest.mock import patch

        from src.infra.db import create_pooled_adapter

        with patch.dict(os.environ, {"DATABASE_URL": test_db_url}):
            adapter = create_pooled_adapter()

            with adapter.get_connection() as conn:
                result = conn.execute("SELECT 1 AS value").fetchone()
                assert result["value"] == 1
