# GPT-4 Code Review: D4 Testing

**Copy this entire prompt and paste into GPT-4**

---

You are a senior QA engineer reviewing the testing strategy of a Python SEC filing extraction system.

## Test Statistics

| Metric | Value |
|--------|-------|
| Total Tests | 3,467 |
| Passed | 3,436 (99.1%) |
| **Failed** | **19** |
| Skipped | 12 |
| Coverage | 81.57% |
| Execution Time | 100s |

## Critical Issue: 19 Failing Tests

**All in:** `tests/unit/web/test_api_images_routes.py`

```
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_invalid_chart_type
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_missing_fields
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_success
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_invalid_segment
FAILED test_api_images_routes.py::TestCreateImageDecision::test_create_decision_duplicate
FAILED test_api_images_routes.py::TestSkipImageCandidate::test_skip_candidate
FAILED test_api_images_routes.py::TestValidChartTypes::test_* (7 tests)
FAILED test_api_images_routes.py::TestValidRejectionReasons::test_* (6 tests)
```

**All returning 409 CONFLICT instead of expected status codes.**

## Coverage Gaps

| Module | Coverage | Gap | Risk |
|--------|----------|-----|------|
| extraction_v2/ | 0% | 100% | **CRITICAL** - New pipeline untested |
| value_extractor.py | 66% | 34% | HIGH - Core extraction |
| html_segmenter.py | ~80% | 20% | MEDIUM - Complex parsing |

### Uncovered Lines (2,118 total)

Key uncovered areas:
- Error handling paths
- Edge cases in table parsing
- Charset encoding fallbacks
- LLM retry/timeout logic

## Test Structure

```
tests/
├── unit/                    # Fast, isolated (2,800+ tests)
│   ├── extraction/          # Pipeline tests
│   ├── review/              # Review system (best coverage)
│   └── web/                 # Flask routes (19 FAILURES)
├── integration/             # Requires DB (500+ tests)
│   └── test_gold_standard_regression.py
├── fixtures/
│   ├── encoding/            # UTF-8, Latin-1, etc.
│   └── tables/              # HTML table samples
```

## Gold Standard Validation

- **Dataset**: 12 companies only
- **Tolerance**: 1% regression
- **Metrics**: Precision, Recall, F1

```python
# scripts/validate_against_gold_standard.py
# Two-pass optimal matching algorithm
# Score: metric_id (2pts) + value (3pts) + text (1pt)
```

**Concern**: 12 companies may not be representative of 7,304 filing corpus.

## Missing Test Categories

1. **Concurrent DB access** - No stress tests
2. **Large file handling** - No memory tests for 10MB+ filings
3. **Adversarial input** - No malformed HTML tests
4. **Performance regression** - Not in CI
5. **End-to-end** - No full filing workflow tests

## Review Questions

1. **19 Failing Tests**: What's causing the 409 CONFLICT responses?
2. **extraction_v2 Coverage**: Why is new pipeline at 0%?
3. **Gold Standard Size**: Is 12 companies enough? What's missing?
4. **Edge Cases**: Are encoding/malformed HTML cases covered?
5. **Mock Balance**: Too much mocking vs real data?
6. **CI Integration**: Are gold standard tests in CI?

## Output Format

```json
{
  "dimension": "D4_TESTING",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D4-001",
      "severity": "Critical|High|Medium|Low",
      "category": "testing",
      "title": "Short title",
      "description": "Detailed description",
      "file": "tests/path/to/test.py",
      "missing_coverage": "What's not tested",
      "recommendation": "What tests to add",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall testing assessment"
}
```

Provide 8-12 findings focusing on test coverage and quality.
