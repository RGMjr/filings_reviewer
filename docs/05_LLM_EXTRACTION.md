# LLM Extraction - Prompt Engineering & Implementation

**Version:** 2.0
**Last Updated:** 2025-11-14

---

## Overview

LLM extraction handles unstructured text where rule-based extraction fails. This covers ~30-50% of metrics that appear only in prose paragraphs.

**Strategy:**
- Use GPT-4o-mini by default (94% cheaper than GPT-4o)
- Use GPT-4o only for low-confidence extractions
- Process only keyword-filtered paragraphs (not entire document)
- Use JSON mode for structured output

---

## System Prompt

```python
SYSTEM_PROMPT = """You are an expert financial analyst specializing in extracting customer and growth metrics from SEC filings.

Your task is to carefully read text from an SEC filing and extract ALL customer-related, user-related, and growth-related metrics mentioned.

IMPORTANT INSTRUCTIONS:
1. Extract ONLY factual data explicitly stated in the text
2. Do NOT infer, estimate, or calculate metrics not directly stated
3. Preserve exact values as written (e.g., "5.2 million", not "5200000")
4. Include the time period if mentioned (e.g., "Q4 2023", "as of December 31, 2023")
5. Note the source context (where in the text the metric appears)
6. Assign a confidence score (0.0-1.0) based on clarity and specificity

METRICS TO EXTRACT (if mentioned):
- User metrics: DAU, MAU, WAU, total users, active users, registered users
- Customer metrics: paying customers, subscribers, customer count
- Engagement: retention rate, churn rate, cohort data, DAU/MAU ratio
- Financial: ARPU, ARPPU, LTV, CAC, NRR, GRR, payback period
- Transaction: GMV, bookings, orders, AOV, transaction volume
- Growth: user growth rate, customer growth rate, MoM/YoY growth

CONFIDENCE SCORING:
- 0.9-1.0: Specific number with clear period and context
- 0.7-0.8: Specific number but vague period or unclear metric definition
- 0.5-0.6: Approximate value or ambiguous wording
- 0.0-0.4: Very uncertain or requires interpretation

OUTPUT FORMAT:
Return a JSON object with a "metrics" array. Each metric must have:
- metric_name: Standardized name (use exact names from list above)
- value: Exact value as stated in text
- period: Time period if mentioned (null if not specified)
- source_type: "text" or "graph_description"
- source_details: The specific sentence/paragraph containing the metric
- confidence: Confidence score (0.0-1.0)

If no metrics are found, return {"metrics": []}.
"""
```

---

## User Prompt Template

```python
def build_user_prompt(
    paragraphs: List[KeywordHit],
    filing_metadata: FilingMetadata
) -> str:
    """Build prompt for LLM extraction"""

    # Build context
    context = f"""
FILING INFORMATION:
Company: {filing_metadata.company_name}
Filing Type: {filing_metadata.filing_type}
Filing Date: {filing_metadata.filing_date}
Industry: {filing_metadata.industry or 'Unknown'}

TEXT TO ANALYZE:
Below are relevant paragraphs from the filing that may contain customer/growth metrics.

"""

    # Add each paragraph
    for idx, hit in enumerate(paragraphs, 1):
        context += f"\n--- Paragraph {idx} ---\n"
        if hit.section:
            context += f"Section: {hit.section}\n"
        context += f"{hit.paragraph}\n"

    context += """

TASK:
Extract all customer and growth metrics from the above paragraphs. Return as JSON.
"""

    return context
```

---

## OpenAI API Call

```python
from openai import OpenAI
import json

def extract_metrics_llm(
    paragraphs: List[KeywordHit],
    filing_metadata: FilingMetadata,
    model: str = "gpt-4o-mini"
) -> Tuple[List[LLMMetric], TokenUsage]:
    """
    Extract metrics using OpenAI API.
    """

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Build prompt
    user_prompt = build_user_prompt(paragraphs, filing_metadata)

    # Make API call
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0,  # Deterministic output
        max_tokens=4000
    )

    # Parse response
    response_text = response.choices[0].message.content
    response_json = json.loads(response_text)

    # Track token usage
    token_usage = TokenUsage(
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        model=model
    )

    # Convert to LLMMetric objects
    metrics = []
    for metric_data in response_json.get("metrics", []):
        metric = LLMMetric(
            metric_name=metric_data["metric_name"],
            value=metric_data["value"],
            value_numeric=parse_number_safe(metric_data["value"]),
            period=metric_data.get("period"),
            period_start=None,  # Parse separately
            period_end=None,
            source_type=SourceType(metric_data["source_type"]),
            source_details=metric_data["source_details"],
            confidence=metric_data["confidence"],
            model=model,
            tokens_used=token_usage.input_tokens + token_usage.output_tokens
        )

        # Parse period if present
        if metric.period:
            start, end = parse_period(metric.period)
            metric.period_start = start
            metric.period_end = end

        metrics.append(metric)

    return metrics, token_usage
```

---

## Chunking Strategy

For very long filings, chunk the filtered paragraphs:

```python
def chunk_paragraphs(
    paragraphs: List[KeywordHit],
    max_chars: int = 8000
) -> List[List[KeywordHit]]:
    """
    Group paragraphs into chunks that fit within token limit.

    Strategy: Keep paragraphs together, don't split mid-paragraph.
    """

    chunks = []
    current_chunk = []
    current_length = 0

    for para in paragraphs:
        para_length = len(para.paragraph)

        # If adding this paragraph would exceed limit, start new chunk
        if current_length + para_length > max_chars and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_length = 0

        current_chunk.append(para)
        current_length += para_length

    # Add final chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def extract_metrics_llm_chunked(
    paragraphs: List[KeywordHit],
    filing_metadata: FilingMetadata,
    model: str = "gpt-4o-mini",
    max_chars_per_chunk: int = 8000
) -> Tuple[List[LLMMetric], List[TokenUsage]]:
    """
    Extract metrics with automatic chunking.
    """

    # Chunk paragraphs
    chunks = chunk_paragraphs(paragraphs, max_chars_per_chunk)

    logger.info(f"Processing {len(paragraphs)} paragraphs in {len(chunks)} chunks")

    all_metrics = []
    all_token_usage = []

    # Process each chunk
    for chunk_idx, chunk in enumerate(chunks):
        logger.debug(f"Processing chunk {chunk_idx + 1}/{len(chunks)}")

        metrics, token_usage = extract_metrics_llm(
            chunk,
            filing_metadata,
            model
        )

        all_metrics.extend(metrics)
        all_token_usage.append(token_usage)

    # Deduplicate metrics (same metric may appear in multiple chunks)
    unique_metrics = deduplicate_metrics(all_metrics)

    return unique_metrics, all_token_usage

def deduplicate_metrics(metrics: List[LLMMetric]) -> List[LLMMetric]:
    """
    Remove duplicate metrics (same metric_name + period + value).

    Keep the one with highest confidence.
    """

    # Group by key
    by_key = {}
    for metric in metrics:
        key = (metric.metric_name, metric.period, metric.value)

        if key not in by_key or metric.confidence > by_key[key].confidence:
            by_key[key] = metric

    return list(by_key.values())
```

---

## Error Handling

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import RateLimitError, APIError

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception_type((RateLimitError, APIError))
)
def extract_metrics_llm_with_retry(
    paragraphs: List[KeywordHit],
    filing_metadata: FilingMetadata,
    model: str = "gpt-4o-mini"
) -> Tuple[List[LLMMetric], TokenUsage]:
    """
    Extract with automatic retry on transient errors.
    """

    try:
        return extract_metrics_llm(paragraphs, filing_metadata, model)

    except RateLimitError as e:
        logger.warning(f"Rate limit hit, retrying: {e}")
        raise  # Will trigger retry

    except APIError as e:
        logger.error(f"OpenAI API error: {e}")
        raise  # Will trigger retry

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response: {e}")
        # Don't retry, return empty
        return [], TokenUsage(0, 0, model)

    except Exception as e:
        logger.error(f"Unexpected error in LLM extraction: {e}")
        return [], TokenUsage(0, 0, model)
```

---

## Selective Re-extraction with GPT-4o

```python
def process_filing_with_fallback(filing_metadata: FilingMetadata) -> FilingResult:
    """
    Main processing pipeline with GPT-4o fallback.

    Flow:
    1. Extract tables (rule-based)
    2. Filter paragraphs (keyword)
    3. Extract from text (GPT-4o-mini)
    4. QA validation
    5. If confidence < 0.7, re-extract with GPT-4o
    """

    # Steps 1-3: Standard extraction
    table_metrics = extract_tables(html, filing_metadata.filing_type)
    paragraphs = filter_paragraphs(html, filing_metadata.filing_type)
    llm_metrics, token_usage_mini = extract_metrics_llm(
        paragraphs,
        filing_metadata,
        model="gpt-4o-mini"
    )

    # Step 4: QA
    all_metrics = table_metrics + llm_metrics
    qa_result = validate_metrics(all_metrics, filing_metadata)

    token_usage_list = [token_usage_mini]

    # Step 5: Fallback to GPT-4o if needed
    if qa_result.should_reextract:
        logger.info(f"Low confidence ({qa_result.overall_confidence:.2f}), re-extracting with GPT-4o")

        llm_metrics_4o, token_usage_4o = extract_metrics_llm(
            paragraphs,
            filing_metadata,
            model="gpt-4o"
        )

        # Replace LLM metrics with GPT-4o results
        llm_metrics = llm_metrics_4o
        token_usage_list.append(token_usage_4o)

        # Re-run QA
        all_metrics = table_metrics + llm_metrics
        qa_result = validate_metrics(all_metrics, filing_metadata)

    return FilingResult(
        filing_metadata=filing_metadata,
        success=True,
        table_metrics=table_metrics,
        llm_metrics=llm_metrics,
        keyword_hits=paragraphs,
        qa_result=qa_result,
        token_usage=token_usage_list,
        processing_time_seconds=time.time() - start_time
    )
```

---

## Prompt Optimization Tips

### 1. Be Specific About Metric Names

❌ Bad:
```
"Extract all metrics"
```

✅ Good:
```
"Extract these specific metrics if mentioned:
- Monthly Active Users (MAU)
- Daily Active Users (DAU)
- Net Revenue Retention (NRR)
..."
```

### 2. Provide Examples

Add few-shot examples to the system prompt:

```python
SYSTEM_PROMPT += """

EXAMPLES:

Input: "Our monthly active users grew 45% to 5.2 million in the fourth quarter of 2023."
Output:
{
  "metrics": [
    {
      "metric_name": "Monthly Active Users",
      "value": "5.2 million",
      "period": "Q4 2023",
      "source_type": "text",
      "source_details": "Our monthly active users grew 45% to 5.2 million in the fourth quarter of 2023.",
      "confidence": 0.95
    }
  ]
}

Input: "We saw strong retention with most cohorts remaining active."
Output:
{
  "metrics": []
}
(No specific metric values mentioned)
"""
```

### 3. Use Structured Output

Always use `response_format={"type": "json_object"}` for consistency.

### 4. Set Temperature to 0

For extraction tasks, use `temperature=0.0` for deterministic output.

---

## Cost Optimization

### Token Counting

```python
import tiktoken

def estimate_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """
    Estimate token count before API call.
    """
    encoder = tiktoken.encoding_for_model(model)
    return len(encoder.encode(text))

def estimate_cost(paragraphs: List[KeywordHit], model: str = "gpt-4o-mini") -> float:
    """
    Estimate cost before extraction.
    """
    # Estimate input tokens
    text = "\n".join(p.paragraph for p in paragraphs)
    input_tokens = estimate_tokens(SYSTEM_PROMPT + text, model)

    # Estimate output tokens (assume ~2000 for typical response)
    output_tokens = 2000

    # Calculate cost
    if model == "gpt-4o-mini":
        cost = (input_tokens * 0.15 / 1_000_000) + (output_tokens * 0.60 / 1_000_000)
    elif model == "gpt-4o":
        cost = (input_tokens * 2.50 / 1_000_000) + (output_tokens * 10.00 / 1_000_000)

    return cost
```

### Batch API (50% Discount)

For non-urgent processing, use OpenAI's Batch API:

```python
def create_batch_job(filings: List[FilingMetadata]) -> str:
    """
    Create batch job for processing multiple filings.

    Returns batch_id for later retrieval.
    """
    client = OpenAI()

    # Create batch requests
    batch_requests = []
    for filing in filings:
        paragraphs = get_paragraphs(filing)  # Cached
        user_prompt = build_user_prompt(paragraphs, filing)

        batch_requests.append({
            "custom_id": filing.filing_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0
            }
        })

    # Upload batch file
    batch_file = client.files.create(
        file=io.BytesIO(json.dumps(batch_requests).encode()),
        purpose="batch"
    )

    # Create batch job
    batch = client.batches.create(
        input_file_id=batch_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )

    return batch.id

# Later, retrieve results
def get_batch_results(batch_id: str) -> Dict[str, Any]:
    client = OpenAI()

    batch = client.batches.retrieve(batch_id)

    if batch.status == "completed":
        # Download results
        results_file = client.files.content(batch.output_file_id)
        return json.loads(results_file.read())

    return {"status": batch.status}
```

---

## Testing LLM Extraction

### Unit Tests with Mock API

```python
from unittest.mock import Mock, patch

def test_llm_extraction():
    mock_response = {
        "metrics": [
            {
                "metric_name": "Monthly Active Users",
                "value": "5.2 million",
                "period": "Q4 2023",
                "source_type": "text",
                "source_details": "Test paragraph",
                "confidence": 0.9
            }
        ]
    }

    with patch('openai.OpenAI') as mock_openai:
        mock_openai.return_value.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content=json.dumps(mock_response)))],
            usage=Mock(prompt_tokens=1000, completion_tokens=200)
        )

        paragraphs = [KeywordHit(paragraph="Test", keywords_matched=["MAU"])]
        filing = FilingMetadata(cik="0000000000", ...)

        metrics, usage = extract_metrics_llm(paragraphs, filing)

        assert len(metrics) == 1
        assert metrics[0].metric_name == "Monthly Active Users"
        assert metrics[0].value_numeric == 5_200_000
```

---

## Next: Implementation Guide

Continue to **06_IMPLEMENTATION_GUIDE.md** for step-by-step build instructions.
