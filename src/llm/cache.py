"""
LLM Response Cache with SQLite backend.

Provides caching for LLM API responses to reduce costs and latency
for repeated or near-repeated prompts.

Cache key is computed from: model, system_message, prompt, temperature, max_tokens.
Cache version field allows safe invalidation when prompts change.
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """Configuration for LLM response cache."""

    enabled: bool = field(
        default_factory=lambda: os.environ.get("LLM_CACHE_ENABLED", "true").lower() == "true"
    )
    db_path: str = field(
        default_factory=lambda: os.environ.get("LLM_CACHE_PATH", "data/llm_cache.db")
    )
    cache_version: str = field(default_factory=lambda: os.environ.get("LLM_CACHE_VERSION", "v1"))
    max_age_days: int = 30


@dataclass
class CachedResponse:
    """A cached LLM response."""

    content: str
    input_tokens: int
    output_tokens: int
    cached: bool = True


class LLMCache:
    """
    SQLite-backed cache for LLM responses.

    Thread-safe using a lock around database operations.
    For production with multiple workers, consider upgrading to Redis or Postgres.
    """

    def __init__(self, config: CacheConfig | None = None):
        """
        Initialize the LLM cache.

        Args:
            config: Cache configuration. If None, uses defaults from environment.
        """
        self.config = config or CacheConfig()
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

        # Statistics
        self._hits = 0
        self._misses = 0

        if self.config.enabled:
            self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database and create schema if needed."""
        try:
            Path(self.config.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self.config.db_path,
                check_same_thread=False,
                timeout=10.0,
            )
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    cache_version TEXT NOT NULL,
                    model TEXT NOT NULL,
                    response_content TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_version ON llm_cache(cache_version)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON llm_cache(created_at)")
            self._conn.commit()
            logger.info(f"LLM cache initialized at {self.config.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize LLM cache: {e}")
            self.config.enabled = False
            self._conn = None

    def _compute_key(
        self,
        model: str,
        system_message: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        """
        Compute a stable hash key for cache lookup.

        The key is a SHA-256 hash of the normalized input parameters.
        Normalization includes stripping whitespace and sorting kwargs.

        Args:
            model: Model identifier
            system_message: System message (may be empty)
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters that affect output

        Returns:
            SHA-256 hex digest
        """
        # Normalize inputs
        normalized_prompt = prompt.strip()
        normalized_system = system_message.strip() if system_message else ""

        key_data = {
            "model": model,
            "system": normalized_system,
            "prompt": normalized_prompt,
            "temp": round(temperature, 2),
            "max_tokens": max_tokens,
            # Include any other kwargs that affect output
            **{k: v for k, v in sorted(kwargs.items()) if v is not None},
        }

        key_json = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_json.encode()).hexdigest()

    def get(
        self,
        model: str,
        system_message: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> CachedResponse | None:
        """
        Get a cached response if it exists and is valid.

        Args:
            model: Model identifier
            system_message: System message
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters

        Returns:
            CachedResponse if found, None otherwise
        """
        if not self.config.enabled or not self._conn:
            return None

        cache_key = self._compute_key(
            model, system_message, prompt, temperature, max_tokens, **kwargs
        )

        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    SELECT response_content, input_tokens, output_tokens
                    FROM llm_cache
                    WHERE cache_key = ? AND cache_version = ?
                    AND created_at > datetime('now', ?)
                """,
                    (
                        cache_key,
                        self.config.cache_version,
                        f"-{self.config.max_age_days} days",
                    ),
                )

                row = cursor.fetchone()
                if row:
                    self._hits += 1
                    logger.debug(f"Cache HIT for key {cache_key[:8]}...")
                    return CachedResponse(
                        content=row[0],
                        input_tokens=row[1],
                        output_tokens=row[2],
                        cached=True,
                    )

                self._misses += 1
                logger.debug(f"Cache MISS for key {cache_key[:8]}...")
                return None

            except sqlite3.Error as e:
                logger.error(f"Cache get error: {e}")
                return None

    def set(
        self,
        model: str,
        system_message: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        response_content: str,
        input_tokens: int,
        output_tokens: int,
        **kwargs: Any,
    ) -> bool:
        """
        Store a response in the cache.

        Args:
            model: Model identifier
            system_message: System message
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            response_content: The LLM response content
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            **kwargs: Additional parameters

        Returns:
            True if stored successfully, False otherwise
        """
        if not self.config.enabled or not self._conn:
            return False

        cache_key = self._compute_key(
            model, system_message, prompt, temperature, max_tokens, **kwargs
        )

        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO llm_cache
                    (cache_key, cache_version, model, response_content, input_tokens, output_tokens)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        cache_key,
                        self.config.cache_version,
                        model,
                        response_content,
                        input_tokens,
                        output_tokens,
                    ),
                )
                self._conn.commit()
                logger.debug(f"Cache SET for key {cache_key[:8]}...")
                return True

            except sqlite3.Error as e:
                logger.error(f"Cache set error: {e}")
                return False

    def stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics including:
            - enabled: Whether cache is enabled
            - total_entries: Number of cached entries
            - total_input_tokens_cached: Sum of input tokens
            - total_output_tokens_cached: Sum of output tokens
            - session_hits: Cache hits in this session
            - session_misses: Cache misses in this session
            - hit_rate: Session hit rate as percentage
        """
        if not self.config.enabled or not self._conn:
            return {
                "enabled": False,
                "total_entries": 0,
                "session_hits": self._hits,
                "session_misses": self._misses,
                "hit_rate": 0.0,
            }

        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_entries,
                        COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                        COALESCE(SUM(output_tokens), 0) as total_output_tokens
                    FROM llm_cache
                    WHERE cache_version = ?
                """,
                    (self.config.cache_version,),
                )

                row = cursor.fetchone()
                total_requests = self._hits + self._misses
                hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

                return {
                    "enabled": True,
                    "total_entries": row[0] or 0,
                    "total_input_tokens_cached": row[1] or 0,
                    "total_output_tokens_cached": row[2] or 0,
                    "session_hits": self._hits,
                    "session_misses": self._misses,
                    "hit_rate": round(hit_rate, 1),
                }

            except sqlite3.Error as e:
                logger.error(f"Cache stats error: {e}")
                return {
                    "enabled": True,
                    "error": str(e),
                    "session_hits": self._hits,
                    "session_misses": self._misses,
                }

    def clear(self, version_only: bool = True) -> int:
        """
        Clear cache entries.

        Args:
            version_only: If True, only clear entries for current version.
                         If False, clear all entries.

        Returns:
            Number of entries deleted
        """
        if not self._conn:
            return 0

        with self._lock:
            try:
                if version_only:
                    cursor = self._conn.execute(
                        "DELETE FROM llm_cache WHERE cache_version = ?",
                        (self.config.cache_version,),
                    )
                else:
                    cursor = self._conn.execute("DELETE FROM llm_cache")

                self._conn.commit()
                deleted = cursor.rowcount
                logger.info(f"Cleared {deleted} cache entries")
                return deleted

            except sqlite3.Error as e:
                logger.error(f"Cache clear error: {e}")
                return 0

    def cleanup_expired(self) -> int:
        """
        Remove expired cache entries.

        Returns:
            Number of entries deleted
        """
        if not self._conn:
            return 0

        with self._lock:
            try:
                cursor = self._conn.execute(
                    "DELETE FROM llm_cache WHERE created_at <= datetime('now', ?)",
                    (f"-{self.config.max_age_days} days",),
                )
                self._conn.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} expired cache entries")
                return deleted

            except sqlite3.Error as e:
                logger.error(f"Cache cleanup error: {e}")
                return 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("LLM cache connection closed")
