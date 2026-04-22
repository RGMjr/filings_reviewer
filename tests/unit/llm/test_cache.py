"""Tests for LLM response cache module."""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.cache import CacheConfig, CachedResponse, LLMCache


class TestCacheConfig:
    """Tests for CacheConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("LLM_CACHE_ENABLED", raising=False)
            mp.delenv("DATABASE_URL", raising=False)
            mp.delenv("LLM_CACHE_VERSION", raising=False)

            config = CacheConfig()

            assert config.enabled is True
            assert config.connection_string == ""
            # Bumped to v2 in Wave B2 (provider abstraction) to invalidate
            # single-provider GPT-4o cached responses under the new multi-
            # provider dispatch.
            assert config.cache_version == "v2"
            assert config.max_age_days == 30

    def test_config_from_environment(self):
        """Test configuration from environment variables."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("LLM_CACHE_ENABLED", "false")
            mp.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
            mp.setenv("LLM_CACHE_VERSION", "v3")

            config = CacheConfig()

            assert config.enabled is False
            assert config.connection_string == "postgresql://user:pass@localhost/testdb"
            assert config.cache_version == "v3"

    def test_config_explicit_values(self):
        """Test explicit configuration values override defaults."""
        config = CacheConfig(
            enabled=False,
            connection_string="postgresql://user:pass@localhost/db",
            cache_version="v3",
            max_age_days=7,
        )

        assert config.enabled is False
        assert config.connection_string == "postgresql://user:pass@localhost/db"
        assert config.cache_version == "v3"
        assert config.max_age_days == 7


class TestCachedResponse:
    """Tests for CachedResponse dataclass."""

    def test_cached_response_creation(self):
        """Test creating a CachedResponse object."""
        response = CachedResponse(
            content="Test content",
            input_tokens=100,
            output_tokens=50,
        )

        assert response.content == "Test content"
        assert response.input_tokens == 100
        assert response.output_tokens == 50
        assert response.cached is True


def _make_mock_conn():
    """Return a mock psycopg connection that supports context-manager cursor use."""
    conn = MagicMock()
    # execute() returns a cursor-like object with fetchone/rowcount
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    cursor.rowcount = 0
    conn.execute.return_value = cursor
    conn.autocommit = False
    return conn


class TestLLMCache:
    """Tests for LLMCache class using a mocked psycopg connection."""

    @pytest.fixture
    def mock_conn(self):
        return _make_mock_conn()

    @pytest.fixture
    def cache(self, mock_conn):
        """Create a cache instance backed by a mock Postgres connection."""
        config = CacheConfig(
            enabled=True,
            connection_string="postgresql://mock/db",
            cache_version="test_v1",
            max_age_days=30,
        )
        with patch("src.llm.cache.psycopg.connect", return_value=mock_conn):
            c = LLMCache(config)
        yield c
        c.close()

    @pytest.fixture
    def disabled_cache(self):
        config = CacheConfig(enabled=False, connection_string="")
        return LLMCache(config)

    def test_cache_initialization(self, mock_conn):
        """Test cache connects and creates schema on init."""
        config = CacheConfig(
            enabled=True,
            connection_string="postgresql://mock/db",
            cache_version="v1",
        )
        with patch("src.llm.cache.psycopg.connect", return_value=mock_conn) as mock_connect:
            cache = LLMCache(config)
            mock_connect.assert_called_once_with("postgresql://mock/db")
            assert cache._conn is not None
            cache.close()

    def test_cache_no_connection_string_disables(self):
        """Cache disables itself when DATABASE_URL is not set."""
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("DATABASE_URL", raising=False)
            config = CacheConfig(enabled=True, connection_string="")
            cache = LLMCache(config)
            assert cache.config.enabled is False
            assert cache._conn is None

    def test_cache_disabled(self, disabled_cache):
        """Disabled cache returns None / False for all operations."""
        result = disabled_cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test prompt",
            temperature=0.0,
            max_tokens=100,
        )
        assert result is None

        success = disabled_cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test prompt",
            temperature=0.0,
            max_tokens=100,
            response_content="Response",
            input_tokens=10,
            output_tokens=20,
        )
        assert success is False

    def test_set_calls_execute(self, cache, mock_conn):
        """set() calls conn.execute with an INSERT ... ON CONFLICT statement."""
        mock_conn.execute.return_value = MagicMock(rowcount=1)
        success = cache.set(
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
        # Verify an INSERT ... ON CONFLICT call was made
        insert_calls = [call for call in mock_conn.execute.call_args_list if "INSERT" in str(call)]
        assert len(insert_calls) >= 1

    def test_get_hit_returns_cached_response(self, cache, mock_conn):
        """get() returns CachedResponse when the DB row is found."""
        mock_conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=("4", 15, 1)))
        result = cache.get(
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

    def test_get_miss_returns_none(self, cache, mock_conn):
        """get() returns None when the DB row is not found."""
        mock_conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))
        result = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Never seen before",
            temperature=0.0,
            max_tokens=100,
        )
        assert result is None

    def test_stats_disabled(self, disabled_cache):
        """stats() returns disabled structure when cache is off."""
        stats = disabled_cache.stats()
        assert stats["enabled"] is False
        assert stats["total_entries"] == 0

    def test_clear_calls_delete(self, cache, mock_conn):
        """clear() calls DELETE and commits."""
        mock_cursor = MagicMock(rowcount=3)
        mock_conn.execute.return_value = mock_cursor
        deleted = cache.clear(version_only=True)
        assert deleted == 3
        mock_conn.commit.assert_called()

    def test_cleanup_expired_calls_delete(self, cache, mock_conn):
        """cleanup_expired() calls DELETE with interval and commits."""
        mock_cursor = MagicMock(rowcount=2)
        mock_conn.execute.return_value = mock_cursor
        deleted = cache.cleanup_expired()
        assert deleted == 2
        delete_calls = [call for call in mock_conn.execute.call_args_list if "DELETE" in str(call)]
        assert len(delete_calls) >= 1

    def test_session_hit_miss_counters(self, cache, mock_conn):
        """Hit and miss counters increment correctly."""
        # Miss
        mock_conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))
        cache.get(model="m", system_message="", prompt="p", temperature=0.0, max_tokens=10)
        assert cache._misses == 1
        assert cache._hits == 0

        # Hit
        mock_conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=("resp", 5, 3)))
        cache.get(model="m", system_message="", prompt="p", temperature=0.0, max_tokens=10)
        assert cache._hits == 1


class TestLLMCacheKeyComputation:
    """Tests for cache key computation edge cases."""

    @pytest.fixture
    def cache(self):
        """Create a cache instance with disabled DB (just for key testing)."""
        config = CacheConfig(enabled=False)
        return LLMCache(config)

    def test_key_includes_model(self, cache):
        """Test that model is included in cache key."""
        key1 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 100)
        key2 = cache._compute_key("gpt-4o", "", "prompt", 0.0, 100)

        assert key1 != key2

    def test_key_includes_system_message(self, cache):
        """Test that system message is included in cache key."""
        key1 = cache._compute_key("gpt-4o-mini", "System A", "prompt", 0.0, 100)
        key2 = cache._compute_key("gpt-4o-mini", "System B", "prompt", 0.0, 100)

        assert key1 != key2

    def test_key_includes_max_tokens(self, cache):
        """Test that max_tokens is included in cache key."""
        key1 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 100)
        key2 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 200)

        assert key1 != key2

    def test_key_includes_kwargs(self, cache):
        """Test that additional kwargs are included in cache key."""
        key1 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 100, top_p=0.9)
        key2 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 100, top_p=0.95)

        assert key1 != key2

    def test_key_ignores_none_kwargs(self, cache):
        """Test that None kwargs don't affect cache key."""
        key1 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 100)
        key2 = cache._compute_key("gpt-4o-mini", "", "prompt", 0.0, 100, top_p=None)

        assert key1 == key2

    def test_key_deterministic(self, cache):
        """Test that cache key is deterministic."""
        key1 = cache._compute_key("gpt-4o-mini", "sys", "prompt", 0.5, 100)
        key2 = cache._compute_key("gpt-4o-mini", "sys", "prompt", 0.5, 100)

        assert key1 == key2

    def test_whitespace_normalization_in_key(self, cache):
        """Prompts with leading/trailing whitespace produce the same key."""
        key1 = cache._compute_key("gpt-4o-mini", "  System  ", "  Prompt  ", 0.0, 100)
        key2 = cache._compute_key("gpt-4o-mini", "System", "Prompt", 0.0, 100)

        assert key1 == key2
