# D5: Performance Review Context

## Dimension Focus
Database query efficiency, memory usage, parallelization opportunities, LLM optimization, caching, bottlenecks.

## Primary Files to Review

### Database Layer
- **src/infra/db.py** (4,006 LOC, 78% coverage) - All database operations
- **src/infra/pool.py** - Connection pooling with psycopg3

### Pipeline Orchestration
- **src/extraction/extraction_pipeline.py** (619 LOC) - Pipeline timing and orchestration
- **src/extraction/html_segmenter.py** (2,029 LOC) - HTML parsing performance

### LLM Integration
- **src/llm/openai_client.py** (133 LOC) - API calls, rate limiting, retries
- **src/extraction/value_extractor.py** (582 LOC) - LLM extraction invocations

---

## Performance Baseline

From `docs/PERFORMANCE_BASELINE.md` (if exists) and architecture docs:

| Metric | Value | Notes |
|--------|-------|-------|
| Processing time per filing | 9-17 seconds | Depends on filing length, LLM usage |
| Expected runtime (full corpus) | 2-5 days | 7,304 filings at 15 sec avg |
| LLM cost per filing | ~$0.10 | Average, varies by metric density |
| Total projected cost | $500-$1,000 | Full corpus extraction |
| Database query count per filing | ~50-100 | Segments, candidates, values |
| Memory usage | Unknown | Needs profiling |

---

## Review Questions

### 1. N+1 Query Problems
**Question**: Are there N+1 query problems in the database layer? Are bulk operations used appropriately?

**Bulk Operations in db.py**:
- ✅ `bulk_insert_segments` - Batch insert source segments
- ✅ `bulk_insert_review_candidates` - Batch insert candidates with conflict resolution
- ✅ `bulk_insert_metric_values` - Batch insert extracted values

**Potential N+1 Patterns** (requires investigation):
- Loading segments for filing: Single query or N queries per segment type?
- Review candidate retrieval: Fetches candidates + metrics in one query or separate?
- Pattern learning queries: Fetches patterns individually or batched?

**Code Sample to Investigate** (db.py):
```python
def get_segments_for_filing(self, filing_id: int, segment_type: str | None = None):
    # Does this cause N+1 when caller iterates and fetches related data?
    pass
```

**Recommendation**: Run query profiler on full extraction to identify N+1 patterns.

### 2. Memory Usage
**Question**: Are there memory leaks or excessive allocations? Large file handling?

**Large Data Structures**:
1. **HTML parsing**: BeautifulSoup parses entire filing HTML into memory
   - Average filing size: ~500KB - 5MB HTML
   - Largest filings: >10MB
   - Risk: Memory spikes for large filings

2. **Segment storage**: All segments held in memory during processing
   - Typical filing: 100-500 segments
   - Each segment: 50-10,000 chars
   - Risk: Moderate (few MB per filing)

3. **Heading cache**: Never invalidated (html_segmenter.py)
   - Cache persists across segment processing
   - Risk: Memory leak if segmenter reused across filings

4. **Pre-computed keyword matches**: `all_keywords` list per segment
   - Typical segment: 10-50 keyword matches
   - Risk: Low (small overhead)

**Code Sample - Heading Cache** (html_segmenter.py):
```python
def __init__(self):
    self._heading_cache = {}  # NEVER CLEARED!

def segment_filing(self, filing_id, html):
    # Processes filing, populates cache
    # Cache never invalidated - memory leak if instance reused
    pass
```

**Recommendation**:
- Profile memory usage on largest filings (>10MB)
- Add cache invalidation or use per-filing caching
- Consider streaming for very large filings

### 3. Parallelization Opportunities
**Question**: What parallelization opportunities exist? ThreadPoolExecutor is used for sentence detection - where else?

**Current Parallelization**:

| Component | Parallelized? | Implementation | Workers |
|-----------|---------------|----------------|---------|
| Sentence detection | ✅ Yes | ThreadPoolExecutor | 4 |
| Filing processing | ❌ No | Sequential | 1 |
| LLM calls | ❌ No | Sequential per segment | 1 |
| DB writes | ❌ No | Transactional batches | 1 |
| HTML parsing | ❌ No | Sequential | 1 |

**Code Sample - Sentence Detection** (html_segmenter.py:100):
```python
PARALLEL_SENTENCE_DETECTION_WORKERS = 4

def _detect_sentences_parallel(self, segments):
    with ThreadPoolExecutor(max_workers=self.PARALLEL_SENTENCE_DETECTION_WORKERS) as executor:
        # Parallel sentence boundary detection
        results = executor.map(detect_boundaries, segments)
    return list(results)
```

**Parallelization Opportunities**:

1. **Filing-level parallelism** (High Impact):
   - Process multiple filings concurrently
   - Bottleneck: Database connection pool size
   - Speedup: 5-10x (limited by SEC rate limit for fetching)

2. **LLM call batching** (High Impact):
   - Batch multiple LLM requests in single API call
   - OpenAI supports batch API for 50% cost reduction
   - Speedup: 2x (cost savings), ~1.2x (latency)

3. **Segment processing** (Medium Impact):
   - Process segments in parallel (keyword matching, classification)
   - Bottleneck: Shared state (database writes)
   - Speedup: 2-3x (CPU-bound tasks)

4. **HTML parsing** (Low Impact):
   - Already fast with BeautifulSoup (V2 uses lxml for 10x speedup)
   - Parallelization overhead would outweigh gains

**Recommendation**: Prioritize filing-level parallelism and LLM batching.

### 4. LLM Optimization
**Question**: Are LLM calls optimized? Batching, caching, minimizing redundant calls?

**Current LLM Usage**:
- **Value extraction**: LLM-first with rule-based fallback
- **Definition extraction**: LLM-enhanced methodology detection
- **Metric name mapping**: 170+ entry hardcoded dict (no LLM call)

**LLM Call Patterns** (openai_client.py):
```python
def extract_value(self, segment_text, metric_id):
    # Single API call per segment
    # No batching, no caching
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[...],
        temperature=0.0,
    )
    return parse_response(response)
```

**Optimization Opportunities**:

1. **Batching** (not currently implemented):
   - OpenAI Batch API: 50% cost reduction, 24hr latency
   - Good for offline processing, bad for interactive
   - Potential savings: $250-$500 on full corpus

2. **Caching** (not currently implemented):
   - Cache LLM responses by (segment_text, metric_id) hash
   - Duplicate segments across filings (common boilerplate)
   - Potential hit rate: 10-20% (needs measurement)

3. **Prompt optimization**:
   - Current prompts: ~200-500 tokens
   - Opportunity: Compress system prompts, use few-shot examples
   - Savings: 20-30% token reduction

4. **Model selection**:
   - Currently: GPT-4 (expensive, accurate)
   - Opportunity: GPT-4o-mini for simple extractions (10x cheaper)
   - Tradeoff: Quality vs cost

**Cost Breakdown** (estimated):
- Rule-based extraction: $0 (50-70% of metrics)
- LLM extraction: ~$0.10 per filing (30-50% of metrics)
- Total projected: $500-$1,000 for full corpus

**Recommendation**: Implement caching first (easy win), then evaluate batch API.

### 5. Caching Effectiveness
**Question**: Is caching effective? Is cache invalidation handled properly?

**Current Caching**:

| Cache | Scope | Invalidation | Effectiveness |
|-------|-------|--------------|---------------|
| **Heading cache** | Per HTMLSegmenter instance | ❌ Never | Unknown, potential leak |
| **Keyword patterns** | Global, @lru_cache | On process restart | ✅ Effective |
| **Filing HTML** | Disk (data/filings/) | Manual deletion | ✅ Effective |
| **LLM responses** | ❌ None | N/A | N/A (opportunity) |

**Heading Cache Issue** (html_segmenter.py):
```python
class HTMLSegmenter:
    def __init__(self):
        self._heading_cache = {}  # BUG: Never cleared!

    def segment_filing(self, filing_id, html):
        # Cache populated during parsing
        # If instance reused for multiple filings, cache grows unbounded
        pass
```

**Impact**: Memory leak if HTMLSegmenter instance reused in long-running process.

**Keyword Pattern Cache** (keyword_config.py):
```python
@lru_cache(maxsize=1)
def load_metric_keywords():
    # Loads config/metric_keywords.yaml once
    # Cached until process restart
    return parse_yaml()
```

**Impact**: ✅ Effective - config loaded once, no invalidation needed (static file).

**Filing HTML Cache**:
- Location: `data/filings/{cik}_{accession}.html`
- Invalidation: Manual or periodic cleanup
- Size: ~500KB - 5MB per filing, ~3-15GB for full corpus

**Recommendation**:
1. Fix heading cache memory leak (clear per filing)
2. Add LLM response caching with TTL
3. Implement filing cache eviction policy (LRU, 1GB limit)

### 6. Pipeline Bottleneck
**Question**: What is the bottleneck in the extraction pipeline? HTML parsing? LLM calls? DB writes?

**Pipeline Stages** (from extraction_pipeline.py):

1. **HTML Segmentation** (HTMLSegmenter)
   - Time: ~1-3 seconds per filing
   - Bottleneck: BeautifulSoup parsing (V2 uses lxml for 10x speedup)

2. **Metric Classification** (MetricClassifier)
   - Time: ~0.5-1 second per filing (regex matching)
   - Bottleneck: CPU-bound keyword matching

3. **Segment Enrichment** (SegmentEnricher)
   - Time: ~0.5-1 second per filing
   - Bottleneck: Boundary detection, sentence parsing

4. **Value Extraction** (ValueExtractor)
   - Time: ~3-10 seconds per filing (if LLM used)
   - Bottleneck: **LLM API calls** (network latency, rate limits)

5. **Definition Extraction** (DefinitionExtractor)
   - Time: ~1-2 seconds per filing (if LLM used)
   - Bottleneck: LLM API calls

6. **Quality Scoring** (QualityScorer)
   - Time: ~0.1-0.5 seconds per filing
   - Bottleneck: Minimal (computation only)

7. **Database Writes**
   - Time: ~0.5-1 second per filing
   - Bottleneck: Network RTT to database, bulk inserts

**Total Time Budget** (per filing):
- HTML parsing: 1-3s (20-30%)
- LLM calls: 3-12s (50-70%) ← **PRIMARY BOTTLENECK**
- Keyword/enrichment: 1-2s (10-15%)
- DB writes: 0.5-1s (5-10%)
- **Total**: 9-17s per filing

**Bottleneck Analysis**:
1. **LLM calls**: 50-70% of total time (primary bottleneck)
2. **HTML parsing**: 20-30% (V2 improves this with lxml)
3. **DB writes**: 5-10% (already optimized with bulk inserts)

**Optimization Priority**:
1. **LLM batching/caching** - 2-5x speedup potential
2. **V2 HTML parser** - 2-3x speedup on parsing stage
3. **Filing-level parallelism** - 5-10x speedup (multi-filing)

---

## Parallelization Current State

| Component | Parallelized | Notes |
|-----------|--------------|-------|
| Sentence detection | ✅ Yes | ThreadPoolExecutor, 4 workers |
| Filing processing | ❌ No | Sequential, one at a time |
| LLM calls | ❌ No | Sequential per segment |
| DB writes | ❌ No | Transactional batches |

---

## Database Query Patterns

From db.py architecture:

- **Connection pooling**: Uses psycopg3 with configurable pool size
- **Upserts**: For idempotent operations (filings, companies, segments)
- **Bulk inserts**: For segments, candidates, values (good!)
- **Transactional cleanup**: Before re-extraction (prevents duplicates)

**Potential Issues**:
- Query patterns not profiled
- No query logging for slow queries
- Connection pool size not documented (default?)

---

## Cost Profile

| Category | Cost per Filing | Notes |
|----------|----------------|-------|
| Rule-based extraction | $0 | 50-70% of metrics |
| LLM extraction (GPT-4) | ~$0.10 | 30-50% of metrics |
| **Total per filing** | **~$0.10** | Average |
| **Total projected (7,304 filings)** | **$500-$1,000** | Full corpus |

**Cost Optimization Opportunities**:
- Batch API: 50% reduction → $250-$500 savings
- GPT-4o-mini for simple cases: 10x reduction → $450-$900 savings
- Caching (10-20% hit rate): ~$50-$100 savings

---

## Performance Recommendations

### P0 - High Impact
1. **Implement LLM response caching** - Easy win, 10-20% cost/latency reduction
2. **Fix heading cache memory leak** - Prevents crashes in long-running processes
3. **Profile query patterns** - Identify and fix N+1 queries

### P1 - Medium Impact
4. **Add filing-level parallelism** - 5-10x speedup (requires connection pool tuning)
5. **Evaluate OpenAI Batch API** - 50% cost reduction for offline processing
6. **Migrate to V2 HTML parser (lxml)** - 2-3x speedup on parsing stage

### P2 - Lower Impact
7. **Implement filing cache eviction** - Prevents disk bloat (LRU, 1GB limit)
8. **Add performance regression tests** - Prevent slowdowns over time
9. **Profile memory usage** - Identify and fix memory leaks

---

## Output Location
Write findings to: `ops/review_artifacts/claude/D5_findings.json`
