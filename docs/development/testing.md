# Testing Strategy

**Version:** 3.2
**Last Updated:** 2026-03-11

---

## Overview

Comprehensive testing strategy for ensuring quality extraction at scale with minimal cost. The test suite achieves **87% code coverage** (75% minimum enforced) across 100+ test files with a mixture of unit, integration, end-to-end, and performance tests.

**Key Principles:**
1. Test components in isolation before integration
2. Use sample/mock data for unit tests (avoid API costs)
3. Validate on real data with integration tests
4. Measure both technical metrics (success rate) and business metrics (extraction quality)
5. Enforce gold standard regression testing for extraction logic changes

---

## Testing Pyramid

```
              ┌─────────────────┐
              │  Gold Standard  │  4 companies (ground-truth CSV)
              │  Regression     │  (Baseline validation)
              └─────────────────┘
                      ▲
          ┌───────────┴───────────┐
          │   E2E Tests           │  Full workflow tests
          │   (e2e/)              │  Browser automation
          └───────────────────────┘
                      ▲
              ┌───────┴───────┐
              │ Integration   │  Database + API tests
              │ (integration/)│  Requires TEST_DATABASE_URL
              └───────────────┘
                      ▲
                  ┌───┴───┐
                  │ Unit  │  Fast, isolated tests
                  │ (unit/)│  No external dependencies
                  └───────┘
```

**Test Structure:**
```
tests/
├── conftest.py          # Root pytest config (gold standard CLI options)
├── fixtures/            # Test data (HTML samples, JSON responses)
├── e2e/                 # End-to-end tests (1 file)
├── performance/         # Performance benchmarks (2 files)
├── unit/               # Unit tests (70+ files)
│   ├── extraction/      # 27 test files
│   ├── extraction_v2/   # 25 test files
│   ├── filing_fetcher/  # 2 test files
│   ├── gold_standard/   # 3 test files
│   ├── infra/           # 7 test files
│   ├── llm/             # 3 test files
│   ├── review/          # 22 test files
│   ├── scripts/         # 2 test files
│   ├── universe/        # 2 test files
│   └── web/             # 9 test files
└── integration/        # Integration tests (30+ files)
    ├── extraction/      # Pipeline integration
    ├── extraction_v2/   # V2 pipeline tests
    ├── universe/        # Universe builder integration
    └── web/             # Workflow tests
```

---

## Running Tests

### Basic Commands

```bash
# Run all tests with coverage (default)
pytest -v

# Run specific test directory
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v

# Run specific test file
pytest tests/unit/extraction/test_html_segmenter.py -v

# Run tests matching pattern
pytest -k "test_value_extraction" -v

# Run tests by marker
pytest -m unit -v
pytest -m integration -v
pytest -m "not slow" -v
```

### Coverage Reports

```bash
# Generate HTML coverage report
pytest --cov=src --cov-report=html
open htmlcov/index.html

# Show coverage in terminal
pytest --cov=src --cov-report=term-missing

# Fail if coverage drops below 75%
pytest --cov=src --cov-fail-under=75
```

### Integration Test Requirements

Integration tests require a test database. Set the `TEST_DATABASE_URL` environment variable:

```bash
# Add to .env
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test

# Run integration tests
pytest tests/integration/ -v

# Skip integration tests (for faster development)
pytest tests/unit/ -v
```

### Test Markers

The test suite uses pytest markers for selective test execution:

```bash
# Run only unit tests (fast, no dependencies)
pytest -m unit -v

# Run only integration tests (requires database)
pytest -m integration -v

# Run gold standard regression tests
pytest -m gold_standard -v

# Run performance benchmarks
pytest -m benchmark -v

# Skip slow tests
pytest -m "not slow" -v
```

---

## Unit Tests

Unit tests are fast, isolated tests with no external dependencies. They test individual components in isolation using mock data.

### Example: HTML Segmenter

**File:** `tests/unit/extraction/test_html_segmenter.py`

```python
"""Unit tests for HTMLSegmenter."""

import tempfile
from pathlib import Path
import pytest
from src.extraction.html_segmenter import HTMLSegmenter


@pytest.fixture
def sample_html():
    """Simple HTML with paragraphs and a table."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <h1>Prospectus Summary</h1>
        <p>We are a leading technology company.</p>
        <p>Our DAU reached 1.5 million in Q4 2023.</p>

        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>DAU</td><td>1,500</td></tr>
            <tr><td>Revenue</td><td>$10M</td></tr>
        </table>

        <p>We define daily active users as users who log in daily.</p>
    </body>
    </html>
    """


def test_segments_paragraphs_and_tables(sample_html):
    """Test that segmenter extracts both paragraphs and tables."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(sample_html)
        html_path = Path(f.name)

    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(html_path=html_path, filing_id=1)

    # Should extract paragraphs and table
    assert len(segments) >= 3

    # Check segment types
    segment_types = {s.segment_type for s in segments}
    assert "paragraph" in segment_types
    assert "table" in segment_types

    html_path.unlink()


def test_table_structure_preserved(sample_html):
    """Test that table structure is preserved in table segments."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(sample_html)
        html_path = Path(f.name)

    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(html_path=html_path, filing_id=1)

    # Find table segment
    table_segments = [s for s in segments if s.segment_type == "table"]
    assert len(table_segments) > 0

    table = table_segments[0]
    assert "DAU" in table.raw_text
    assert "1,500" in table.raw_text

    html_path.unlink()
```

### Example: Value Extractor

**File:** `tests/unit/extraction_v2/test_value_binding.py`

```python
"""Unit tests for ValueExtractor."""

from datetime import date
from decimal import Decimal
from src.extraction.models import SourceSegment
from src.extraction.value_extractor import ValueExtractor


def build_segment(**overrides) -> SourceSegment:
    """Helper to construct a SourceSegment with sensible defaults."""
    defaults = {
        "filing_id": 1,
        "segment_type": "paragraph",
        "raw_text": "Placeholder",
        "sequence_index": 0,
        "candidate_metric_ids": [],
        "contains_numeric_disclosure_flag": True,
    }
    defaults.update(overrides)
    return SourceSegment(**defaults)


def test_extract_numeric_value_from_text():
    """Test extraction of numeric values from text segments."""
    segment = build_segment(
        raw_text="We had approximately 1,500 daily active users (DAUs).",
        candidate_metric_ids=["cm_daily_active_users"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=42)

    assert len(values) == 1
    value = values[0]
    assert value.metric_id == "cm_daily_active_users"
    assert value.value_numeric == Decimal("1500")
    assert value.extraction_method == "rule_text_smart"


def test_extract_percentage_from_text():
    """Test extraction of percentage values."""
    segment = build_segment(
        raw_text="Our net revenue retention was 127% in 2023.",
        candidate_metric_ids=["cm_net_revenue_retention"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=42)

    assert len(values) == 1
    assert values[0].value_numeric == Decimal("127")
    assert values[0].unit == "%"


def test_handles_missing_data_indicators():
    """Test that missing data indicators (—, N/A) are skipped."""
    segment = build_segment(
        raw_text="Our NRR was 127% in 2023 and — in 2022.",
        candidate_metric_ids=["cm_net_revenue_retention"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=42)

    # Should only extract the valid 127%, not the —
    assert len(values) == 1
    assert values[0].value_numeric == Decimal("127")
```

### Example: Metric Classifier

**File:** `tests/unit/extraction/test_metric_classifier.py`

```python
"""Unit tests for MetricClassifier."""

from src.extraction.metric_classifier import MetricClassifier
from src.extraction.models import SourceSegment


def test_classify_dau_segment():
    """Test classification of segment containing DAU keywords."""
    segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text="Our daily active users (DAU) reached 2.5 million.",
        sequence_index=0,
        candidate_metric_ids=[],
        contains_numeric_disclosure_flag=True,
    )

    classifier = MetricClassifier()
    classified = classifier.classify_segment(segment)

    assert "cm_daily_active_users" in classified.candidate_metric_ids


def test_require_both_signal():
    """Test that REQUIRE_BOTH metrics need both keyword types."""
    # Segment with only metric keyword (no context keyword)
    segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text="We had 5,000 monthly active users.",
        sequence_index=0,
        candidate_metric_ids=[],
        contains_numeric_disclosure_flag=True,
    )

    classifier = MetricClassifier()
    classified = classifier.classify_segment(segment)

    # MAU requires REQUIRE_BOTH, so needs context signal too
    # Without context signal, should not classify
    assert "cm_monthly_active_users" not in classified.candidate_metric_ids
```

---

## Integration Tests

Integration tests validate component interactions and require external dependencies (database, files). They test end-to-end workflows with real data.

### Database Setup

Integration tests require a test database:

```bash
# Start test database (Docker)
docker compose up -d

# Or set custom database URL
export TEST_DATABASE_URL=postgresql://user:pass@localhost:5433/test_db

# Run integration tests
pytest tests/integration/ -v
```

### Example: Filing Pipeline Integration

**File:** `tests/integration/test_filing_pipeline.py`

```python
"""Integration tests for end-to-end filing pipeline."""

from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.sec_client import SECClient, FilingMetadata


class TestFilingPipeline:
    """Integration tests for complete filing processing pipeline."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a filing fetcher with temp storage."""
        sec_client = SECClient(user_agent="test-client test@example.com")
        return FilingFetcher(
            storage_root=str(tmp_path / "test_filings"),
            sec_client=sec_client
        )

    @pytest.fixture
    def sample_filing_html(self):
        """Create realistic S-1 filing HTML."""
        return """
        <DOCUMENT>
        <TYPE>S-1
        <SEQUENCE>1
        <TEXT>
        <HTML>
        <HEAD><TITLE>Form S-1</TITLE></HEAD>
        <BODY>
        <P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
        <P>FORM S-1 REGISTRATION STATEMENT</P>
        <P>We had 10,500 daily active users as of December 31, 2023.</P>
        <TABLE>
            <TR><TH>Metric</TH><TH>2023</TH><TH>2022</TH></TR>
            <TR><TD>DAU (thousands)</TD><TD>10.5</TD><TD>8.2</TD></TR>
        </TABLE>
        </BODY>
        </HTML>
        </TEXT>
        </DOCUMENT>
        """

    def test_full_pipeline_extracts_metrics(self, fetcher, sample_filing_html, db):
        """Test that full pipeline extracts metrics from filing."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-24-000001",
            primary_doc_url="https://www.sec.gov/test/filing.htm",
        )

        # Mock HTTP response
        with patch.object(fetcher.session, "get") as mock_get:
            mock_response = Mock()
            mock_response.text = sample_filing_html
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            # Fetch filing
            html_path = fetcher.fetch_filing(metadata)
            assert html_path.exists()

            # Process through pipeline
            from src.extraction.html_segmenter import HTMLSegmenter
            from src.extraction.metric_classifier import MetricClassifier
            from src.extraction.value_extractor import ValueExtractor

            segmenter = HTMLSegmenter()
            classifier = MetricClassifier()
            extractor = ValueExtractor()

            # Segment
            segments = segmenter.segment_filing(html_path, filing_id=1)
            assert len(segments) > 0

            # Classify
            classified = [classifier.classify_segment(s) for s in segments]

            # Extract values
            values = []
            for segment in classified:
                if segment.candidate_metric_ids:
                    values.extend(extractor.extract_from_text(segment, company_id=1))

            # Verify extraction
            assert len(values) > 0

            # Check for DAU metric
            dau_values = [v for v in values if "daily_active_users" in v.metric_id]
            assert len(dau_values) > 0
```

### Example: Review Workflow

**File:** `tests/integration/web/test_review_workflow.py`

```python
"""Integration tests for review workflow."""

import pytest
from src.infra.db import DatabaseConnection


@pytest.mark.integration
def test_review_workflow_end_to_end(db: DatabaseConnection):
    """Test complete review workflow from candidate to decision."""
    # 1. Insert test filing
    company_id = db.insert_company(
        cik="0001234567",
        company_name="Test Corp",
        sic_code="7372"
    )

    filing_id = db.insert_filing(
        company_id=company_id,
        form_type="S-1",
        filing_date="2024-01-15",
        accession_number="0001234567-24-000001"
    )

    # 2. Insert segment
    segment_id = db.insert_source_segment(
        filing_id=filing_id,
        segment_type="paragraph",
        raw_text="We had 1,500 DAU in Q4 2023.",
        sequence_index=1
    )

    # 3. Generate review candidate
    from src.review.candidate_generator import CandidateGenerator
    generator = CandidateGenerator(db)
    candidates = generator.generate_candidates([filing_id])

    assert len(candidates) > 0

    # 4. Record review decision
    candidate = candidates[0]
    db.insert_review_decision(
        candidate_id=candidate.candidate_id,
        reviewer_id="test_reviewer",
        decision="accept",
        canonical_metric_id="cm_daily_active_users"
    )

    # 5. Verify decision recorded
    decisions = db.get_review_decisions(filing_id=filing_id)
    assert len(decisions) > 0
    assert decisions[0].decision == "accept"
```

---

## Gold Standard Regression Testing

Gold standard tests validate extraction accuracy against manually curated ground truth. These tests **must pass** before merging changes to extraction logic or keyword configuration.

### Overview

The gold standard consists of 37 manually verified filings with known metrics. The test suite compares current extraction performance against a saved baseline and fails if metrics degrade.

**Key Metrics:**
- **Precision**: % of extracted metrics that are correct (minimize false positives)
- **Recall**: % of actual metrics that were found (minimize false negatives)
- **F1 Score**: Harmonic mean of precision and recall

### Running Gold Standard Tests

```bash
# Run gold standard regression tests (uses existing DB extractions)
pytest -m gold_standard -v

# Run with fresh extraction (slower but more accurate)
pytest -m gold_standard --gold-standard-mode=fresh -v

# Run with custom tolerance (default: 1%)
pytest -m gold_standard --gold-standard-tolerance=0.02 -v

# Update baseline after confirmed improvements
pytest -m gold_standard --gold-standard-update-baseline -v
```

### Creating/Updating Baseline

When you make improvements to extraction logic, update the baseline:

```bash
# Run validation script to see current metrics
python3 scripts/validate_against_gold_standard.py --all

# If metrics improved, update baseline
python3 scripts/validate_against_gold_standard.py --all --update-baseline

# Verify tests pass with new baseline
pytest -m gold_standard -v
```

### Test Assertions

**File:** `tests/integration/test_gold_standard_regression.py`

The gold standard tests include:
- `test_overall_precision_above_baseline` - Fails if precision drops
- `test_overall_recall_above_baseline` - Fails if recall drops
- `test_overall_f1_above_baseline` - Fails if F1 score drops
- `test_no_company_recall_regressions` - Fails if any company's recall decreased

**Example output on regression:**
```
FAILED tests/integration/test_gold_standard_regression.py::test_overall_precision_above_baseline

Precision regression detected!
  Baseline: 0.912 (91.2%)
  Current:  0.887 (88.7%)
  Drop:     -0.025 (-2.5%)

Tolerance: 0.010 (1.0%)
REGRESSION: Precision dropped by 2.5%, exceeding 1.0% tolerance.
```

### Gold Standard CLI Options

The root `conftest.py` provides custom CLI options:

```python
def pytest_addoption(parser):
    """Add gold standard CLI options."""
    parser.addoption(
        "--gold-standard-mode",
        choices=["db", "fresh"],
        default="db",
        help="'db' uses existing extractions, 'fresh' re-extracts"
    )
    parser.addoption(
        "--gold-standard-tolerance",
        type=float,
        default=0.01,
        help="Regression tolerance (e.g., 0.01 = 1%)"
    )
    parser.addoption(
        "--gold-standard-update-baseline",
        action="store_true",
        help="Update baseline instead of comparing"
    )
```

### When to Run Gold Standard Tests

**Required before merging:**
- Changes to `src/extraction_v2/` (any stage)
- Changes to `config/metric_keywords.yaml`
- Changes to `src/gold_standard/` validation logic

**Run fresh extraction when:**
- You've changed extraction algorithms
- You suspect cached DB extractions are stale
- You want the most accurate validation

---

## Type Checking

The project enforces strict type checking on critical modules.

### Running Type Checks

```bash
# Check review module (strict mode)
mypy src/review/ --strict

# Check all source code (permissive mode)
mypy src/
```

### Type Checking Configuration

From `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
strict_optional = true
ignore_missing_imports = true

# Strict mode for review module
[[tool.mypy.overrides]]
module = "src.review.*"
disallow_untyped_defs = true
disallow_any_generics = true
warn_return_any = true
no_implicit_reexport = true
```

**Coverage:**
- `src/review/*` - Full strict mode (100% type coverage)
- Other modules - Permissive mode (gradual typing)

---

## Performance Testing

Performance tests measure execution speed and resource usage for optimization.

### Running Performance Tests

```bash
# Run all performance/benchmark tests
pytest tests/performance/ -v

# Run with benchmark marker
pytest -m benchmark -v

# Generate performance report
pytest tests/performance/test_segment_enricher_performance.py -v --durations=10
```

### Example: Segment Enricher Performance

**File:** `tests/performance/test_segment_enricher_performance.py`

```python
"""Performance tests for segment enricher."""

import pytest
import time
from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.models import SourceSegment


@pytest.mark.benchmark
def test_enricher_performance_1000_segments(benchmark):
    """Benchmark enricher with 1000 segments."""
    enricher = SegmentEnricher()

    # Create test segments
    segments = []
    for i in range(1000):
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=f"Test segment {i} with some metrics like DAU and MAU.",
            sequence_index=i,
            candidate_metric_ids=["cm_daily_active_users"],
            contains_numeric_disclosure_flag=True,
        )
        segments.append(segment)

    # Benchmark enrichment
    def enrich():
        return enricher.enrich_segments(segments)

    result = benchmark(enrich)

    # Verify reasonable performance
    assert benchmark.stats['mean'] < 1.0  # Should complete in <1 second
```

### Example: Candidate Generation Benchmark

**File:** `tests/performance/test_candidate_generation_benchmark.py`

Tests the performance of review candidate generation with large datasets.

---

## End-to-End Tests

E2E tests validate complete user workflows including browser interactions.

### Example: Metric Dropdown Search

**File:** `tests/e2e/test_metric_dropdown_search.py`

Tests the review interface metric dropdown search functionality. Requires Selenium or Playwright for browser automation.

```bash
# Run E2E tests
pytest tests/e2e/ -v
```

---

## Coverage Requirements

### Enforcement

Coverage is enforced via pytest configuration:

```toml
[tool.pytest.ini_options]
addopts = [
    "--cov=src",
    "--cov-fail-under=75",  # Fail if below 75%
    "--cov-report=term-missing",
    "--cov-report=html",
]
```

### Current Coverage

**Overall:** 87% (target: 75% minimum)

**By Module:**
- `src/extraction_v2/` - 75%+
- `src/review/` - 85%+
- `src/web/` - 80%+
- `src/infra/` - 85%+

### Viewing Coverage

```bash
# Generate HTML coverage report
pytest --cov=src --cov-report=html

# Open in browser
open htmlcov/index.html

# Show uncovered lines
pytest --cov=src --cov-report=term-missing
```

---

## Validation Metrics

### Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Test Coverage | ≥75% | `pytest --cov=src` |
| Test Success Rate | 100% | All tests pass on main |
| Type Check Pass | 100% | `mypy src/review/ --strict` |
| Gold Standard Precision | ≥80% | `pytest -m gold_standard` |
| Gold Standard Recall | ≥55% | `pytest -m gold_standard` |

### Quality Metrics (Gold Standard)

Current V2 scores as of 2026-03-11: Text-only P=95.0%, R=83.5%, F1=88.9%; Image-enabled P=92.3%, R=83.5%, F1=87.7%. V1 baseline (retired): P=89.4%, R=63.2%, F1=74.1%.

| Metric | Target | Formula |
|--------|--------|---------|
| Precision | >80% | `true_positives / (true_positives + false_positives)` |
| Recall | >55% | `true_positives / (true_positives + false_negatives)` |
| F1 Score | >0.65 | `2 * (precision * recall) / (precision + recall)` |

### Manual QA Protocol

For validating extraction on new filings:

1. **Open actual SEC filing** in browser
2. **Find metrics section** manually
3. **Compare to extracted metrics:**
   - ✅ Correctly extracted (true positive)
   - ❌ Incorrectly extracted (false positive)
   - ⚠️ Missed metric (false negative)
   - ℹ️ Correctly ignored (true negative)

4. **Record results** in spreadsheet:
   ```csv
   filing_id,metric_name,extracted_value,actual_value,status,notes
   0001...,DAU,1.5M,1.5M,correct,""
   0001...,MAU,5.2M,,false_positive,"No MAU mentioned"
   0001...,NRR,,127%,missed,"NRR in text, not table"
   ```

5. **Calculate accuracy:**
   ```python
   import pandas as pd

   df = pd.read_csv('qa_results.csv')

   precision = (
       len(df[df['status'] == 'correct']) /
       len(df[df['status'].isin(['correct', 'false_positive'])])
   )

   recall = (
       len(df[df['status'] == 'correct']) /
       len(df[df['status'].isin(['correct', 'missed'])])
   )

   f1 = 2 * (precision * recall) / (precision + recall)

   print(f"Precision: {precision:.1%}")
   print(f"Recall: {recall:.1%}")
   print(f"F1 Score: {f1:.1%}")
   ```

---

## Coverage Targets by Module

This section documents coverage targets and current state by module category. These are **visibility targets**, not CI gates - use this as a prioritization guide when writing tests.

### Coverage Target Tiers

| Tier | Target | Rationale |
|------|--------|-----------|
| **Critical** | 90-100% | Core business logic, data integrity |
| **Standard** | 85-95% | Most production code |
| **Acceptable** | 75-85% | Infrastructure, utilities |
| **Minimum** | 75% | CI enforcement threshold |

### Module Coverage Dashboard

| Module Category | Target | Current Status | Priority |
|-----------------|--------|----------------|----------|
| **Core Extraction** | | | |
| `src/extraction_v2/` | 85% | Production | High |
| **Review System** | | | |
| `src/review/` | 95% | ~95% | Maintained |
| **Web Routes** | | | |
| `src/web/routes/` | 90% | 30-97% (uneven) | High |
| **Infrastructure** | | | |
| `src/infra/db.py` | 90% | ~85% | Medium |
| `src/infra/sec_client.py` | 80% | Varies | Low |
| **LLM Integration** | | | |
| `src/llm/` | 75% | ~75% | Low (expensive to test) |
| **Universe Builder** | | | |
| `src/universe/` | 85% | Varies | Medium |

### Viewing Current Coverage

```bash
# Full coverage report with missing lines
pytest --cov=src --cov-report=term-missing

# HTML report for detailed exploration
pytest --cov=src --cov-report=html
# Open htmlcov/index.html in browser

# Coverage for specific module
pytest --cov=src/web/routes --cov-report=term-missing tests/unit/web/
```

---

## Continuous Integration

### GitHub Actions Workflows

Active workflow files in `.github/workflows/`:

- `claude.yml` - Claude Code integration
- `claude-code-review.yml` - Automated code review
- `docs-sync.yml` - Documentation synchronization

To run tests locally before pushing (equivalent to CI):

```bash
# Unit tests
pytest tests/unit/ -v

# Type checks
mypy src/review/ --strict

# Code formatting check
ruff format --check src/ tests/

# Linter
ruff check src/ tests/
```

### Pre-commit Hooks

Install pre-commit hooks to run tests before commits:

```bash
# pre-commit is included in dev dependencies; install hooks after uv sync:
pre-commit install

# Run manually
pre-commit run --all-files
```

---

## Test Data

### Sample Filings for Testing

Known good filings used in tests:

```python
TEST_FILINGS = {
    "slack": {
        "cik": "1764925",
        "company": "Slack Technologies",
        "form_type": "S-1",
        "expected_metrics": ["DAU", "Paid Customers", "Net Revenue Retention"]
    },
    "snowflake": {
        "cik": "1640147",
        "company": "Snowflake Inc.",
        "form_type": "S-1",
        "expected_metrics": ["Customers", "Net Revenue Retention", "Product Revenue"]
    },
    "datadog": {
        "cik": "1561550",
        "company": "Datadog Inc.",
        "form_type": "S-1",
        "expected_metrics": ["Customers", "Annual Recurring Revenue"]
    }
}
```

### Fixture Files

Test fixtures are located in `tests/fixtures/`:

```
tests/fixtures/
├── html/               # Sample HTML filings
│   ├── simple_s1.html
│   ├── table_with_metrics.html
│   └── sgml_wrapped.html
├── json/               # API responses
│   ├── sec_index.json
│   └── company_search.json
└── csv/                # Gold standard data
    └── golden_set_251218.csv
```

---

## Common Testing Patterns

### Using Fixtures

```python
import pytest
from src.infra.db import DatabaseConnection


@pytest.fixture
def db(test_db_url):
    """Provide database connection for tests."""
    db = DatabaseConnection(test_db_url)
    yield db
    db.close()


def test_with_database(db):
    """Test that uses database fixture."""
    company_id = db.insert_company(
        cik="0001234567",
        company_name="Test Corp",
        sic_code="7372"
    )
    assert company_id > 0
```

### Mocking External APIs

```python
from unittest.mock import Mock, patch


def test_sec_api_call():
    """Test SEC API call with mocked response."""
    with patch('requests.get') as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = {"filings": []}
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # Your test code here
        from src.infra.sec_client import SECClient
        client = SECClient(user_agent="test test@example.com")
        result = client.search_filings(cik="0001234567")

        assert result is not None
```

### Parameterized Tests

```python
import pytest


@pytest.mark.parametrize("input_value,expected", [
    ("1,500", 1500),
    ("1.5M", 1500000),
    ("$2.3B", 2300000000),
    ("45%", 45),
])
def test_value_normalization(input_value, expected):
    """Test normalization of various value formats."""
    from src.extraction.value_extractor import normalize_value
    assert normalize_value(input_value) == expected
```

---

## Troubleshooting

### Common Issues

**Issue:** Tests fail with "No module named 'src'"
```bash
# Solution: Sync all dependencies including dev extras
uv sync --all-extras
```

**Issue:** Integration tests fail with database connection error
```bash
# Solution: Set TEST_DATABASE_URL
export TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/test_db

# Or start Docker container
docker compose up -d
```

**Issue:** Coverage report shows 0%
```bash
# Solution: Ensure tests are actually running
pytest -v --cov=src --cov-report=term

# Check if source files are being imported
python3 -c "from src.extraction.html_segmenter import HTMLSegmenter; print('OK')"
```

**Issue:** Gold standard tests fail with "baseline not found"
```bash
# Solution: Create baseline
python3 scripts/validate_against_gold_standard.py --all --update-baseline
```

---

## Next Steps

- **Production Deployment:** See `docs/operations/deployment-guide.md` for production setup
- **Adding New Tests:** Follow existing patterns in `tests/unit/` or `tests/integration/`
- **Improving Coverage:** Run `pytest --cov=src --cov-report=html` and check `htmlcov/index.html`
- **Gold Standard Validation:** See `.claude/rules/gold-standard.md` for detailed workflow

---

## Related Documentation

- [System Architecture](../architecture/system-overview.md)
- [Extraction Pipeline](../architecture/extraction-decisions.md)
- [Human Review System](../HUMAN_REVIEW_SYSTEM.md)
- [V2 Migration Guide](../V2_MIGRATION_GUIDE.md)
- [Gold Standard Rules](../../.claude/rules/gold-standard.md)
