# WORKER PROMPT: Task IMG-1-4 - Page Routes for Image Review

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-4
TASK NAME:     Create Flask page routes for image review UI
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours
RISK LEVEL:    Low (new routes, no existing routes modified)
TASK SIZE:     M
DEPENDS ON:    IMG-1-2
UNLOCKS:       IMG-1-6
BLOCKS:        IMG-1-6, IMG-1-7, IMG-1-8
PARALLEL WITH: IMG-1-3, IMG-1-5
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create Flask page routes for the image review UI under `/review/images/`. These routes render HTML templates for human reviewers to classify chart images.

**Business Rationale**: Web interface enables efficient human review of chart images with keyboard shortcuts and visual context.

**Current Behavior**: No image review routes exist.

**Desired Behavior**: Three page routes render filing list, review interface, and navigation.

## Prerequisites

- IMG-1-2 complete (database methods exist)
- Understand existing review routes: `src/web/routes/review.py`

## Files to Create

1. **`src/web/routes/review_images.py`** - New blueprint with page routes

## Files to Modify

1. **`src/web/app.py`** - Register new blueprint

## Files to Read (Context Only)

- `src/web/routes/review.py` - Existing review routes (patterns to follow)
- `src/web/templates/review.html` - Existing review template (structure reference)
- `src/infra/db.py` - Database methods (IMG-1-2), specifically:
  - `get_filings_with_image_candidates()` - Returns filing list with counts
  - `get_filings_with_image_candidates_count()` - Returns total count for pagination
  - `get_image_review_candidates_for_filing()` - Returns candidates with decision data
  - `get_image_review_candidate()` - Returns single candidate with full context
  - `get_next_pending_image_candidate()` - Returns next pending for navigation
  - `get_image_review_progress()` - Returns overall progress stats
- `src/review/models.py` - Constants: `IMAGE_CHART_TYPES`, `IMAGE_REJECTION_REASONS`, `IMAGE_REVIEW_STATUSES`, `IMAGE_DECISIONS`

## Implementation Requirements

### Core Functionality

1. **Blueprint Registration**
   ```python
   review_images_bp = Blueprint('review_images', __name__, url_prefix='/review/images')
   ```

2. **Route: `/review/images/filings`**
   - List filings with image candidates
   - Query params: `status` (pending/reviewed/skipped), `page`, `per_page`
   - Template: `image_filing_list.html`
   - Context: filings list with candidate counts, pagination info

3. **Route: `/review/images/<int:filing_id>`**
   - Main review interface for a filing
   - Query params: `image_candidate_id` (jump to specific), `status` (filter), `sort` (tier/confidence/position)
   - If no candidate_id, select first pending or first candidate if none pending
   - Template: `review_images.html`
   - Context: See "Template Context Variables" section below

4. **Route: `/review/images/<int:filing_id>/next`**
   - Navigate to next pending candidate
   - Query params: `current` (current candidate_id)
   - Uses `db.get_next_pending_image_candidate()` for navigation
   - Redirect to next pending candidate URL
   - If no more pending, redirect to filing list with flash message

5. **Helper: Build SEC Filing URL**
   ```python
   def _build_sec_filing_url(cik: str, accession_number: str) -> str:
       """Build URL to SEC EDGAR filing directory."""
       acc_no_dashes = accession_number.replace('-', '')
       cik_stripped = cik.lstrip('0') or '0'
       return f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{acc_no_dashes}/"
   ```

   **Note**: This is a simpler version than `_resolve_sec_filing_url()` in review.py. For image review, we only need the directory URL since we're linking to images, not the primary document.

### Template Context Variables

**For `image_filing_list.html`:**

This matches the return value of `db.get_filings_with_image_candidates()`:

```python
{
    'filings': [
        {
            'filing_id': int,
            'accession_number': str,
            'form_type': str,
            'filing_date': datetime,
            'company_name': str,
            'cik': str,
            'total_candidates': int,
            'pending_count': int,
            'reviewed_count': int,
            'skipped_count': int,
            'first_candidate_date': datetime,
        },
        ...
    ],
    'pagination': {
        'page': int,
        'per_page': int,
        'offset': int,
        'limit': int,
        'total_count': int,
        'total_pages': int,
        'has_prev': bool,
        'has_next': bool,
    },
    'progress': {  # From db.get_image_review_progress()
        'total_candidates': int,
        'pending_count': int,
        'reviewed_count': int,
        'skipped_count': int,
        'review_pct': float,
        'total_filings': int,
        'filings_with_pending': int,
        'by_tier': dict,
    },
    'current_status_filter': str | None,
    'review_statuses': tuple,  # IMAGE_REVIEW_STATUSES
}
```

**For `review_images.html`:**

Candidate data comes from `db.get_image_review_candidates_for_filing()` which returns flat rows with decision fields from LEFT JOIN:

```python
{
    'filing': {
        'filing_id': int,
        'company_id': int,
        'company_name': str,
        'cik': str,
        'accession_number': str,
        'form_type': str,
        'filing_date': datetime,
        'sec_url': str,  # Built by _build_sec_filing_url()
    },
    'current_candidate': {
        # Core candidate fields (from image_review_candidates table)
        'image_candidate_id': int,
        'filing_id': int,
        'company_id': int,
        'image_src': str,
        'image_url': str | None,
        'image_width': int | None,
        'image_height': int | None,
        'image_alt': str | None,
        'image_index': int,
        'preceding_text': str | None,
        'detected_keywords': list | None,  # JSONB array, may be None
        'cohort_confidence': float | None,
        'detection_tier': str | None,
        'review_status': str,
        'created_at': datetime,

        # Decision fields (from LEFT JOIN to image_review_decisions)
        'image_decision_id': int | None,
        'decision': str | None,  # 'relevant' | 'not_relevant'
        'chart_type': str | None,
        'rejection_reason': str | None,
        'decision_notes': str | None,  # Aliased from reviewer_notes
        'review_time_seconds': int | None,
        'decision_created_at': datetime | None,
    },
    'candidates': [...],  # All candidates for sidebar (same structure)
    'all_candidates': [...],  # Unfiltered candidates for progress calculation
    'progress': {
        'total': int,
        'pending': int,
        'reviewed': int,
        'skipped': int,
    },
    'current_filters': {
        'status': str,  # 'pending', 'reviewed', 'skipped', or 'all'
        'sort': str,  # 'tier', 'confidence', or 'position'
        'has_active_filters': bool,
    },
    'chart_types': [  # For dropdown - matches IMAGE_CHART_TYPES
        ('cohort_table', 'Cohort Table'),
        ('cohort_heatmap', 'Cohort Heatmap'),
        ('line_chart', 'Line Chart'),
        ('bar_chart', 'Bar Chart'),
        ('stacked_bar', 'Stacked Bar'),
        ('other_chart', 'Other Chart'),
        ('mixed', 'Mixed'),
    ],
    'rejection_reasons': [  # For dropdown - matches IMAGE_REJECTION_REASONS
        ('decorative', 'Decorative (logo, icon)'),
        ('not_a_chart', 'Not a Chart'),
        ('wrong_subject', 'Wrong Subject'),
        ('duplicate', 'Duplicate'),
        ('unreadable', 'Unreadable'),
        ('other', 'Other'),
    ],
    'image_decisions': tuple,  # IMAGE_DECISIONS ('relevant', 'not_relevant')
    'review_statuses': tuple,  # IMAGE_REVIEW_STATUSES
}
```

### Error Handling

- 404 if filing_id not found
- Redirect to filing list if filing has no candidates (with flash message)
- Flash warning if requested candidate_id not found, show first pending instead
- Flash success when all candidates reviewed

### Design Decision: No Audit Logging (for now)

The existing `review.py` has `@review_bp.before_request` and `@review_bp.after_request` hooks for audit logging. For IMG-1-4, we will **not** add audit logging to keep the scope focused. This can be added as a follow-up task (IMG-1-9) if needed for compliance.

## Test Requirements

### Coverage Target: **≥ 85%** for `review_images.py`

### Test File: `tests/unit/web/test_review_images_routes.py`

### Test Categories (10+ tests recommended)

1. **Filing List Tests** (4 tests)
   - `test_filing_list_returns_filings_with_counts` - Basic list display
   - `test_filing_list_pagination_works` - Page/per_page params
   - `test_filing_list_status_filter_works` - Filter by pending/reviewed/skipped
   - `test_filing_list_invalid_status_shows_warning` - Invalid filter handled

2. **Review Interface Tests** (4 tests)
   - `test_review_filing_renders_with_valid_candidate` - Basic render
   - `test_review_filing_selects_first_pending_when_no_id` - Default selection
   - `test_review_filing_404_for_invalid_filing` - Filing not found
   - `test_review_filing_redirects_when_no_candidates` - Empty filing

3. **Navigation Tests** (3 tests)
   - `test_next_candidate_redirects_correctly` - Normal navigation
   - `test_next_candidate_handles_all_done` - No more pending
   - `test_next_candidate_error_handling` - Database error

## Acceptance Criteria

- [ ] Blueprint created and registered in app.py
- [ ] `/review/images/` redirects to `/review/images/filings`
- [ ] `/review/images/filings` renders filing list with correct context
- [ ] `/review/images/<filing_id>` renders review interface with correct context
- [ ] `/review/images/<filing_id>/next` navigates correctly
- [ ] Context variables match database return structures exactly
- [ ] 404 errors for invalid filing IDs
- [ ] Flash messages for edge cases (all done, candidate not found, etc.)
- [ ] **10+ unit tests** covering routes
- [ ] ≥ 85% test coverage for `review_images.py`
- [ ] All new tests pass
- [ ] All existing tests still pass

## Do NOT

- Create templates (that's IMG-1-6)
- Create API routes (that's IMG-1-5)
- Modify existing review routes (`src/web/routes/review.py`)
- Add JavaScript (that's IMG-1-7)
- Add audit logging (defer to IMG-1-9 if needed)

## Verification Commands

```bash
# Run tests for new routes
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_images_routes.py -v --tb=short

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_images_routes.py \
  --cov=src.web.routes.review_images --cov-report=term-missing

# Verify blueprint registered (start app and check routes)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python -c "from src.web.app import create_app; app = create_app(); print([r.rule for r in app.url_map.iter_rules() if 'images' in r.rule])"

# Manual verification (after templates exist in IMG-1-6)
# DATABASE_URL=... python -m flask --app src.web.app run
# Visit http://localhost:5000/review/images/filings
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing review routes**: `src/web/routes/review.py`
- **Dependencies**: IMG-1-2 (database methods)
- **Related**: IMG-1-5 (API routes), IMG-1-6 (templates)

---

**Last Updated**: 2026-01-13
**Format Version**: 2.6
**Revision Notes**: Updated template context variables to match actual database return structures. Added explicit DB method references. Clarified that decision fields are flat (from LEFT JOIN), not nested dict. Added audit logging design decision. Increased test count to 10+.
