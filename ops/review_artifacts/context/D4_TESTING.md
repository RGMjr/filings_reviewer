# D4: Testing Review Context

## Dimension Focus
Coverage gaps, edge cases, integration tests, gold standard effectiveness, mock vs real data balance.

## Test Structure

```
tests/
├── unit/                    # Fast, isolated tests
│   ├── extraction/          # Extraction pipeline tests
│   ├── extraction_v2/       # V2 pipeline tests (sparse)
│   ├── review/              # Review system (most comprehensive)
│   ├── web/                 # Flask routes
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

## Coverage Statistics

| Module | Coverage | Notes |
|--------|----------|-------|
| src/review/ | 98% | Most comprehensive |
| src/extraction/metric_classifier.py | 98% | Well tested |
| src/extraction/segment_enricher.py | 98% | Well tested |
| src/extraction/quality_scorer.py | 100% | Fully covered |
| src/extraction/value_extractor.py | 66% | **Gap** |
| src/extraction_v2/ | 0% | **Critical gap** |
| src/web/routes/ | 94-97% | Good coverage |

## Primary Files to Review

### Gold Standard Infrastructure
- `src/gold_standard/baseline.py` (313 LOC) - Baseline metrics management
- `src/gold_standard/fresh_extractor.py` (434 LOC) - Re-extraction without DB
- `scripts/validate_against_gold_standard.py` (1,175 LOC) - Validation CLI

### Test Configuration
- `pyproject.toml` - pytest config, coverage settings
- `tests/conftest.py` - Shared fixtures

## Review Questions

1. **Critical Coverage Gaps**: What critical code paths lack test coverage? Focus on extraction_v2 (0%) and value_extractor (66%).

2. **Edge Case Coverage**: Are edge cases tested? Encoding issues, malformed HTML, empty segments, etc.

3. **Integration Test Sufficiency**: Is integration test coverage sufficient for the database layer and pipeline?

4. **Gold Standard Representativeness**: Is the gold standard dataset (12 companies) representative? What's missing?

5. **Mock vs Real Balance**: Is there over-reliance on mocks? Where would real data tests add value?

6. **Regression Triggers**: Are regression tests triggered appropriately when extraction/keyword code changes?

## Known Testing Gaps

1. **extraction_v2/**: 0% coverage - new pipeline untested
2. **value_extractor.py**: 66% coverage - core extraction undertested
3. **Gold standard size**: Only 12 companies - limited diversity
4. **No adversarial tests**: Missing tests for malicious/malformed input
5. **Performance benchmarks**: Limited performance regression testing

## Gold Standard Details

- Location: `data/gold_standard/golden_set_251218.csv`
- Companies: 12 (Slack, Samsara, Farfetch, etc.)
- Tolerance: 1% regression tolerance
- Metrics tracked: Precision, Recall, F1

## Output Location
Write findings to: `ops/review_artifacts/claude/D4_findings.json`
