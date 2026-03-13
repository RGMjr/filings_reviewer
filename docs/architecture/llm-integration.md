# LLM Integration - OpenAI GPT-4o-mini

**Date:** 2025-12-09
**Status:** ✅ All Phases Complete - Production Ready
**Sprint:** Sprint 3 - LLM Integration (Complete)

---

## Overview

This document describes the integration of OpenAI's GPT-4o-mini model for enhanced metric extraction from SEC S-1 and F-1 filings. The LLM integration augments the existing rule-based extraction pipeline with AI-powered semantic understanding.

## Architecture

### Integration Approach

**Hybrid Model: Rule-Based + LLM Enhancement**

```
┌─────────────────────────────────────────────────────────────┐
│                   EXTRACTION PIPELINE                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Stage 1: HTML Segmentation (Rule-Based) ✓                 │
│  Stage 2: Metric Classification (Keyword-Based) ✓           │
│                                                              │
│  ┌────────────────────────────────────────────────┐        │
│  │ Stage 3: Value Extraction                      │        │
│  │  • Rule-based (regex, tables) ✓                │        │
│  │  • LLM-enhanced (GPT-4o-mini) ← NEW            │        │
│  │  • Fallback: rules if LLM fails                │        │
│  └────────────────────────────────────────────────┘        │
│                                                              │
│  ┌────────────────────────────────────────────────┐        │
│  │ Stage 4: Definition Extraction                 │        │
│  │  • Rule-based (keyword proximity) ✓            │        │
│  │  • LLM-enhanced (GPT-4o-mini) ← NEW            │        │
│  │  • Fallback: rules if LLM fails                │        │
│  └────────────────────────────────────────────────┘        │
│                                                              │
│  Stage 5: Quality Scoring (Rule-Based) ✓                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Benefits of Hybrid Approach:**
- ✅ Better accuracy with LLM semantic understanding
- ✅ Graceful degradation if LLM unavailable
- ✅ Cost control (use LLM only when needed)
- ✅ Gradual rollout and A/B testing capability

---

## Components

### 1. OpenAI Client (`src/llm/openai_client.py`) and Vision Client (`src/llm/vision_client.py`)

**Class:** `OpenAIClient`

**Features:**
- ✅ Automatic retry with exponential backoff (3 retries)
- ✅ Token counting using tiktoken
- ✅ Real-time cost tracking per request
- ✅ Cumulative cost statistics
- ✅ Rate limiting support
- ✅ Comprehensive error handling

**Configuration:**
```python
client = OpenAIClient(
    model="gpt-4o-mini",           # Cost-efficient model
    temperature=0.1,                # Deterministic (low randomness)
    max_tokens=4096,                # Max response length
    max_retries=3,                  # Retry failed requests
    retry_delay=1.0                 # Initial delay (exponential)
)
```

**Key Methods:**
- `complete(prompt, system_message)` - Single completion request
- `complete_batch(prompts, ...)` - Batch processing with rate limiting
- `count_tokens(text)` - Count tokens in text
- `calculate_cost(input, output)` - Calculate request cost
- `get_cost_summary()` - Get cumulative statistics

**Error Handling:**
- `RateLimitError` - Automatic retry with backoff
- `APIConnectionError` - Retry network failures
- `APIError` - Retry 5xx errors, fail on 4xx

### 2. Prompt Templates (`src/llm/prompts.py`)

**Class:** `PromptTemplates`

**System Messages:**
1. `SYSTEM_VALUE_EXTRACTION` - Expert role for value extraction
2. `SYSTEM_DEFINITION_EXTRACTION` - Expert role for definition extraction

**Prompt Methods:**

| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `value_extraction_from_text()` | Extract values from text segments | segment_text, metric_names | JSON array of values |
| `value_extraction_from_table()` | Extract values from table segments | table_text, table_html, metric_names | JSON array with row/col labels |
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

---

## Cost Analysis

### Model Pricing (GPT-4o-mini)

| Type | Cost per 1M Tokens |
|------|-------------------|
| Input | $0.15 |
| Output | $0.60 |

### Test Results

**Simple Completion Test:**
- Input: 13 tokens
- Output: 1 token
- Cost: **$0.000003**

**Metric Extraction Test:**
- Input: 421 tokens (segment + prompt)
- Output: 76 tokens (JSON response)
- Cost: **$0.000109**

### Projected Costs

**Assumptions:**
- Average S-1 filing: ~50,000 words = ~67,000 tokens
- 10 LLM calls per filing (different segments)
- Average output: ~100 tokens per call

**Cost per Filing:**
- Input: ~67,000 tokens × 10 calls = 670,000 tokens
- Output: ~100 tokens × 10 calls = 1,000 tokens
- **Total: ~$0.10 per filing**

**Corpus of 106 Filings:**
- Total cost: **~$10.60**
- Within budget ✓

**Comparison to Other Models:**

| Model | Cost per Filing | 106 Filings | Notes |
|-------|----------------|-------------|-------|
| **GPT-4o-mini** | **$0.10** | **$10.60** | ✓ Selected |
| GPT-4o | $1.65 | $175.00 | 17x more expensive |
| o1 | $9.90 | $1,049.00 | Overkill for extraction |

---

## Testing

Unit tests for the LLM module are in `tests/unit/llm/`. The standalone `scripts/test_llm_client.py` script was removed during dead-code cleanup (commit 378b37f).

---

## Integration Status

### Phase 1: Infrastructure ✅ COMPLETE

| Component | Status | Files |
|-----------|--------|-------|
| OpenAI Client | ✅ Complete | `src/llm/openai_client.py` |
| Prompt Templates | ✅ Complete | `src/llm/prompts.py` |
| Token Counting | ✅ Complete | tiktoken integration |
| Cost Tracking | ✅ Complete | `CostTracker` class |
| Error Handling | ✅ Complete | Retry logic with backoff |
| Vision Client | ✅ Complete | `src/llm/vision_client.py` |

### Phase 2: Pipeline Integration ✅ COMPLETE

| Component | Status | Notes |
|-----------|--------|-------|
| ValueExtractor | ✅ Complete | LLM extraction with quote verification |
| DefinitionExtractor | ✅ Complete | LLM extraction with quote verification |
| Pipeline Orchestration | ✅ Complete | Hybrid rule-based + LLM fallback |
| Real Filing Tests | ✅ Complete | Tested with corpus filings |
| Quote Verification | ✅ Complete | Validates LLM-extracted quotes against source |

### Phase 3: Validation & Tuning ✅ COMPLETE

| Task | Status | Description |
|------|--------|-------------|
| Manual Validation | ✅ Complete | Validated against real filings |
| Prompt Tuning | ✅ Complete | Improved prompts for extraction quality |
| Quote Verification | ✅ Complete | Ensures extracted quotes exist in source text |
| Metric Name Mapping | ✅ Complete | Maps LLM responses to standardized metric names |

---

## Usage Examples

### Basic Usage

```python
from src.llm.openai_client import OpenAIClient
from src.llm.prompts import PromptTemplates

# Initialize client
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

✅ **DO:**
- Chunk large filings into segments (~8,000 chars)
- Count tokens before sending to estimate costs
- Use tiktoken for accurate token counting

❌ **DON'T:**
- Send entire filing in one request (context limit)
- Ignore token counts (cost overruns)
- Use character counts as proxy (inaccurate)

### 2. Error Handling

✅ **DO:**
- Always have rule-based fallback
- Log all LLM failures for analysis
- Retry on transient errors (rate limits, network)

❌ **DON'T:**
- Retry on 4xx errors (client errors)
- Fail entire pipeline on LLM errors
- Ignore cost tracking

### 3. Prompt Engineering

✅ **DO:**
- Use structured JSON output format
- Provide clear examples in prompts
- Specify units and formats explicitly
- Include relevant context in prompts

❌ **DON'T:**
- Use vague or ambiguous instructions
- Expect LLM to infer formatting
- Omit important context

### 4. Cost Optimization

✅ **DO:**
- Use GPT-4o-mini for extraction tasks
- Batch similar requests together
- Monitor cumulative costs
- Set cost thresholds/alerts

❌ **DON'T:**
- Use GPT-4o unless necessary
- Process segments multiple times
- Ignore cost tracking
- Use reasoning models (o1) for extraction

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

## Completed Milestones

### Phase 1: Infrastructure ✅

1. ✅ Create LLM client infrastructure
2. ✅ Create prompt templates
3. ✅ Test client with sample data

### Phase 2: Integration ✅

4. ✅ Integrate with ValueExtractor (LLM extraction)
5. ✅ Integrate with DefinitionExtractor (LLM extraction)
6. ✅ Test with real filings from corpus
7. ✅ Compare LLM vs rule-based accuracy

### Phase 3: Quality Improvements ✅

8. ✅ Add quote verification for LLM-extracted quotes
9. ✅ Add metric name mapping for standardization
10. ✅ Tune prompts for better extraction quality
11. ✅ Add stride optimization for large document performance

---

## Dependencies

```txt
# requirements.txt
openai>=1.0.0      # OpenAI API client
tiktoken>=0.5.0    # Token counting
```

**Installation:** Managed via `uv sync --all-extras` (declared in `pyproject.toml`).

**Environment:**
```bash
export OPENAI_API_KEY="sk-..."
```

---

## References

- **OpenAI API Docs:** https://platform.openai.com/docs/api-reference
- **GPT-4o-mini Pricing:** https://openai.com/api/pricing/
- **tiktoken:** https://github.com/openai/tiktoken
- **Development Plan:** `ops/DEVELOPMENT_PLAN.md` Sprint 3

---

## Summary

**Status:** ✅ **All Phases Complete - Production Ready**

**Key Achievements:**
- Robust OpenAI client with error handling and retry logic
- Structured prompt templates for value and definition extraction
- Token counting and cost tracking
- Quote verification to validate LLM-extracted quotes against source text
- Metric name mapping for standardized responses
- Stride optimization for large document performance (10x faster)
- Comprehensive test coverage (88-95%)

**Projected Costs:**
- Per filing: ~$0.10
- 106 filings: ~$10.60
- Well within budget ✓

**Integration Complete:** ValueExtractor and DefinitionExtractor fully enhanced with LLM methods
