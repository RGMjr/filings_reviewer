# WORKER PROMPT: Task HRI-6 - Add Filtering and Sorting to Review Interface

```
===============================================================================
TASK ID:       HRI-6
TASK NAME:     Add candidate filtering and sorting options to review interface
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.5
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2 hr (backend 45 min, frontend 45 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low
PARALLEL WITH: HRI-4, HRI-5
===============================================================================
```

## Objective

Add filter dropdowns and sort options for candidates to improve review efficiency. Reviewers can focus on specific subsets (e.g., low-confidence candidates first) instead of reviewing in document order.

**Business Rationale**: Power users reviewing large filings with 50+ candidates waste time scrolling through already-reviewed items. Filters let them focus on pending candidates, specific metric types, or uncertain classifications that need attention.

**Current Behavior**:
- Candidates shown in document order (by `char_position`)
- No way to filter by status, metric type, or confidence level
- No way to sort by confidence or value magnitude
- Must scroll through entire list to find specific candidates

**Desired Behavior**:
- Dropdown filters for status, metric type, and confidence level
- Sort options: document order, confidence (asc/desc), value magnitude
- Filters persist in URL parameters for bookmarking/sharing
- Active filters shown as badges with "Clear all" option

## Prerequisites

- None (standalone)
- Read `src/web/routes/review.py` lines 280-350 for `review_filing()` route
- Read `src/infra/db.py` `get_review_candidates_with_decisions()` method

## Files to Modify

1. **`src/infra/db.py`** - Add filter/sort parameters to `get_review_candidates_with_decisions()`
2. **`src/web/routes/review.py`** - Parse URL query params, pass to db method and template
3. **`src/web/templates/review.html`** - Add filter/sort UI controls in progress bar section
4. **`tests/unit/web/test_review_routes.py`** - Add tests for filter/sort URL parameters
5. **`tests/integration/web/test_review_workflow.py`** - Add integration tests for filtered views

## Files to Read (Context Only)

- `src/web/templates/review.html:70-100` - Progress bar section (add filters here)
- `src/web/templates/review.html:530-570` - Sidebar candidate list (receives filtered data)
- `src/infra/db.py:618-720` - Current `get_review_candidates_with_decisions()` implementation
- `src/review/models.py` - `REVIEW_STATUSES` constant for valid status values

## Implementation Requirements

### 1. Database Layer: Enhanced Candidate Query

**Location**: `src/infra/db.py` - `get_review_candidates_with_decisions()` method

- Add new optional parameters:
  - `metric_id: Optional[str]` - Filter by `suggested_metric_id`
  - `confidence_level: Optional[str]` - Filter by confidence tier: 'high' (>=0.7), 'medium' (0.4-0.7), 'low' (<0.4)
  - `sort_by: Optional[str]` - Sort field: 'position' (default), 'confidence_asc', 'confidence_desc', 'value_asc', 'value_desc'

- Confidence level filtering should use these thresholds:
  - `high`: `suggestion_confidence >= 0.7`
  - `medium`: `suggestion_confidence >= 0.4 AND suggestion_confidence < 0.7`
  - `low`: `suggestion_confidence < 0.4`

- Sort options should map to ORDER BY clauses:
  - `position`: `ORDER BY char_position` (current default)
  - `confidence_asc`: `ORDER BY suggestion_confidence ASC, char_position`
  - `confidence_desc`: `ORDER BY suggestion_confidence DESC, char_position`
  - `value_asc`: `ORDER BY parsed_value ASC, char_position`
  - `value_desc`: `ORDER BY parsed_value DESC, char_position`

- Validate parameters to prevent SQL injection

### 2. Route Layer: URL Parameter Parsing

**Location**: `src/web/routes/review.py` - `review_filing()` route

- Parse query parameters from URL:
  - `status`: 'pending' | 'reviewed' | 'all' (default 'all')
  - `metric`: metric_id string or 'all'
  - `confidence`: 'high' | 'medium' | 'low' | 'all'
  - `sort`: 'position' | 'confidence_asc' | 'confidence_desc' | 'value_asc' | 'value_desc'

- Pass parsed parameters to `get_review_candidates_with_decisions()`

- Add helper function to get unique metrics for current filing (for dropdown options):
  ```python
  def get_unique_metrics_for_filing(candidates: List[Dict]) -> List[str]:
      """Extract unique metric IDs from candidates for filter dropdown."""
      pass
  ```

- Pass filter state to template context:
  - `current_filters`: dict with current filter values
  - `available_metrics`: list of unique metrics in this filing
  - `sort_options`: list of available sort options

### 3. Template Layer: Filter UI

**Location**: `src/web/templates/review.html` - Add below progress bar (around line 100)

- Add a filter bar with Bootstrap dropdowns:
  - Status dropdown: All | Pending | Reviewed
  - Metric dropdown: All | [list of metrics in filing]
  - Confidence dropdown: All | High (70%+) | Medium (40-70%) | Low (<40%)
  - Sort dropdown: Document Order | Confidence (Low First) | Confidence (High First) | Value (Low First) | Value (High First)

- Active filters shown as dismissible badges
- "Clear all filters" button when any filter is active
- Filters submit as GET parameters (form with method="GET")
- Show count of filtered results: "Showing X of Y candidates"

### 4. URL Parameter Persistence

- All filter state encoded in URL query string:
  - Example: `?status=pending&confidence=low&sort=confidence_asc`
- Enables bookmarking and sharing filtered views
- Form submission preserves filing_id in URL path

### Error Handling

- **Invalid filter values**: Ignore and use defaults (don't error)
- **Invalid sort values**: Fall back to 'position' (document order)
- **Empty results**: Show "No candidates match filters" message with clear button
- **Missing confidence data**: Treat NULL confidence as excluded from confidence filters

### Performance Requirements

- Filter UI should not add perceptible latency (<50ms additional)
- Database query should remain efficient with filters (indexes exist on relevant columns)
- No client-side filtering (all filtering server-side for consistency)

## Test Requirements

### Coverage Target: **>= 90%** for modified routes

### Test Categories (10+ tests recommended)

1. **URL Parameter Parsing Tests** (4 tests)
   - Valid status filter applied to query
   - Valid confidence filter applied to query
   - Valid sort parameter applied
   - Invalid parameters ignored (fallback to defaults)

2. **Filter Behavior Tests** (3 tests)
   - Status filter returns only matching candidates
   - Confidence filter uses correct thresholds
   - Combined filters work correctly (AND logic)

3. **Sort Behavior Tests** (2 tests)
   - Sort by confidence ascending
   - Sort by confidence descending

4. **Template Context Tests** (2 tests)
   - Filter controls receive correct current values
   - Available metrics list populated correctly

5. **Integration Tests** (2 tests)
   - End-to-end: apply filter, verify filtered results displayed
   - URL parameters persist across navigation

### Known Edge Cases to Test

- Filing with no pending candidates (status=pending returns empty)
- Filing with all same confidence level
- Candidate with NULL confidence value
- Single-candidate filing (trivial case)

## Acceptance Criteria

- [ ] Status filter dropdown working (All/Pending/Reviewed)
- [ ] Metric type filter dropdown populated with filing's metrics
- [ ] Confidence level filter working (All/High/Medium/Low)
- [ ] Sort dropdown with 5 options (position, confidence x2, value x2)
- [ ] Filters persist in URL query parameters
- [ ] "Showing X of Y candidates" count displayed
- [ ] "Clear all filters" button works
- [ ] Active filters shown as dismissible badges
- [ ] Invalid parameters handled gracefully (no errors)
- [ ] **10+ unit tests** covering filter/sort scenarios
- [ ] **Test coverage >= 90%** for `src/web/routes/review.py`
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] `mypy src/web/routes/review.py --strict` passes (if previously passing)

## Do NOT

- Add client-side (JavaScript) filtering (use server-side only for consistency)
- Modify candidate generation logic (`src/review/candidate_generator.py`)
- Change pagination behavior significantly (filters work within existing pagination)
- Add new database indexes (existing indexes should be sufficient)
- Modify the sidebar candidate list layout (just populate with filtered data)
- Add sort by metric type (not useful, creates inconsistent ordering)

## Verification Commands

```bash
# Run route tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v --tb=short

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_review_workflow.py -v --tb=short

# Check coverage (must be >= 90%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py \
  --cov=src/web/routes/review --cov-report=term-missing

# Type safety check
mypy src/web/routes/review.py --strict

# Manual verification:
# 1. Start server: DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -m flask --app src.web.app run --debug --port 5002
# 2. Navigate to /review/filings, select a filing
# 3. Test each filter dropdown
# 4. Test sort options
# 5. Verify URL updates with filter params
# 6. Verify "Clear all" resets filters
# 7. Verify empty results show appropriate message
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example database layer changes</summary>

```python
# In src/infra/db.py - get_review_candidates_with_decisions()

# Add new parameters
def get_review_candidates_with_decisions(
    self,
    filing_id: int,
    status: Optional[str] = None,
    metric_id: Optional[str] = None,
    confidence_level: Optional[str] = None,  # 'high', 'medium', 'low'
    sort_by: str = 'position',  # 'position', 'confidence_asc', etc.
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict]:
    # ... existing code ...

    # Add metric filter
    if metric_id:
        sql += " AND rc.suggested_metric_id = %(metric_id)s"
        params["metric_id"] = metric_id

    # Add confidence filter
    if confidence_level == 'high':
        sql += " AND rc.suggestion_confidence >= 0.7"
    elif confidence_level == 'medium':
        sql += " AND rc.suggestion_confidence >= 0.4 AND rc.suggestion_confidence < 0.7"
    elif confidence_level == 'low':
        sql += " AND rc.suggestion_confidence < 0.4"

    # Dynamic ORDER BY
    sort_clauses = {
        'position': 'rc.char_position',
        'confidence_asc': 'rc.suggestion_confidence ASC, rc.char_position',
        'confidence_desc': 'rc.suggestion_confidence DESC, rc.char_position',
        'value_asc': 'rc.parsed_value ASC, rc.char_position',
        'value_desc': 'rc.parsed_value DESC, rc.char_position',
    }
    order_by = sort_clauses.get(sort_by, 'rc.char_position')
    sql += f" ORDER BY {order_by}"
```

</details>

<details>
<summary>Expand to see example template filter UI</summary>

```jinja2
{# Add after progress bar section (around line 100) #}
<div class="card mb-3">
    <div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-center">
            {# Status Filter #}
            <div class="col-auto">
                <label class="visually-hidden" for="statusFilter">Status</label>
                <select name="status" id="statusFilter" class="form-select form-select-sm">
                    <option value="all" {{ 'selected' if current_filters.status == 'all' }}>All Status</option>
                    <option value="pending" {{ 'selected' if current_filters.status == 'pending' }}>Pending</option>
                    <option value="reviewed" {{ 'selected' if current_filters.status == 'reviewed' }}>Reviewed</option>
                </select>
            </div>

            {# Metric Filter #}
            <div class="col-auto">
                <select name="metric" class="form-select form-select-sm">
                    <option value="all">All Metrics</option>
                    {% for metric in available_metrics %}
                        <option value="{{ metric }}" {{ 'selected' if current_filters.metric == metric }}>
                            {{ metric|replace('_', ' ')|title|truncate(25) }}
                        </option>
                    {% endfor %}
                </select>
            </div>

            {# Confidence Filter #}
            <div class="col-auto">
                <select name="confidence" class="form-select form-select-sm">
                    <option value="all">All Confidence</option>
                    <option value="high" {{ 'selected' if current_filters.confidence == 'high' }}>High (70%+)</option>
                    <option value="medium" {{ 'selected' if current_filters.confidence == 'medium' }}>Medium (40-70%)</option>
                    <option value="low" {{ 'selected' if current_filters.confidence == 'low' }}>Low (&lt;40%)</option>
                </select>
            </div>

            {# Sort #}
            <div class="col-auto">
                <select name="sort" class="form-select form-select-sm">
                    <option value="position">Document Order</option>
                    <option value="confidence_asc" {{ 'selected' if current_filters.sort == 'confidence_asc' }}>Confidence (Low First)</option>
                    <option value="confidence_desc" {{ 'selected' if current_filters.sort == 'confidence_desc' }}>Confidence (High First)</option>
                    <option value="value_asc" {{ 'selected' if current_filters.sort == 'value_asc' }}>Value (Low First)</option>
                    <option value="value_desc" {{ 'selected' if current_filters.sort == 'value_desc' }}>Value (High First)</option>
                </select>
            </div>

            <div class="col-auto">
                <button type="submit" class="btn btn-primary btn-sm">Apply</button>
            </div>

            {% if current_filters.has_active_filters %}
                <div class="col-auto">
                    <a href="{{ url_for('review.review_filing', filing_id=filing.filing_id) }}"
                       class="btn btn-outline-secondary btn-sm">Clear All</a>
                </div>
            {% endif %}
        </form>

        {# Results count #}
        <div class="text-muted small mt-2">
            Showing {{ candidates|length }} of {{ total_candidates }} candidates
            {% if current_filters.has_active_filters %}
                (filtered)
            {% endif %}
        </div>
    </div>
</div>
```

</details>

## Reference

- **Issue source**: HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.5
- **Related completed tasks**:
  - HRI-1 (Fix Health Check Bug) - commit 82aa9da
  - HRI-2 (Add API Audit Logging) - commit 32291b0
  - HRI-3 (Improve Metric Classification Accuracy) - commit cfdb296
- **Related pending tasks**:
  - HRI-4 (Display Confidence Scores) - can run in parallel
  - HRI-5 (Keyboard Shortcuts) - can run in parallel
  - HRI-8 (Bulk Actions) - depends on HRI-6 completion

## Post-Implementation

After completing this task:

1. **Manual testing**:
   - Test all filter combinations on at least 2 filings
   - Verify URL parameters update correctly
   - Test clear filters functionality
   - Verify empty results show appropriate message

2. **Update documentation**:
   - Mark HRI-6 as complete in `docs/HUMAN_REVIEW_SYSTEM_TASKS.md`
   - Update status in `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md`

3. **Archive this file**:
   - Move to `docs/archive/worker-prompts/WORKER_PROMPT_TASK_HRI-6.md`

4. **Commit and push**:
   ```bash
   git add src/infra/db.py src/web/routes/review.py src/web/templates/review.html
   git add tests/unit/web/test_review_routes.py tests/integration/web/test_review_workflow.py
   git add docs/HUMAN_REVIEW_SYSTEM_TASKS.md docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md
   git commit -m "HRI-6: Add filtering and sorting to review interface

   - Add filter dropdowns: status, metric type, confidence level
   - Add sort options: document order, confidence (asc/desc), value (asc/desc)
   - Filters persist in URL query parameters for bookmarking
   - Show 'Showing X of Y candidates' count with filtered results
   - Add 'Clear all filters' button when filters active
   - Enhanced get_review_candidates_with_decisions() with filter params
   - 10+ unit tests covering filter/sort scenarios

   Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"

   git push origin main
   ```

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)
