# Testing

**Last Updated:** 2026-04-08

---

## Overview

The test suite enforces correctness across the extraction pipeline, review system, web API, infrastructure, and gold standard regression framework.

**Test philosophy:**
1. Rule-based extraction logic is tested in isolation before integration — unit tests cover individual stages and parsers without database or LLM dependencies.
2. Integration tests require a real PostgreSQL test database (`TEST_DATABASE_URL`). They validate database upsert idempotency, full pipeline runs on cached HTML fixtures, and API transaction integrity.
3. Gold standard regression tests guard against precision/recall regressions on a curated set of known-good filings.

**Coverage requirement:** 75% minimum, enforced by `pytest-cov` (`fail_under = 75` in `pyproject.toml`). The `src/extraction/` (V1, retired) directory is excluded from coverage measurement.

**Type safety:** `src/review/` passes `mypy --strict`. Other modules use permissive mypy settings.

---

## Running Tests

### Default run (excludes slow/gold_standard markers)

```bash
pytest -v
```

The default `addopts` in `pyproject.toml` deselects `slow`, `v2_parity`, `gold_standard`, and `transcript_gold_standard` markers. The standard run collects ~4490 of 4529 total tests.

### With coverage

```bash
pytest --cov=src --cov-report=html
# Open htmlcov/index.html for line-level detail

pytest --cov=src --cov-report=term-missing
```

### Single module or subdirectory

```bash
pytest tests/unit/extraction_v2/ -v
pytest tests/unit/review/ -v
pytest tests/integration/web/ -v
pytest tests/unit/extraction_v2/test_pipeline.py -v
```

### Filter by test name pattern

```bash
pytest -k "test_false_positive" -v
pytest -k "TestCandidateGeneration" -v
```

### Gold standard regression (requires cached HTML and baseline)

```bash
# Fresh mode — re-extracts from local HTML, no database required (recommended)
pytest -m gold_standard --gold-standard-mode=fresh -v

# DB mode — uses existing database rows
pytest -m gold_standard --gold-standard-mode=db -v

# With relaxed tolerance (default 1%)
pytest -m gold_standard --gold-standard-mode=fresh --gold-standard-tolerance=0.02 -v

# Update baseline instead of comparing
pytest -m gold_standard --gold-standard-mode=fresh --gold-standard-update-baseline -v
```

### Transcript gold standard

```bash
pytest -m transcript_gold_standard --transcript-split=tuning -v
pytest -m transcript_gold_standard --transcript-split=test -v
```

### Presentation gold standard

```bash
pytest tests/unit/test_presentation_gold_standard.py -v
```

### Performance benchmarks

```bash
pytest tests/performance/ -v --benchmark-only
```

### V2 parity (full re-extraction across all gold standard companies — slow)

```bash
pytest -m v2_parity -v
```

---

## Directory Structure

```
tests/
├── conftest.py                         # Root: CLI options, gold standard fixtures, transcript fixtures
├── unit/                               # Fast, isolated — no external dependencies
│   ├── extraction_v2/                  # V2 pipeline stage unit tests
│   │   ├── test_pipeline.py            # PipelineConfig, PipelineContext, process_filing
│   │   ├── test_candidate_generation.py # CandidateGenerationStage keyword matching
│   │   ├── test_false_positive_filter_stage.py # FalsePositiveFilterStage (V2-native + V1 delegate)
│   │   ├── test_models.py              # V2 dataclass validation (MetricFact, Segment, Table, etc.)
│   │   ├── test_period_inference.py    # Period parsing and inference
│   │   ├── test_number_parsing.py      # Number regex and multiplier handling
│   │   ├── test_deduplication.py       # Fact deduplication logic
│   │   ├── test_quality_scoring.py     # V2QualityScorer
│   │   ├── test_presentation_converter.py # Presentation-to-Document converter
│   │   ├── test_transcript_converter.py   # Transcript-to-Document converter
│   │   ├── test_batch_runner.py        # BatchRunner logic (no DB)
│   │   ├── test_image_pipeline_integration.py # Image pipeline stage wiring
│   │   ├── test_image_triage.py        # Image triage and classification
│   │   └── ...                         # Additional stage and utility tests
│   ├── review/                         # Review module unit tests (mypy --strict applies)
│   │   ├── test_candidate_generator.py # CandidateGenerator, NUMBER_REGEX, keyword matching
│   │   ├── test_keyword_matching.py    # METRIC_KEYWORDS, SPECIFIC_KEYWORD_PATTERNS
│   │   ├── test_false_positive_filter.py # FP filter rules
│   │   ├── test_confidence_scoring.py  # ConfidenceScorer
│   │   ├── test_pattern_analyzer.py    # PatternAnalyzer
│   │   ├── test_number_parsing.py      # NumberMatch parsing
│   │   └── ...                         # Additional review subsystem tests
│   ├── gold_standard/                  # Gold standard module unit tests (no DB)
│   │   ├── test_baseline.py            # BaselineMetrics, compare_to_baseline, load_baseline
│   │   ├── test_v2_validator.py        # V2GoldStandardValidator logic
│   │   ├── test_fresh_extractor.py     # FreshExtractor (file-based extraction)
│   │   └── test_unified_comparison.py  # UnifiedComparisonRunner
│   ├── infra/                          # Infrastructure unit tests
│   │   ├── test_db_validation.py       # DatabaseAdapter validation
│   │   ├── test_http_client.py         # HTTP client and retry logic
│   │   ├── test_sec_client.py          # SEC EDGAR client
│   │   ├── test_validation.py          # Input validation helpers
│   │   └── ...
│   ├── web/                            # Flask route unit tests (mocked DB)
│   │   ├── test_api_routes.py          # Core review API endpoints
│   │   ├── test_api_bulk.py            # Bulk decision endpoints
│   │   ├── test_review_v2_routes.py    # V2 review routes and pagination
│   │   ├── test_api_images_routes.py   # Image review routes
│   │   ├── test_auth.py                # Authentication middleware
│   │   └── ...
│   ├── llm/                            # LLM module unit tests
│   │   ├── test_openai_client.py       # OpenAI client wrapping
│   │   ├── test_cache.py               # PostgreSQL-backed LLM cache
│   │   ├── test_prompts.py             # Prompt construction
│   │   └── test_vision_client.py       # Vision/image LLM client
│   ├── universe/                       # Universe builder unit tests
│   ├── filing_fetcher/                 # FilingFetcher unit tests
│   ├── scripts/                        # Script entry-point unit tests
│   └── test_presentation_gold_standard.py  # Presentation GS evaluation
│
├── integration/                        # Requires TEST_DATABASE_URL
│   ├── conftest.py                     # DB fixtures: test_db_adapter, clean_db, fixture helpers
│   ├── extraction_v2/                  # V2 pipeline integration tests
│   │   ├── test_e2e_pipeline.py        # Full V2 run on cached gold standard filings
│   │   ├── test_persistence.py         # V2PersistenceAdapter DB writes
│   │   ├── test_batch_runner_db.py     # BatchRunner with real DB
│   │   ├── test_presentation_e2e.py    # Presentation pipeline end-to-end
│   │   ├── test_transcript_e2e.py      # Transcript pipeline end-to-end
│   │   ├── test_transcript_gold_standard.py  # Transcript GS regression
│   │   └── test_quality_scoring_integration.py
│   ├── web/                            # Web API integration tests (real DB + Flask test client)
│   │   ├── test_api_integration.py     # Review API transaction integrity
│   │   ├── test_review_workflow.py     # Full accept/reject/reclassify workflow
│   │   ├── test_v2_review_workflow.py  # V2 review workflow
│   │   ├── test_bulk_workflow.py       # Bulk decision workflow
│   │   └── test_image_review_workflow.py
│   ├── universe/
│   │   └── test_universe_builder_integration.py
│   ├── filing_fetcher/
│   │   └── test_filing_fetcher_db.py
│   ├── test_gold_standard_regression.py  # Gold standard regression tests (pytest -m gold_standard)
│   ├── test_gold_standard_coverage.py
│   ├── test_db_upsert.py               # DB upsert idempotency
│   ├── test_migration_safety.py        # Migration ordering and safety
│   └── ...
│
├── performance/                        # Benchmark tests (pytest-benchmark)
│   ├── conftest.py                     # benchmark_db, realistic_segments_100/500 fixtures
│   └── test_candidate_generation_benchmark.py  # CandidateGenerator throughput benchmarks
│
├── e2e/                                # Browser-level end-to-end tests
│   └── test_metric_dropdown_search.py
│
└── ui/                                 # Local UI test servers (not collected by pytest)
    ├── test_server.py
    └── unified_test_server.py
```

---

## Test Markers

Defined in `pyproject.toml` under `[tool.pytest.ini_options]`:

| Marker | Description | Default run |
|--------|-------------|-------------|
| `unit` | Fast, no external dependencies | Included |
| `integration` | Requires database connection | Included |
| `slow` | Slow-running tests | **Excluded** |
| `benchmark` | Performance benchmark tests | Included |
| `gold_standard` | GS regression tests — require baseline file and cached HTML | **Excluded** |
| `transcript_gold_standard` | Transcript GS regression tests | **Excluded** |
| `performance` | Performance tests | Included |
| `v2_parity` | Full V2 vs V1 extraction across all GS companies | **Excluded** |

The default `addopts` excludes: `not slow and not v2_parity and not gold_standard and not transcript_gold_standard`.

Run excluded markers explicitly:
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
pytest -m slow -v
pytest -m v2_parity -v
```

---

## Writing Tests

### Conventions

- Test files are named `test_*.py`. Test classes are named `Test*`. Test functions are named `test_*`.
- Unit tests under `tests/unit/` must not require `TEST_DATABASE_URL`. Use mocks for DB/HTTP/LLM calls.
- Integration tests under `tests/integration/` use the `clean_db` fixture (function-scoped) which truncates all tables before and after each test.
- Use `pytest.mark.integration` on integration test modules.

### Key fixtures

**From `tests/integration/conftest.py`:**

```python
# session-scoped — one DB adapter shared across all tests in a session
def test_db_adapter(test_db_url, _terminate_stale_connections): ...

# function-scoped — truncates all tables before and after each test
def clean_db(test_db_adapter): ...

# Filing/company factory helpers (not fixtures — call directly with db)
create_test_company(db, cik="0001234567", company_name="Test Corp")
create_test_company_and_filing(db, cik="...", accession_number="...", form_type="S-1")
create_test_candidate(db, filing_id=..., context_text="We have 10,000 customers.")
create_test_decision(db, candidate_id=..., decision="accept")
create_test_v2_document(db, filing_id=...)
create_test_v2_fact(db, filing_id=..., canonical_metric_id="cm_customers_period_end")
create_test_v2_decision(db, fact_id=..., decision="accept")
create_test_image_candidate(db, filing_id=...)
create_test_image_decision(db, image_candidate_id=...)

# Filing fixture metadata (loads from data/fixtures/*.json)
fixture_shopify    # Shopify S-1 2015
fixture_datadog    # Datadog F-1 2019
fixture_spac       # dMY SPAC 2020
mock_sec_client_with_fixtures   # MockSECClient preloaded with all three
```

**From `tests/performance/conftest.py`:**

```python
benchmark_db              # function-scoped clean DB for benchmarks
realistic_segments_100    # 100-segment filing with realistic metric text
realistic_segments_500    # 500-segment filing
db_with_1000_patterns     # DB seeded with 1000 synthetic learned patterns
```

**From `tests/unit/llm/conftest.py`:**

```python
mock_openai_response      # MagicMock with choices[0].message.content set
mock_openai_client        # Patches src.llm.openai_client.OpenAI
mock_tiktoken             # Patches src.llm.openai_client.tiktoken
disabled_cache_config     # CacheConfig(enabled=False)
```

### Typical unit test structure

```python
# tests/unit/extraction_v2/test_pipeline.py
from src.extraction_v2.models import EvidencePack, MetricFact, SourceLocator, Unit
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline, process_filing

def _create_valid_fact(confidence: float) -> MetricFact:
    return MetricFact(
        canonical_metric_id="cm_test_metric",
        value=100.0,
        value_raw="100",
        unit=Unit.COUNT,
        confidence=confidence,
        requires_review=True,
        source_locator=SourceLocator(segment_id="test-segment"),
        evidence_pack=EvidencePack(snippet_html="<span>test</span>"),
    )
```

```python
# tests/unit/review/test_candidate_generator.py
from src.review.candidate_generator import CandidateGenerator
from src.review.keyword_matching import METRIC_KEYWORDS, KeywordMatch
from src.review.models import ReviewCandidate
from src.review.number_parsing import NUMBER_REGEX, NumberMatch

class TestNumberRegex:
    def test_integer_with_commas(self):
        text = "We have 10,000 customers"
        matches = list(NUMBER_REGEX.finditer(text))
        assert matches[0].group("number") == "10,000"
```

```python
# tests/integration/extraction_v2/test_e2e_pipeline.py
from src.extraction_v2.persistence import V2PersistenceAdapter
from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline
from src.infra.db import DatabaseAdapter

pytestmark = pytest.mark.integration

@pytest.fixture(scope="module")
def db_adapter():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return DatabaseAdapter(url)
```

### Marking integration tests

```python
import pytest
pytestmark = pytest.mark.integration
```

Or on individual tests:
```python
@pytest.mark.integration
def test_db_upsert_is_idempotent(clean_db): ...
```

---

## Coverage Dashboard

Run `pytest --cov=src --cov-report=term-missing` to get current numbers. The global minimum is 75% (`fail_under = 75`). `src/extraction/` (V1, retired) is excluded from measurement via `omit` in `pyproject.toml`.

| Module | Notes |
|--------|-------|
| `src/extraction_v2/` | Production pipeline — highest test investment |
| `src/review/` | Strict mypy coverage, well-tested |
| `src/web/routes/` | Mix of unit (mocked DB) and integration tests |
| `src/infra/` | DB, pool, SEC client, HTTP client |
| `src/llm/` | Tested with mocked OpenAI client |
| `src/universe/` | Universe builder and classifier tests |
| `src/gold_standard/` | Baseline, validator, fresh extractor |

To check coverage for a specific module:

```bash
pytest --cov=src/extraction_v2 --cov-report=term-missing tests/unit/extraction_v2/
pytest --cov=src/review --cov-report=term-missing tests/unit/review/
```

---

## Gold Standard Validation

### What it is

The gold standard is a hand-labeled CSV (`data/gold_standard/golden_set_260407.csv`) of known metric extractions for a set of real filings. The baseline file (`data/gold_standard/baseline.json`) records precision/recall/F1 at the last accepted state. Regression tests fail CI if any of those scores drops below the baseline threshold.

### Baseline file location

```
data/gold_standard/baseline.json
```

### Modes

**Fresh mode** (recommended, no database required): Re-extracts from cached HTML files in `data/gold_standard/{Company_Name}/filing.html` on each run.

**DB mode**: Reads extraction results already stored in the test database.

### Running regression tests

```bash
# Standard regression check
pytest -m gold_standard --gold-standard-mode=fresh -v

# With 2% tolerance instead of 1% default
pytest -m gold_standard --gold-standard-mode=fresh --gold-standard-tolerance=0.02 -v

# Parallel workers (default 4)
pytest -m gold_standard --gold-standard-mode=fresh --gold-standard-workers=8 -v
```

### Updating the baseline

Run when extraction improvements intentionally raise the bar:

```bash
pytest -m gold_standard --gold-standard-mode=fresh --gold-standard-update-baseline -v
```

Or via script:

```bash
python3 scripts/validate_against_gold_standard.py \
    --all --mode fresh \
    --update-baseline \
    --baseline-path data/gold_standard/baseline.json
```

### What the tests check

Defined in `tests/integration/test_gold_standard_regression.py`:

- `test_overall_precision_above_baseline` — overall precision must not drop below baseline
- `test_overall_recall_above_baseline` — overall recall must not drop below baseline
- `test_overall_f1_above_baseline` — overall F1 must not drop below baseline
- `test_no_company_recall_regressions` — per-company recall must not drop on any single company

Tests skip gracefully if `data/gold_standard/baseline.json` does not exist.

### Transcript gold standard

Transcript baselines are stored in `data/spike_results/`:
- `transcript_baseline_tuning.json` — tuning split (default)
- `transcript_baseline_test.json` — held-out test split

```bash
pytest -m transcript_gold_standard --transcript-split=tuning -v
pytest -m transcript_gold_standard --transcript-update-baseline -v
```

### Presentation gold standard

```bash
pytest tests/unit/test_presentation_gold_standard.py -v
```

---

## Type Checking

`src/review/` is the only module with strict mypy enforcement:

```bash
mypy src/review/ --strict
```

The `pyproject.toml` overrides apply `disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`, and `no_implicit_reexport` to `src.review.*`.

All other modules use relaxed settings (`disallow_untyped_defs = false`). `src/infra/` and `src/extraction/` imports are skipped entirely (`follow_imports = "skip"`).

For a broader check without strict mode:

```bash
mypy src/
```

---

## Pre-Commit Checklist

Before committing changes that touch `src/`, `tests/`, `scripts/`, `config/`, `sql/`, or `pyproject.toml`:

```bash
pytest -x -q          # fast fail — stop on first failure
black src/ tests/      # format
ruff check src/ tests/ # lint
mypy src/review/ --strict  # type check (review module only)
```

Documentation-only or `.claude/`-only commits may skip lint and tests.
