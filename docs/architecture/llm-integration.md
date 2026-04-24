# LLM Integration - OpenAI GPT-4o / GPT-4o-mini

**Date:** 2026-04-08
**Status:** Production
**Pipeline:** V2 (sole production pipeline)

---

## Overview

This document describes the LLM integration in the V2 extraction pipeline. The integration uses two OpenAI models with distinct roles: GPT-4o-mini for text-based extraction tasks and GPT-4o for vision/chart analysis. A PostgreSQL-backed cache reduces costs and latency for repeated prompts.

## Architecture

### Integration Approach

**Hybrid Model: Rule-Based First, LLM for Vision**

```
┌─────────────────────────────────────────────────────────────┐
│                   V2 EXTRACTION PIPELINE                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Stage 1: Ingestion (lxml parsing, segmentation)            │
│  Stage 2: Candidate Generation (keyword matching)           │
│  Stage 3: Section Classification (rule-based)               │
│                                                              │
│  ┌────────────────────────────────────────────────┐        │
│  │ Stage 4: Image Triage (rule-based)             │        │
│  │  • Classify images: CHART, TABLE_IMAGE, etc.   │        │
│  │  • Score relevance from section context        │        │
│  │  • Queue high-relevance images for Stage 5     │        │
│  └────────────────────────────────────────────────┘        │
│                                                              │
│  ┌────────────────────────────────────────────────┐        │
│  │ Stage 5: OCR & Chart Extraction         ← LLM  │        │
│  │  • TABLE_IMAGE: OCR API to extract text        │        │
│  │  • CHART: VisionClient (GPT-4o) for labeled    │        │
│  │    data values only (no interpolation)         │        │
│  └────────────────────────────────────────────────┘        │
│                                                              │
│  Stage 6:  Value Binding (rule-based)                       │
│  Stage 7:  Period Inference (rule-based)                    │
│  Stage 8:  Deduplication (rule-based)                       │
│  Stage 9:  False Positive Filter (rule-based, 13 rules)     │
│  Stage 9.5: Definition Extraction (rule-based, no LLM)      │
│  Stage 10: Fact Construction (rule-based)                   │
│  Stage 11: Validation (rule-based)                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key design points:**
- LLM is invoked only in Stage 5, and only when `enable_image_extraction=True` in `PipelineConfig`
- Definition extraction (Stage 9.5) is pure rule-based in V2 — no LLM calls
- Value binding (Stage 6) is pure rule-based — no LLM calls
- Text-based stages use `OpenAIClient` (GPT-4o-mini) when needed; image stages use `VisionClient` (GPT-4o)
- All `OpenAIClient` calls pass through the PostgreSQL-backed `LLMCache` automatically

---

## Components

### 1. OpenAI Client (`src/llm/openai_client.py`)

**Class:** `OpenAIClient`

**Features:**
- Automatic retry with exponential backoff (3 retries)
- Token counting using tiktoken
- Real-time cost tracking per request
- Cumulative cost statistics
- Rate limiting support
- Comprehensive error handling
- Transparent PostgreSQL-backed response caching (via `LLMCache`)

**Configuration:**
```python
client = OpenAIClient(
    model="gpt-4o-mini",           # Cost-efficient model
    temperature=0.1,                # Deterministic (low randomness)
    max_tokens=4096,                # Max response length
    max_retries=3,                  # Retry failed requests
    retry_delay=1.0,                # Initial delay (exponential)
    cache_config=None,              # Uses LLM_CACHE_ENABLED env var by default
)
```

**Key Methods:**
- `complete(prompt, system_message)` - Single completion request (checks cache first, stores on miss)
- `complete_batch(prompts, ...)` - Batch processing with rate limiting
- `count_tokens(text)` - Count tokens in text
- `calculate_cost(input, output)` - Calculate request cost
- `get_cost_summary()` - Get cumulative statistics
- `get_cache_stats()` - Get cache hit rate and savings statistics
- `clear_cache()` - Clear cached responses for the current cache version

**Error Handling:**
- `RateLimitError` - Automatic retry with backoff
- `APIConnectionError` - Retry network failures
- `APIError` - Retry 5xx errors, fail on 4xx

### 2. Vision Client (`src/llm/vision_client.py`)

**Class:** `VisionClient`

**Purpose:** Sends chart and table images to GPT-4o Vision to extract structured data. Used exclusively in Stage 5 (OCR & Chart Extraction) when image extraction is enabled.

**Design principle:** "Charts only when labeled" — the client extracts only data values explicitly labeled on a chart. It never interpolates values from axis positions.

**Phase 2 prompt additions (2026-04-16):** The chart extraction prompt passed to `VisionClient` was extended with two additive hint blocks. Block A provides cohort-vintage vs. elapsed-period guidance (helping the model distinguish "Year 1/2/3" elapsed-period charts from "2019/2020/2021" vintage-cohort charts). Block B provides a worked example. The prompt is still one Vision call per chart with no schema changes.

**Features:**
- MIME type detection from magic bytes (JPEG, PNG, GIF, WebP)
- Configurable image detail level (`high` for accuracy, `low` for speed/cost)
- Retry logic with exponential backoff (same error handling as `OpenAIClient`)
- Per-request cost tracking

**Configuration:**
```python
client = VisionClient(model="gpt-4o")  # Default: gpt-4o
```

**Key Methods:**
- `analyze_image(image_bytes, prompt, *, detail, max_tokens, max_retries)` - Send image bytes to GPT-4o Vision and return a `VisionResponse`

**Response dataclass (`VisionResponse`):**

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str` | LLM response text |
| `model` | `str` | Model identifier used |
| `prompt_tokens` | `int` | Tokens in prompt (including image encoding) |
| `completion_tokens` | `int` | Tokens in completion |
| `cost_usd` | `float` | Estimated cost for this request |
| `latency_ms` | `int` | Request latency in milliseconds |

**Error Handling:**
- `ValueError` - Empty image bytes or empty prompt (fails immediately, no retry)
- `RateLimitError` - Automatic retry with exponential backoff
- `APIConnectionError` - Retry with backoff
- `APIError` (5xx) - Retry with backoff; 4xx errors raise immediately

**Supported image formats:**
- JPEG, PNG, GIF, WebP (detected from magic bytes; defaults to PNG if unknown)

**Pipeline integration (Stage 5):**
```python
# Lazily imported in OCRExtractionStage to avoid hard dependency
from src.llm.vision_client import VisionClient

client = VisionClient()
response = client.analyze_image(
    image_bytes=image_data,
    prompt="Extract labeled data values from this chart...",
    detail="high",
)
```

### 2.1 Chart Fact Bridge — metric-presence emission (post-processing, no LLM)

**Module:** `src/extraction_v2/stages/chart_fact_bridge.py` (stage `PipelineStage.CHART_FACT_BRIDGE`)

**Purpose:** Emits image-level *metric-presence* records from the structured `ChartData` produced by Stage 5's Vision call. Writes `[{metric_id, score}, ...]` to `v2_image_assets.detected_metrics`. **This is not an LLM call** — it is deterministic post-processing of already-extracted chart output. No second Vision request is made. Under the chart-presence pivot (#86, 2026-04-23), the bridge does **not** emit per-value `MetricFact` rows; reviewers adjudicate the presence signal via `v2_image_metric_confirmations`.

**Classifier** (rule-based, no LLM):
- `src/extraction_v2/chart/metric_classifier.py` — `ChartMetricClassifier.classify_all(chart, nearby_text)` scores each `ChartData` against patterns from `config/metric_keywords.yaml` and returns a list of `(canonical_metric_id, score)` pairs for every metric that passes the cohort + metric gates. Score threshold for emission: `PipelineConfig.chart_presence_min_score` (default 0.5).

**Cost:** zero incremental LLM cost. Bridge consumes `ImageAsset.chart_data` populated by Stage 5 and writes `ImageAsset.detected_metrics`. The retired per-value hallucination guards (image-confidence gate, label-required gate, axis-range sanity, cohort-year sanity, fact review threshold), `CohortParser`-based value emission, and `unit_inference` are all moot post-pivot because no per-value facts are produced.

### 3. Prompt Templates (`src/llm/prompts.py`)

**Class:** `PromptTemplates`

**System Messages:**
1. `SYSTEM_VALUE_EXTRACTION` - Expert role for value extraction
2. `SYSTEM_DEFINITION_EXTRACTION` - Expert role for definition extraction

**Prompt Methods:**

| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `value_extraction_from_text()` | Extract values from text segments | segment_text, metric_names, context_text | JSON array of values |
| `value_extraction_from_table()` | Extract values from table segments | table_text, table_html, metric_names, context_text | JSON array with row/col labels |
| `definition_extraction()` | Extract metric definitions | segment_text, metric_names | JSON array of definitions |
| `classification_prompt()` | Classify segment content | segment_text | JSON with classification flags |

**Output Format:**

All prompts return structured JSON for easy parsing:

```json
// Value Extraction
[
  {
    "metric_name": "monthly_active_users",
    "value": "125",
    "units": "millions",
    "period": "December 31, 2023",
    "cohort_label": null,
    "quote": "As of December 31, 2023, we had 125 million MAU."
  }
]

// Definition Extraction
[
  {
    "metric_name": "monthly_active_users",
    "definition_text": "users who logged in at least once in a calendar month",
    "includes_calculation": false,
    "quote": "We define MAU as users who logged in at least once..."
  }
]
```

**Utility Methods:**
- `parse_json_response(text)` - Robust JSON parsing with markdown handling
- `validate_value_extraction_response(data)` - Schema validation
- `validate_definition_extraction_response(data)` - Schema validation

### 4. LLM Response Cache (`src/llm/cache.py`)

**Class:** `LLMCache`

**Purpose:** PostgreSQL-backed cache for LLM API responses. Reduces costs and latency when the same prompt is submitted multiple times (e.g., reprocessing a filing after a bug fix). Integrated transparently into `OpenAIClient.complete()`.

**Cache key:** SHA-256 hash of `{model, system_message, prompt, temperature, max_tokens}` (normalized: whitespace stripped, kwargs sorted).

**Configuration via environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CACHE_ENABLED` | `true` | Set to `false` to disable caching entirely |
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `LLM_CACHE_VERSION` | `v1` | Cache namespace; increment to invalidate all entries without deleting rows |

**Configuration dataclass (`CacheConfig`):**
```python
config = CacheConfig(
    enabled=True,           # Read from LLM_CACHE_ENABLED
    connection_string="...",# Read from DATABASE_URL
    cache_version="v1",     # Read from LLM_CACHE_VERSION
    max_age_days=30,        # Entries older than this are ignored on read
)
```

**Database schema (auto-created on init):**
```sql
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key         TEXT PRIMARY KEY,
    cache_version     TEXT NOT NULL,
    model             TEXT NOT NULL,
    response_content  TEXT NOT NULL,
    input_tokens      INTEGER NOT NULL,
    output_tokens     INTEGER NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
```

**Key Methods:**

| Method | Description |
|--------|-------------|
| `get(model, system_message, prompt, temperature, max_tokens)` | Returns `CachedResponse` on hit, `None` on miss |
| `set(model, system_message, prompt, ..., response_content, input_tokens, output_tokens)` | Stores response (upserts on conflict) |
| `stats()` | Returns hit rate, total entries, and token savings for current session |
| `clear(version_only=True)` | Deletes entries for current version (or all entries if `version_only=False`) |
| `cleanup_expired()` | Removes entries older than `max_age_days` |

**Thread safety:** All database operations use a threading lock. The cache maintains a single persistent connection and reconnects automatically on `OperationalError`.

**Invalidating the cache:**

To invalidate all cached responses without dropping rows (e.g., after a prompt change):
```bash
LLM_CACHE_VERSION=v2  # Increment in .env or environment
```

Entries from the old version remain in the table but are ignored on reads.

---

## Cost Analysis

### Model Pricing

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Use case |
|-------|----------------------|------------------------|----------|
| GPT-4o-mini | $0.15 | $0.60 | Text extraction prompts |
| GPT-4o | $2.50 | $10.00 | Vision/chart extraction |

### Projected Costs

**Text extraction (GPT-4o-mini):**
- Average S-1 filing: ~50,000 words = ~67,000 tokens
- 10 LLM calls per filing
- Average output: ~100 tokens per call
- **Total: ~$0.10 per filing**

**Vision extraction (GPT-4o):**
- Cost depends on image count and detail level
- `detail="high"` uses significantly more tokens than `detail="low"`
- Only incurred when `enable_image_extraction=True` in `PipelineConfig`

**Cache impact:** Reprocessing a filing after a bug fix costs $0 for any prompt that was already cached, provided the prompt text, model, and temperature are unchanged and the cache version has not been incremented.

---

## Usage Examples

### Basic Text Extraction

```python
from src.llm.openai_client import OpenAIClient
from src.llm.prompts import PromptTemplates

# Initialize client (cache enabled by default via LLM_CACHE_ENABLED)
client = OpenAIClient(model="gpt-4o-mini")

# Extract values from text
segment_text = "We had 125 million MAU in Q4 2023..."
prompt = PromptTemplates.value_extraction_from_text(
    segment_text=segment_text,
    metric_names="monthly_active_users, customer_count"
)

response = client.complete(
    prompt,
    system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION
)

# Parse response
data = PromptTemplates.parse_json_response(response.content)
for item in data:
    print(f"{item['metric_name']}: {item['value']} {item['units']}")

# Check costs
summary = client.get_cost_summary()
print(f"Total cost: ${summary['total_cost_usd']}")
print(f"Cache stats: {client.get_cache_stats()}")
```

### Vision / Chart Extraction

```python
from src.llm.vision_client import VisionClient

client = VisionClient()  # Uses gpt-4o by default

with open("chart.png", "rb") as f:
    image_bytes = f.read()

response = client.analyze_image(
    image_bytes=image_bytes,
    prompt="Extract all explicitly labeled data values from this chart. "
           "Return a JSON array of {label, value, period} objects. "
           "Do not interpolate any values.",
    detail="high",
)

print(response.content)
print(f"Cost: ${response.cost_usd:.4f}, latency: {response.latency_ms}ms")
```

### Batch Processing

```python
# Process multiple segments
segments = [segment1, segment2, segment3]

prompts = [
    PromptTemplates.value_extraction_from_text(seg, "active_users")
    for seg in segments
]

responses = client.complete_batch(
    prompts,
    system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION,
    delay_between_requests=0.1  # Rate limiting
)

# Aggregate results
all_values = []
for response in responses:
    data = PromptTemplates.parse_json_response(response.content)
    all_values.extend(data)
```

---

## Best Practices

### 1. Token Management

- Chunk large filings into segments (~8,000 chars)
- Count tokens before sending to estimate costs
- Use tiktoken for accurate token counting
- Do not send entire filings in one request

### 2. Error Handling

- Always have a rule-based fallback path
- Log all LLM failures for analysis
- Retry on transient errors (rate limits, network)
- Do not retry on 4xx errors

### 3. Prompt Engineering

- Use structured JSON output format
- Provide clear examples in prompts
- Specify units and formats explicitly
- Include relevant context in prompts

### 4. Cost Optimization

- Use GPT-4o-mini for text extraction tasks
- Use GPT-4o only for vision/chart extraction
- Keep `LLM_CACHE_ENABLED=true` in all environments to avoid duplicate API calls
- Monitor cumulative costs via `get_cost_summary()`
- Set `detail="low"` for image triage; `detail="high"` only for final extraction

---

## Monitoring & Debugging

### Cost Monitoring

```python
# Check costs after processing
summary = client.get_cost_summary()
print(f"Requests: {summary['total_requests']}")
print(f"Tokens: {summary['total_tokens']:,}")
print(f"Cost: ${summary['total_cost_usd']}")
print(f"Avg/request: ${summary['avg_cost_per_request']}")

# Check cache performance
cache_stats = client.get_cache_stats()
print(f"Cache hit rate: {cache_stats['hit_rate']}%")
print(f"Cached entries: {cache_stats['total_entries']}")

# Alert if cost exceeds threshold
if summary['total_cost_usd'] > 5.0:
    logger.warning(f"Cost threshold exceeded: ${summary['total_cost_usd']}")
```

### Response Validation

```python
# Validate response structure
response = client.complete(prompt)
data = PromptTemplates.parse_json_response(response.content)

if not PromptTemplates.validate_value_extraction_response(data):
    logger.error("Invalid response structure")
    # Fall back to rule-based extraction
```

### Debugging Failed Extractions

```python
# Log full context for failed extractions
try:
    response = client.complete(prompt)
    data = PromptTemplates.parse_json_response(response.content)
except Exception as e:
    logger.error(f"Extraction failed: {e}")
    logger.debug(f"Prompt: {prompt[:500]}")
    logger.debug(f"Response: {response.content if response else 'None'}")
    # Fall back to rules
```

---

## Component Summary

| Component | File | Model | Used in |
|-----------|------|-------|---------|
| `OpenAIClient` | `src/llm/openai_client.py` | gpt-4o-mini | Text extraction (when called explicitly) |
| `VisionClient` | `src/llm/vision_client.py` | gpt-4o | V2 Stage 5 — OCR & Chart Extraction |
| `LLMCache` | `src/llm/cache.py` | n/a | Transparently via `OpenAIClient.complete()` |
| `PromptTemplates` | `src/llm/prompts.py` | n/a | Prompt construction and response parsing |
| `ChartFactBridgeStage` | `src/extraction_v2/stages/chart_fact_bridge.py` | **none (rule-based)** | Post-processes Stage 5 `ChartData` into `v2_image_assets.detected_metrics` (metric-presence records; no `MetricFact` rows post-#86) |
| `ChartMetricClassifier` | `src/extraction_v2/chart/metric_classifier.py` | **none (rule-based)** | Classifies `ChartData` against YAML patterns |

---

## Dependencies

```txt
# requirements.txt
openai>=1.0.0      # OpenAI API client
tiktoken>=0.5.0    # Token counting
psycopg[binary]    # PostgreSQL (for LLMCache)
```

**Environment:**
```bash
export OPENAI_API_KEY="sk-..."
export DATABASE_URL="postgresql://..."    # Required for LLMCache
export LLM_CACHE_ENABLED="true"          # Default: true
export LLM_CACHE_VERSION="v1"            # Increment to invalidate cache
```

---

## References

- **OpenAI API Docs:** https://platform.openai.com/docs/api-reference
- **GPT-4o Pricing:** https://openai.com/api/pricing/
- **tiktoken:** https://github.com/openai/tiktoken
- **V2 Pipeline:** `docs/architecture/extraction-v2-pipeline.md`
