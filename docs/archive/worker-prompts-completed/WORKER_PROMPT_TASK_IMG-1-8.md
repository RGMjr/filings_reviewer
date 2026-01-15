# WORKER PROMPT: Task IMG-1-8 - Integration Tests

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-8
TASK NAME:     Create integration tests for image review workflow
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-2 hours
RISK LEVEL:    None (test-only, no production code changes)
TASK SIZE:     S
DEPENDS ON:    IMG-1-4, IMG-1-5, IMG-1-6, IMG-1-7
UNLOCKS:       None (final task)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create integration tests that verify the complete image review workflow from database to API to UI rendering.

**Business Rationale**: Integration tests ensure all components work together correctly and catch regressions during future development.

**Current Behavior**: No integration tests for image review.

**Desired Behavior**: Test suite covers end-to-end workflow with database fixtures, API calls, and template rendering.

## Prerequisites

- All IMG-1-* tasks complete (IMG-1-1 through IMG-1-7)
- Understand existing integration tests: `tests/integration/web/test_review_workflow.py`

## Files to Create

1. **`tests/integration/web/test_image_review_workflow.py`** - Integration test suite

## Files to Read (Context Only)

- `tests/integration/web/test_review_workflow.py` - Existing integration test patterns
- `tests/integration/conftest.py` - Test fixtures (has `create_test_image_candidate`, `create_test_image_decision` helpers)
- `src/web/routes/review_images.py` - Routes being tested
- `src/web/routes/api_images.py` - API routes being tested
- `src/review/models.py` - Valid constants: `IMAGE_CHART_TYPES`, `IMAGE_REJECTION_REASONS`, `IMAGE_DETECTION_TIERS`

## Implementation Requirements

### Test Fixtures

Use existing helpers from `tests/integration/conftest.py`:

```python
from tests.integration.conftest import (
    create_test_company_and_filing,
    create_test_image_candidate,
)
```

1. **Database Fixtures**
   ```python
   @pytest.fixture
   def sample_filing(db):
       """Create a filing for testing."""
       company_id, filing_id = create_test_company_and_filing(db)
       return {"company_id": company_id, "filing_id": filing_id}

   @pytest.fixture
   def sample_image_candidates(db, sample_filing):
       """Create image candidates across all tiers."""
       filing_id = sample_filing["filing_id"]
       company_id = sample_filing["company_id"]
       candidate_ids = []

       # Tier 1: High confidence cohort (1 candidate)
       _, _, cid1 = create_test_image_candidate(
           db,
           filing_id=filing_id,
           company_id=company_id,
           image_src="cohort_chart.jpg",
           detection_tier="tier_1_cohort",
           cohort_confidence=0.95,
           image_index=1,
       )
       candidate_ids.append(cid1)

       # Tier 2: Large images (2 candidates)
       for i in range(2):
           _, _, cid = create_test_image_candidate(
               db,
               filing_id=filing_id,
               company_id=company_id,
               image_src=f"large_chart_{i}.jpg",
               detection_tier="tier_2_large",
               cohort_confidence=0.60,
               image_index=i + 2,
           )
           candidate_ids.append(cid)

       # Tier 3: All non-decorative (3 candidates)
       for i in range(3):
           _, _, cid = create_test_image_candidate(
               db,
               filing_id=filing_id,
               company_id=company_id,
               image_src=f"misc_chart_{i}.jpg",
               detection_tier="tier_3_all",
               cohort_confidence=0.40,
               image_index=i + 4,
           )
           candidate_ids.append(cid)

       return candidate_ids
   ```

2. **Flask Test Client** (follow existing pattern from `test_review_workflow.py`)
   ```python
   @pytest.fixture
   def app(test_db_url):
       """Create Flask app for integration testing."""
       app = create_app("testing")
       app.config["DATABASE_URL"] = test_db_url
       app.config["TESTING"] = True
       return app

   @pytest.fixture
   def client(app):
       """Flask test client."""
       return app.test_client()

   @pytest.fixture
   def db(test_db_url):
       """Create database adapter for test setup."""
       return DatabaseAdapter(test_db_url)
   ```

### Test Categories

1. **Filing List Page Tests** (3 tests)

   ```python
   def test_filing_list_renders(client, sample_filing, sample_image_candidates):
       """Filing list page renders with image candidate counts."""
       response = client.get('/review/images/filings')
       assert response.status_code == 200
       # Company name should appear in HTML
       assert b'Test Corp' in response.data

   def test_filing_list_shows_counts(client, sample_filing, sample_image_candidates):
       """Filing list shows correct pending/reviewed counts."""
       response = client.get('/review/images/filings')
       assert response.status_code == 200
       html = response.data.decode("utf-8")
       # Should show 6 total candidates (1 + 2 + 3 from fixture)
       assert "6" in html

   def test_filing_list_pagination(client, sample_filing, sample_image_candidates):
       """Filing list pagination works."""
       response = client.get('/review/images/filings?page=1&per_page=5')
       assert response.status_code == 200
   ```

2. **Review Interface Tests** (4 tests)

   ```python
   def test_review_page_renders(client, sample_filing, sample_image_candidates):
       """Review page renders with candidate data."""
       filing_id = sample_filing["filing_id"]
       response = client.get(f'/review/images/{filing_id}')
       assert response.status_code == 200
       # Should contain image URL or SEC reference
       html = response.data.decode("utf-8")
       assert 'sec.gov' in html or 'image' in html.lower()

   def test_review_page_shows_specific_candidate(client, sample_filing, sample_image_candidates):
       """Review page shows specific candidate when requested."""
       filing_id = sample_filing["filing_id"]
       candidate_id = sample_image_candidates[0]
       response = client.get(f'/review/images/{filing_id}?image_candidate_id={candidate_id}')
       assert response.status_code == 200

   def test_review_page_invalid_filing_returns_404(client):
       """Review page returns 404 for invalid filing."""
       response = client.get('/review/images/99999')
       assert response.status_code == 404

   def test_review_page_shows_tier_info(client, sample_filing, sample_image_candidates):
       """Review page displays detection tier information."""
       filing_id = sample_filing["filing_id"]
       response = client.get(f'/review/images/{filing_id}')
       assert response.status_code == 200
       html = response.data.decode("utf-8").lower()
       assert 'tier' in html
   ```

3. **API Decision Tests** (5 tests)

   Valid chart types: `cohort_table`, `cohort_heatmap`, `line_chart`, `bar_chart`, `stacked_bar`, `other_chart`, `mixed`
   Valid rejection reasons: `decorative`, `not_a_chart`, `wrong_subject`, `duplicate`, `unreadable`, `other`

   ```python
   def test_create_relevant_decision(client, sample_filing, sample_image_candidates):
       """API creates relevant decision with chart type."""
       candidate_id = sample_image_candidates[0]
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'relevant',
               'chart_type': 'bar_chart',
           },
           content_type='application/json'
       )
       assert response.status_code == 201
       data = response.get_json()
       assert data['status'] == 'success'
       assert 'decision_id' in data

   def test_create_not_relevant_decision(client, sample_filing, sample_image_candidates):
       """API creates not_relevant decision with rejection reason."""
       candidate_id = sample_image_candidates[1]
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'not_relevant',
               'rejection_reason': 'decorative',
           },
           content_type='application/json'
       )
       assert response.status_code == 201
       data = response.get_json()
       assert data['status'] == 'success'

   def test_decision_returns_next_candidate(client, sample_filing, sample_image_candidates):
       """API returns next candidate info after decision."""
       candidate_id = sample_image_candidates[0]
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'relevant',
               'chart_type': 'line_chart',
           },
           content_type='application/json'
       )
       assert response.status_code == 201
       data = response.get_json()
       assert 'next_candidate' in data

   def test_decision_validation_chart_type_required(client, sample_filing, sample_image_candidates):
       """API rejects relevant decision without chart_type."""
       candidate_id = sample_image_candidates[2]  # Use unused candidate
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'relevant',
               # Missing chart_type
           },
           content_type='application/json'
       )
       assert response.status_code == 400
       data = response.get_json()
       assert data['status'] == 'error'

   def test_decision_validation_rejection_reason_required(client, sample_filing, sample_image_candidates):
       """API rejects not_relevant decision without rejection_reason."""
       candidate_id = sample_image_candidates[3]  # Use unused candidate
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'not_relevant',
               # Missing rejection_reason
           },
           content_type='application/json'
       )
       assert response.status_code == 400
       data = response.get_json()
       assert data['status'] == 'error'
   ```

4. **Skip and Undo Tests** (3 tests)

   ```python
   def test_skip_candidate(client, sample_filing, sample_image_candidates):
       """API skips candidate and returns next."""
       candidate_id = sample_image_candidates[4]  # Use unused candidate
       response = client.post(f'/api/image-candidates/{candidate_id}/skip')
       assert response.status_code == 200
       data = response.get_json()
       assert data['status'] == 'success'

   def test_undo_decision(client, sample_filing, sample_image_candidates):
       """API deletes decision and resets candidate status."""
       # First create a decision
       candidate_id = sample_image_candidates[5]  # Use unused candidate
       create_response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'relevant',
               'chart_type': 'cohort_table',
           },
           content_type='application/json'
       )
       assert create_response.status_code == 201
       decision_id = create_response.get_json()['decision_id']

       # Then delete it
       response = client.delete(f'/api/image-decisions/{decision_id}')
       assert response.status_code == 200
       data = response.get_json()
       assert data['status'] == 'success'

   def test_undo_invalid_decision_returns_404(client):
       """API returns 404 for invalid decision ID."""
       response = client.delete('/api/image-decisions/99999')
       assert response.status_code == 404
   ```

5. **End-to-End Workflow Test** (1 test)

   ```python
   def test_full_review_workflow(client, db, sample_filing, sample_image_candidates):
       """Complete workflow: list → review → decide → navigate."""
       filing_id = sample_filing["filing_id"]

       # 1. View filing list
       list_response = client.get('/review/images/filings')
       assert list_response.status_code == 200

       # 2. Enter review for filing
       review_response = client.get(f'/review/images/{filing_id}')
       assert review_response.status_code == 200

       # 3. Make decision on first candidate
       decision_response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': sample_image_candidates[0],
               'decision': 'relevant',
               'chart_type': 'stacked_bar',
           },
           content_type='application/json'
       )
       assert decision_response.status_code == 201
       data = decision_response.get_json()
       assert data['next_candidate'] is not None  # More candidates remain
       next_url = data['next_candidate']['url']

       # 4. Follow to next candidate
       next_response = client.get(next_url)
       assert next_response.status_code == 200

       # 5. Verify database state - candidate should be reviewed
       candidate = db.get_image_candidate(sample_image_candidates[0])
       assert candidate['review_status'] == 'reviewed'
   ```

6. **Pattern Learning Verification** (1 test)

   ```python
   def test_tier_distribution_captured_with_decisions(client, db, sample_filing, sample_image_candidates):
       """Verify detection_tier is preserved when decisions are made."""
       # Make decision on tier_1_cohort candidate
       client.post('/api/image-decisions',
           json={
               'image_candidate_id': sample_image_candidates[0],
               'decision': 'relevant',
               'chart_type': 'cohort_table',
           },
           content_type='application/json'
       )

       # Verify tier is still accessible from candidate
       candidate = db.get_image_candidate(sample_image_candidates[0])
       assert candidate['detection_tier'] == 'tier_1_cohort'
   ```

7. **Navigation Tests** (2 tests)

   ```python
   def test_next_candidate_route(client, sample_filing, sample_image_candidates):
       """Next candidate route redirects correctly."""
       filing_id = sample_filing["filing_id"]
       response = client.get(f'/review/images/{filing_id}/next')
       assert response.status_code == 302  # Redirect to next pending

   def test_next_candidate_with_current_id(client, sample_filing, sample_image_candidates):
       """Next candidate route respects current parameter."""
       filing_id = sample_filing["filing_id"]
       current_id = sample_image_candidates[0]
       response = client.get(f'/review/images/{filing_id}/next?current={current_id}')
       assert response.status_code == 302
   ```

## Test Requirements

### Coverage Target: **≥ 85%** for routes tested

### Test Count: **19 tests** (3 + 4 + 5 + 3 + 1 + 1 + 2)

## Acceptance Criteria

- [ ] Test file created at `tests/integration/web/test_image_review_workflow.py`
- [ ] Fixtures use existing helpers from `tests/integration/conftest.py`
- [ ] **19 integration tests** pass
- [ ] Tests cover all page routes (filing list, review, next)
- [ ] Tests cover all API endpoints (create decision, skip, delete/undo)
- [ ] Tests verify validation errors (missing chart_type, missing rejection_reason)
- [ ] Tests verify navigation flow (next candidate, redirect behavior)
- [ ] Tests verify database state changes (status updates)
- [ ] No flaky tests (consistent pass/fail)
- [ ] All existing tests still pass

## Do NOT

- Modify existing integration tests
- Add unit tests (those are in IMG-1-2, IMG-1-4, IMG-1-5)
- Test JavaScript behavior (browser testing only)
- Add production code changes

## Verification Commands

```bash
# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_image_review_workflow.py -v

# Run with coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_image_review_workflow.py \
  --cov=src.web.routes.review_images --cov=src.web.routes.api_images \
  --cov-report=term-missing

# Run all integration tests to ensure no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/ --no-cov -q
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing integration tests**: `tests/integration/web/test_review_workflow.py`
- **Test helpers**: `tests/integration/conftest.py` (create_test_image_candidate, etc.)
- **Model constants**: `src/review/models.py` (IMAGE_CHART_TYPES, IMAGE_REJECTION_REASONS)
- **Dependencies**: All IMG-1-* tasks
- **Related**: Pattern learning queries in plan document

---

**Last Updated**: 2026-01-14
**Format Version**: 2.7

**Update Notes (2026-01-14)**:
- Added explicit imports from `tests/integration/conftest.py` helpers
- Updated fixture code to use `create_test_image_candidate` helper correctly
- Added valid chart types and rejection reasons from `src/review/models.py`
- Increased test count to 19 (added navigation tests)
- Fixed candidate index references to avoid reusing candidates across tests
- Added database state verification in end-to-end test
- Added `test_db_url` fixture pattern from existing tests
