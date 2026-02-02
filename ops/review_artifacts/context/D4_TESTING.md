# D4: Testing Review Context

## Dimension Focus
Coverage gaps, edge cases, integration tests, gold standard effectiveness, mock vs real data balance.

## Test Structure

```
tests/
├── unit/                    # Fast, isolated tests (3,436 passing, 19 failing)
│   ├── extraction/          # Extraction pipeline tests
│   ├── extraction_v2/       # V2 pipeline tests (SPARSE - 0% coverage)
│   ├── review/              # Review system (most comprehensive)
│   ├── web/                 # Flask routes (19 failures here)
│   ├── infra/               # Infrastructure
│   ├── llm/                 # LLM integration
│   └── gold_standard/       # Validation tests
├── integration/             # Requires TEST_DATABASE_URL
│   ├── extraction/
│   ├── web/
│   └── test_gold_standard_regression.py
├── e2e/                     # End-to-end browser tests
└── fixtures/                # Test data
    ├── encoding/            # UTF-8, ASCII, Latin-1 samples
    └── tables/              # HTML financial table fixtures
```

---

## Coverage Statistics

From ops/review_artifacts/static_analysis/coverage_summary.txt:

| Module | Coverage | Statements | Missing | Notes |
|--------|----------|------------|---------|-------|
| **Overall** | **81.57%** | 11,491 | 2,118 | Exceeds 75% target ✅ |
| src/review/ | 98% | ~1,200 | ~24 | Most comprehensive |
| src/extraction/metric_classifier.py | 98% | 215 | 4 | Well tested |
| src/extraction/segment_enricher.py | 98% | 312 | 6 | Well tested |
| src/extraction/quality_scorer.py | 100% | 87 | 0 | Fully covered ✅ |
| **src/extraction/value_extractor.py** | **66%** | 420 | 143 | **Critical gap** ❌ |
| **src/extraction_v2/** | **0%** | ~800 | ~800 | **Critical gap** ❌ |
| src/web/routes/ | 94-97% | ~450 | ~20 | Good coverage |
| src/infra/db.py | 78% | 1,124 | 247 | Room for improvement |

**Test Execution Results** (from SUMMARY.md):
- Tests run: 3,467
- Passed: 3,436 (99.1%)
- **Failed: 19 (0.9%)** ❌
- Skipped: 12
- Execution time: 100.05s (1:40)

---

## Critical Test Failures

### All 19 Failures in `tests/unit/web/test_api_images_routes.py`

| Test Category | Count | Likely Root Cause |
|---------------|-------|-------------------|
| `TestCreateImageDecision` | 5 | Image decision API schema changes |
| `TestSkipImageCandidate` | 1 | Candidate skip logic regression |
| `TestValidChartTypes` | 7 | Chart type validation enum changes |
| `TestValidRejectionReasons` | 6 | Rejection reason enum changes |

**Hypothesis**: Recent changes to `extraction_v2/models.py` or `review/models.py` broke the API contract for image/chart handling. Tests may need updating to reflect new enum values or validation rules.

**Impact**: Image/chart extraction quality may be compromised. Blocking issue for review.

**Recommendation**: Fix these 19 tests immediately before proceeding with deeper code review.

---

## Coverage Gaps Analysis

### P0 - Critical Gaps

#### 1. extraction_v2/ (0% coverage)
**Files**:
- `ingestion_stage.py` - V2 HTML parser using lxml
- `models.py` - V2 data models
- `stages/classification.py` - V2 metric classification
- 6 files total, ~800 statements uncovered

**Concerns**:
- Entire V2 pipeline untested
- No migration path from V1 without test safety net
- Unclear if V2 is production-ready or experimental
- Performance/quality claims unvalidated

**Recommendation**: Add V2 test suite before any production use. Minimum 75% coverage.

#### 2. value_extractor.py (66% coverage, 143 statements missing)
**Uncovered Areas** (requires investigation):
- Table row parsing edge cases
- LLM fallback logic
- Error handling paths
- Cohort label normalization
- Period end inference

**Impact**: Core extraction logic undertested. False positive/negative edge cases may slip through.

**Recommendation**: Prioritize covering `_parse_table_row` (CC=34) and LLM extraction paths.

---

### P1 - High Priority Gaps

#### 3. db.py (78% coverage, 247 statements missing)
**Uncovered Areas**:
- Connection pool error handling
- Transaction rollback scenarios
- Constraint violation handling
- Bulk insert conflict resolution edge cases

**Impact**: Database errors in production may have unexpected behavior.

#### 4. html_segmenter.py (84% coverage)
**Uncovered Areas**:
- Encoding fallback cascade (UTF-8 → Latin-1)
- Malformed HTML handling
- Fractional sequence index edge cases
- Heading cache invalidation (doesn't exist!)

**Impact**: Malformed filings may cause extraction failures.

---

## Edge Case Coverage

### Encoding Edge Cases

**Fixtures**: `tests/fixtures/encoding/`
- UTF-8 samples: ✅ Tested
- Latin-1 samples: ✅ Tested
- ASCII samples: ✅ Tested

**Missing**:
- Mixed encodings in single file
- Invalid UTF-8 sequences
- Encoding declaration vs actual encoding mismatch
- Confidence threshold boundary cases (exactly 0.80)

### Table Edge Cases

**Fixtures**: `tests/fixtures/tables/`
- Simple tables: ✅ Tested
- Nested tables: ⚠️ Limited
- Colspan/rowspan: ⚠️ Limited (V2 has implementation, 0% covered)
- Very wide tables (>20 columns): ❌ Missing
- Tables with images in cells: ❌ Missing
- Malformed tables (unclosed tags): ❌ Missing

### Number Parsing Edge Cases

**Tested**:
- Standard formats (1,234.56): ✅
- Percentages (12.5%): ✅
- Dollar amounts ($1.2M): ✅
- Ratios (3.5x): ✅

**Missing**:
- Ambiguous formats ("12%" vs "12 percentage points")
- Scientific notation (1.2e6)
- Negative numbers in tables
- Overflow/underflow (very large/small numbers)

---

## Gold Standard Infrastructure

### Files

- **src/gold_standard/baseline.py** (313 LOC) - Baseline metrics management
- **src/gold_standard/fresh_extractor.py** (434 LOC) - Re-extraction without DB
- **scripts/validate_against_gold_standard.py** (1,175 LOC) - Validation CLI

### Gold Standard Dataset

**Location**: `data/gold_standard/golden_set_251218.csv`

**Companies**: 12 total
- Slack Technologies
- Samsara
- Farfetch
- (9 others - see dataset)

**Metrics Tracked**:
- Precision: ~91%
- Recall: ~85%
- F1: ~88%
- Tolerance: 1% regression threshold

### Validation Workflow

```bash
# Quick validation
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Formal validation (pytest)
pytest -m gold_standard --gold-standard-mode=fresh -v

# Update baseline (after intentional changes)
python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
```

---

## Review Questions

### 1. Critical Coverage Gaps
**Question**: What critical code paths lack test coverage? Focus on extraction_v2 (0%) and value_extractor (66%).

**Immediate Priorities**:
1. **extraction_v2/** - Add basic smoke tests for V2 pipeline before any production use
2. **value_extractor.py** - Cover table parsing edge cases (34% uncovered)
3. **db.py** - Cover error handling paths (22% uncovered)

**Risk Assessment**:
- extraction_v2 at 0% is a blocker for migration
- value_extractor at 66% risks extraction quality regressions
- 19 failing tests in web routes must be fixed

### 2. Edge Case Coverage
**Question**: Are edge cases tested? Encoding issues, malformed HTML, empty segments, etc.

**Well-Covered**:
- Standard encodings (UTF-8, Latin-1, ASCII)
- Basic table structures
- Common number formats

**Gaps**:
- Malformed HTML (unclosed tags, invalid nesting)
- Mixed/mismatched encodings
- Very wide tables, colspan/rowspan
- Adversarial input (injection attempts, extremely long segments)
- Boundary conditions (exactly at MAX_SEGMENT_LENGTH)

**Recommendation**: Add adversarial test suite for robustness.

### 3. Integration Test Sufficiency
**Question**: Is integration test coverage sufficient for the database layer and pipeline?

**Current State**:
- Integration tests require `TEST_DATABASE_URL`
- Tests cover: extraction pipeline, web routes, gold standard regression
- Total integration tests: ~50 (estimated from structure)

**Gaps**:
- No end-to-end tests for full filing processing (fetch → extract → review)
- Limited testing of database connection pooling
- No tests for concurrent access patterns
- No performance benchmarks in CI

**Recommendation**: Add end-to-end smoke tests and performance regression suite.

### 4. Gold Standard Representativeness
**Question**: Is the gold standard dataset (12 companies) representative? What's missing?

**Current Dataset**: 12 companies (mostly SaaS)

**Diversity Gaps**:
- Industry diversity (SaaS-heavy, limited e-commerce, fintech, etc.)
- Filing complexity (length, table density, encoding issues)
- Metric diversity (some metrics may have 0-1 examples)
- Time period (all from similar IPO vintage?)

**Impact**:
- May miss edge cases in other industries
- Precision/recall may not generalize to full corpus
- New metrics lack validation data

**Recommendation**: Expand gold standard to 25-30 companies with diverse characteristics.

### 5. Mock vs Real Balance
**Question**: Is there over-reliance on mocks? Where would real data tests add value?

**Current Mock Usage**:
- LLM calls: Mocked in most tests (good - avoids cost/latency)
- Database: Mixed (mocked in unit, real in integration)
- HTTP requests (SEC API): Mocked (good - avoids rate limits)

**Over-Mocking Risks**:
- LLM response format changes not caught
- Database constraint violations not tested
- SEC API response variations missed

**Under-Tested with Real Data**:
- Full pipeline with actual SEC filings
- LLM extraction quality (only gold standard validates)
- Database performance under load

**Recommendation**: Add "smoke tests" with real LLM/DB on subset of data.

### 6. Regression Triggers
**Question**: Are regression tests triggered appropriately when extraction/keyword code changes?

**Current Triggers** (from CLAUDE.md):
- Gold standard tests: Manual trigger required
- pytest markers: `@pytest.mark.gold_standard`
- CI integration: Not clear if automated

**Gaps**:
- No automatic trigger when `metric_keywords.yaml` changes
- No automatic trigger when extraction modules change
- No visual diff for gold standard failures (just metrics)

**Recommendation**: Add pre-commit hook to run gold standard validation on keyword/extraction changes.

---

## Known Testing Gaps

1. **extraction_v2/**: 0% coverage - new pipeline completely untested
2. **value_extractor.py**: 66% coverage - core extraction logic undertested
3. **Gold standard size**: Only 12 companies - limited diversity
4. **No adversarial tests**: Missing tests for malicious/malformed input
5. **Performance benchmarks**: No regression testing for performance
6. **19 failing tests**: Image routes tests broken (needs immediate fix)

---

## Test Configuration

### pyproject.toml

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html",
]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests as integration tests (require database)",
    "gold_standard: marks tests for gold standard validation",
]
```

### tests/conftest.py

**Shared Fixtures**:
- `db` - Test database adapter
- `llm_client` - Mocked OpenAI client
- `sample_filing` - Sample filing HTML
- `sample_segments` - Pre-segmented test data

---

## Static Analysis Summary

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Overall Coverage | 81.57% | 75% | ✅ Exceeds |
| Passing Tests | 3,436 | 100% | ✅ Good |
| Failing Tests | 19 | 0 | ❌ Must fix |
| Skipped Tests | 12 | - | ⚠️ Review |
| Slowest Module | extraction_v2 | - | ❌ 0% coverage |
| Highest Coverage | quality_scorer.py | - | ✅ 100% |
| Lowest Coverage | value_extractor.py | - | ❌ 66% |

---

## Recommendations

### Immediate (P0)
1. Fix 19 failing tests in `test_api_images_routes.py`
2. Add smoke tests for extraction_v2 (at least 50% coverage)
3. Increase value_extractor.py coverage to 75%+

### Short-term (P1)
4. Add adversarial test suite (malformed HTML, encoding edge cases)
5. Expand gold standard to 25-30 companies
6. Add performance regression benchmarks

### Long-term (P2)
7. Add end-to-end tests with real SEC filings
8. Implement pre-commit hook for gold standard validation
9. Add integration tests for concurrent access patterns

---

## Output Location
Write findings to: `ops/review_artifacts/claude/D4_findings.json`
