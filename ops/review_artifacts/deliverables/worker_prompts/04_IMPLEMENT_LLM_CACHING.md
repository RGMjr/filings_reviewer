# Worker Prompt: Implement LLM Response Caching

## Task ID: REV-04
## Priority: P1 (High Impact)
## Effort: S (2-4 hours)
## Finding IDs: G-D5-003, P-D5-001

---

## Problem Statement

Every LLM prompt triggers a paid, latency-heavy network call. For large corpora, repeated or near-repeated text patterns across filings (templated disclosures) cause avoidable cost and time.

### Current Impact

- **50-70%** of extraction runtime is LLM calls
- **$500-$1,000** projected cost for 7,304 filings
- **No cache** - identical prompts re-processed

### Optimization Potential

- **5-25%** cost/time reduction from caching
- Higher if re-runs are common (development, debugging)

---

## Files to Modify

- `src/llm/openai_client.py` - Add caching layer
- `src/llm/cache.py` (new) - Cache implementation
- `config/` - Cache configuration

---

## Acceptance Criteria

1. [ ] LLM responses cached by hash of (model, system_message, prompt, temperature, max_tokens)
2. [ ] Cache hit skips API call and returns stored response
3. [ ] Cache includes usage fields for cost tracking
4. [ ] Cache version field for safe invalidation on prompt changes
5. [ ] SQLite backend for single-host (production can upgrade to Redis/Postgres)
6. [ ] Cache statistics logged (hits, misses, savings)
7. [ ] Easy to disable for testing/debugging

---

## Implementation

### Step 1: Create Cache Module

```python
# src/llm/cache.py
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class CacheConfig:
    enabled: bool = True
    db_path: str = "data/llm_cache.db"
    cache_version: str = "v1"  # Bump to invalidate all cached responses
    max_age_days: int = 30

class LLMCache:
    """SQLite-backed cache for LLM responses."""

    def __init__(self, config: CacheConfig):
        self.config = config
        self._conn: Optional[sqlite3.Connection] = None
        if config.enabled:
            self._init_db()

    def _init_db(self):
        Path(self.config.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.config.db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                cache_key TEXT PRIMARY KEY,
                cache_version TEXT,
                model TEXT,
                response_content TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_version ON llm_cache(cache_version)")
        self._conn.commit()

    def _compute_key(
        self,
        model: str,
        system_message: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        **kwargs
    ) -> str:
        """Compute stable hash key for cache lookup."""
        # Normalize prompt (strip whitespace, lowercase for better hits)
        normalized_prompt = prompt.strip()

        key_data = {
            "model": model,
            "system": system_message.strip() if system_message else "",
            "prompt": normalized_prompt,
            "temp": round(temperature, 2),
            "max_tokens": max_tokens,
            # Include any other kwargs that affect output
            **{k: v for k, v in sorted(kwargs.items()) if v is not None}
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
        **kwargs
    ) -> Optional[dict]:
        """Get cached response if exists and valid."""
        if not self.config.enabled or not self._conn:
            return None

        cache_key = self._compute_key(model, system_message, prompt, temperature, max_tokens, **kwargs)

        cursor = self._conn.execute("""
            SELECT response_content, prompt_tokens, completion_tokens
            FROM llm_cache
            WHERE cache_key = ? AND cache_version = ?
            AND created_at > datetime('now', ?)
        """, (cache_key, self.config.cache_version, f"-{self.config.max_age_days} days"))

        row = cursor.fetchone()
        if row:
            logger.debug(f"Cache HIT for key {cache_key[:8]}...")
            return {
                "content": row[0],
                "prompt_tokens": row[1],
                "completion_tokens": row[2],
                "cached": True
            }

        logger.debug(f"Cache MISS for key {cache_key[:8]}...")
        return None

    def set(
        self,
        model: str,
        system_message: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        response_content: str,
        prompt_tokens: int,
        completion_tokens: int,
        **kwargs
    ):
        """Store response in cache."""
        if not self.config.enabled or not self._conn:
            return

        cache_key = self._compute_key(model, system_message, prompt, temperature, max_tokens, **kwargs)

        self._conn.execute("""
            INSERT OR REPLACE INTO llm_cache
            (cache_key, cache_version, model, response_content, prompt_tokens, completion_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (cache_key, self.config.cache_version, model, response_content, prompt_tokens, completion_tokens))
        self._conn.commit()

        logger.debug(f"Cache SET for key {cache_key[:8]}...")

    def stats(self) -> dict:
        """Get cache statistics."""
        if not self._conn:
            return {"enabled": False}

        cursor = self._conn.execute("""
            SELECT
                COUNT(*) as total_entries,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens
            FROM llm_cache
            WHERE cache_version = ?
        """, (self.config.cache_version,))

        row = cursor.fetchone()
        return {
            "enabled": True,
            "total_entries": row[0] or 0,
            "total_prompt_tokens_cached": row[1] or 0,
            "total_completion_tokens_cached": row[2] or 0,
        }
```

### Step 2: Integrate with OpenAI Client

```python
# src/llm/openai_client.py
from src.llm.cache import LLMCache, CacheConfig

class OpenAIClient:
    def __init__(self, ..., cache_config: CacheConfig = None):
        ...
        self._cache = LLMCache(cache_config or CacheConfig())
        self._cache_hits = 0
        self._cache_misses = 0

    def complete(
        self,
        prompt: str,
        system_message: str = None,
        temperature: float = 0.0,
        max_tokens: int = 1000,
        **kwargs
    ) -> LLMResponse:
        # Check cache first
        cached = self._cache.get(
            model=self.model,
            system_message=system_message or "",
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        if cached:
            self._cache_hits += 1
            return LLMResponse(
                content=cached["content"],
                prompt_tokens=cached["prompt_tokens"],
                completion_tokens=cached["completion_tokens"],
                model=self.model,
                cached=True
            )

        self._cache_misses += 1

        # Make actual API call
        response = self._call_api(prompt, system_message, temperature, max_tokens, **kwargs)

        # Store in cache
        self._cache.set(
            model=self.model,
            system_message=system_message or "",
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_content=response.content,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            **kwargs
        )

        return response

    def get_cache_stats(self) -> dict:
        """Get cache performance statistics."""
        stats = self._cache.stats()
        stats["session_hits"] = self._cache_hits
        stats["session_misses"] = self._cache_misses
        stats["hit_rate"] = (
            self._cache_hits / (self._cache_hits + self._cache_misses)
            if (self._cache_hits + self._cache_misses) > 0 else 0
        )
        return stats
```

### Step 3: Add Configuration

```python
# Add to config or environment
LLM_CACHE_ENABLED = os.environ.get("LLM_CACHE_ENABLED", "true").lower() == "true"
LLM_CACHE_PATH = os.environ.get("LLM_CACHE_PATH", "data/llm_cache.db")
LLM_CACHE_VERSION = os.environ.get("LLM_CACHE_VERSION", "v1")
```

---

## Verification Commands

```bash
# Run extraction twice and compare times
time python -c "
from src.extraction.extraction_pipeline import ExtractionPipeline
pipeline = ExtractionPipeline()
pipeline.process_filing(123)  # First run - cache miss
"

time python -c "
from src.extraction.extraction_pipeline import ExtractionPipeline
pipeline = ExtractionPipeline()
pipeline.process_filing(123)  # Second run - cache hit
"

# Check cache stats
python -c "
from src.llm.openai_client import OpenAIClient
client = OpenAIClient()
print(client.get_cache_stats())
"

# Clear cache for testing
rm data/llm_cache.db
```

---

## Notes

- For production with multiple workers, upgrade to Redis or Postgres backend
- Consider adding TTL-based cache cleanup job
- Log cache hit/miss rates for monitoring
- Bump `cache_version` when prompts change to invalidate old responses
