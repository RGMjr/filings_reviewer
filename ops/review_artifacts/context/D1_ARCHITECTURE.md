# D1: Architecture Review Context

## Dimension Focus
Module coupling, data flow, separation of concerns, scalability, architectural decisions.

## Primary Files to Review

### src/extraction/extraction_pipeline.py (619 LOC)
**Role**: Orchestrates the 6-stage extraction pipeline
**Complexity**: CC=5-10 (moderate)
**Key concerns**:
- Pipeline stage sequencing and error handling
- Transactional database writes
- Segment selection tiering logic

**Code Sample** (lines 52-90):
```python
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
```

**Data Flow**: Filing → HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → DefinitionExtractor → QualityScorer → Database

---

### src/infra/db.py (4,006 LOC, MI=0.0)
**Role**: Database adapter with 50+ methods
**Complexity**: Average CC=8.2, Max CC=42 (`bulk_insert_review_candidates`)
**Key concerns**:
- File is extremely large for a single module (10% of total source code)
- Connection pooling management
- Mix of CRUD operations and business logic
- Unmaintainable by Radon MI score (0.0)

**Code Sample** (lines 39-100):
```python
class DatabaseAdapter:
    """
    Database adapter for Postgres operations.

    Provides connection management and common query patterns for the filings
    analysis system. Supports both per-operation connections (default) and
    connection pooling via psycopg_pool.

    Usage without pooling (per-operation connections):
        adapter = DatabaseAdapter(connection_string)

    Usage with pooling (recommended for Flask apps and scripts):
        from src.infra.pool import create_pool
        pool = create_pool(connection_string)
        adapter = DatabaseAdapter(connection_string, pool=pool)
    """

    def __init__(
        self,
        connection_string: str,
        pool: ConnectionPool | None = None,
    ):
        self.connection_string = connection_string
        self._pool = pool
        self._connection = None

    @contextmanager
    def get_connection(self):
        """
        Get a database connection context manager.

        If a connection pool was provided to __init__, connections are borrowed
        from the pool and automatically returned when the context exits.
        Otherwise, a new connection is created and closed per operation.
        """
        if self._pool is not None:
            # Use pooled connection - returned to pool on exit
            with self._pool.connection() as conn:
                try:
                    yield conn
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Database error, rolling back: {e}")
                    raise
        else:
            # Original behavior: create/close connection per operation
            conn = psycopg.connect(self.connection_string, row_factory=dict_row)
            try:
                yield conn
                # ... (continues)
```

**Methods Include**:
- Company CRUD: `upsert_company`, `get_company`, `delete_company`
- Filing CRUD: `upsert_filing`, `get_filing`, `delete_filing`
- Segment operations: `bulk_insert_segments`, `get_segments_for_filing`
- Review candidates: `bulk_insert_review_candidates` (CC=42)
- Pattern learning: `get_learned_patterns`, `insert_learned_pattern`
- 50+ total methods mixing concerns

---

### src/review/candidate_generator.py (400 LOC)
**Role**: Generates review candidates from segments
**Complexity**: Average CC=12, Max CC=57 (`_process_segment`)
**Key concerns**:
- Integration with extraction pipeline
- Keyword matching and false positive filtering
- Critical complexity in `_process_segment` (CC=57)

**Code Sample**: See `_process_segment` function (lines 481-847) in D2 context for full implementation.

**Responsibilities**:
1. Find numbers in segment text
2. Match nearby keywords to metrics
3. Apply boundary detection (bullets, tables, sentences)
4. Filter false positives
5. Compute confidence scores
6. Apply learned pattern rules

---

### config/metric_keywords.yaml (545 lines)
**Role**: Externalized metric keyword patterns
**Key concerns**:
- Single source of truth for patterns (no hardcoded fallback)
- YAML anchors for shared context patterns
- 45+ metrics defined
- Required context constraints for revenue synonyms

**Structure**:
```yaml
---
# Shared context anchor
_revenue_synonym_context: &revenue_synonym_context
  required_context:
    patterns:
      - '\bcohort\b'
      - '\bper\s+customer\b'
    proximity_chars: 1500

# Metric definition
cm_customers_period_end:
  patterns:
    - '\bpaid\s+customers?\b'
    - '\bcustomers?\s+\(?period\s*end\)?\b'
  exclusions:
    - '\bretention\s+rate\b'
  specific_patterns:
    - 'paid\s+customers?'

# Deprecated metrics still included
cm_bookings:
  <<: *revenue_synonym_context
  patterns:
    - '\bbookings\b'
```

---

## Review Questions

### 1. Module Boundaries
**Question**: Are module boundaries clear and appropriate? Is there inappropriate coupling?

**Key Areas**:
- `db.py` (4,006 LOC) mixes infrastructure, CRUD, and business logic
- `extraction/` depends on `review/` for boundary detection (circular?)
- `review/candidate_generator.py` imports from `extraction/` and `llm/`
- Web layer (`web/routes/`) calls DB directly, bypassing service layer

**Evidence of Coupling**:
```python
# candidate_generator.py imports from extraction
from src.extraction.models import SourceSegment
from src.review.boundary_detection import BoundaryDetector

# html_segmenter.py imports from review
from src.review.boundary_detection import BoundaryDetector  # <-- coupling
```

### 2. Data Flow
**Question**: How does data flow through the extraction pipeline? Is it clear and traceable?

**Current Flow**:
```
Filing HTML → HTMLSegmenter (segment_filing)
  → SourceSegment objects
  → MetricClassifier (classify_segments)
  → candidate_metric_ids added to segments
  → SegmentEnricher (enrich_segments)
  → enrichment flags added
  → ValueExtractor (extract_values)
  → MetricValue objects
  → DefinitionExtractor (extract_definitions)
  → MetricDefinition objects
  → QualityScorer (score_filing)
  → FilingMetricIncidence objects
  → Database writes (transactional)
```

**Clarity**: Flow is clear in `extraction_pipeline.py` but obscured by:
- Side effects in enrichment (modifies segment dicts)
- LLM calls scattered across stages
- Caching in segmenter (heading cache never invalidated)

### 3. db.py Size
**Question**: Is the 4,006-line db.py a maintainability problem? Should it be split?

**Metrics**:
- LOC: 4,006 (10% of total source)
- Maintainability Index: 0.0 (unmaintainable)
- Max Complexity: 42 (`bulk_insert_review_candidates`)
- Method Count: 50+

**Concerns**:
- Single point of failure for all data access
- Difficult to test (requires full DB setup)
- Mixes concerns: connection management, CRUD, conflict resolution, validation
- Complex methods like `bulk_insert_review_candidates` (CC=42) handle business logic

**Recommendation**: Split by bounded context (companies, filings, segments, review, patterns)

### 4. V1 vs V2 Pipeline
**Question**: extraction_v2/ exists but has 0% coverage. Should it replace extraction/, or coexist? What's the migration strategy?

**Current State**:
- `extraction_v2/` has 6 files: ingestion_stage.py, models.py, stages/, etc.
- 0% test coverage (critical gap)
- Not integrated into pipeline
- Uses lxml (faster) instead of BeautifulSoup
- Implements stable XPath locators

**Strategic Questions**:
- Is V2 production-ready or experimental?
- What's the rollback plan if V2 has issues?
- Can V1 and V2 run in parallel for comparison?
- What's the performance/quality tradeoff?

### 5. Config Scalability
**Question**: Is the YAML keyword config approach scalable as metrics grow?

**Current State**:
- 545 lines, 45+ metrics
- YAML anchors for shared context (good)
- Regex patterns validated at load time
- No versioning or migration strategy

**Concerns**:
- Large YAML becomes hard to review in diffs
- No schema validation (typos could break extraction)
- Deprecated metrics still present (clutter)
- Performance impact of loading/parsing (currently @lru_cache)

### 6. Dependency Direction
**Question**: Do dependencies flow in the right direction (infrastructure → domain → presentation)?

**Dependency Graph**:
```
web/ → llm/, extraction/, review/, infra/db.py
review/ → extraction/, infra/
extraction/ → review/boundary_detection (CIRCULAR), infra/
infra/ → (no internal deps)
llm/ → (no internal deps)
```

**Issues**:
- **Circular dependency**: extraction/html_segmenter.py imports from review/boundary_detection.py
- **Presentation → Domain**: web/routes/ calls DB adapter directly (no service layer)
- **Domain → Infrastructure**: Extraction modules know about DB schema

---

## Known Architectural Concerns

1. **db.py monolith**: 4,006 LOC, MI=0.0, 50+ methods mixing concerns
2. **Pipeline coupling**: extraction and review modules have tight coupling (circular import)
3. **V2 transition**: New pipeline exists but no clear migration path (0% coverage)
4. **State management**: Mix of stateless functions and stateful classes (e.g., HTMLSegmenter heading cache)
5. **No service layer**: Web routes call DB directly, bypassing potential business logic encapsulation

---

## Files Structure

```
src/
├── infra/           # Infrastructure (db, http, sec client)
│   ├── db.py        # 4,006 LOC - largest file, MI=0.0
│   ├── pool.py      # Connection pooling
│   ├── sec_client.py
│   └── validation.py
├── extraction/      # V1 extraction pipeline (20 files)
│   ├── extraction_pipeline.py  # Orchestrator (619 LOC)
│   ├── html_segmenter.py       # 2,029 LOC, MI=0.0
│   ├── metric_classifier.py
│   ├── segment_enricher.py
│   ├── value_extractor.py      # 582 LOC
│   └── ...
├── extraction_v2/   # V2 pipeline (6 files, 0% coverage)
│   ├── ingestion_stage.py
│   ├── models.py
│   └── stages/
├── review/          # Human review system (20 files)
│   ├── candidate_generator.py  # 400 LOC, max CC=57
│   ├── keyword_matching.py     # max CC=46
│   ├── false_positive_filter.py # 750 LOC
│   ├── pattern_analyzer.py     # 2,544 LOC, MI=0.0
│   ├── boundary_detection.py   # Imported by extraction/ (circular)
│   └── ...
├── web/             # Flask application
│   ├── routes/      # API and UI routes
│   └── templates/
└── llm/             # LLM integration
    ├── openai_client.py
    └── prompts.py
```

---

## Static Analysis Metrics

| File | LOC | MI | Max CC | Test Coverage |
|------|-----|-----|--------|---------------|
| db.py | 4,006 | 0.0 | 42 | 78% |
| html_segmenter.py | 2,029 | 0.0 | 37 | 84% |
| pattern_analyzer.py | 2,544 | 0.0 | 38 | 96% |
| extraction_pipeline.py | 619 | A | 12 | 92% |
| candidate_generator.py | 400 | A | 57 | 98% |

---

## Output Location
Write findings to: `ops/review_artifacts/claude/D1_findings.json`
