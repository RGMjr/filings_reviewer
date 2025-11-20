# Development Plan - SEC Filings Reviewer
**Last Updated:** 2025-11-19
**Current Phase:** Phase 2a - Foundation Hardening

---

## Executive Summary

This document tracks the development roadmap for the SEC Filings Reviewer project. The project is currently transitioning from Phase 1 (UniverseBuilder - complete) to Phase 2 (Extraction Pipeline - 40% complete).

**Current Status:**
- ✅ Phase 1: UniverseBuilder (6,304 filings identified) - PRODUCTION READY
- 🟡 Phase 2: Extraction pipeline - 70% designed, 40% implemented
- 📊 Overall Test Coverage: 76% (target: 75% minimum)

---

## Immediate Priorities (Next 7 Days)

### ✅ **COMPLETED: Security & .env Template**
**Status:** DONE (2025-11-19)
- [x] Created `.env.template` with placeholder values
- [x] Verified `.env` is in `.gitignore`
- [x] Confirmed `.env` never committed to git history
- [x] Repository is private (no public exposure)
- [x] **Decision:** Skip API key rotation (pragmatic approach - no actual exposure)

### ✅ **COMPLETED: value_extractor.py Testing**
**Status:** DONE (2025-11-19)
- [x] Added 46 comprehensive tests (2 → 48 tests)
- [x] Coverage improved from 5% → 97%
- [x] All edge cases covered:
  - Number parsing (commas, currency, millions/billions, decimals, negatives, percentages)
  - Period extraction (Q1 2024, FY 2023, standalone years)
  - Cohort label parsing (acquisition, tenure cohorts)
  - Unit inference (USD, percent, count)
  - Table extraction (HTML tables, malformed rows, non-numeric cells)
  - Text extraction and routing

**Files Modified:**
- `tests/unit/extraction/test_value_extractor.py` (+700 lines)

---

## Current Sprint: Extraction Module Testing (Days 1-7)

### 🔄 **IN PROGRESS: quality_scorer.py Testing**
**Status:** NOT STARTED
**Current Coverage:** 2% (1 test)
**Target Coverage:** 90%+ (15+ tests)
**Estimated Time:** 8-12 hours

**Scope:**
- [ ] Test quality score computation (0-3 scale)
- [ ] Test alignment assessment algorithm
- [ ] Test keyword overlap ratio calculation
- [ ] Test edge cases (missing definitions, conflicting data)
- [ ] Test aggregation logic (filing-level scores)
- [ ] Test QA status transitions
- [ ] Test alignment flag logic

**Key Functions to Test:**
- `compute_quality_score()`
- `assess_alignment()`
- `calculate_keyword_overlap()`
- `aggregate_filing_scores()`

**Definition of Done:**
- 15+ new tests added
- 90%+ coverage achieved
- All tests passing
- Edge cases documented

---

### ⏳ **PENDING: filing_fetcher.py Testing**
**Status:** NOT STARTED
**Current Coverage:** 0% (0 tests)
**Target Coverage:** 90%+ (25+ tests)
**Estimated Time:** 10-14 hours

**Scope:**
- [ ] Test download functionality with mock SEC client
- [ ] Test caching logic (local file storage)
- [ ] Test security checks (path traversal prevention)
- [ ] Test error handling (404s, timeouts, corrupt HTML)
- [ ] Test retry logic
- [ ] Test file validation
- [ ] Test storage organization (data/filings/{cik}/{accession}/)

**Key Functions to Test:**
- `fetch_filing()`
- `download_and_cache()`
- `validate_filing_path()`
- `handle_download_error()`
- `retry_with_backoff()`

**Definition of Done:**
- 25+ new tests added
- 90%+ coverage achieved
- All tests passing
- Security edge cases covered

---

### 📋 **Additional Week 1 Tasks**

#### Test Coverage Improvements
- [ ] Run full test suite to verify overall coverage stays >75%
- [ ] Generate coverage report: `pytest --cov=src --cov-report=html`
- [ ] Review `htmlcov/index.html` for any gaps

#### Code Quality
- [ ] Run black formatter: `black src/ tests/`
- [ ] Run ruff linter: `ruff check src/ tests/`
- [ ] Fix any linting issues

#### Documentation
- [ ] Update IMPLEMENTATION_SUMMARY.md with recent progress
- [ ] Document any new edge cases discovered during testing

---

## Next Sprint: FilingFetcher Integration (Days 8-21)

### 🎯 **Priority 1: Integrate FilingFetcher with UniverseBuilder**
**Estimated Time:** 2-3 days

**Tasks:**
- [ ] Add `processing_status` workflow to filings table:
  - `pending` → Initial state after universe build
  - `fetched` → HTML downloaded and cached
  - `processed` → Extraction pipeline completed
  - `failed` → Download or extraction failed
- [ ] Update UniverseBuilder to set initial status = 'pending'
- [ ] Create batch download runner script
- [ ] Add database queries to fetch pending filings
- [ ] Implement batch processing with progress tracking

**Definition of Done:**
- UniverseBuilder sets processing_status = 'pending'
- FilingFetcher updates status to 'fetched' after successful download
- Batch runner can process N filings in sequence
- Database tracks download metrics (bytes, time, errors)

---

### 🎯 **Priority 2: Test with Real SEC EDGAR**
**Estimated Time:** 1-2 days

**Tasks:**
- [ ] Download 10-20 real filings from test companies:
  - Shopify S-1 (2015)
  - Datadog F-1 (2019)
  - Zoom S-1 (2019)
- [ ] Verify storage organization: `data/filings/{cik}/{accession}/primary.htm`
- [ ] Test error handling with:
  - Invalid CIKs (404 errors)
  - Network timeouts
  - Rate limiting scenarios
- [ ] Validate downloaded HTML integrity
- [ ] Test retry logic with exponential backoff

**Definition of Done:**
- 10-20 real filings successfully downloaded
- File structure matches spec: `data/filings/{cik}/{accession}/`
- Error handling tested and working
- Download metrics logged

---

### 🎯 **Priority 3: Add Processing Monitoring**
**Estimated Time:** 1 day

**Tasks:**
- [ ] Log download metrics (bytes, time, errors)
- [ ] Track processing status in database
- [ ] Generate status reports:
  - Total filings: 6,304
  - Pending: X
  - Fetched: Y
  - Processed: Z
  - Failed: N
- [ ] Add command-line status checker

**Definition of Done:**
- Structured logging implemented
- Database tracks all status transitions
- Status report script works

---

## Sprint 3: LLM Integration (Days 22-42)

### 🎯 **Priority 1: OpenAI API Integration**
**Estimated Time:** 1 week

**Tasks:**
- [ ] Set up OpenAI client with error handling
- [ ] Implement prompt engineering for metric extraction:
  - Value extraction prompts
  - Definition extraction prompts
  - Calculation methodology prompts
- [ ] Add token counting and cost tracking
- [ ] Implement rate limiting (RPM, TPM)
- [ ] Add retry logic for API failures
- [ ] Create fallback rules when LLM fails

**OpenAI Configuration:**
- Model: GPT-4o (or GPT-4o-mini for cost savings)
- Max tokens per request: TBD based on testing
- Temperature: 0.1 (deterministic)
- Chunk size: 8,000 characters

**Cost Tracking:**
- [ ] Log tokens per filing
- [ ] Calculate cost per filing
- [ ] Track cumulative costs
- [ ] Alert if cost exceeds threshold

**Definition of Done:**
- OpenAI client integrated
- Prompts tested with 5 sample filings
- Cost tracking implemented
- Error handling tested

---

### 🎯 **Priority 2: Manual Validation**
**Estimated Time:** 1 week

**Tasks:**
- [ ] Process 5-10 real filings through extraction pipeline
- [ ] Manually review extracted metrics for accuracy
- [ ] Compare LLM outputs to human-extracted metrics
- [ ] Measure precision/recall:
  - True positives: Correctly extracted metrics
  - False positives: Incorrectly identified metrics
  - False negatives: Missed metrics
- [ ] Document extraction patterns and edge cases
- [ ] Tune prompts based on errors

**Test Filings for Validation:**
1. Shopify S-1 (2015) - Good cohort disclosure
2. Datadog F-1 (2019) - Dollar-based retention
3. Zoom S-1 (2019) - Customer metrics
4. Slack S-1 (2019) - Retention metrics
5. Snowflake S-1 (2020) - Net revenue retention

**Definition of Done:**
- 5-10 filings manually validated
- Extraction accuracy measured
- Prompt improvements documented
- Quality baseline established

---

## Sprint 4: Production Readiness (Days 43-56)

### 🎯 **End-to-End Testing**
**Tasks:**
- [ ] Process 100+ filings through full pipeline
- [ ] Validate database integrity
- [ ] Generate extraction quality report
- [ ] Fix bugs identified during testing

### 🎯 **Performance Optimization**
**Tasks:**
- [ ] Benchmark extraction speed (filings per hour)
- [ ] Optimize slow queries
- [ ] Implement caching where appropriate
- [ ] Profile memory usage

### 🎯 **Deployment Preparation**
**Tasks:**
- [ ] Docker containerization
- [ ] CI/CD pipeline setup (GitHub Actions)
- [ ] Database backup procedures
- [ ] Configuration management

---

## Long-Term Roadmap (3-12 Months)

### Phase 3: Analytics & Reporting (Months 3-4)
- [ ] Build analytics dashboard
- [ ] Metric incidence report by year/industry
- [ ] Comparison tool (issuer vs canonical definitions)
- [ ] Quality report (incidence by score level)
- [ ] Trend analysis (disclosure improving over time?)

### Phase 4: Manual Review Workflow (Months 4-5)
- [ ] UI/CLI for reviewing uncertain classifications
- [ ] Feedback mechanism for improving classifiers
- [ ] Audit trail of manual overrides
- [ ] Bulk upload of corrections

### Phase 5: Expansion (Months 6-12)
- [ ] Add 10-K/10-K/A support
- [ ] Industry-specific metrics (fintech, marketplace, e-commerce)
- [ ] CMASB standards alignment
- [ ] Regulatory integration (SEC comment letters)

---

## Testing Standards

### Coverage Requirements
- **Minimum:** 75% (enforced by pytest.ini)
- **Target:** 90%+ for new modules
- **Current:** 76% overall

### Test Organization
```
tests/
├── unit/                     # Fast, isolated tests
│   ├── universe/            # 35 tests, 98% coverage ✅
│   ├── extraction/          # 76 tests, 95% coverage ✅
│   └── infra/               # 10 tests
│
└── integration/             # Database-backed tests
    ├── universe/            # 2 tests ✅
    └── filing_pipeline/     # 1 test
```

### Test Quality Checklist
- [ ] Descriptive test names (`test_parse_number_with_commas`)
- [ ] Comprehensive edge cases
- [ ] Proper fixtures and mocks
- [ ] Database isolation for integration tests
- [ ] Clear assertions with helpful error messages

---

## Key Decisions & Rationale

### Security Decision (2025-11-19)
**Decision:** Skip API key rotation
**Rationale:**
- `.env` never committed to git (verified)
- Repository is private
- No actual exposure occurred
- Pragmatic approach: fix storage, move on to high-value work

**Action Taken:**
- Created `.env.template` for documentation
- Verified `.gitignore` properly excludes `.env`

### Testing Approach
**Decision:** Focus on extraction modules first
**Rationale:**
- UniverseBuilder already has 98% coverage
- Extraction modules are critical path for Phase 2
- Low current coverage (2-5%) represents high risk

---

## Progress Tracking

### Week 1 Progress (Nov 18-24, 2025)
- [x] **Day 1:** Security assessment + value_extractor.py testing (97% coverage) ✅
- [ ] **Day 2:** quality_scorer.py testing (target: 90% coverage)
- [ ] **Day 3:** quality_scorer.py testing (complete)
- [ ] **Day 4:** filing_fetcher.py testing (start)
- [ ] **Day 5:** filing_fetcher.py testing (continue)
- [ ] **Day 6:** filing_fetcher.py testing (complete)
- [ ] **Day 7:** Overall test suite validation + documentation

### Metrics to Track
- Total tests: 133 → Target: 200+
- Overall coverage: 76% → Target: 80%+
- Lines of code tested: TBD
- Bugs found and fixed: TBD

---

## Resources & References

### Documentation
- [01_ANALYTIC_REQUIREMENTS.md](docs/01_ANALYTIC_REQUIREMENTS.md) - Business requirements
- [04_EXTRACTION_ARCHITECTURE.md](docs/04_EXTRACTION_ARCHITECTURE.md) - Extraction pipeline design
- [06_QA_AND_QUALITY_MODEL.md](docs/06_QA_AND_QUALITY_MODEL.md) - Quality scoring framework
- [07_TEST_STRATEGY_AND_FIX_PROCESS.md](docs/07_TEST_STRATEGY_AND_FIX_PROCESS.md) - Testing approach

### Code Locations
- Extraction modules: `src/extraction/`
- Tests: `tests/unit/extraction/`
- Database schema: `sql/03_create_analysis_schema.sql`
- Metric taxonomy: `sql/04_seed_metrics_taxonomy.sql`

### Commands
```bash
# Run all tests with coverage
pytest --cov=src --cov-report=html

# Run specific module tests
pytest tests/unit/extraction/test_value_extractor.py -v

# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Generate coverage report
open htmlcov/index.html
```

---

## Notes & Observations

### 2025-11-19: value_extractor.py Testing Complete
- Added 46 tests in ~2 hours
- Improved coverage from 5% → 97%
- Identified edge cases in period extraction (leap years, invalid dates)
- Table extraction logic is robust
- Cohort label parsing handles multiple formats well

**Next Steps:**
- Apply same testing pattern to quality_scorer.py
- Consider generating tests using Python Testing MCP for remaining modules

---

## Contact & Support

**Project Owner:** RGM
**Repository:** https://github.com/RGMjr/filings_reviewer (private)
**CMASB Initiative:** Customer Metrics Accounting Standards Board

For questions or clarifications, refer to:
- [CLAUDE.md](CLAUDE.md) - Claude AI guidance
- [README.md](README.md) - Project overview and setup
- [AGENTS.md](AGENTS.md) - Repository guidelines
