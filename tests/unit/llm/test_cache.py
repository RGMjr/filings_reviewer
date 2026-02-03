"""Tests for LLM response cache module."""

import os
import tempfile
from pathlib import Path

import pytest

from src.llm.cache import CacheConfig, CachedResponse, LLMCache


class TestCacheConfig:
    """Tests for CacheConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        # Clear environment to test defaults
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("LLM_CACHE_ENABLED", raising=False)
            mp.delenv("LLM_CACHE_PATH", raising=False)
            mp.delenv("LLM_CACHE_VERSION", raising=False)

            config = CacheConfig()

            assert config.enabled is True
            assert config.db_path == "data/llm_cache.db"
            assert config.cache_version == "v1"
            assert config.max_age_days == 30

    def test_config_from_environment(self):
        """Test configuration from environment variables."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("LLM_CACHE_ENABLED", "false")
            mp.setenv("LLM_CACHE_PATH", "/custom/path.db")
            mp.setenv("LLM_CACHE_VERSION", "v2")

            config = CacheConfig()

            assert config.enabled is False
            assert config.db_path == "/custom/path.db"
            assert config.cache_version == "v2"

    def test_config_explicit_values(self):
        """Test explicit configuration values override defaults."""
        config = CacheConfig(
            enabled=False,
            db_path="/explicit/path.db",
            cache_version="v3",
            max_age_days=7,
        )

        assert config.enabled is False
        assert config.db_path == "/explicit/path.db"
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


class TestLLMCache:
    """Tests for LLMCache class."""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary directory for cache database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def cache(self, temp_cache_dir):
        """Create a cache instance with temporary database."""
        config = CacheConfig(
            enabled=True,
            db_path=os.path.join(temp_cache_dir, "test_cache.db"),
            cache_version="test_v1",
            max_age_days=30,
        )
        cache = LLMCache(config)
        yield cache
        cache.close()

    @pytest.fixture
    def disabled_cache(self, temp_cache_dir):
        """Create a disabled cache instance."""
        config = CacheConfig(
            enabled=False,
            db_path=os.path.join(temp_cache_dir, "disabled_cache.db"),
        )
        return LLMCache(config)

    def test_cache_initialization(self, temp_cache_dir):
        """Test cache initializes database correctly."""
        db_path = os.path.join(temp_cache_dir, "init_test.db")
        config = CacheConfig(enabled=True, db_path=db_path)

        cache = LLMCache(config)

        assert Path(db_path).exists()
        assert cache._conn is not None
        cache.close()

    def test_cache_disabled(self, disabled_cache):
        """Test disabled cache returns None for all operations."""
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

    def test_set_and_get(self, cache):
        """Test storing and retrieving from cache."""
        # Store a response
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

        # Retrieve it
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

    def test_cache_miss(self, cache):
        """Test cache returns None for missing entries."""
        result = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Never seen before",
            temperature=0.0,
            max_tokens=100,
        )

        assert result is None

    def test_different_prompts_different_keys(self, cache):
        """Test different prompts produce different cache keys."""
        # Store first response
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Prompt A",
            temperature=0.0,
            max_tokens=100,
            response_content="Response A",
            input_tokens=10,
            output_tokens=10,
        )

        # Store second response
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Prompt B",
            temperature=0.0,
            max_tokens=100,
            response_content="Response B",
            input_tokens=10,
            output_tokens=10,
        )

        # Retrieve both
        result_a = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Prompt A",
            temperature=0.0,
            max_tokens=100,
        )

        result_b = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Prompt B",
            temperature=0.0,
            max_tokens=100,
        )

        assert result_a.content == "Response A"
        assert result_b.content == "Response B"

    def test_different_temperatures_different_keys(self, cache):
        """Test different temperatures produce different cache keys."""
        # Store with temp=0.0
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Same prompt",
            temperature=0.0,
            max_tokens=100,
            response_content="Deterministic",
            input_tokens=10,
            output_tokens=10,
        )

        # Store with temp=0.7
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Same prompt",
            temperature=0.7,
            max_tokens=100,
            response_content="Creative",
            input_tokens=10,
            output_tokens=10,
        )

        # Retrieve both
        result_0 = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Same prompt",
            temperature=0.0,
            max_tokens=100,
        )

        result_7 = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Same prompt",
            temperature=0.7,
            max_tokens=100,
        )

        assert result_0.content == "Deterministic"
        assert result_7.content == "Creative"

    def test_whitespace_normalization(self, cache):
        """Test that prompts are normalized (whitespace stripped)."""
        # Store with extra whitespace
        cache.set(
            model="gpt-4o-mini",
            system_message="  System  ",
            prompt="  Prompt with spaces  ",
            temperature=0.0,
            max_tokens=100,
            response_content="Response",
            input_tokens=10,
            output_tokens=10,
        )

        # Retrieve without extra whitespace
        result = cache.get(
            model="gpt-4o-mini",
            system_message="System",
            prompt="Prompt with spaces",
            temperature=0.0,
            max_tokens=100,
        )

        assert result is not None
        assert result.content == "Response"

    def test_stats(self, cache):
        """Test cache statistics."""
        # Initial stats
        stats = cache.stats()
        assert stats["enabled"] is True
        assert stats["total_entries"] == 0
        assert stats["session_hits"] == 0
        assert stats["session_misses"] == 0

        # Add some entries and lookups
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="Response",
            input_tokens=10,
            output_tokens=20,
        )

        # Cache hit
        cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
        )

        # Cache miss
        cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Missing",
            temperature=0.0,
            max_tokens=100,
        )

        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["total_input_tokens_cached"] == 10
        assert stats["total_output_tokens_cached"] == 20
        assert stats["session_hits"] == 1
        assert stats["session_misses"] == 1
        assert stats["hit_rate"] == 50.0

    def test_clear_version_only(self, cache):
        """Test clearing cache entries for current version only."""
        # Add entry
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="Response",
            input_tokens=10,
            output_tokens=10,
        )

        assert cache.stats()["total_entries"] == 1

        # Clear version
        deleted = cache.clear(version_only=True)

        assert deleted == 1
        assert cache.stats()["total_entries"] == 0

    def test_cache_version_isolation(self, temp_cache_dir):
        """Test that different cache versions are isolated."""
        db_path = os.path.join(temp_cache_dir, "version_test.db")

        # Create cache with v1
        config_v1 = CacheConfig(enabled=True, db_path=db_path, cache_version="v1")
        cache_v1 = LLMCache(config_v1)

        cache_v1.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="V1 Response",
            input_tokens=10,
            output_tokens=10,
        )
        cache_v1.close()

        # Create cache with v2 - should not see v1 entry
        config_v2 = CacheConfig(enabled=True, db_path=db_path, cache_version="v2")
        cache_v2 = LLMCache(config_v2)

        result = cache_v2.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
        )

        assert result is None  # v2 shouldn't see v1's entries
        cache_v2.close()

    def test_replace_existing_entry(self, cache):
        """Test that setting same key replaces existing entry."""
        # First set
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="First Response",
            input_tokens=10,
            output_tokens=10,
        )

        # Second set with same key
        cache.set(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
            response_content="Second Response",
            input_tokens=15,
            output_tokens=20,
        )

        # Should get the second response
        result = cache.get(
            model="gpt-4o-mini",
            system_message="",
            prompt="Test",
            temperature=0.0,
            max_tokens=100,
        )

        assert result.content == "Second Response"
        assert result.input_tokens == 15
        assert result.output_tokens == 20

        # Should still only have one entry
        assert cache.stats()["total_entries"] == 1


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
