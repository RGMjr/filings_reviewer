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
- `tests/conftest.py` - Test fixtures
- `src/web/routes/review_images.py` - Routes being tested
- `src/web/routes/api_images.py` - API routes being tested

## Implementation Requirements

### Test Fixtures

1. **Database Fixtures**
   ```python
   @pytest.fixture
   def sample_filing(db):
       """Create a filing for testing."""
       # Insert company and filing
       # Return filing_id

   @pytest.fixture
   def sample_image_candidates(db, sample_filing):
       """Create image candidates across all tiers."""
       # Insert candidates:
       # - 1 tier_1_cohort (high confidence)
       # - 2 tier_2_large
       # - 3 tier_3_all
       # Return list of candidate_ids
   ```

2. **Flask Test Client**
   ```python
   @pytest.fixture
   def client(app):
       """Flask test client."""
       return app.test_client()
   ```

### Test Categories

1. **Filing List Page Tests** (3 tests)

   ```python
   def test_filing_list_renders(client, sample_filing, sample_image_candidates):
       """Filing list page renders with image candidate counts."""
       response = client.get('/review/images/filings')
       assert response.status_code == 200
       assert b'sample_company' in response.data  # Company name appears

   def test_filing_list_shows_counts(client, sample_filing, sample_image_candidates):
       """Filing list shows correct pending/reviewed counts."""
       response = client.get('/review/images/filings')
       assert b'6' in response.data  # Total candidates
       assert b'pending' in response.data.lower()

   def test_filing_list_pagination(client, sample_filing):
       """Filing list pagination works."""
       response = client.get('/review/images/filings?page=1&per_page=5')
       assert response.status_code == 200
   ```

2. **Review Interface Tests** (4 tests)

   ```python
   def test_review_page_renders(client, sample_filing, sample_image_candidates):
       """Review page renders with candidate data."""
       response = client.get(f'/review/images/{sample_filing}')
       assert response.status_code == 200
       assert b'image_url' in response.data or b'sec.gov' in response.data

   def test_review_page_shows_candidate(client, sample_filing, sample_image_candidates):
       """Review page shows specific candidate when requested."""
       candidate_id = sample_image_candidates[0]
       response = client.get(f'/review/images/{sample_filing}?image_candidate_id={candidate_id}')
       assert response.status_code == 200

   def test_review_page_invalid_filing(client):
       """Review page returns 404 for invalid filing."""
       response = client.get('/review/images/99999')
       assert response.status_code == 404

   def test_review_page_shows_tier(client, sample_filing, sample_image_candidates):
       """Review page displays detection tier information."""
       response = client.get(f'/review/images/{sample_filing}')
       assert b'tier' in response.data.lower()
   ```

3. **API Decision Tests** (5 tests)

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
       assert data['success'] is True
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
       data = response.get_json()
       assert 'next_candidate' in data

   def test_decision_validation_chart_type_required(client, sample_image_candidates):
       """API rejects relevant decision without chart_type."""
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': sample_image_candidates[0],
               'decision': 'relevant',
               # Missing chart_type
           },
           content_type='application/json'
       )
       assert response.status_code == 400

   def test_decision_validation_rejection_required(client, sample_image_candidates):
       """API rejects not_relevant decision without rejection_reason."""
       response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': sample_image_candidates[0],
               'decision': 'not_relevant',
               # Missing rejection_reason
           },
           content_type='application/json'
       )
       assert response.status_code == 400
   ```

4. **Skip and Undo Tests** (3 tests)

   ```python
   def test_skip_candidate(client, sample_image_candidates):
       """API skips candidate and returns next."""
       candidate_id = sample_image_candidates[0]
       response = client.post(f'/api/image-candidates/{candidate_id}/skip')
       assert response.status_code == 200
       data = response.get_json()
       assert data['success'] is True

   def test_undo_decision(client, sample_image_candidates):
       """API deletes decision and resets candidate status."""
       # First create a decision
       candidate_id = sample_image_candidates[0]
       create_response = client.post('/api/image-decisions',
           json={
               'image_candidate_id': candidate_id,
               'decision': 'relevant',
               'chart_type': 'cohort_table',
           },
           content_type='application/json'
       )
       decision_id = create_response.get_json()['decision_id']

       # Then delete it
       response = client.delete(f'/api/image-decisions/{decision_id}')
       assert response.status_code == 200
       assert response.get_json()['success'] is True

   def test_undo_invalid_decision(client):
       """API returns 404 for invalid decision ID."""
       response = client.delete('/api/image-decisions/99999')
       assert response.status_code == 404
   ```

5. **End-to-End Workflow Test** (1 test)

   ```python
   def test_full_review_workflow(client, db, sample_filing, sample_image_candidates):
       """Complete workflow: list → review → decide → navigate."""
       # 1. View filing list
       list_response = client.get('/review/images/filings')
       assert list_response.status_code == 200

       # 2. Enter review for filing
       review_response = client.get(f'/review/images/{sample_filing}')
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
       next_url = decision_response.get_json()['next_candidate']['url']

       # 4. Follow to next candidate
       next_response = client.get(next_url)
       assert next_response.status_code == 200

       # 5. Verify database state
       # (Check candidate status updated to 'reviewed')
   ```

### Pattern Learning Verification (1 test)

```python
def test_tier_distribution_captured(client, db, sample_filing, sample_image_candidates):
    """Verify detection_tier is captured for pattern learning."""
    # Make decisions on candidates from different tiers
    # Query database to verify tier info preserved with decisions
    pass
```

## Test Requirements

### Coverage Target: **≥ 85%** for integration tests

### Test Count: **15+ tests**

## Acceptance Criteria

- [ ] Test file created at correct location
- [ ] Fixtures create realistic test data
- [ ] **15+ integration tests** pass
- [ ] Tests cover all routes (filing list, review, next)
- [ ] Tests cover all API endpoints (create, skip, delete)
- [ ] Tests verify validation errors
- [ ] Tests verify navigation flow
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
- **Dependencies**: All IMG-1-* tasks
- **Related**: Pattern learning queries in plan document

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6
