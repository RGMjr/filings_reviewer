"""Tests for the PostgreSQL backend of the LLM response cache."""

import os
from unittest.mock import patch

import pytest

from src.llm.cache import CacheConfig, LLMCache


class TestCacheConfigPostgres:
    """Tests for CacheConfig with PostgreSQL backend fields."""

    def test_default_backend_is_sqlite(self):
        """Test that backend defaults to sqlite."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("LLM_CACHE_BACKEND", raising=False)
            mp.delenv("DATABASE_URL", raising=False)

            config = CacheConfig()

            assert config.backend == "sqlite"
            assert config.database_url == ""

    def test_backend_from_environment(self):
        """Test that backend reads from LLM_CACHE_BACKEND env var."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("LLM_CACHE_BACKEND", "postgres")
            mp.setenv("DATABASE_URL", "postgresql://user:pass@host/db")

            config = CacheConfig()

            assert config.backend == "postgres"
            assert config.database_url == "postgresql://user:pass@host/db"

    def test_explicit_backend_values(self):
        """Test explicit configuration values for backend."""
        config = CacheConfig(
            backend="postgres",
            database_url="postgresql://localhost/test",
        )

        assert config.backend == "postgres"
        assert config.database_url == "postgresql://localhost/test"


class TestSQLDialectHelpers:
    """Tests for SQL dialect helper methods."""

    @pytest.fixture
    def sqlite_cache(self):
        """Create a disabled SQLite-backend cache for helper testing."""
        config = CacheConfig(enabled=False, backend="sqlite")
        return LLMCache(config)

    @pytest.fixture
    def postgres_cache(self):
        """Create a disabled PostgreSQL-backend cache for helper testing."""
        config = CacheConfig(enabled=False, backend="postgres")
        return LLMCache(config)

    def test_placeholder_sqlite(self, sqlite_cache):
        """Test placeholder returns ? for SQLite."""
        assert sqlite_cache._placeholder() == "?"

    def test_placeholder_postgres(self, postgres_cache):
        """Test placeholder returns %s for PostgreSQL."""
        assert postgres_cache._placeholder() == "%s"

    def test_age_filter_sqlite(self, sqlite_cache):
        """Test age filter SQL for SQLite."""
        result = sqlite_cache._age_filter()
        assert "datetime('now'" in result
        assert "-30 days" in result

    def test_age_filter_postgres(self, postgres_cache):
        """Test age filter SQL for PostgreSQL."""
        result = postgres_cache._age_filter()
        assert "now() - interval" in result
        assert "30 days" in result

    def test_age_filter_custom_days(self):
        """Test age filter respects max_age_days config."""
        config = CacheConfig(enabled=False, backend="postgres", max_age_days=7)
        cache = LLMCache(config)
        result = cache._age_filter()
        assert "7 days" in result

    def test_expired_filter_sqlite(self, sqlite_cache):
        """Test expired filter SQL for SQLite."""
        result = sqlite_cache._expired_filter()
        assert "datetime('now'" in result
        assert "<=" in result

    def test_expired_filter_postgres(self, postgres_cache):
        """Test expired filter SQL for PostgreSQL."""
        result = postgres_cache._expired_filter()
        assert "now() - interval" in result
        assert "<=" in result

    def test_upsert_sql_sqlite(self, sqlite_cache):
        """Test upsert SQL uses INSERT OR REPLACE for SQLite."""
        result = sqlite_cache._upsert_sql()
        assert "INSERT OR REPLACE" in result
        assert "?" in result
        assert "%s" not in result

    def test_upsert_sql_postgres(self, postgres_cache):
        """Test upsert SQL uses ON CONFLICT for PostgreSQL."""
        result = postgres_cache._upsert_sql()
        assert "ON CONFLICT (cache_key) DO UPDATE" in result
        assert "%s" in result
        assert "?" not in result
        assert "EXCLUDED.response_content" in result


class TestPostgresGracefulFailure:
    """Tests for graceful degradation when PostgreSQL is unavailable."""

    def test_postgres_no_database_url_disables_cache(self):
        """Test that postgres backend with no DATABASE_URL disables cache."""
        config = CacheConfig(
            enabled=True,
            backend="postgres",
            database_url="",
        )
        cache = LLMCache(config)

        assert cache.config.enabled is False
        assert cache._conn is None

    def test_postgres_connection_failure_disables_cache(self):
        """Test that a connection failure disables cache gracefully."""
        config = CacheConfig(
            enabled=True,
            backend="postgres",
            database_url="postgresql://invalid:invalid@localhost:1/nonexistent",
        )

        # The connection will fail, cache should disable itself
        cache = LLMCache(config)

        assert cache.config.enabled is False
        assert cache._conn is None

        # Operations should return safe defaults
        assert cache.get("model", "", "prompt", 0.0, 100) is None
        assert cache.set("model", "", "prompt", 0.0, 100, "resp", 10, 10) is False
        assert cache.stats()["enabled"] is False
        assert cache.clear() == 0
        assert cache.cleanup_expired() == 0

    def test_postgres_import_error_disables_cache(self):
        """Test that missing psycopg library disables cache gracefully."""
        config = CacheConfig(
            enabled=True,
            backend="postgres",
            database_url="postgresql://user:pass@host/db",
        )

        with patch.dict("sys.modules", {"psycopg": None}):
            cache = LLMCache(config)

            assert cache.config.enabled is False
            assert cache._conn is None

    def test_disabled_postgres_cache_skips_init(self):
        """Test that disabled cache with postgres backend does not connect."""
        config = CacheConfig(
            enabled=False,
            backend="postgres",
            database_url="postgresql://user:pass@host/db",
        )
        cache = LLMCache(config)

        assert cache._conn is None
        assert cache._backend == "postgres"


class TestPostgresBackendIntegration:
    """Integration tests for the PostgreSQL backend.

    These tests require a running PostgreSQL instance accessible via
    TEST_DATABASE_URL. They are skipped when the env var is not set.
    """

    @pytest.fixture
    def pg_cache(self):
        """Create a PostgreSQL-backed cache using test database."""
        test_url = os.environ.get("TEST_DATABASE_URL")
        if not test_url:
            pytest.skip("TEST_DATABASE_URL not set")

        config = CacheConfig(
            enabled=True,
            backend="postgres",
            database_url=test_url,
            cache_version="test_pg_v1",
            max_age_days=30,
        )
        cache = LLMCache(config)

        if not cache.config.enabled:
            pytest.skip("PostgreSQL connection failed")

        # Ensure table exists (run migration DDL inline for test isolation)
        cache._conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                cache_version TEXT NOT NULL,
                model TEXT NOT NULL,
                response_content TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        cache._conn.commit()

        # Clean test entries before each test
        cache.clear(version_only=True)

        yield cache

        # Cleanup
        cache.clear(version_only=True)
        cache.close()

    def test_set_and_get(self, pg_cache):
        """Test storing and retrieving from PostgreSQL cache."""
        success = pg_cache.set(
            model="gpt-4o-mini",
            system_message="You are helpful",
            prompt="What is 2+2?",
            temperature=0.0,
            max_tokens=100,
            response_content="4",
            input_tokens=15,
            output_tokens=1,
        )
        assert success is True

        result = pg_cache.get(
            model="gpt-4o-mini",
            system_message="You are helpful",
            prompt="What is 2+2?",
            temperature=0.0,
            max_tokens=100,
        )
        assert result is not None
        assert result.content == "4"
        assert result.input_tokens == 15
        assert result.output_tokens == 1
        assert result.cached is True

    def test_cache_miss(self, pg_cache):
        """Test cache returns None for missing entries."""
        result = pg_cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Never seen before",
            temperature=0.0,
            max_tokens=100,
        )
        assert result is None

    def test_upsert_replaces_existing(self, pg_cache):
        """Test that upserting same key replaces existing entry."""
        pg_cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="First",
            input_tokens=10,
            output_tokens=10,
        )

        pg_cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="Second",
            input_tokens=15,
            output_tokens=20,
        )

        result = pg_cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
        )
        assert result.content == "Second"
        assert result.input_tokens == 15
        assert pg_cache.stats()["total_entries"] == 1

    def test_stats(self, pg_cache):
        """Test cache statistics with PostgreSQL backend."""
        stats = pg_cache.stats()
        assert stats["enabled"] is True
        assert stats["total_entries"] == 0

        pg_cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="Response",
            input_tokens=10,
            output_tokens=20,
        )

        # Hit
        pg_cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
        )

        # Miss
        pg_cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Missing",
            temperature=0.0,
            max_tokens=100,
        )

        stats = pg_cache.stats()
        assert stats["total_entries"] == 1
        assert stats["total_input_tokens_cached"] == 10
        assert stats["total_output_tokens_cached"] == 20
        assert stats["session_hits"] == 1
        assert stats["session_misses"] == 1
        assert stats["hit_rate"] == 50.0

    def test_clear(self, pg_cache):
        """Test clearing cache entries."""
        pg_cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="Response",
            input_tokens=10,
            output_tokens=10,
        )

        deleted = pg_cache.clear(version_only=True)
        assert deleted == 1
        assert pg_cache.stats()["total_entries"] == 0
