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

## Code Examples

### LLM Client (No Batching)
```python
# src/llm/openai_client.py
def complete(self, prompt: str) -> str:
    """Single completion - no batching."""
    response = self.client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return response.choices[0].message.content

def complete_batch(self, prompts: List[str]) -> List[str]:
    """'Batch' is actually sequential with rate limiting."""
    results = []
    for prompt in prompts:
        time.sleep(0.1)  # Rate limit
        results.append(self.complete(prompt))
    return results
```

### Heading Cache (Never Invalidated)
```python
# src/extraction/html_segmenter.py
class HTMLSegmenter:
    def __init__(self):
        self._heading_cache = {}  # Built once per filing
        self._element_position_map = {}  # Also cached

    def segment_filing(self, html: str):
        self._build_heading_cache(html)  # Populated here
        # ... never cleared until object destroyed
```

### Database Bulk Insert (CC=42)
```python
# src/infra/db.py:1421
def bulk_insert_review_candidates(self, candidates: List[ReviewCandidate]):
    """
    Complex function with:
    - Validation logic
    - Transformation logic
    - Batch chunking
    - Transaction management
    All mixed together (CC=42)
    """
```

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
