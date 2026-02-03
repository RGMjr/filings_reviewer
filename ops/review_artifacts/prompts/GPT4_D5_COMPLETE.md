# GPT-4 Code Review: D5 Performance

**Copy this entire prompt and paste into GPT-4**

---

You are a performance engineer reviewing a Python SEC filing extraction system.

## Performance Profile

| Metric | Value |
|--------|-------|
| Filing processing | 9-17 seconds each |
| Full corpus | 7,304 filings |
| Projected runtime | 2-5 days |
| LLM cost | ~$0.10/filing |
| Total projected cost | $500-$1,000 |

**Primary Bottleneck**: LLM calls account for 50-70% of extraction time.

## Current Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Per-Filing Pipeline                  │
├─────────────────────────────────────────────────────┤
│ 1. HTML Parsing (~1-2s)                             │
│ 2. Segment Classification (~0.5s)                   │
│ 3. Segment Enrichment (~0.5s)                       │
│ 4. Value Extraction (LLM) (~5-12s) ← BOTTLENECK    │
│ 5. Quality Scoring (~0.1s)                          │
│ 6. Database Write (~0.5s)                           │
└─────────────────────────────────────────────────────┘
           ↓ Sequential (no parallelization)
```

## Parallelization Status

| Component | Parallelized? | Notes |
|-----------|--------------|-------|
| Filing processing | No | Sequential |
| LLM calls | No | Sequential with rate limit |
| Sentence detection | Yes | ThreadPoolExecutor(4) |
| DB writes | No | Transactional batches |

## Caching Status

| Cache | Scope | Invalidation |
|-------|-------|--------------| 
| Heading cache | Per-filing | **Never** (potential issue) |
| Keyword patterns | Global | @lru_cache |
| Filing HTML | Disk | Manual |
| LLM responses | **None** | Not implemented |

## Review Questions

1. **LLM Caching**: Could caching reduce costs/time significantly?
2. **Filing Parallelization**: What's blocking parallel filing processing?
3. **N+1 Queries**: Are there N+1 patterns in db.py (4,006 LOC)?
4. **Memory Usage**: Are large filings causing memory issues?
5. **Batch Operations**: Should LLM calls be truly batched?
6. **Profiling**: Are there profiling/benchmarking tools in place?

## Output Format

```json
{
  "dimension": "D5_PERFORMANCE",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D5-001",
      "severity": "Critical|High|Medium|Low",
      "category": "performance",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "current_impact": "How it affects performance now",
      "optimization_potential": "Expected improvement",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall performance assessment"
}
```

Provide 8-12 findings focusing on speed and cost optimization.



---

# ACTUAL SOURCE CODE

## src/llm/openai_client.py

```python
"""
OpenAI API Client with error handling, retry logic, and cost tracking.

This module provides a robust wrapper around the OpenAI API with:
- Automatic retry with exponential backoff
- Token counting and cost tracking
- Rate limiting
- Comprehensive error handling
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    import tiktoken
except ImportError:
    tiktoken = None

try:
    from openai import APIConnectionError, APIError, OpenAI, RateLimitError
except ImportError as e:
    raise ImportError("OpenAI package not installed. Run: pip install openai tiktoken") from e

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM with metadata."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    latency_ms: int
    timestamp: datetime


@dataclass
class CostTracker:
    """Track cumulative LLM API costs."""

    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    failed_requests: int = 0

    def add_request(self, response: LLMResponse):
        """Add a successful request to tracking."""
        self.total_requests += 1
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cost += response.cost

    def add_failure(self):
        """Record a failed request."""
        self.failed_requests += 1

    def summary(self) -> dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "avg_cost_per_request": (
                round(self.total_cost / self.total_requests, 4)
                if self.total_requests > 0
                else 0
            ),
        }


class OpenAIClient:
    """
    OpenAI API client with robust error handling and cost tracking.

    Features:
    - Automatic retry with exponential backoff
    - Token counting using tiktoken
    - Cost tracking per request and cumulative
    - Rate limiting
    - Comprehensive error handling
    """

    # Pricing per 1M tokens (as of 2025-01)
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o-mini)
            temperature: Sampling temperature (0.0-2.0, default: 0.1 for deterministic)
            max_tokens: Maximum tokens in response
            max_retries: Number of retries on failure
            retry_delay: Initial delay between retries (exponential backoff)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize tokenizer for counting
        if tiktoken:
            try:
                self.tokenizer = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to cl100k_base for newer models
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
                logger.warning(
                    f"No tokenizer for {model}, using cl100k_base as fallback"
                )
        else:
            self.tokenizer = None
            logger.warning("tiktoken not installed, token counting will be estimated")

        # Cost tracking
        self.cost_tracker = CostTracker()

        logger.info(f"OpenAI client initialized with model: {model}")

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Input text

        Returns:
            Token count
        """
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Rough estimate: 1 token ≈ 4 characters
            return len(text) // 4

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost for a request.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        pricing = self.PRICING.get(self.model, self.PRICING["gpt-4o-mini"])

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def complete(
        self,
        prompt: str,
        system_message: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Send completion request to OpenAI API with retry logic.

        Args:
            prompt: User prompt
            system_message: Optional system message
            **kwargs: Additional arguments to pass to API

        Returns:
            LLMResponse with content and metadata

        Raises:
            APIError: If all retries fail
        """
        # Build messages
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        # Count input tokens
        input_text = (system_message or "") + prompt
        input_tokens = self.count_tokens(input_text)

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                # Make API call
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs,
                )

                latency_ms = int((time.time() - start_time) * 1000)

                # Extract response
                content = response.choices[0].message.content
                output_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens

                # Calculate cost
                cost = self.calculate_cost(input_tokens, output_tokens)

                # Create response object
                llm_response = LLMResponse(
                    content=content,
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    timestamp=datetime.now(),
                )

                # Track cost
                self.cost_tracker.add_request(llm_response)

                logger.debug(
                    f"LLM request successful: {output_tokens} tokens, ${cost:.4f}, {latency_ms}ms"
                )

                return llm_response

            except RateLimitError as e:
                last_error = e
                delay = self.retry_delay * (2**attempt)
                logger.warning(
                    f"Rate limit hit, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

            except APIConnectionError as e:
                last_error = e
                delay = self.retry_delay * (2**attempt)
                logger.warning(
                    f"Connection error, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

            except APIError as e:
                last_error = e
                # Don't retry on 4xx errors (except rate limit)
                if hasattr(e, "status_code") and 400 <= e.status_code < 500:
                    logger.error(f"API error (non-retryable): {e}")
                    self.cost_tracker.add_failure()
                    raise
                else:
                    delay = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"API error, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(delay)

        # All retries exhausted
        self.cost_tracker.add_failure()
        logger.error(f"All {self.max_retries} retries exhausted")
        raise last_error

    def complete_batch(
        self,
        prompts: list[str],
        system_message: str | None = None,
        delay_between_requests: float = 0.1,
    ) -> list[LLMResponse]:
        """
        Send multiple completion requests with rate limiting.

        Args:
            prompts: List of user prompts
            system_message: Optional system message for all prompts
            delay_between_requests: Delay between requests (seconds)

        Returns:
            List of LLMResponse objects
        """
        responses = []

        for i, prompt in enumerate(prompts):
            logger.info(f"Processing prompt {i + 1}/{len(prompts)}")

            try:
                response = self.complete(prompt, system_message=system_message)
                responses.append(response)
            except Exception as e:
                logger.error(f"Failed to process prompt {i + 1}: {e}")
                # Continue with next prompt
                continue

            # Rate limiting delay
            if i < len(prompts) - 1:
                time.sleep(delay_between_requests)

        return responses

    def get_cost_summary(self) -> dict[str, Any]:
        """Get cumulative cost tracking summary."""
        return self.cost_tracker.summary()

    def reset_cost_tracker(self):
        """Reset cost tracking to zero."""
        self.cost_tracker = CostTracker()
        logger.info("Cost tracker reset")
```

## src/extraction/extraction_pipeline.py

```python
"""
Extraction Pipeline - End-to-end metric extraction orchestration.

This module orchestrates the complete extraction pipeline:
1. HTML Segmentation
2. Metric Classification
3. Value Extraction
4. Definition Extraction
5. Quality Scoring
6. Database Storage
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.infra.db import DatabaseAdapter

from .definition_extractor import DefinitionExtractor
from .html_segmenter import HTMLSegmenter
from .metric_classifier import MetricClassifier
from .models import (
    FilingMetricIncidence,
    MetricDefinition,
    MetricValue,
    SourceSegment,
)
from .quality_scorer import QualityScorer
from .segment_enricher import SegmentEnricher, cluster_goldmine_segments
from .value_extractor import ValueExtractor

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of processing a single filing."""

    filing_id: int
    success: bool
    error: str | None = None
    num_segments: int = 0
    num_values: int = 0
    num_definitions: int = 0
    num_incidences: int = 0


class ExtractionPipeline:
    """
    Orchestrate the complete metric extraction pipeline.

    Pipeline stages:
    1. Segment HTML into source_segments
    2. Classify segments for metric content
    3. Extract numeric values from segments
    4. Extract definitions and methodologies
    5. Compute quality scores and incidence
    6. Write all results to database
    """

    def __init__(
        self, db: DatabaseAdapter, llm_client: Optional["OpenAIClient"] = None
    ):
        """
        Initialize the extraction pipeline.

        Args:
            db: Database adapter
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, extractors will use LLM with rule-based fallback.
                       If not provided, only rule-based extraction will be used.
        """
        self.db = db
        self.llm_client = llm_client
        self.segmenter = HTMLSegmenter()
        self.classifier = MetricClassifier()
        self.enricher = SegmentEnricher()
        self.value_extractor = ValueExtractor(llm_client=llm_client)
        self.definition_extractor = DefinitionExtractor(llm_client=llm_client)
        self.quality_scorer = QualityScorer()

        if llm_client:
            logger.info("✓ Pipeline initialized with LLM-enhanced extraction and enrichment")
        else:
            logger.info("✓ Pipeline initialized with rule-based extraction and enrichment")

    def process_filing(self, filing_id: int) -> ExtractionResult:
        """
        Run full extraction pipeline for a single filing.

        Steps:
            1. Fetch filing metadata from database
            2. Segment HTML
            3. Classify segments
            4. Extract values
            5. Extract definitions
            6. Compute quality scores
            7. Write all to database in a transaction

        Args:
            filing_id: Database filing ID

        Returns:
            ExtractionResult with processing summary
        """
        logger.info(f"Processing filing {filing_id}")

        try:
            # Step 0: Fetch filing metadata
            filing = self._get_filing_metadata(filing_id)
            if not filing:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="Filing not found in database",
                )

            # Step 1: Segment HTML
            logger.info("  Stage 1: Segmenting HTML")
            segments = self.segmenter.segment_filing(
                filing_id=filing_id, html_path=filing["html_storage_path"]
            )

            if not segments:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="No segments extracted from HTML",
                )

            # Step 2: Classify segments
            logger.info(f"  Stage 2: Classifying {len(segments)} segments")
            classified_segments = self.classifier.classify_batch(segments)

            # Step 2b: Enrich segments with richness metadata
            logger.info(f"  Stage 2b: Enriching {len(classified_segments)} segments")
            self.enricher.enrich_batch(classified_segments)  # mutates in place

            # Step 2c: Tiered segment selection
            logger.info("  Stage 2c: Selecting segments via tiered prioritization")
            selected_segments = self._select_segments_tiered(classified_segments)

            # Log goldmine statistics
            goldmines = [s for s in selected_segments if (s.richness_score or 0) >= 6.0]
            clusters = cluster_goldmine_segments(goldmines) if goldmines else []
            logger.info(f"  Identified {len(goldmines)} goldmine segments in {len(clusters)} clusters")

            # Step 3: Extract values (from selected segments)
            logger.info(f"  Stage 3: Extracting values from {len(selected_segments)} segments")
            all_values = []
            for seg in selected_segments:
                values = self.value_extractor.extract_from_segment(
                    seg, company_id=filing["company_id"]
                )
                all_values.extend(values)

            # Step 4: Extract definitions (from selected segments)
            logger.info(f"  Stage 4: Extracting definitions from {len(selected_segments)} segments")
            definitions = self.definition_extractor.extract_definitions(
                selected_segments, company_id=filing["company_id"]
            )

            # Step 5: Compute quality scores (based on selected segments)
            logger.info("  Stage 5: Computing quality scores")
            incidences = self.quality_scorer.score_filing(
                filing_id=filing_id,
                company_id=filing["company_id"],
                segments=selected_segments,
                values=all_values,
                definitions=definitions,
            )

            # Step 6: Write to database
            logger.info("  Stage 6: Writing to database")
            self._write_results(
                filing_id, selected_segments, all_values, definitions, incidences
            )

            logger.info(f"✓ Successfully processed filing {filing_id}")
            logger.info(
                f"    Total segments: {len(classified_segments)}, Selected: {len(selected_segments)}, "
                + f"Goldmines: {len(goldmines)}, Values: {len(all_values)}, "
                + f"Definitions: {len(definitions)}, Incidences: {len(incidences)}"
            )

            return ExtractionResult(
                filing_id=filing_id,
                success=True,
                num_segments=len(selected_segments),
                num_values=len(all_values),
                num_definitions=len(definitions),
                num_incidences=len(incidences),
            )

        except (ValueError, KeyError) as e:
            # Data/validation errors - filing data is invalid or missing expected fields
            logger.error(
                f"✗ Data error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except OSError as e:
            # File system errors - HTML file not found or unreadable
            logger.error(
                f"✗ File error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except Exception as e:
            # Unexpected errors - log with full details for debugging
            logger.critical(
                f"✗ Unexpected error processing filing {filing_id}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

    def process_batch(self, filing_ids: list[int]) -> dict[str, int]:
        """
        Process multiple filings.

        Args:
            filing_ids: List of filing IDs to process

        Returns:
            Statistics dictionary with counts
        """
        logger.info(f"Processing batch of {len(filing_ids)} filings")

        stats = {
            "total": len(filing_ids),
            "success": 0,
            "failed": 0,
            "total_segments": 0,
            "total_values": 0,
            "total_definitions": 0,
            "total_incidences": 0,
        }

        for i, filing_id in enumerate(filing_ids):
            logger.info(f"[{i+1}/{len(filing_ids)}] Processing filing {filing_id}")

            result = self.process_filing(filing_id)

            if result.success:
                stats["success"] += 1
                stats["total_segments"] += result.num_segments
                stats["total_values"] += result.num_values
                stats["total_definitions"] += result.num_definitions
                stats["total_incidences"] += result.num_incidences
            else:
                stats["failed"] += 1
                logger.error(f"  Failed: {result.error}")

        logger.info("")
        logger.info("=" * 80)
        logger.info("Batch Processing Summary")
        logger.info("=" * 80)
        logger.info(f"Total filings: {stats['total']}")
        logger.info(f"Successful: {stats['success']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info(f"Total segments: {stats['total_segments']}")
        logger.info(f"Total values: {stats['total_values']}")
        logger.info(f"Total definitions: {stats['total_definitions']}")
        logger.info(f"Total incidences: {stats['total_incidences']}")
        logger.info("=" * 80)

        return stats

    def _get_filing_metadata(self, filing_id: int) -> dict | None:
        """Fetch filing metadata from database."""
        result = self.db.query(
            """
            SELECT filing_id, company_id, cik, accession_number, html_storage_path
            FROM filings
            WHERE filing_id = %(filing_id)s
        """,
            {"filing_id": filing_id},
        )

        if not result:
            return None

        filing = result[0]

        # Check if HTML file exists
        if (
            not filing["html_storage_path"]
            or not Path(filing["html_storage_path"]).exists()
        ):
            logger.error(f"HTML file not found: {filing['html_storage_path']}")
            return None

        return filing

    def _select_segments_tiered(
        self, segments: list[SourceSegment]
    ) -> list[SourceSegment]:
        """
        Select segments using tiered prioritization.

        Tiers (processed in order, deduplicated):
        1. High richness (>= 6.0) - up to 30 segments
        2. Medium richness (4.0-6.0) - up to 40 segments
        3. Critical flags (definitions/methodologies) - remainder up to 80 total

        Args:
            segments: Enriched segments with richness_score populated

        Returns:
            Selected segments, deduplicated and sorted by richness
        """
        RICHNESS_THRESHOLD = 6.0
        MEDIUM_THRESHOLD = 4.0
        MAX_HIGH_RICHNESS = 30
        MAX_MEDIUM_RICHNESS = 40
        MAX_TOTAL = 80

        selected_ids: set[int] = set()  # Use object id for deduplication
        result: list[SourceSegment] = []

        # Tier 1: High richness (goldmines)
        high_richness = sorted(
            [s for s in segments if (s.richness_score or 0) >= RICHNESS_THRESHOLD],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_HIGH_RICHNESS]

        for seg in high_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        high_count = len(result)

        # Tier 2: Medium richness (supporting context)
        medium_richness = sorted(
            [
                s
                for s in segments
                if MEDIUM_THRESHOLD <= (s.richness_score or 0) < RICHNESS_THRESHOLD
            ],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_MEDIUM_RICHNESS]

        for seg in medium_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        # NEW: Direct Hit Tier (Specific matches with lower richness)
        # Allows short segments that are highly specific (e.g. "Churn rate was 5%")
        # Threshold: 3.0 (Lower than medium)
        DIRECT_HIT_THRESHOLD = 3.0
        direct_hits = [
            s for s in segments
            if (s.richness_score or 0) >= DIRECT_HIT_THRESHOLD
            and (s.richness_score or 0) < MEDIUM_THRESHOLD
            and s.candidate_metric_ids
            and len(s.candidate_metric_ids) == 1 # Very specific
            and s.contains_numeric_disclosure_flag # Must have numbers
        ]

        for seg in direct_hits:
            if len(result) >= MAX_TOTAL:
                break
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        medium_count = len(result) - high_count

        # Tier 3: Critical flags (definitions/methodologies)
        critical = [
            s
            for s in segments
            if (s.contains_definition_flag or s.contains_methodology_flag)
            and id(s) not in selected_ids
        ]

        critical_count = 0
        for seg in critical:
            if len(result) >= MAX_TOTAL:
                break
            result.append(seg)
            selected_ids.add(id(seg))
            critical_count += 1

        logger.info(
            f"  Selected: {high_count} high-richness, {medium_count} medium-richness, "
            f"{critical_count} critical (total: {len(result)})"
        )

        return result

    def _write_results(
        self,
        filing_id: int,
        segments: list[SourceSegment],
        values: list[MetricValue],
        definitions: list[MetricDefinition],
        incidences: list[FilingMetricIncidence],
    ):
        """
        Write all extraction results to database in a transaction.

        Args:
            filing_id: Filing ID
            segments: Source segments
            values: Metric values
            definitions: Metric definitions
            incidences: Filing-metric incidences
        """
        # Use database transaction for atomicity
        # If any insert fails, everything rolls back

        cleanup_sql = [
            "DELETE FROM filing_metric_incidence WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_definitions WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_values WHERE filing_id = %(filing_id)s",
            "DELETE FROM source_segments WHERE filing_id = %(filing_id)s",
        ]

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Remove any prior extraction artifacts for this filing so re-runs are idempotent.
                for statement in cleanup_sql:
                    cur.execute(statement, {"filing_id": filing_id})

                # Insert source segments
                segment_id_map: dict[int, int] = {}
                for seg in segments:
                    cur.execute(
                        """
                        INSERT INTO source_segments (
                            filing_id, segment_type, section_path, section_heading,
                            sequence_index, raw_text, raw_html,
                            candidate_metric_ids,
                            contains_definition_flag,
                            contains_methodology_flag,
                            contains_numeric_disclosure_flag,
                            classifier_confidence,
                            metric_density,
                            distinct_metric_count,
                            contains_temporal_trend,
                            contains_cohort_breakdown,
                            image_count,
                            richness_score
                        ) VALUES (
                            %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
                            %(sequence_index)s, %(raw_text)s, %(raw_html)s,
                            %(candidate_metric_ids)s,
                            %(contains_definition_flag)s,
                            %(contains_methodology_flag)s,
                            %(contains_numeric_disclosure_flag)s,
                            %(classifier_confidence)s,
                            %(metric_density)s,
                            %(distinct_metric_count)s,
                            %(contains_temporal_trend)s,
                            %(contains_cohort_breakdown)s,
                            %(image_count)s,
                            %(richness_score)s
                        )
                        RETURNING source_segment_id
                        """,
                        seg.to_dict(),
                    )
                    result = cur.fetchone()
                    if result:
                        db_id = result["source_segment_id"]
                        segment_id_map[seg.sequence_index] = db_id
                        seg.source_segment_id = db_id

                # Update values with actual segment IDs
                valid_values: list[MetricValue] = []
                for val in values:
                    if val.source_segment_id in segment_id_map:
                        val.source_segment_id = segment_id_map[val.source_segment_id]
                        valid_values.append(val)
                    else:
                        logger.warning(
                            "Skipping metric value for filing %s because segment %s was not persisted",
                            filing_id,
                            val.source_segment_id,
                        )

                # Insert metric values
                for val in valid_values:
                    cur.execute(
                        """
                        INSERT INTO metric_values (
                            filing_id, company_id, metric_id, source_segment_id,
                            source_type, extraction_method,
                            value_numeric, value_text, unit, currency,
                            period_start, period_end, period_type,
                            cohort_type, cohort_bucket_raw, cohort_bucket_normalized,
                            segment_dimension, segment_value,
                            qa_status, qa_notes, alignment_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s, %(source_segment_id)s,
                            %(source_type)s, %(extraction_method)s,
                            %(value_numeric)s, %(value_text)s, %(unit)s, %(currency)s,
                            %(period_start)s, %(period_end)s, %(period_type)s,
                            %(cohort_type)s, %(cohort_bucket_raw)s, %(cohort_bucket_normalized)s,
                            %(segment_dimension)s, %(segment_value)s,
                            %(qa_status)s, %(qa_notes)s, %(alignment_flag)s
                        )
                        """,
                        val.to_dict(),
                    )

                # Update definitions with actual segment IDs
                valid_definitions: list[MetricDefinition] = []
                for defn in definitions:
                    if (
                        defn.definition_segment_id is not None
                        and defn.definition_segment_id in segment_id_map
                    ):
                        defn.definition_segment_id = segment_id_map[
                            defn.definition_segment_id
                        ]

                    if (
                        defn.methodology_segment_id is not None
                        and defn.methodology_segment_id in segment_id_map
                    ):
                        defn.methodology_segment_id = segment_id_map[
                            defn.methodology_segment_id
                        ]
                    valid_definitions.append(defn)

                # Insert metric definitions
                for defn in valid_definitions:
                    cur.execute(
                        """
                        INSERT INTO metric_definitions (
                            filing_id, company_id, metric_id,
                            definition_version_in_filing,
                            definition_text_normalized, methodology_text_normalized,
                            definition_raw_text, methodology_raw_text,
                            definition_segment_id, methodology_segment_id,
                            alignment_flag, alignment_notes
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(definition_version_in_filing)s,
                            %(definition_text_normalized)s, %(methodology_text_normalized)s,
                            %(definition_raw_text)s, %(methodology_raw_text)s,
                            %(definition_segment_id)s, %(methodology_segment_id)s,
                            %(alignment_flag)s, %(alignment_notes)s
                        )
                        """,
                        defn.to_dict(),
                    )

                # Update incidences with actual segment IDs
                for inc in incidences:
                    if (
                        inc.primary_definition_segment_id is not None
                        and inc.primary_definition_segment_id in segment_id_map
                    ):
                        inc.primary_definition_segment_id = segment_id_map[
                            inc.primary_definition_segment_id
                        ]
                    elif inc.primary_definition_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_definition_segment_id = None

                    if (
                        inc.primary_methodology_segment_id is not None
                        and inc.primary_methodology_segment_id in segment_id_map
                    ):
                        inc.primary_methodology_segment_id = segment_id_map[
                            inc.primary_methodology_segment_id
                        ]
                    elif inc.primary_methodology_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_methodology_segment_id = None

                # Insert filing-metric incidences
                for inc in incidences:
                    cur.execute(
                        """
                        INSERT INTO filing_metric_incidence (
                            filing_id, company_id, metric_id,
                            metric_disclosed_flag,
                            num_numeric_segments, num_definition_segments, num_methodology_segments,
                            primary_definition_segment_id, primary_methodology_segment_id,
                            quality_overall_score, quality_definition_score,
                            quality_methodology_score, quality_completeness_score,
                            quality_comparability_score,
                            alignment_flag, quality_notes,
                            has_cohort_breakdown_flag, has_tenure_breakdown_flag,
                            has_acquisition_cohort_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(metric_disclosed_flag)s,
                            %(num_numeric_segments)s, %(num_definition_segments)s, %(num_methodology_segments)s,
                            %(primary_definition_segment_id)s, %(primary_methodology_segment_id)s,
                            %(quality_overall_score)s, %(quality_definition_score)s,
                            %(quality_methodology_score)s, %(quality_completeness_score)s,
                            %(quality_comparability_score)s,
                            %(alignment_flag)s, %(quality_notes)s,
                            %(has_cohort_breakdown_flag)s, %(has_tenure_breakdown_flag)s,
                            %(has_acquisition_cohort_flag)s
                        )
                        """,
                        inc.to_dict(),
                    )

        logger.info(f"    Inserted {len(segments)} source segments")
        logger.info(f"    Inserted {len(valid_values)} metric values")
        logger.info(f"    Inserted {len(valid_definitions)} metric definitions")
        logger.info(f"    Inserted {len(incidences)} filing-metric incidences")
```
