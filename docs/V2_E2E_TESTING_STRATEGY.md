# V2 E2E Testing Strategy

## Overview

This document outlines the end-to-end testing strategy for merging the V2-rewrite branch to main. The goal is to ensure the V2 extraction pipeline works correctly across all layers: extraction, persistence, API, and web UI.

## Current State Assessment

### What Already Exists

| Layer | Tests | Location | Status |
|-------|-------|----------|--------|
| Pipeline E2E | Slack/Samsara full extraction | `tests/integration/extraction_v2/test_e2e_pipeline.py` | Mature |
| Provenance | Every fact has source_locator + evidence_pack | `TestE2EProvenance` | Mature |
| Table Reconstruction | header_path/stub_path binding | `TestE2ETableReconstruction` | Mature |
| Persistence | Roundtrip extraction → DB → retrieval | `TestE2EPersistence` | Mature |
| Idempotency | Re-running produces same facts | `TestE2EIdempotency` | Mature |
| Performance | 30s completion gate | `TestE2EPerformance` | Mature |
| V1/V2 Comparison | Side-by-side validation | `test_v1_v2_comparison.py` | Mature |
| Gold Standard | Baseline regression | `pytest -m gold_standard` | Mature |

### Gaps to Fill Before Merge

| Gap | Risk Level | Description |
|-----|------------|-------------|
| Web UI with V2 data | ~~**High**~~ **COMPLETE** | `review_v2.py`, `api_v2.py`, `v2_filing_list.html`, `v2_review.html`, `v2_stats.html` — all implemented (WP-21, 2026-02-28) |
| API endpoints for V2 | ~~**High**~~ **COMPLETE** | `POST /api/v2/decisions`, `DELETE /api/v2/decisions/<id>` implemented in `api_v2.py` |
| Migration 12 | ~~**High**~~ **COMPLETE** | `sql/12_drop_v1_fk_constraints.sql` created (2026-02-28) |
| WP-23: Batch extraction | **Medium** | Run batch extraction on remaining 8 filings — scripts ready, runtime execution pending |
| Error recovery | **Medium** | Pipeline failures, partial extractions |
| Browser E2E | **Low** | Playwright tests (skeletons exist) |

---

## Recommended E2E Test Categories

### 1. Pipeline Extraction E2E (Existing - Enhance)

**Purpose:** Validate the full 11-stage pipeline produces correct facts from HTML.

**Current Coverage:**
- `TestE2ESlackFiling` - Slack S-1 extraction
- `TestE2ESamsaraFiling` - Samsara S-1 extraction

**Enhancements Needed:**

```python
# tests/integration/extraction_v2/test_e2e_pipeline.py

class TestE2EEdgeCases:
    """Edge cases for pipeline robustness."""

    def test_filing_with_no_metrics(self, pipeline, empty_filing_html):
        """Pipeline handles filings with no extractable metrics gracefully."""
        result = pipeline.process(html_path=empty_filing_html, filing_id=1)
        assert result.success is True
        assert result.fact_count == 0
        assert result.error_message is None

    def test_filing_with_malformed_tables(self, pipeline, malformed_table_html):
        """Pipeline recovers from malformed table structures."""
        result = pipeline.process(html_path=malformed_table_html, filing_id=2)
        assert result.success is True
        # Some facts may still be extracted from text

    def test_filing_with_only_images(self, pipeline, image_heavy_filing):
        """Pipeline handles image-heavy filings (charts, no text metrics)."""
        result = pipeline.process(html_path=image_heavy_filing, filing_id=3)
        # Should attempt OCR extraction
        assert result.images  # Images were processed

    def test_extremely_large_filing(self, pipeline, large_filing_html):
        """Pipeline completes within timeout for large filings."""
        result = pipeline.process(html_path=large_filing_html, filing_id=4)
        assert result.success is True
        assert result.total_duration_ms < 60_000  # 60s max


class TestE2EConfidenceThresholds:
    """Validate confidence scoring and review routing."""

    def test_high_confidence_auto_accept(self, pipeline, clear_metric_filing):
        """Facts with confidence >= 0.90 are auto-accepted."""
        result = pipeline.process(html_path=clear_metric_filing, filing_id=5)
        high_conf_facts = [f for f in result.facts if f.confidence >= 0.90]
        for fact in high_conf_facts:
            assert fact.review_status == ReviewStatus.AUTO_ACCEPTED

    def test_low_confidence_flagged(self, pipeline, ambiguous_metric_filing):
        """Facts with confidence < 0.15 are flagged for review."""
        result = pipeline.process(html_path=ambiguous_metric_filing, filing_id=6)
        low_conf_facts = [f for f in result.facts if f.confidence < 0.15]
        for fact in low_conf_facts:
            assert fact.review_status == ReviewStatus.PENDING_REVIEW
```

### 2. Database Persistence E2E (Existing - Enhance)

**Purpose:** Validate facts persist correctly and can be retrieved.

**Current Coverage:**
- `TestE2EPersistence` - Basic roundtrip

**Enhancements Needed:**

```python
# tests/integration/extraction_v2/test_persistence_e2e.py

class TestV2PersistenceE2E:
    """Full persistence layer validation."""

    def test_all_v2_tables_populated(self, pipeline, clean_db, sample_filing):
        """All V2 tables receive data after extraction."""
        result = pipeline.process(html_path=sample_filing, filing_id=1)

        with clean_db.get_connection() as conn:
            # Check all V2 tables have data
            tables = [
                "v2_documents",
                "v2_segments",
                "v2_tables",
                "v2_table_cells",
                "v2_image_assets",
                "v2_metric_facts",
            ]
            for table in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                # v2_image_assets may be 0 if no images
                if table != "v2_image_assets":
                    assert count > 0, f"{table} should have data"

    def test_fact_evidence_pack_persisted(self, pipeline, clean_db, sample_filing):
        """EvidencePack data is fully persisted and retrievable."""
        result = pipeline.process(html_path=sample_filing, filing_id=1)

        # Retrieve facts from DB
        facts = clean_db.get_v2_facts_for_filing(filing_id=1)

        for fact in facts:
            assert fact.evidence_pack is not None
            assert fact.evidence_pack.snippet_html is not None
            assert fact.source_locator is not None
            assert fact.source_locator.xpath is not None

    def test_concurrent_extraction_safe(self, pipeline, clean_db, sample_filings):
        """Multiple filings can be extracted concurrently."""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(pipeline.process, html_path=f, filing_id=i)
                for i, f in enumerate(sample_filings)
            ]
            results = [f.result() for f in futures]

        assert all(r.success for r in results)
```

### 3. V1/V2 Comparison E2E (Existing - Formalize)

**Purpose:** Ensure V2 extracts at least as well as V1 on known filings.

```python
# tests/integration/extraction_v2/test_v1_v2_comparison_e2e.py

class TestV1V2ComparisonE2E:
    """Formal V1 vs V2 comparison for merge readiness."""

    @pytest.mark.parametrize("fixture", ["slack", "samsara", "shopify", "datadog"])
    def test_v2_extracts_all_v1_metrics(self, fixture, gold_standard_dir):
        """V2 extracts all metrics that V1 found."""
        v1_facts = run_v1_extraction(gold_standard_dir / f"{fixture}.html")
        v2_facts = run_v2_extraction(gold_standard_dir / f"{fixture}.html")

        v1_metric_ids = {f.canonical_metric_id for f in v1_facts}
        v2_metric_ids = {f.canonical_metric_id for f in v2_facts}

        missing = v1_metric_ids - v2_metric_ids
        assert not missing, f"V2 missing metrics found by V1: {missing}"

    @pytest.mark.parametrize("fixture", ["slack", "samsara", "shopify", "datadog"])
    def test_v2_values_match_v1(self, fixture, gold_standard_dir):
        """V2 values are within 2% tolerance of V1."""
        v1_facts = run_v1_extraction(gold_standard_dir / f"{fixture}.html")
        v2_facts = run_v2_extraction(gold_standard_dir / f"{fixture}.html")

        for v1_fact in v1_facts:
            v2_match = find_matching_fact(v2_facts, v1_fact)
            if v2_match:
                assert_values_within_tolerance(
                    v1_fact.value,
                    v2_match.value,
                    tolerance=0.02
                )

    def test_v2_has_better_provenance(self, gold_standard_dir):
        """V2 facts have richer provenance than V1."""
        v1_facts = run_v1_extraction(gold_standard_dir / "slack.html")
        v2_facts = run_v2_extraction(gold_standard_dir / "slack.html")

        # V2 should have XPath locators
        for fact in v2_facts:
            assert fact.source_locator.xpath is not None
            assert fact.evidence_pack.snippet_html is not None
```

### 4. API Endpoint E2E (New)

**Purpose:** Validate V2 data is accessible via API.

```python
# tests/integration/web/test_api_v2_e2e.py

pytestmark = pytest.mark.integration

class TestV2APIE2E:
    """E2E tests for V2 API endpoints."""

    def test_get_v2_facts_for_filing(self, client, populated_v2_filing):
        """GET /api/v2/filings/{id}/facts returns V2 facts."""
        response = client.get(f"/api/v2/filings/{populated_v2_filing}/facts")
        assert response.status_code == 200

        data = response.json
        assert "facts" in data
        assert len(data["facts"]) > 0

        # Verify V2-specific fields
        fact = data["facts"][0]
        assert "evidence_pack" in fact
        assert "source_locator" in fact
        assert "confidence" in fact

    def test_get_v2_fact_detail(self, client, populated_v2_filing):
        """GET /api/v2/facts/{id} returns full fact with evidence."""
        # First get facts list
        facts_response = client.get(f"/api/v2/filings/{populated_v2_filing}/facts")
        fact_id = facts_response.json["facts"][0]["id"]

        # Get detail
        response = client.get(f"/api/v2/facts/{fact_id}")
        assert response.status_code == 200

        data = response.json
        assert data["evidence_pack"]["snippet_html"] is not None
        assert data["source_locator"]["xpath"] is not None

    def test_review_v2_fact(self, client, authenticated_user, v2_fact_pending_review):
        """POST /api/v2/facts/{id}/review accepts/rejects fact."""
        response = client.post(
            f"/api/v2/facts/{v2_fact_pending_review}/review",
            json={"decision": "accept", "notes": "Looks correct"},
            headers={"Authorization": f"Bearer {authenticated_user.token}"}
        )
        assert response.status_code == 200

        # Verify status updated
        fact = client.get(f"/api/v2/facts/{v2_fact_pending_review}").json
        assert fact["review_status"] == "accepted"
```

### 5. Web UI E2E (New - Browser Tests)

**Purpose:** Validate V2 facts display correctly in review UI.

```python
# tests/e2e/test_v2_review_ui.py

"""
V2 Review UI E2E Tests

Execute via Playwright MCP tools. Requires Flask dev server on localhost:5003.

Setup:
    cd /home/user/filings_reviewer
    flask run --port 5003
"""

SELECTORS = {
    "filing_row": "tr.filing-row",
    "fact_row": "tr.fact-row",
    "fact_confidence": ".fact-confidence",
    "fact_evidence": ".fact-evidence",
    "fact_xpath": ".fact-xpath",
    "accept_button": ".btn-accept",
    "reject_button": ".btn-reject",
    "review_status_badge": ".review-status",
}


def test_v2_filing_shows_facts():
    """
    Test: V2 filing page displays extracted facts with confidence scores.

    Steps (execute via Playwright MCP):
    1. browser_navigate to http://localhost:5003/filings
    2. browser_click on a filing with V2 extraction
    3. browser_snapshot to see fact list
    4. Verify: fact rows show confidence percentages
    5. Verify: fact rows show review status badges
    """
    pass


def test_v2_fact_evidence_panel():
    """
    Test: Clicking a V2 fact shows evidence panel with HTML snippet.

    Steps (execute via Playwright MCP):
    1. Navigate to a V2 filing's fact list
    2. browser_click on a fact row
    3. browser_snapshot to see evidence panel
    4. Verify: Evidence panel shows snippet_html content
    5. Verify: Evidence panel shows XPath locator
    6. Verify: Evidence panel shows header_path/stub_path if from table
    """
    pass


def test_v2_fact_review_workflow():
    """
    Test: User can accept/reject V2 facts via review UI.

    Steps (execute via Playwright MCP):
    1. Navigate to a V2 fact pending review
    2. browser_click accept button
    3. browser_snapshot to verify success toast
    4. Verify: Fact status badge updates to "Accepted"
    5. Repeat with reject button on another fact
    """
    pass


def test_v2_bulk_review():
    """
    Test: User can bulk accept/reject multiple V2 facts.

    Steps (execute via Playwright MCP):
    1. Navigate to V2 filing fact list
    2. browser_click checkbox on multiple facts
    3. browser_click bulk accept button
    4. Verify: All selected facts show "Accepted" status
    """
    pass
```

### 6. Migration Path E2E (New)

**Purpose:** Validate V1 → V2 transition scenarios.

```python
# tests/integration/extraction_v2/test_migration_e2e.py

pytestmark = pytest.mark.integration

class TestV1ToV2MigrationE2E:
    """E2E tests for V1 to V2 migration scenarios."""

    def test_filing_with_v1_data_can_run_v2(self, clean_db, v1_extracted_filing):
        """Filing previously extracted with V1 can be re-extracted with V2."""
        # Verify V1 data exists
        v1_values = clean_db.get_metric_values(filing_id=v1_extracted_filing)
        assert len(v1_values) > 0

        # Run V2 extraction
        pipeline = V2Pipeline()
        result = pipeline.process(
            html_path=get_filing_html(v1_extracted_filing),
            filing_id=v1_extracted_filing
        )

        assert result.success is True

        # V2 data now exists alongside V1
        v2_facts = clean_db.get_v2_facts_for_filing(filing_id=v1_extracted_filing)
        assert len(v2_facts) > 0

    def test_v2_reextraction_is_idempotent(self, clean_db, v2_extracted_filing):
        """Running V2 extraction twice produces same facts (upsert)."""
        # First extraction
        pipeline = V2Pipeline()
        result1 = pipeline.process(
            html_path=get_filing_html(v2_extracted_filing),
            filing_id=v2_extracted_filing
        )
        facts1 = clean_db.get_v2_facts_for_filing(filing_id=v2_extracted_filing)

        # Second extraction
        result2 = pipeline.process(
            html_path=get_filing_html(v2_extracted_filing),
            filing_id=v2_extracted_filing
        )
        facts2 = clean_db.get_v2_facts_for_filing(filing_id=v2_extracted_filing)

        # Same number of facts (upserted, not duplicated)
        assert len(facts1) == len(facts2)

        # Same values
        for f1, f2 in zip(sorted(facts1), sorted(facts2)):
            assert f1.canonical_metric_id == f2.canonical_metric_id
            assert f1.value == f2.value
```

---

## Implementation Priority

### Phase 1: Pre-Merge Blockers (Must Have)

| Test | Effort | Risk Mitigated |
|------|--------|----------------|
| V1/V2 comparison on all gold standard filings | Low | Regression in extraction quality |
| Persistence roundtrip for all V2 tables | Low | Data loss after extraction |
| Idempotency verification | Low | Duplicate data on re-runs |

### Phase 2: High Value (Should Have)

| Test | Effort | Risk Mitigated |
|------|--------|----------------|
| API endpoint tests for V2 facts | Medium | API contract breakage |
| Edge case filings (empty, malformed, large) | Medium | Runtime failures in production |
| Concurrent extraction safety | Medium | Race conditions |

### Phase 3: Polish (Nice to Have)

| Test | Effort | Risk Mitigated |
|------|--------|----------------|
| Browser E2E with Playwright | High | UI rendering issues |
| Performance regression V1 vs V2 | Medium | Slowdown after merge |
| Migration path tests | Medium | Data coexistence issues |

---

## Test Data Strategy

### Gold Standard Filings (Existing)

| Filing | Use Case | Location |
|--------|----------|----------|
| Slack S-1 | ARR, customer count, NRR | `fixtures/gold_standard/slack_s1.html` |
| Samsara S-1 | Multi-metric, tables | `fixtures/gold_standard/samsara_s1.html` |
| Shopify S-1 | GMV, merchants | `fixtures/gold_standard/shopify_s1_2015.html` |
| Datadog F-1 | International filing | `fixtures/gold_standard/datadog_f1_2019.html` |

### Synthetic Fixtures (To Create)

| Fixture | Purpose | Contents |
|---------|---------|----------|
| `empty_filing.html` | No extractable metrics | Boilerplate SEC structure, no numbers |
| `malformed_tables.html` | Table recovery | Broken colspan/rowspan, nested tables |
| `image_heavy.html` | OCR path | Metrics only in chart images |
| `large_filing.html` | Performance | 10MB+ HTML, 500+ segments |
| `ambiguous_metrics.html` | Confidence scoring | Multiple candidates, unclear context |

---

## Running E2E Tests

```bash
# Run all V2 E2E tests
pytest tests/integration/extraction_v2/test_e2e_pipeline.py -v

# Run V1/V2 comparison
pytest tests/integration/extraction_v2/test_v1_v2_comparison.py -v

# Run gold standard validation
pytest -m gold_standard --gold-standard-mode=fresh -v

# Run with database (requires TEST_DATABASE_URL)
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test \
    pytest tests/integration/ -v

# Run browser E2E (requires dev server)
flask run --port 5003 &
# Then execute test functions via Playwright MCP
```

---

## Success Criteria for Merge

Before merging V2-rewrite to main, all of the following must pass:

1. **Gold Standard**: `pytest -m gold_standard --gold-standard-mode=fresh` passes
2. **V1/V2 Comparison**: V2 extracts >= 95% of metrics V1 found
3. **V2 Values**: Within 2% tolerance of V1 values
4. **Persistence**: All V2 tables populated, evidence_pack retrievable
5. **Idempotency**: Re-extraction produces same fact count
6. **Performance**: Extraction completes within 30s for gold standard filings
7. **Coverage**: Overall test coverage remains >= 75%

---

## Appendix: Existing Test Infrastructure

### Composable Fixtures

```python
# Available in tests/integration/conftest.py
create_test_company(db)                    # Returns company_id
create_test_company_and_filing(db)         # Returns (company_id, filing_id)
create_test_candidate(db, filing_id=None)  # Auto-creates dependencies
```

### Database Cleanup

```python
@pytest.fixture
def clean_db(test_db_adapter):
    """Truncates all tables before/after each test."""
    # Uses SET CONSTRAINTS DEFERRED for FK-safe truncation
```

### Markers

```python
@pytest.mark.integration      # Requires TEST_DATABASE_URL
@pytest.mark.gold_standard    # Baseline regression tests
@pytest.mark.slow             # Long-running tests
@pytest.mark.benchmark        # Performance tests
```
