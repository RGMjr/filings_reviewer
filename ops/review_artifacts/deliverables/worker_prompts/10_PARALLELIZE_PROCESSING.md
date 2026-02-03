# Worker Prompt: Parallelize Filing Processing

## Task ID: REV-10
## Priority: P2 (Performance)
## Effort: M (1-2 weeks)
## Finding IDs: G-D5-001, G-D5-002

---

## Problem Statement

Batch processing runs filings **one at a time**. With 7,304 filings:
- **2-5 day projected runtime** (linear scaling)
- **Cannot exploit** available CPU/IO concurrency
- **Any single slow filing** blocks throughput

### Current Bottlenecks

1. **Filing-level**: Sequential processing of 7,304 filings
2. **Segment-level**: LLM calls serialized within each filing
3. **LLM latency**: 50-70% of runtime

---

## Target Architecture

```
                    ┌─────────────────┐
                    │  Rate Limiter   │
                    │  (Token Bucket) │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    ┌────▼────┐        ┌─────▼────┐        ┌────▼────┐
    │ Worker 1│        │ Worker 2 │        │ Worker N│
    │ Filing A│        │ Filing B │        │ Filing C│
    └────┬────┘        └────┬─────┘        └────┬────┘
         │                  │                   │
    ┌────▼────┐        ┌────▼────┐        ┌────▼────┐
    │Segment 1│        │Segment 1│        │Segment 1│
    │Segment 2│◄──────►│Segment 2│◄──────►│Segment 2│
    │Segment N│ Async  │Segment N│ Async  │Segment N│
    └─────────┘        └─────────┘        └─────────┘
```

---

## Acceptance Criteria

1. [ ] Parallel filing processing with configurable worker count
2. [ ] Per-worker database connections (connection pool)
3. [ ] Global LLM rate limiter across all workers
4. [ ] Async segment processing within filings (optional)
5. [ ] Progress tracking and error recovery
6. [ ] 3-10x throughput improvement
7. [ ] No data corruption under concurrent access

---

## Implementation

### Step 1: Rate Limiter for LLM Calls

```python
# src/llm/rate_limiter.py
import asyncio
import time
from threading import Lock
from dataclasses import dataclass

@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60
    tokens_per_minute: int = 90000
    max_concurrent: int = 10

class TokenBucketRateLimiter:
    """
    Thread-safe token bucket rate limiter for LLM API calls.

    Supports both request-based and token-based limits.
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._request_tokens = config.requests_per_minute
        self._api_tokens = config.tokens_per_minute
        self._last_refill = time.monotonic()
        self._lock = Lock()
        self._semaphore = asyncio.Semaphore(config.max_concurrent)

    def acquire(self, estimated_tokens: int = 1000) -> float:
        """
        Acquire permission to make an API call.

        Returns: Seconds to wait before making the call (0 if immediate).
        """
        with self._lock:
            self._refill()

            # Check request limit
            if self._request_tokens < 1:
                wait_time = 60 / self.config.requests_per_minute
                return wait_time

            # Check token limit
            if self._api_tokens < estimated_tokens:
                wait_time = estimated_tokens / (self.config.tokens_per_minute / 60)
                return wait_time

            # Consume tokens
            self._request_tokens -= 1
            self._api_tokens -= estimated_tokens
            return 0.0

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill

        # Refill at rate per second
        request_refill = elapsed * (self.config.requests_per_minute / 60)
        token_refill = elapsed * (self.config.tokens_per_minute / 60)

        self._request_tokens = min(
            self._request_tokens + request_refill,
            self.config.requests_per_minute
        )
        self._api_tokens = min(
            self._api_tokens + token_refill,
            self.config.tokens_per_minute
        )
        self._last_refill = now
```

### Step 2: Parallel Batch Runner

```python
# src/extraction/parallel_runner.py
import concurrent.futures
from typing import List, Callable, Optional
from dataclasses import dataclass
import logging
from threading import Lock

logger = logging.getLogger(__name__)

@dataclass
class ParallelConfig:
    max_workers: int = 4
    chunk_size: int = 10
    timeout_per_filing: int = 300  # 5 minutes
    retry_failed: bool = True
    max_retries: int = 2

class ParallelBatchRunner:
    """
    Run filing extraction in parallel with controlled concurrency.
    """

    def __init__(
        self,
        config: ParallelConfig,
        db_factory: Callable,
        rate_limiter: TokenBucketRateLimiter,
    ):
        self.config = config
        self._db_factory = db_factory
        self._rate_limiter = rate_limiter
        self._progress_lock = Lock()
        self._processed = 0
        self._failed = 0

    def process_batch(
        self,
        filing_ids: List[int],
        process_fn: Callable[[int, "DatabaseAdapter"], None],
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> dict:
        """
        Process a batch of filings in parallel.

        Args:
            filing_ids: List of filing IDs to process
            process_fn: Function(filing_id, db) -> None
            progress_callback: Function(processed, failed, total) -> None

        Returns:
            {"processed": N, "failed": N, "errors": [...]}
        """
        total = len(filing_ids)
        errors = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_workers
        ) as executor:
            # Submit all tasks
            futures = {
                executor.submit(
                    self._process_one,
                    fid,
                    process_fn,
                ): fid
                for fid in filing_ids
            }

            # Collect results
            for future in concurrent.futures.as_completed(futures):
                filing_id = futures[future]
                try:
                    future.result(timeout=self.config.timeout_per_filing)
                    with self._progress_lock:
                        self._processed += 1
                except Exception as e:
                    with self._progress_lock:
                        self._failed += 1
                    errors.append({"filing_id": filing_id, "error": str(e)})
                    logger.error(f"Filing {filing_id} failed: {e}")

                # Report progress
                if progress_callback:
                    with self._progress_lock:
                        progress_callback(self._processed, self._failed, total)

        return {
            "processed": self._processed,
            "failed": self._failed,
            "errors": errors,
        }

    def _process_one(
        self,
        filing_id: int,
        process_fn: Callable,
    ):
        """Process a single filing with its own DB connection."""
        # Each worker gets its own DB connection
        db = self._db_factory()
        try:
            process_fn(filing_id, db, self._rate_limiter)
        finally:
            db.close()
```

### Step 3: Update Extraction Pipeline

```python
# src/extraction/extraction_pipeline.py

class ExtractionPipeline:
    def __init__(self, ..., rate_limiter: TokenBucketRateLimiter = None):
        ...
        self._rate_limiter = rate_limiter or TokenBucketRateLimiter(RateLimitConfig())

    def process_filing(
        self,
        filing_id: int,
        db: "DatabaseAdapter" = None,
        rate_limiter: TokenBucketRateLimiter = None,
    ):
        """
        Process a single filing.

        Thread-safe when given dedicated db connection and shared rate_limiter.
        """
        db = db or self.db
        limiter = rate_limiter or self._rate_limiter

        # ... existing logic ...

        # Before LLM call:
        wait_time = limiter.acquire(estimated_tokens=2000)
        if wait_time > 0:
            time.sleep(wait_time)

        # Make LLM call
        response = self.llm_client.complete(...)

    def process_batch_parallel(
        self,
        filing_ids: List[int],
        workers: int = 4,
        progress_callback: Callable = None,
    ) -> dict:
        """
        Process multiple filings in parallel.

        Args:
            filing_ids: Filings to process
            workers: Number of parallel workers
            progress_callback: Progress reporting function

        Returns:
            Processing results summary
        """
        runner = ParallelBatchRunner(
            config=ParallelConfig(max_workers=workers),
            db_factory=lambda: DatabaseAdapter(self.db.connection_string),
            rate_limiter=self._rate_limiter,
        )

        return runner.process_batch(
            filing_ids,
            process_fn=self.process_filing,
            progress_callback=progress_callback,
        )
```

### Step 4: Async Segment Processing (Optional, Higher Complexity)

```python
# src/extraction/async_extractor.py
import asyncio
from typing import List

class AsyncSegmentExtractor:
    """
    Process segments within a filing asynchronously.

    Use when LLM calls dominate per-filing time and
    segment count is high.
    """

    def __init__(self, llm_client, rate_limiter, max_concurrent: int = 5):
        self._llm = llm_client
        self._limiter = rate_limiter
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def extract_values_async(
        self,
        segments: List[dict],
    ) -> List[dict]:
        """
        Extract values from segments concurrently.
        """
        tasks = [
            self._extract_one(seg)
            for seg in segments
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle results
        values = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Segment {i} failed: {result}")
            else:
                values.extend(result)

        return values

    async def _extract_one(self, segment: dict) -> List[dict]:
        """Extract values from a single segment."""
        async with self._semaphore:
            # Wait for rate limit
            wait_time = self._limiter.acquire(estimated_tokens=2000)
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            # Run extraction (sync code in executor)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self._sync_extract,
                segment,
            )
```

---

## Configuration

```python
# config/extraction.py

PARALLEL_CONFIG = {
    "max_workers": int(os.environ.get("EXTRACTION_WORKERS", 4)),
    "llm_requests_per_minute": int(os.environ.get("LLM_RPM", 60)),
    "llm_tokens_per_minute": int(os.environ.get("LLM_TPM", 90000)),
    "llm_max_concurrent": int(os.environ.get("LLM_CONCURRENT", 10)),
    "timeout_per_filing": int(os.environ.get("FILING_TIMEOUT", 300)),
}
```

---

## Verification Commands

```bash
# Benchmark single-threaded
time python scripts/run_extraction.py --filing-ids 1,2,3,4,5 --workers 1

# Benchmark multi-threaded
time python scripts/run_extraction.py --filing-ids 1,2,3,4,5 --workers 4

# Monitor rate limiting
python scripts/run_extraction.py --filing-ids $(seq -s, 1 100) --workers 8 --verbose

# Check for data integrity
pytest tests/integration/test_parallel_extraction.py -v
```

---

## Expected Results

| Metric | Single-threaded | 4 Workers | 8 Workers |
|--------|-----------------|-----------|-----------|
| Throughput | 1x | 3-4x | 5-7x |
| LLM utilization | ~20% | ~60% | ~80% |
| DB connections | 1 | 4 | 8 |
| Runtime (7k filings) | 5 days | 1.5 days | 1 day |

---

## Risk Mitigation

- **DB contention**: Use connection pooling, test under load
- **LLM rate limits**: Token bucket ensures compliance
- **Data corruption**: Each filing processed independently, no shared state
- **Error isolation**: Failed filings don't affect others
- **Progress recovery**: Track processed IDs for resume
