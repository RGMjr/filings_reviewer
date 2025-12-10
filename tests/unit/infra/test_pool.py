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
            result = create_pool(
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
        """Should return healthy status when pool works."""
        from src.infra.pool import check_pool_health

        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)
        mock_pool.get_stats.return_value = {"pool_size": 2, "pool_available": 2}
        mock_pool.min_size = 2
        mock_pool.max_size = 10

        result = check_pool_health(mock_pool)

        assert result["healthy"] is True
        assert result["message"] == "Pool is healthy"
        assert result["stats"] is not None

    def test_unhealthy_pool(self):
        """Should return unhealthy status when pool fails."""
        from src.infra.pool import check_pool_health

        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("Connection failed")

        result = check_pool_health(mock_pool)

        assert result["healthy"] is False
        assert "Connection failed" in result["message"]
        assert result["stats"] is None


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
