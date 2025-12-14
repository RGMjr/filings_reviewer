# Test Coverage Analyzer Skill

**Version:** 1.0.0
**Created:** 2025-12-11
**Purpose:** Analyze test coverage gaps and generate test files following project patterns

---

## Skill Overview

This skill analyzes pytest coverage reports, identifies gaps, and generates production-ready test files following the established patterns in the SEC Filings Reviewer project. It produces:

- Coverage gap analysis with specific uncovered lines
- Test case suggestions for each gap
- Generated unit test files (mocking external dependencies)
- Generated integration test files (real database operations)
- Edge case recommendations based on module type
- Test plan with time estimates to reach target coverage

**When to use this skill:**
- After implementing new features (to reach coverage targets)
- When coverage drops below 75% threshold
- To identify quick wins for coverage improvement
- Before code reviews or PRs
- To generate missing tests systematically

**When NOT to use this skill:**
- For 100% coverage on simple getters/setters (not worth the effort)
- For external library code
- For deprecated code scheduled for removal
- When tests exist but coverage tool miscounts

---

## Input Parameters

When invoking this skill, provide:

```yaml
target_coverage: 75  # Minimum coverage percentage (default: 75 from pyproject.toml)
focus_modules:  # Optional: limit analysis to specific modules
  - "src/web"
  - "src/review"
exclude_patterns:  # Patterns to exclude from analysis
  - "__init__.py"
  - "*/migrations/*"
test_type: "unit" | "integration" | "both"  # Which tests to generate
generate_tests: true  # Whether to create test files
generate_report: true  # Whether to create coverage gap report
quick_wins_only: false  # Only show files with <5 missing statements (easy targets)
```

---

## Project Testing Standards

### Coverage Requirements

**From pyproject.toml:**
```toml
[tool.pytest.ini_options]
addopts = [
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html",
    "--cov-fail-under=75",  # Minimum 75% coverage
]

[tool.coverage.report]
fail_under = 75
show_missing = true  # Always show uncovered line numbers
```

**Module-Specific Targets:**
- **Critical modules** (db.py, validation.py): 90-100% coverage
- **Core logic** (extraction, review): 85-95% coverage
- **Infrastructure** (clients, helpers): 80-90% coverage
- **Web routes**: 90-95% coverage
- **Scripts**: 70-80% coverage (acceptable lower bar)

### Test Structure

**Directory Layout:**
```
tests/
├── unit/              # Fast tests, no external dependencies
│   ├── extraction/    # Mirrors src/extraction structure
│   ├── review/
│   ├── web/
│   └── infra/
├── integration/       # Slower tests, real database
│   ├── extraction/
│   ├── web/
│   └── conftest.py    # Shared integration fixtures
└── conftest.py        # Root conftest (if needed)
```

**Test File Naming:**
- `test_{module_name}.py` for unit tests
- `test_{module_name}_integration.py` for integration tests
- Special: `test_{module}_golden.py` for golden file comparisons

---

## Unit Test Patterns

### Basic Test Structure

```python
"""
Unit tests for {module_name}.

{Brief description of what module does and what tests cover.}
"""

import pytest
from unittest.mock import MagicMock, patch, Mock
from decimal import Decimal
from datetime import datetime

from src.{path}.{module_name} import ClassName, function_name


# =============================================================================
# Test {ClassName} or {function_group}
# =============================================================================


class Test{ClassName}:
    """Tests for {ClassName}."""

    def test_{method_name}_happy_path(self):
        """Test {method_name} with valid input."""
        # Arrange
        instance = ClassName(param1="value1")
        input_data = {"key": "value"}

        # Act
        result = instance.method_name(input_data)

        # Assert
        assert result == expected_value
        assert instance.state_changed_correctly

    def test_{method_name}_handles_none(self):
        """Test {method_name} handles None input."""
        instance = ClassName()

        result = instance.method_name(None)

        assert result is None  # or appropriate behavior

    def test_{method_name}_raises_on_invalid_type(self):
        """Test {method_name} raises TypeError for invalid input."""
        instance = ClassName()

        with pytest.raises(TypeError, match="Expected str"):
            instance.method_name(123)  # Wrong type

    @pytest.mark.parametrize(
        "input_value,expected",
        [
            ("case1", "result1"),
            ("case2", "result2"),
            ("edge_case", "edge_result"),
        ],
    )
    def test_{method_name}_parametrized(self, input_value, expected):
        """Test {method_name} with multiple input cases."""
        instance = ClassName()

        result = instance.method_name(input_value)

        assert result == expected
```

### Fixtures Pattern

```python
@pytest.fixture
def sample_instance():
    """Create a sample instance for testing."""
    return ClassName(
        param1="test_value",
        param2=100,
    )


@pytest.fixture
def sample_data():
    """Create sample data for tests."""
    return {
        "field1": "value1",
        "field2": 123,
        "nested": {"key": "val"},
    }


@pytest.fixture
def mock_database():
    """Mock database adapter."""
    mock_db = MagicMock()
    mock_db.query.return_value = [{"id": 1, "name": "Test"}]
    return mock_db
```

### Mocking External Dependencies

```python
def test_function_with_database_call():
    """Test function that uses database."""
    with patch("src.module.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db.query.return_value = [{"data": "value"}]
        mock_get_db.return_value = mock_db

        result = function_that_calls_db()

        assert result == expected
        mock_db.query.assert_called_once_with(expected_sql, expected_params)


def test_function_with_external_api():
    """Test function that calls external API."""
    with patch("src.module.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = {"api": "data"}
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = function_that_calls_api()

        assert result == expected
        mock_get.assert_called_once()
```

---

## Integration Test Patterns

### Basic Integration Structure

```python
"""
Integration tests for {module_name}.

Tests with real database operations to verify end-to-end behavior.
"""

import os
import pytest

from src.infra.db import DatabaseAdapter
from src.{path}.{module_name} import ClassName


@pytest.fixture(scope="module")
def db_url():
    """Get test database URL from environment."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="module")
def db_adapter(db_url):
    """Create database adapter for tests."""
    return DatabaseAdapter(db_url)


@pytest.fixture
def clean_db(db_adapter):
    """
    Provide clean database for each test.

    Truncates tables before and after test.
    """
    # Setup: clean tables
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
            cur.execute("TRUNCATE TABLE child_table CASCADE")
            cur.execute("TRUNCATE TABLE parent_table CASCADE")
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

    yield db_adapter

    # Teardown: clean tables
    with db_adapter.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
            cur.execute("TRUNCATE TABLE child_table CASCADE")
            cur.execute("TRUNCATE TABLE parent_table CASCADE")
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Test{ClassName}Integration:
    """Integration tests for {ClassName}."""

    def test_end_to_end_flow(self, clean_db):
        """Test complete workflow with database."""
        # Create test data
        company_id = clean_db.upsert_company(
            cik="0001234567",
            company_name="Test Co"
        )

        # Execute operation
        instance = ClassName(clean_db)
        result = instance.process(company_id)

        # Verify results persisted
        rows = clean_db.query(
            "SELECT * FROM results WHERE company_id = %(id)s",
            {"id": company_id}
        )
        assert len(rows) == expected_count
        assert rows[0]["status"] == "completed"

    def test_transaction_atomicity(self, clean_db):
        """Test that operations are atomic (all-or-nothing)."""
        instance = ClassName(clean_db)

        # Attempt operation that should fail
        with pytest.raises(ValueError):
            instance.process_with_invalid_data()

        # Verify no partial data persisted
        rows = clean_db.query("SELECT * FROM results")
        assert len(rows) == 0  # Transaction rolled back
```

### Test Data Helpers (from conftest.py)

```python
def create_test_company(
    db: DatabaseAdapter,
    cik: str = "0001234567",
    company_name: str = "Test Company Inc",
) -> int:
    """Create test company and return company_id."""
    return db.upsert_company(
        cik=cik,
        company_name=company_name
    )


def create_test_filing(
    db: DatabaseAdapter,
    company_id: int,
    accession_number: str = "0001234567-24-000001",
) -> int:
    """Create test filing and return filing_id."""
    return db.upsert_filing(
        company_id=company_id,
        cik="0001234567",
        accession_number=accession_number,
        form_type="S-1",
        filing_date="2024-01-15",
        sec_html_url=f"https://www.sec.gov/test/{accession_number}",
    )
```

---

## Edge Case Library

### By Module Type

**For Route Handlers (Flask):**
- Invalid URL parameters (negative IDs, non-integers)
- Missing required query parameters
- Page overflow (page > total_pages)
- Database errors during request
- Empty result sets
- Concurrent requests (race conditions)
- Invalid JSON in POST body
- CSRF/XSS attack vectors (if applicable)

**For Database Methods:**
- Empty result sets (no rows)
- Null/None values in optional fields
- Duplicate key violations
- Foreign key violations
- NOT NULL violations
- CHECK constraint violations
- Transaction isolation issues
- Concurrent updates (optimistic locking)

**For Parsers/Extractors:**
- Empty input strings
- None/null inputs
- Malformed input (invalid format)
- Very large inputs (performance)
- Unicode/special characters
- Edge boundary values (max/min)

**For Models/Dataclasses:**
- Null/None in optional fields
- Invalid types for fields
- Missing required fields
- Validation failures
- Serialization/deserialization

**For Pipelines/Workflows:**
- Empty input collections
- Partial failures (some items succeed, some fail)
- External dependency failures (network, API)
- Timeout scenarios
- State consistency across steps

---

## Coverage Analysis Process

### Phase 1: Run Coverage and Parse Results

```bash
# Run pytest with coverage
pytest --cov=src --cov-report=term-missing --cov-report=html

# Output shows:
# Name                          Stmts   Miss  Cover   Missing
# -----------------------------------------------------------
# src/web/routes/export.py         45     12    73%   23-28, 45-47, 67
```

**Parse output to identify:**
1. Files below target coverage
2. Specific uncovered line numbers
3. Total statements needed to cover
4. Current vs target coverage gap

### Phase 2: Categorize Gaps

For each uncovered line range, determine:

**Error Handling:**
- Exception handlers
- Error logging
- Error response generation

**Edge Cases:**
- None/null checks
- Empty collection checks
- Boundary conditions

**Happy Path:**
- Normal execution flow
- Common use cases

**Integration Points:**
- Database operations
- External API calls
- File I/O

### Phase 3: Generate Test Suggestions

For each gap, suggest specific test:

**Example:**
```
File: src/web/routes/export.py
Lines: 23-28 (6 statements)
Category: Error handling
Suggestion:
  def test_export_filing_handles_invalid_format(client, mock_db):
      """Test export route rejects invalid format parameter."""
      response = client.post("/api/filings/1/export", json={"format": "invalid"})
      assert response.status_code == 400
      assert "Invalid format" in response.json["message"]
```

### Phase 4: Prioritize Quick Wins

**Quick Win Criteria:**
- Files with <10 missing statements
- Missing statements are error handlers (easy to test)
- Missing statements are in utility functions (fast tests)
- High-value files (critical path, high usage)

**Sort by:**
1. Impact (critical modules first)
2. Effort (fewest statements first)
3. Risk (bug-prone modules first)

---

## Output: Coverage Gap Report

**Format:**

```markdown
# Coverage Gap Analysis

**Generated:** 2025-12-11
**Target Coverage:** 75%
**Current Coverage:** 68%
**Gap:** 7 percentage points
**Statements Needed:** ~150 (estimated)

## Coverage Improvement Tracking

**Previous Coverage:** {X}% (if known, e.g., from last analysis)
**Current Coverage:** 68%
**Improvement:** +{Y} percentage points (or "First analysis")

**Test Count Growth:**
- Previous: {N} tests (if known)
- Current: {M} tests
- Added: {M-N} tests

## Summary

- **Files Below Target:** 12
- **Total Missing Statements:** 387
- **Quick Wins (≤10 missing):** 5 files
- **High Priority (critical modules):** 3 files

## Quick Wins (Recommended First)

### 1. src/web/routes/export.py

**Coverage Improvement:** 73% → 85% (+12 percentage points)
**Test Count:** {current_tests} → {current_tests + 3} tests (+3 tests)
**Missing:** 6 statements (lines 23-28, 45)
**Effort:** Low (1-2 tests)
**Priority:** High (user-facing route)

**Suggested Tests:**
1. `test_export_filing_handles_invalid_format()` - Lines 23-25
2. `test_export_filing_handles_database_error()` - Lines 26-28
3. `test_export_filing_validates_filing_exists()` - Line 45

**Expected Result After Completion:**
✅ Coverage improved from 73% → 85%
✅ Added 3 comprehensive tests
✅ All error cases covered

### 2. src/review/helpers.py (82% → 90%)

**Missing:** 4 statements (lines 67-70)
**Effort:** Low (1 test)
**Priority:** Medium

**Suggested Tests:**
1. `test_generate_candidates_for_filing_handles_empty_segments()` - Lines 67-70

## Detailed Analysis

### src/extraction/value_extractor.py (66% → 85%)

**Missing:** 45 statements
**Effort:** Medium (8-10 tests)
**Priority:** High (core extraction logic)

**Uncovered Line Ranges:**
- Lines 123-135: Error handling for invalid number formats
- Lines 156-167: Edge case for None values
- Lines 201-215: Decimal precision handling

**Suggested Tests:**
1. `test_extract_value_handles_malformed_currency()` - Lines 123-128
2. `test_extract_value_handles_none_input()` - Lines 156-160
3. `test_extract_value_preserves_decimal_precision()` - Lines 201-207
...

## Test Plan

**To reach 75% coverage:**
- Quick wins: ~2 hours (5 files, 20 statements)
- Medium effort: ~5 hours (4 files, 80 statements)
- High effort: ~8 hours (3 files, 50 statements)

**Total Estimated Time:** 15 hours
**Recommended Approach:** Complete all quick wins first (immediate progress)
```

---

## Output: Generated Test File

**Example Unit Test:**

```python
"""
Unit tests for export routes.

Tests export functionality with mocked database.
Generated by test-coverage-analyzer skill.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.web.app import create_app


@pytest.fixture
def app():
    """Create Flask app for testing."""
    app = create_app("testing")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Create mock database adapter."""
    with patch("src.web.routes.export.get_db") as mock_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        yield mock


# =============================================================================
# Test export_filing() route
# =============================================================================


class TestExportFiling:
    """Tests for export_filing route."""

    def test_export_filing_accepts_valid_csv_format(self, client, mock_db):
        """Test export accepts CSV format."""
        mock_db.get_filing.return_value = {"filing_id": 1, "company_name": "Test"}
        mock_db.create_export.return_value = 123

        response = client.post(
            "/api/filings/1/export",
            json={"format": "csv"}
        )

        assert response.status_code == 201
        assert response.json["export_id"] == 123

    def test_export_filing_handles_invalid_format(self, client, mock_db):
        """Test export rejects invalid format parameter."""
        response = client.post(
            "/api/filings/1/export",
            json={"format": "invalid"}
        )

        assert response.status_code == 400
        assert "Invalid format" in response.json["message"]

    def test_export_filing_validates_filing_exists(self, client, mock_db):
        """Test export validates filing exists."""
        mock_db.get_filing.return_value = None

        response = client.post(
            "/api/filings/999/export",
            json={"format": "csv"}
        )

        assert response.status_code == 404
        assert "Filing not found" in response.json["message"]

    def test_export_filing_handles_database_error(self, client, mock_db):
        """Test export handles database errors gracefully."""
        mock_db.get_filing.side_effect = Exception("DB connection failed")

        response = client.post(
            "/api/filings/1/export",
            json={"format": "csv"}
        )

        assert response.status_code == 500
        assert "Internal server error" in response.json["message"]
```

---

## Common Test Patterns Reference

### Testing Exceptions

```python
def test_function_raises_value_error():
    """Test function raises ValueError for invalid input."""
    with pytest.raises(ValueError, match="Expected positive"):
        function_that_validates(-1)


def test_function_raises_specific_exception():
    """Test function raises custom exception with message."""
    with pytest.raises(CustomException) as exc_info:
        function_that_fails()

    assert "specific error message" in str(exc_info.value)
```

### Testing Logging

```python
def test_function_logs_warning(caplog):
    """Test function logs warning message."""
    import logging

    with caplog.at_level(logging.WARNING):
        function_that_warns()

    assert "Warning message" in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
```

### Testing File Operations

```python
def test_function_reads_file(tmp_path):
    """Test function reads file correctly."""
    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # Test reading
    result = function_that_reads(str(test_file))

    assert result == "test content"


def test_function_creates_file(tmp_path):
    """Test function creates file."""
    output_file = tmp_path / "output.txt"

    function_that_writes(str(output_file), "data")

    assert output_file.exists()
    assert output_file.read_text() == "data"
```

### Parametrized Tests

```python
@pytest.mark.parametrize(
    "input_value,expected_output,expected_unit",
    [
        ("$1.5M", Decimal("1500000"), "usd"),
        ("45%", Decimal("45"), "percentage"),
        ("10,000", Decimal("10000"), "count"),
        ("$2.5B", Decimal("2500000000"), "usd"),
    ],
)
def test_parse_number_formats(input_value, expected_output, expected_unit):
    """Test parsing different number formats."""
    result = parse_number(input_value)

    assert result.value == expected_output
    assert result.unit == expected_unit
```

---

## Usage Examples

### Example 1: Analyze all modules and generate report only

```
"Use test-coverage-analyzer skill to:
- Analyze all src/ modules
- Target 75% coverage
- Generate coverage gap report
- Show quick wins (files with <10 missing statements)
- Do not generate test files yet"
```

**Output:** Coverage gap report with prioritized recommendations

### Example 2: Generate tests for specific module

```
"Use test-coverage-analyzer skill to:
- Focus on src/web/routes/export.py
- Generate unit tests to reach 85% coverage
- Include tests for error handling and edge cases"
```

**Output:** Unit test file `tests/unit/web/test_export_routes.py`

### Example 3: Generate integration tests

```
"Use test-coverage-analyzer skill to:
- Focus on src/review/pattern_analyzer.py
- Generate integration tests
- Include database transaction tests
- Target 90% coverage"
```

**Output:** Integration test file `tests/integration/test_pattern_analyzer.py`

### Example 4: Quick wins analysis

```
"Use test-coverage-analyzer skill to:
- Find quick wins only (files with <10 missing statements)
- Prioritize by criticality (infrastructure and web routes first)
- Generate tests for top 3 quick wins"
```

**Output:** Report + 3 test files for highest-impact quick wins

---

## Workflow Integration

**Typical Development Cycle:**

1. **After feature implementation:**
   ```
   "Use test-coverage-analyzer skill to analyze src/review/new_feature.py
   and generate tests to reach 85% coverage"
   ```

2. **Before code review:**
   ```
   "Use test-coverage-analyzer skill to find all files below 75% coverage
   and generate report with quick wins highlighted"
   ```

3. **During refactoring:**
   ```
   "Use test-coverage-analyzer skill to ensure src/extraction/refactored_module.py
   maintains 80%+ coverage. Generate any missing tests."
   ```

4. **Periodic coverage maintenance:**
   ```
   "Use test-coverage-analyzer skill to:
   - Analyze all modules
   - Show files that dropped below target since last commit
   - Generate tests for regressions"
   ```

---

## Best Practices Checklist

When generating tests, ensure:

**Test Structure:**
- [ ] Descriptive docstrings for all tests
- [ ] Clear Arrange-Act-Assert pattern
- [ ] One logical assertion per test (or related assertions)
- [ ] Test names describe what is being tested

**Coverage:**
- [ ] Happy path tested
- [ ] Error cases tested (exceptions, validation failures)
- [ ] Edge cases tested (None, empty, boundary values)
- [ ] Integration points tested (if applicable)

**Mocking:**
- [ ] External dependencies mocked in unit tests
- [ ] Real dependencies used in integration tests
- [ ] Mock assertions verify interactions

**Fixtures:**
- [ ] Reusable test data in fixtures
- [ ] Proper fixture scope (function vs module vs session)
- [ ] Cleanup in fixture teardown (for integration tests)

**Assertions:**
- [ ] Specific assertions (not just `assert result`)
- [ ] Error messages in assertions when helpful
- [ ] Multiple related assertions grouped logically

---

## Version History

**1.1.0** (2025-12-12)
- Enhanced coverage improvement tracking
- Added "Before → After" coverage visualization (e.g., "5% → 97%")
- Added test count growth tracking (e.g., "2 → 48 tests")
- Added "Expected Result After Completion" celebration format
- Added coverage history section to track improvements over time
- Matches actual usage patterns from DEVELOPMENT_PLAN.md

**1.0.0** (2025-12-11)
- Initial skill creation
- Based on pytest patterns from 475+ existing tests
- Includes unit and integration test generation
- Coverage gap analysis with prioritization
- Edge case library by module type
- Test data helpers from conftest.py patterns

---

## Related Skills

- **implementation-planner**: Use before implementing features to plan test strategy
- **flask-api-builder**: Generates tests automatically with routes
- **code-module-grader**: Evaluates test quality after generation

---

## Notes

- This skill uses pytest coverage data to identify gaps
- Generated tests follow project patterns (83% average coverage achieved)
- Integration tests require TEST_DATABASE_URL to be set
- Parametrized tests preferred for testing multiple similar cases
- Always verify generated tests run and pass before committing
- Coverage targets are guidelines - 100% coverage not always necessary
