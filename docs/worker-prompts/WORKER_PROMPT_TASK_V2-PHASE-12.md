# WORKER PROMPT: Task V2-PHASE-12 - Database Persistence

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       V2-PHASE-12
TASK NAME:     Database Persistence for V2 Extraction Pipeline
WORKSTREAM:    V2 Extraction Pipeline
SOURCE:        docs/V2_IMPLEMENTATION_ROADMAP.md Phase 12
STATUS:        🟡 PENDING
COMPLETION:    [Path to completion summary, if complete]
TIME ESTIMATE: 1-2 hours (M-size task)
TIME ACTUAL:   [Actual time taken, if complete]
RISK LEVEL:    Low - Database schema already exists, follows V1 patterns
TASK SIZE:     M
DEPENDS ON:    V2-PHASE-11 (Validation), sql/09_v2_schema.sql (schema exists)
UNLOCKS:       V2-PHASE-13 (Integration & Validation)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a persistence layer to store V2 extraction pipeline results (MetricFacts, Tables, Segments, Images) in PostgreSQL. This enables end-to-end pipeline execution and sets the foundation for the human review workflow.

**Business Rationale**: Without persistence, extracted metrics only exist in memory. Storing them enables the review UI, historical analysis, and production deployment.

**Current Behavior**: V2 pipeline extracts MetricFacts but returns them only in `PipelineResult`. No database storage.

**Desired Behavior**: After pipeline execution, all V2 entities are persisted to the database. Re-running extraction for the same filing updates existing records (idempotent).

## Prerequisites

- V2-PHASE-11 complete (Validation stage)
- Database schema exists: `sql/09_v2_schema.sql`
- V1 database adapter patterns: `src/infra/db.py`

## Files to Create

1. **`src/extraction_v2/persistence.py`** - Persistence layer with upsert functions for all V2 tables
2. **`tests/integration/extraction_v2/__init__.py`** - Integration test package
3. **`tests/integration/extraction_v2/test_persistence.py`** - Integration tests for persistence

## Files to Modify

1. **`src/extraction_v2/pipeline.py`** - Add optional persistence after validation stage
2. **`src/extraction_v2/__init__.py`** - Export persistence functions

## Files to Read (Context Only)

- `sql/09_v2_schema.sql` - Target database schema (v2_documents, v2_segments, v2_tables, v2_table_cells, v2_image_assets, v2_metric_facts)
- `src/infra/db.py` - V1 patterns for upsert, connection management, JSONB handling
- `src/extraction_v2/models.py` - V2 data models to persist
- `src/extraction_v2/pipeline.py` - PipelineResult structure

## Implementation Requirements

### Core Functionality

1. **V2PersistenceAdapter Class**
   - Constructor accepts `DatabaseAdapter` (existing V1 adapter)
   - Provides methods to persist each entity type
   - Uses transactions for atomicity
   - Handles JSONB serialization for complex fields

2. **Document Persistence (`persist_document`)**
   - Upsert to `v2_documents` table
   - Key: `filing_id` (unique constraint exists)
   - Update computed statistics: segment_count, table_count, image_count, fact_count
   - Set status and timing fields

3. **Segment Persistence (`persist_segments`)**
   - Batch upsert to `v2_segments` table
   - Key: `(doc_id, sequence_idx)` for uniqueness
   - Handle prev/next segment linking

4. **Table Persistence (`persist_tables`)**
   - Upsert to `v2_tables` table
   - For each table, upsert cells to `v2_table_cells`
   - Use `table_id` as foreign key
   - Serialize `header_path` and `stub_path` as TEXT[]

5. **Image Persistence (`persist_images`)**
   - Upsert to `v2_image_assets` table
   - Serialize `chart_data` as JSONB
   - Handle optional `ocr_table_id` reference

6. **Fact Persistence (`persist_facts`)**
   - Upsert to `v2_metric_facts` table
   - Key: `fact_id` (UUID primary key)
   - Serialize `source_locator` and `evidence_pack` as JSONB
   - Handle `alternate_evidence` UUID array

7. **Full Pipeline Persistence (`persist_pipeline_result`)**
   - Single method to persist entire `PipelineResult`
   - Use transaction for atomicity
   - Order: document → segments → tables → images → facts
   - Return success/failure with error details

### JSONB Serialization

- `source_locator`: Use `SourceLocator.to_dict()`
- `evidence_pack`: Use `EvidencePack.to_dict()`
- `chart_data`: Serialize `ChartData` to dict (add `to_dict()` if missing)
- Use `json.dumps()` for PostgreSQL JSONB columns

### Idempotency Requirements

- All operations must be safe to re-run
- Use `ON CONFLICT ... DO UPDATE` pattern
- Preserve `created_at`, update `updated_at`
- For facts with same `fact_id`, update all fields

### Error Handling

- **Connection errors**: Raise with clear message, don't swallow
- **Constraint violations**: Log and include in error response
- **Serialization errors**: Catch and report which field failed
- **Transaction failures**: Rollback entire operation

### Performance Requirements

- Batch inserts for segments (100+ per document)
- Batch inserts for cells (1000+ for large tables)
- Use `execute_values` or similar for bulk operations
- Target: <500ms for typical document (50 segments, 10 tables)

## Test Requirements

### Coverage Target: **≥ 85%** for `persistence.py`

### Test Categories (15+ tests recommended)

1. **Document Persistence** (3-4 tests)
   - Insert new document
   - Update existing document (upsert)
   - Verify computed statistics update

2. **Segment Persistence** (3-4 tests)
   - Batch insert segments
   - Verify ordering preserved
   - Handle empty segment list

3. **Table Persistence** (3-4 tests)
   - Insert table with cells
   - Verify header_path/stub_path arrays
   - Handle table with no cells

4. **Fact Persistence** (3-4 tests)
   - Insert fact with full provenance
   - Verify JSONB fields round-trip
   - Update existing fact (idempotency)

5. **Full Pipeline Persistence** (3-4 tests)
   - Persist complete PipelineResult
   - Verify transaction atomicity (rollback on error)
   - Handle empty results

### Integration Test Setup

- Use `TEST_DATABASE_URL` environment variable
- Create/drop test tables in fixtures
- Use `pytest.mark.integration` marker
- Skip if no database connection

## Constraints (DO NOT)

- Modify V1 database tables (companies, filings, source_segments, etc.)
- Add new columns to existing schema (use schema as-is)
- Create new SQL migration files (schema exists)
- Use raw SQL without parameterization (SQL injection risk)
- Commit connection in persistence methods (caller controls transaction)

## Verification Commands

```bash
# Run integration tests
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \
  pytest tests/integration/extraction_v2/test_persistence.py -v

# Check type safety
mypy src/extraction_v2/persistence.py --strict

# Lint check
ruff check src/extraction_v2/persistence.py

# Coverage
pytest tests/integration/extraction_v2/test_persistence.py --cov=src/extraction_v2/persistence --cov-report=term-missing
```

## Acceptance Criteria

- [ ] AC-1: `src/extraction_v2/persistence.py` exists with `V2PersistenceAdapter` class
- [ ] AC-2: `persist_document()` upserts to v2_documents with computed stats
- [ ] AC-3: `persist_segments()` batch upserts to v2_segments
- [ ] AC-4: `persist_tables()` upserts tables and cells with array fields
- [ ] AC-5: `persist_images()` upserts to v2_image_assets with JSONB chart_data
- [ ] AC-6: `persist_facts()` upserts to v2_metric_facts with JSONB fields
- [ ] AC-7: `persist_pipeline_result()` persists full result in single transaction
- [ ] AC-8: All operations are idempotent (re-runs safe)
- [ ] AC-9: Integration tests in `tests/integration/extraction_v2/test_persistence.py`
- [ ] AC-10: Coverage ≥ 85% for persistence module
- [ ] AC-11: `mypy --strict` passes on persistence module
- [ ] AC-12: `ruff check` passes

## Notes

- The v2_documents table has a UNIQUE constraint on filing_id
- v2_metric_facts uses UUID primary keys (not auto-increment)
- v2_table_cells has UNIQUE constraint on (table_id, row_idx, col_idx)
- The schema includes triggers for updated_at timestamps
- v2_review_decisions table exists but is NOT part of this task (handled by review workflow)
