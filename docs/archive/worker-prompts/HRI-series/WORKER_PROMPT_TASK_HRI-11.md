# WORKER PROMPT: Task HRI-11 - Statistics Dashboard

```
===============================================================================
TASK ID:       HRI-11
TASK NAME:     Create /review/stats dashboard with review metrics and visualizations
WORKSTREAM:    Human Review Interface (Nice-to-Have)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.2
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3 hr (backend 1 hr, frontend 1.5 hr, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low
PARALLEL WITH: HRI-10
===============================================================================
```

## Objective

Create a statistics dashboard at `/review/stats` that displays review progress and decision analytics. This gives reviewers visibility into their work and helps project managers track progress.

**Business Rationale**: Visibility into review progress motivates completion and helps identify bottlenecks. Currently there's no aggregate view of decisions, so managers can't track progress without running SQL queries.

**Current Behavior**: No statistics view exists. Users must run manual SQL queries to see decision counts.

**Desired Behavior**: Dashboard at `/review/stats` shows total decisions, daily trends, breakdown by metric type, and overall progress percentage.

## Prerequisites

- Existing database methods: `get_decision_statistics()` and `get_decision_stats_by_metric()` in `src/infra/db.py` (lines 1434-1620)
- Sufficient decision data (30+ decisions recommended for meaningful charts)
- Understanding of existing review routes structure

## Files to Create

1. **`src/web/templates/stats.html`** - Dashboard template with Chart.js visualizations

## Files to Modify

1. **`src/web/routes/review.py`** - Add `/review/stats` route
2. **`src/infra/db.py`** - Add `get_daily_decision_counts()` method for time series data
3. **`tests/unit/web/test_review_routes.py`** - Add tests for stats route
4. **`tests/integration/test_db_review_methods.py`** - Add tests for new DB method

## Files to Read (Context Only)

- `src/web/templates/base.html` - Base template structure for consistent styling
- `src/web/templates/filing_list.html` - Reference for card/layout patterns
- `src/web/routes/review.py` - Existing route patterns and audit logging hooks

## Implementation Requirements

### Core Functionality

1. **New Route: `/review/stats`**
   - Add route handler in `src/web/routes/review.py`
   - Fetch statistics using existing `get_decision_statistics()` method
   - Fetch metric breakdown using existing `get_decision_stats_by_metric()` method
   - Fetch daily counts using new `get_daily_decision_counts()` method
   - Pass all data to template context
   - Should work with existing audit logging hooks (no changes needed)

2. **New Database Method: `get_daily_decision_counts(days=7)`**
   - Add to `src/infra/db.py` in the Review Decision Methods section
   - Returns list of dicts with `date` and `count` for last N days
   - Include days with zero decisions (fill gaps for chart)
   - Order by date ascending (oldest first for chart rendering)

3. **Statistics to Display**
   - **Summary Cards (top row):**
     - Total decisions made
     - Accept/reject/reclassify counts with percentages
     - Average review time (if available)
     - Overall progress (reviewed / total candidates %)
   - **Daily Decisions Chart:**
     - Bar chart showing decisions per day for last 7 days
     - Use Chart.js (CDN) for visualization
     - Handle empty days (show as 0)
   - **Decisions by Metric Type:**
     - Horizontal bar chart or table showing breakdown
     - Group by metric ID, show count and accept rate
   - **Recent Activity (optional):**
     - Last 5-10 decisions with timestamp, filing, decision type

4. **Template Structure (`stats.html`)**
   - Extend `base.html` for consistent navigation/styling
   - Responsive layout using Bootstrap grid
   - Card components for each statistics section
   - Include Chart.js from CDN (no npm/bundler)
   - Graceful handling of empty data (show "No decisions yet" message)

### Error Handling

- **No decisions**: Display friendly "No review decisions yet" message with link to filing list
- **Database errors**: Catch and log, display error message to user
- **Chart rendering errors**: Degrade gracefully to text-only display

### Performance Requirements

- Page load should complete in <500ms
- Database queries should use existing indexes
- Charts should render client-side to not block server response

## Test Requirements

### Coverage Target: **≥ 90%** for new code in `src/web/routes/review.py` stats route

### Test Categories (6+ tests)

1. **Route Tests** (3 tests in `test_review_routes.py`)
   - Test `/review/stats` returns 200 status
   - Test template renders with expected context variables
   - Test route handles empty database gracefully

2. **Database Method Tests** (3 tests in `test_db_review_methods.py`)
   - Test `get_daily_decision_counts()` returns correct format
   - Test `get_daily_decision_counts()` handles empty data
   - Test `get_daily_decision_counts()` fills date gaps correctly

### Known Edge Cases to Test

- Zero decisions in database (new install)
- Single decision only
- Decisions span multiple days
- `avg_review_time_seconds` is None

## Acceptance Criteria

- [ ] `/review/stats` route accessible and returns 200
- [ ] Total decisions displayed correctly
- [ ] Accept/reject/reclassify counts shown with percentages
- [ ] Daily chart shows last 7 days with Chart.js
- [ ] Metric breakdown chart/table displays
- [ ] Progress percentage calculated correctly
- [ ] Empty state handled with friendly message
- [ ] 6+ unit tests covering route and new DB method
- [ ] Existing tests still pass
- [ ] Template extends `base.html` for consistent styling
- [ ] Page is responsive (works on mobile)
- [ ] NO changes to existing route signatures

## Do NOT

- Add real-time updates (WebSocket/polling) - static refresh is sufficient
- Add user-level statistics (no multi-user auth yet - HRI-12)
- Expose raw SQL queries in API responses
- Bundle JavaScript (use CDN for Chart.js)
- Modify existing `get_decision_statistics()` or `get_decision_stats_by_metric()` methods
- Add new npm dependencies

## Verification Commands

```bash
# Run route tests (includes new stats tests)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v

# Run DB method tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_db_review_methods.py -v -k "daily_decision"

# Check coverage for review routes
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py \
  --cov=src/web/routes/review --cov-report=term-missing

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/ tests/integration/web/ --no-cov -q

# Manual verification (start server first)
# Navigate to http://localhost:5000/review/stats
```

## Expected Impact

**Before HRI-11**:
- No visibility into review progress
- Managers must run SQL queries to check status
- Reviewers don't know how much they've completed

**After HRI-11**:
- Clear dashboard showing all key metrics
- Visual daily trend chart motivates consistent work
- Progress percentage shows completion status
- Metric breakdown helps identify problem areas

## Post-Implementation Tasks

After completing HRI-11:

1. **Update documentation:**
   - Update `docs/HUMAN_REVIEW_SYSTEM_TASKS.md` - mark HRI-11 as complete
   - Update `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md` - update P3.2 status
   - Update `docs/CLAUDE.md` if any new patterns introduced

2. **Archive this worker prompt:**
   - Move to `docs/archive/workstreams/HRI/WORKER_PROMPT_TASK_HRI-11.md`
   - Create `docs/archive/workstreams/HRI/HRI-11_COMPLETION_SUMMARY.md` with results

3. **Commit and push:**
   ```bash
   git add src/web/routes/review.py src/web/templates/stats.html src/infra/db.py \
           tests/unit/web/test_review_routes.py tests/integration/test_db_review_methods.py
   git commit -m "HRI-11: Add statistics dashboard at /review/stats

   - Add /review/stats route with review metrics dashboard
   - Add get_daily_decision_counts() DB method for time series
   - Add Chart.js visualizations for daily trends and metric breakdown
   - Display total decisions, percentages, and progress

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"
   git push origin main
   ```

## Reference

- **Issue source**: HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.2
- **Dependencies**: None (standalone, can run parallel with HRI-10)
- **Related**: HRI-12 (inter-rater agreement) will build on statistics infrastructure

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)
