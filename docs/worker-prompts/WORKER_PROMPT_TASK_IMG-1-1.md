# WORKER PROMPT: Task IMG-1-1 - Database Schema for Image Review

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-1
TASK NAME:     Create database schema for image review candidates and decisions
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 30-60 min
RISK LEVEL:    Low (new tables, no existing data affected)
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       IMG-1-2
BLOCKS:        IMG-1-2, IMG-1-3, IMG-1-4, IMG-1-5
PARALLEL WITH: None (foundation task)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create the database schema for storing image review candidates and human review decisions. This enables the human-in-the-loop workflow for classifying chart images in SEC filings.

**Business Rationale**: Chart images in filings (cohort charts, revenue visualizations) contain valuable metrics that text extraction misses. Human review classifies which images are worth extracting data from.

**Current Behavior**: No image review tables exist.

**Desired Behavior**: Two new tables (`image_review_candidates`, `image_review_decisions`) support the image review workflow with pattern learning capabilities.

## Prerequisites

- None (standalone foundation task)
- Read existing review schema for patterns: `sql/07_create_review_schema.sql`

## Files to Create

1. **`sql/09_create_image_review_schema.sql`** - Schema migration with tables, indexes, constraints, views

## Files to Read (Context Only)

- `sql/07_create_review_schema.sql` - Existing review schema patterns (constraints, views, triggers)
- `data/discovery/chart_image_inventory.csv` - Understand data fields being stored

## Implementation Requirements

### Core Functionality

1. **Table: `image_review_candidates`**
   - Primary key: `image_candidate_id BIGSERIAL`
   - Foreign keys: `filing_id` (filings), `company_id` (companies)
   - Image identification: `image_src TEXT`, `image_url TEXT`
   - Metadata: `image_width INT`, `image_height INT`, `image_alt TEXT`
   - Context: `preceding_text TEXT`, `detected_keywords TEXT[]`
   - Scoring: `cohort_confidence NUMERIC(3,2)`, `is_decorative BOOLEAN`
   - **Pattern learning**: `detection_tier TEXT` with CHECK constraint for values: 'tier_1_cohort', 'tier_2_large', 'tier_3_all', 'seed_list'
   - Status: `review_status TEXT` DEFAULT 'pending' with CHECK for: 'pending', 'reviewed', 'skipped'
   - Timestamps: `created_at`, `updated_at` with trigger
   - Unique constraint: `(filing_id, image_src)`

2. **Table: `image_review_decisions`**
   - Primary key: `image_decision_id BIGSERIAL`
   - Foreign key: `image_candidate_id` (UNIQUE - one decision per candidate)
   - Decision: `decision TEXT` with CHECK for: 'relevant', 'not_relevant'
   - Chart type: `chart_type TEXT` with CHECK for 7 values (required if relevant)
   - Rejection: `rejection_reason TEXT` with CHECK for 6 values (required if not_relevant)
   - Metadata: `reviewer_id TEXT`, `reviewer_notes TEXT`, `review_time_seconds INT`
   - Timestamp: `created_at`
   - Constraints enforcing chart_type required when relevant, rejection_reason when not_relevant

3. **Indexes** (follow patterns from 07_create_review_schema.sql)
   - On filing_id, company_id, review_status, detection_tier
   - Partial index for pending candidates
   - Index on decision type

4. **Views** (optional but useful)
   - `v_image_review_progress_by_filing` - Progress summary per filing
   - `v_image_decision_stats_by_tier` - Decision distribution by detection_tier (for pattern learning)

5. **Triggers**
   - Reuse `update_updated_at_column()` function for `image_review_candidates`

### Chart Type Values

```sql
'cohort_table', 'cohort_heatmap', 'line_chart', 'bar_chart', 'stacked_bar', 'other_chart', 'mixed'
```

### Rejection Reason Values

```sql
'decorative', 'not_a_chart', 'wrong_subject', 'duplicate', 'unreadable', 'other'
```

### Error Handling

- Use CASCADE for filing/company foreign keys
- Use SET NULL for optional segment reference
- All NOT NULL constraints where appropriate

## Test Requirements

### Coverage Target: N/A (SQL schema)

Schema validation via psql:
- Tables created successfully
- Constraints enforce valid values
- Indexes exist
- Views are queryable

## Acceptance Criteria

- [ ] `sql/09_create_image_review_schema.sql` created
- [ ] Both tables created with all columns
- [ ] `detection_tier` column exists with CHECK constraint
- [ ] Chart type and rejection reason CHECK constraints work
- [ ] Unique constraint on `(filing_id, image_src)` works
- [ ] Foreign key constraints reference correct tables
- [ ] Indexes created for common query patterns
- [ ] `updated_at` trigger works on image_review_candidates
- [ ] Schema can be applied to test database without errors
- [ ] Comments on tables and columns for documentation

## Do NOT

- Modify existing tables (filings, companies, source_segments)
- Add migrations for existing review tables (07_create_review_schema.sql)
- Create application code (that's IMG-1-2)

## Verification Commands

```bash
# Apply schema to test database
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test \
  -f sql/09_create_image_review_schema.sql

# Verify tables exist
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test \
  -c "\dt image_*"

# Verify columns
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test \
  -c "\d image_review_candidates"

# Test constraint - should fail
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test \
  -c "INSERT INTO image_review_candidates (filing_id, company_id, image_src, image_url, detection_tier, review_status) VALUES (1, 1, 'test.jpg', 'http://test', 'invalid_tier', 'pending');"

# Test constraint - should succeed
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test \
  -c "INSERT INTO image_review_candidates (filing_id, company_id, image_src, image_url, detection_tier, review_status) VALUES (1, 1, 'test.jpg', 'http://test', 'tier_1_cohort', 'pending');"
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing review schema**: `sql/07_create_review_schema.sql`
- **Dependencies**: None
- **Related**: IMG-1-2 (database methods)

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6
