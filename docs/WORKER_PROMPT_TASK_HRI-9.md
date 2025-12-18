# WORKER PROMPT: Task HRI-9 - Add Context Expansion

```
===============================================================================
TASK ID:       HRI-9
TASK NAME:     Add "Show more context" and "View in SEC filing" links
WORKSTREAM:    Human Review Interface (Nice-to-Have)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.1
STATUS:        COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 1 hr (backend 20 min, frontend 40 min)
TIME ACTUAL:   ~1 hr
RISK LEVEL:    Low
PARALLEL WITH: HRI-10, HRI-11 (all independent P3 tasks)
===============================================================================
```

## Objective

Add "Show more context" and "View in SEC filing" capabilities to candidate cards, allowing reviewers to see surrounding text and verify against the original SEC document.

**Business Rationale**: Sometimes the default 30-50 word context isn't enough to confidently classify a candidate. Direct links to SEC filings enable verification of ambiguous cases without leaving the review interface.

**Current Behavior**: Fixed context window (~50 words) with no link to source document.

**Desired Behavior**:
- "Show more" button expands context to ~150+ words
- "View in SEC" link opens the original SEC EDGAR filing in a new tab

## Prerequisites

- None (standalone task)
- Understanding of source_segments table structure (stores segment metadata)
- Familiarity with review.html template from HRI-4/HRI-5/HRI-6/HRI-7

## Files to Modify

1. **`src/web/routes/review.py`** - Add endpoint for fetching expanded context
2. **`src/web/routes/api.py`** - Add API endpoint for AJAX context expansion (alternative)
3. **`src/web/templates/review.html`** - Add "Show more" button and SEC link UI
4. **`src/web/static/js/review.js`** - Add AJAX handler for context expansion
5. **`src/infra/db.py`** - Add method to fetch adjacent segments (if not existing)

## Files to Read (Context Only)

- `sql/03_create_analysis_schema.sql` - source_segments table schema (sequence_index for ordering)
- `src/infra/db.py` - Existing `get_source_segments_for_filing()` method
- `src/web/templates/review.html` - Current candidate card structure
- Recent HRI commits (568779c, 77d1c23) - Established patterns for review UI features

## Implementation Requirements

### 1. SEC Filing Link

- **Construct SEC EDGAR URL** from existing filing metadata:
  - Format: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number_nodashes}/{primary_document}`
  - The `accession_number` needs dashes removed (e.g., `0001193125-24-123456` → `0001193125024123456`)
  - Use `sec_html_url` from filings table if available (may already be complete URL)
- **UI Element**:
  - Small link/button with external link icon
  - Text: "View in SEC" or icon-only with tooltip
  - Opens in new tab (`target="_blank"`)
  - Position: Near candidate header or in action button area

### 2. Context Expansion ("Show More")

- **Fetch Adjacent Segments**:
  - Use `source_segment_id` from candidate to locate current segment
  - Fetch segments with `sequence_index` ± 1-2 (before and after)
  - Concatenate text from adjacent segments
  - Return expanded context (target: 150-300 words)

- **API Endpoint** (choose one approach):
  - Option A: `GET /api/candidates/<candidate_id>/expanded-context`
  - Option B: `GET /review/context/<candidate_id>`
  - Return JSON: `{"expanded_context": "...", "segment_count": N}`

- **UI Behavior**:
  - Button text: "Show more" initially
  - After expansion: "Show less" to collapse
  - Smooth expansion animation (CSS transition)
  - Loading indicator during fetch

- **Edge Cases**:
  - Handle missing source_segment_id (show disabled button or hide)
  - Handle segments at beginning/end of filing (fewer adjacent segments)
  - Handle segments with no adjacent segments (return current context only)

### 3. Data Requirements

- **From review_candidates table**:
  - `source_segment_id` (foreign key to source_segments)
  - Candidate already has `context_text` for current display

- **From source_segments table**:
  - `sequence_index` for ordering
  - `raw_text` for expanded content
  - `filing_id` for fetching adjacent segments

- **From filings table**:
  - `cik`, `accession_number`, `sec_html_url` for SEC link construction

### Error Handling

- **Missing segment**: Return current context with flag `"can_expand": false`
- **Database error**: Return 500 with error message, log error
- **Invalid candidate_id**: Return 404

## Test Requirements

### Coverage Target: **>= 90%** for new code paths

### Test Categories (6+ tests)

1. **SEC Link Construction** (2 tests)
   - Test correct URL constructed from filing metadata
   - Test graceful handling when sec_html_url is already complete URL

2. **Context Expansion Endpoint** (3 tests)
   - Test expanded context returned for valid candidate
   - Test handles candidate with no source_segment_id
   - Test handles segment at filing boundary (first/last segment)

3. **Edge Cases** (1+ tests)
   - Test 404 for invalid candidate_id
   - Test handles missing adjacent segments gracefully

### Manual Testing Checklist

- [ ] "View in SEC" link opens correct filing page
- [ ] "Show more" button fetches and displays expanded context
- [ ] "Show less" collapses back to original context
- [ ] Loading indicator appears during fetch
- [ ] Works across different filings (S-1, F-1)

## Acceptance Criteria

- [ ] "View in SEC filing" link present on each candidate card
- [ ] Link opens correct SEC EDGAR page in new tab
- [ ] "Show more context" button appears when expansion available
- [ ] Clicking "Show more" fetches and displays ~150 words of surrounding context
- [ ] "Show less" collapses back to original view
- [ ] Graceful handling when expansion not available (no button or disabled)
- [ ] 6+ unit tests covering new functionality
- [ ] All existing tests still pass
- [ ] JavaScript syntax valid (`node --check src/web/static/js/review.js`)
- [ ] No breaking changes to existing review workflow

## Do NOT

- Embed full SEC filing content (just link to it)
- Cache expanded context long-term (fetch fresh each time)
- Change the default context size (keep existing ~50 word window)
- Modify source_segments table schema
- Add new dependencies (use existing Flask/Jinja2/vanilla JS patterns)
- Break existing candidate card layout

## Verification Commands

```bash
# Run review route tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v

# Run API tests (if endpoint added to api.py)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api.py -v

# Check JavaScript syntax
node --check src/web/static/js/review.js

# Full web tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/ tests/integration/web/ -v --tb=short

# Manual verification (start server, review a filing)
# 1. Click "View in SEC" - verify correct page opens
# 2. Click "Show more" - verify context expands
# 3. Click "Show less" - verify context collapses
```

## Expected Impact

**Before HRI-9**:
- Reviewers see ~50 words of context, fixed
- Must manually navigate to SEC EDGAR to verify
- Ambiguous cases require external research

**After HRI-9**:
- Reviewers can expand to ~150 words with one click
- Direct link to SEC filing for verification
- Faster decision-making on edge cases

## Post-Implementation Tasks

After completing HRI-9:

1. **Update Documentation**:
   - Mark HRI-9 as COMPLETE in `docs/HUMAN_REVIEW_SYSTEM_TASKS.md`
   - Update `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md` P3.1 status
   - Add implementation notes (commit hash, any deviations from plan)

2. **Archive**:
   - No temporary files expected for this task

3. **Commit and Push**:
   ```bash
   git add src/web/routes/review.py src/web/routes/api.py \
           src/web/templates/review.html src/web/static/js/review.js \
           src/infra/db.py tests/unit/web/ docs/
   git commit -m "HRI-9: Add context expansion and SEC filing links

   - Add 'View in SEC' link to candidate cards (opens EDGAR in new tab)
   - Add 'Show more context' with AJAX expansion to ~150 words
   - Add endpoint for fetching adjacent segment text
   - N tests added covering expansion and link generation

   Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"
   git push origin main
   ```

## Reference

- **Issue source**: HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.1
- **Dependencies**: None
- **Related tasks**: HRI-10 (Session Persistence), HRI-11 (Statistics Dashboard)
- **Completed prerequisites**: HRI-6 (Filtering), HRI-7 (Decision History)

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)
