# D5: Performance Review Context

## Dimension Focus
Database query efficiency, memory usage, parallelization opportunities, LLM optimization, caching, bottlenecks.

## Primary Files to Review

### Database Layer
- `src/infra/db.py` (4,006 LOC) - All database operations
- `src/infra/pool.py` - Connection pooling

### Pipeline Orchestration
- `src/extraction/extraction_pipeline.py` (619 LOC) - Pipeline timing
- `src/extraction/html_segmenter.py` (2,029 LOC) - HTML parsing performance

### LLM Integration
- `src/llm/openai_client.py` (133 LOC) - API calls
- `src/extraction/value_extractor.py` (582 LOC) - LLM invocations

## Review Questions

1. **N+1 Queries**: Are there N+1 query problems in the database layer? Are bulk operations used appropriately?

2. **Memory Usage**: Are there memory leaks or excessive allocations? Large file handling?

3. **Parallelization**: What parallelization opportunities exist? ThreadPoolExecutor is used for sentence detection - where else?

4. **LLM Optimization**: Are LLM calls optimized? Batching, caching, minimizing redundant calls?

5. **Caching Effectiveness**: Is caching effective? Is cache invalidation handled properly?

6. **Pipeline Bottleneck**: What is the bottleneck in the extraction pipeline? HTML parsing? LLM calls? DB writes?

## Known Performance Characteristics

From docs (PERFORMANCE_BASELINE.md):
- Processing time: ~9-17 seconds per filing
- Expected runtime: 2-5 days for full corpus (7,304 filings)
- LLM cost: ~$0.10 per filing average

## Parallelization Current State

| Component | Parallelized | Notes |
|-----------|--------------|-------|
| Sentence detection | Yes | ThreadPoolExecutor, 4 workers |
| Filing processing | No | Sequential |
| LLM calls | No | Sequential per segment |
| DB writes | No | Transactional batches |

## Caching Current State

| Cache | Scope | Invalidation |
|-------|-------|--------------|
| Heading cache | Per filing | Never (potential issue) |
| Keyword patterns | Global | @lru_cache |
| Filing HTML | Disk | Manual |

## Database Query Patterns

- Uses psycopg3 with connection pooling
- Upserts for idempotent operations
- Bulk inserts for segments and candidates
- Transactional cleanup before re-extraction

## Cost Profile

- Rule-based extraction: $0 (50-70% of metrics)
- LLM extraction: ~$0.10 per filing
- Total projected: $500-$1,000 for full corpus

## Output Location
Write findings to: `ops/review_artifacts/claude/D5_findings.json`
