# WORKER PROMPT: Task DUP-1 - Database Schema Migration

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       DUP-1
TASK NAME:     Add unique indexes and suppressed_candidates table to prevent duplicate review candidates
WORKSTREAM:    Human Review System Improvements
SOURCE:        Slack filing duplicate candidates analysis (snuggly-watching-micali.md)
STATUS:        ✅ COMPLETE
COMPLETION:    2026-01-06
TIME ESTIMATE: 2-3 hours (investigation 30 min, schema design 45 min, testing 45 min)
TIME ACTUAL:   ~1 hour
RISK LEVEL:    Low (schema additions, no modifications to existing data)
TASK SIZE:     M
DEPENDS ON:    None (data cleanup already completed)
UNLOCKS:       DUP-2 (Upsert Logic and Suppression Logging)
BLOCKS:        DUP-2, DUP-3
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create database schema changes to prevent duplicate review candidates and enable learning from suppressed alternatives.

**Business Rationale**: The Slack filing had 122 candidates when only 61 unique ones should exist - the candidate generation script was run twice, creating exact duplicates. This wastes reviewer time and corrupts analysis. The `suppressed_candidates` table enables learning when human reclassification reveals our confidence scoring was wrong.

**Current Behavior**: `review_candidates` table allows duplicate inserts for same (filing, segment, position, metric) combination. No logging of suppressed alternatives.

**Desired Behavior**:
1. Unique indexes prevent duplicate candidates at the database level
2. `suppressed_candidates` table captures alternatives for learning

## Prerequisites

- Data cleanup already completed (64 duplicates deleted from Slack and Samsara filings)
- Verify no duplicates exist: `SELECT COUNT(*) = COUNT(DISTINCT (filing_id, source_segment_id, char_position, suggested_metric_id)) FROM review_candidates WHERE source_segment_id IS NOT NULL;`

## Files to Create

1. **`sql/08_add_suppressed_candidates.sql`** - Migration script with suppressed_candidates table and unique indexes

## Files to Modify

None (new file only)

## Files to Read (Context Only)

- `sql/07_create_review_schema.sql` - Existing review schema for consistency
- `src/review/models.py` - ReviewCandidate model for field reference

## Implementation Requirements

### Core Functionality

1. **Suppressed Candidates Table**
   - Store full candidate data (all fields from review_candidates) for potential learning
   - Link to winner candidate via `winner_candidate_id` (nullable, SET NULL on delete)
   - Track suppression reason: 'lower_confidence', 'cross_sentence', 'duplicate_execution'
   - Store winner's confidence at suppression time for comparison
   - Include indexes for learning queries (by winner, filing, metric)

2. **Unique Indexes on review_candidates**
   - Handle NULL `source_segment_id` (16 of 413 candidates have NULL)
   - PostgreSQL treats NULLs as distinct, so need two partial indexes:
     - One for candidates WITH source_segment_id
     - One for candidates WITHOUT source_segment_id
   - Key: (filing_id, source_segment_id, char_position, suggested_metric_id)
   - Exclude `triggering_keyword` from key (best candidate wins regardless of keyword)

3. **Constraint Definitions**
   - CHECK constraint on suppression_reason enum values
   - CHECK constraint on keyword_position ('before', 'after')
   - Foreign key to review_candidates with ON DELETE SET NULL

### Error Handling

- Migration should be idempotent (DROP IF EXISTS before CREATE)
- Include verification queries at end of script
- Add helpful comments for future maintenance

## Test Requirements

### Coverage Target: N/A (SQL migration script)

### Manual Verification Tests

1. **Index creation verification**
   - Run migration script
   - Verify indexes exist: `\d review_candidates`
   - Verify suppressed_candidates table exists: `\d suppressed_candidates`

2. **Unique constraint test**
   - Attempt to insert duplicate candidate
   - Verify constraint violation error

3. **NULL handling test**
   - Insert candidate with NULL source_segment_id
   - Attempt duplicate with NULL source_segment_id
   - Verify constraint violation

4. **Suppression logging test**
   - Insert row into suppressed_candidates
   - Verify all fields populated correctly

## Acceptance Criteria

- [ ] `sql/08_add_suppressed_candidates.sql` created
- [ ] `suppressed_candidates` table with all required fields
- [ ] Unique index `uq_review_candidates_with_segment` for non-NULL segment_id
- [ ] Unique index `uq_review_candidates_without_segment` for NULL segment_id
- [ ] CHECK constraint on suppression_reason values
- [ ] Indexes on suppressed_candidates for learning queries
- [ ] Migration script is idempotent (can run multiple times safely)
- [ ] Verification queries at end of script pass
- [ ] No existing data modified (only schema additions)

## Do NOT

- Modify existing data in review_candidates
- Change existing columns in review_candidates
- Add foreign key constraints that could fail on existing data
- Create migration that isn't idempotent

## Verification Commands

```bash
# Run migration
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -f sql/08_add_suppressed_candidates.sql

# Verify indexes exist
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "\d review_candidates" | grep uq_review_candidates

# Verify table exists
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "\d suppressed_candidates"

# Test uniqueness constraint (should fail)
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
INSERT INTO review_candidates (filing_id, company_id, source_segment_id, char_position, context_text, raw_number_text, triggering_keyword, keyword_distance, keyword_position, suggested_metric_id)
SELECT filing_id, company_id, source_segment_id, char_position, context_text, raw_number_text, triggering_keyword, keyword_distance, keyword_position, suggested_metric_id
FROM review_candidates
LIMIT 1;
" 2>&1 | grep -q "duplicate key" && echo "✓ Unique constraint working" || echo "✗ Unique constraint NOT working"
```

## Critical Evaluation Phase

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] SQL follows project conventions (lowercase keywords, consistent formatting)
- [ ] Comments explain purpose of each section
- [ ] Index names are descriptive and follow naming convention

### 2. Schema Design Assessment
- [ ] All fields from ReviewCandidate model included in suppressed_candidates
- [ ] Appropriate data types used
- [ ] Indexes cover expected query patterns

### 3. Identify Improvements
Document any potential improvements discovered during evaluation.

### 4. User Approval (REQUIRED)
**STOP and ask the user** before committing.

## Expected Impact

**Before DUP-1**:
- Running candidate generation twice creates exact duplicates
- No record of suppressed alternatives for learning

**After DUP-1**:
- Unique indexes prevent duplicate candidates at database level
- `suppressed_candidates` table ready for learning integration

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6
