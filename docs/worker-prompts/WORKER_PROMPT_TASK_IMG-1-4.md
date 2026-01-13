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
- `src/infra/db.py` - Database methods (IMG-1-2)

## Implementation Requirements

### Core Functionality

1. **Blueprint Registration**
   ```python
   review_images_bp = Blueprint('review_images', __name__, url_prefix='/review/images')
   ```

2. **Route: `/review/images/filings`**
   - List filings with image candidates
   - Query params: `status` (pending/reviewed/all), `page`, `per_page`
   - Template: `image_filing_list.html`
   - Context: filings list with candidate counts, pagination info

3. **Route: `/review/images/<int:filing_id>`**
   - Main review interface for a filing
   - Query params: `image_candidate_id` (jump to specific), `status` (filter)
   - If no candidate_id, redirect to first pending or show "all done" message
   - Template: `review_images.html`
   - Context:
     - Filing metadata (company_name, accession_number, sec_url)
     - Current candidate with all metadata
     - All candidates for sidebar (with review status)
     - Progress stats (total, pending, reviewed)
     - Chart types and rejection reasons for dropdowns

4. **Route: `/review/images/<int:filing_id>/next`**
   - Navigate to next pending candidate
   - Query params: `current` (current candidate_id)
   - Redirect to next pending candidate URL
   - If no more pending, redirect to filing list with flash message

5. **Helper: Build SEC Filing URL**
   ```python
   def build_sec_filing_url(cik: str, accession_number: str) -> str:
       """Build URL to SEC EDGAR filing page."""
       acc_no_dashes = accession_number.replace('-', '')
       return f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dashes}/"
   ```

### Template Context Variables

**For `image_filing_list.html`:**
```python
{
    'filings': [
        {
            'filing_id': int,
            'company_name': str,
            'accession_number': str,
            'total_candidates': int,
            'pending_count': int,
            'reviewed_count': int,
        },
        ...
    ],
    'pagination': {
        'page': int,
        'per_page': int,
        'total': int,
        'pages': int,
    },
    'status_filter': str,
}
```

**For `review_images.html`:**
```python
{
    'filing': {
        'filing_id': int,
        'company_name': str,
        'accession_number': str,
        'cik': str,
        'sec_url': str,
    },
    'candidate': {
        'image_candidate_id': int,
        'image_src': str,
        'image_url': str,
        'image_width': int | None,
        'image_height': int | None,
        'image_alt': str | None,
        'preceding_text': str | None,
        'detected_keywords': list[str],
        'cohort_confidence': float,
        'detection_tier': str,
        'review_status': str,
        'decision': dict | None,  # If already reviewed
    },
    'all_candidates': [...],  # For sidebar
    'progress': {
        'total': int,
        'pending': int,
        'reviewed': int,
    },
    'chart_types': [
        ('cohort_table', 'Cohort Table'),
        ('cohort_heatmap', 'Cohort Heatmap'),
        ('line_chart', 'Line Chart'),
        ('bar_chart', 'Bar Chart'),
        ('stacked_bar', 'Stacked Bar'),
        ('other_chart', 'Other Chart'),
        ('mixed', 'Mixed'),
    ],
    'rejection_reasons': [
        ('decorative', 'Decorative (logo, icon)'),
        ('not_a_chart', 'Not a Chart'),
        ('wrong_subject', 'Wrong Subject'),
        ('duplicate', 'Duplicate'),
        ('unreadable', 'Unreadable'),
        ('other', 'Other'),
    ],
}
```

### Error Handling

- 404 if filing_id not found
- 404 if image_candidate_id not found
- Redirect to filing list if filing has no candidates
- Flash messages for navigation edge cases

## Test Requirements

### Coverage Target: **≥ 85%** for `review_images.py`

### Test Categories (8+ tests recommended)

1. **Filing List Tests** (3 tests)
   - Returns filings with counts
   - Pagination works
   - Status filter works

2. **Review Interface Tests** (3 tests)
   - Renders with valid candidate
   - Redirects to first pending when no candidate_id
   - Returns 404 for invalid filing

3. **Navigation Tests** (2 tests)
   - Next route redirects correctly
   - Next route handles "all done" case

## Acceptance Criteria

- [ ] Blueprint created and registered in app.py
- [ ] `/review/images/filings` renders filing list
- [ ] `/review/images/<filing_id>` renders review interface
- [ ] `/review/images/<filing_id>/next` navigates correctly
- [ ] Context variables include all required data
- [ ] 404 errors for invalid filing/candidate IDs
- [ ] Flash messages for edge cases
- [ ] **8+ unit tests** covering routes
- [ ] All new tests pass
- [ ] All existing tests still pass

## Do NOT

- Create templates (that's IMG-1-6)
- Create API routes (that's IMG-1-5)
- Modify existing review routes (`src/web/routes/review.py`)
- Add JavaScript (that's IMG-1-7)

## Verification Commands

```bash
# Run tests for new routes
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_images_routes.py -v

# Verify blueprint registered (start app and check routes)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python -c "from src.web.app import create_app; app = create_app(); print([r.rule for r in app.url_map.iter_rules() if 'images' in r.rule])"

# Manual verification (after templates exist)
# DATABASE_URL=... python -m flask --app src.web.app run
# Visit http://localhost:5000/review/images/filings
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing review routes**: `src/web/routes/review.py`
- **Dependencies**: IMG-1-2 (database methods)
- **Related**: IMG-1-5 (API routes), IMG-1-6 (templates)

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6
