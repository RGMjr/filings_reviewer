# Customer Metrics Filings Analysis

A system for systematically analyzing SEC filings to assess how companies disclose customer-related metrics.

## Project Overview

This project supports the Customer Metrics Accounting Standards Board (CMASB) initiative by:
- Discovering and classifying S-1 IPO filings
- Extracting customer metrics from SEC filings
- Assessing disclosure quality and comparability
- Demonstrating the need for standardized customer metrics disclosure

## Current Status

| Phase | Component | Status |
|-------|-----------|--------|
| 1 | UniverseBuilder | ✅ Complete (7,304 in-scope filings identified) |
| 2a | FilingFetcher | ✅ Complete |
| 2b | Extraction Pipeline | ✅ Complete (rule-based) |
| 3 | LLM Integration | ✅ Infrastructure Complete (GPT-4o-mini integrated) |
| 4 | Production Extraction | 🟡 In Progress (CMASB Phase 1B deployed) |

**Test Coverage:** 68% overall (323 tests passing)
- Core modules: ~82% (target met)
- LLM modules: 0% (manual testing only)
- Target: 75% minimum (below due to untested LLM code)

For detailed progress tracking and sprint planning, see **[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)**.

## Installation

### Prerequisites
- Python 3.11+
- PostgreSQL database

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd filings_reviewer
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**

   Create a `.env` file:
   ```bash
   DATABASE_URL=postgresql://user:password@localhost/filings_analysis
   ```

4. **Create database schema**
   ```bash
   # Create database
   createdb filings_analysis

   # Run schema creation
   psql -d filings_analysis -f sql/01_create_schema.sql
   ```

## Usage

### Example: Building Universe with Mock Data

```python
from src.infra.db import DatabaseAdapter
from src.infra.sec_client import MockSECClient, FilingMetadata
from src.universe.universe_builder import UniverseBuilder

# Set up database
db = DatabaseAdapter("postgresql://localhost/filings_analysis")

# Create sample filings
sample_filings = [
    FilingMetadata(
        cik="0001419612",
        company_name="Shopify Inc.",
        form_type="S-1",
        filing_date="2015-04-14",
        accession_number="0001193125-15-140667",
        primary_doc_url="https://www.sec.gov/...",
        ticker="SHOP",
    ),
]

# Initialize and run
sec_client = MockSECClient(mock_filings=sample_filings)
builder = UniverseBuilder(sec_client=sec_client, db=db)

in_scope_count = builder.build_universe("2015-01-01", "2025-12-31")
print(f"In-scope filings: {in_scope_count}")

# Get statistics
stats = builder.get_coverage_stats()
print(stats)
```

### Running the Example Script

```bash
# With mock data (recommended for testing)
python examples/build_universe_example.py --mode mock

# With real SEC API (requires proper user agent)
python examples/build_universe_example.py --mode real
```

## Testing

### Unit Tests

Run fast tests without external dependencies:

```bash
# All unit tests
pytest tests/unit/ -v

# Specific test file
pytest tests/unit/universe/test_classifiers.py -v

# With coverage
pytest tests/unit/ --cov=src --cov-report=html
```

Coverage report will be in `htmlcov/index.html`.

### Integration Tests

Integration tests require PostgreSQL. You can run them against the Dockerized Postgres instance defined in `docker-compose.yml`.
See [Integration Test README](tests/integration/README.md) for setup.

**Setup (Docker-based):**
```bash
# 1) Start Postgres via Docker
docker compose up -d

# 2) Point tests at the Docker test database
#    (user: dev, password: dev, port: 5433)
export TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test

# 3) Run integration tests
pytest tests/integration/ -v

# Specific integration test
pytest tests/integration/universe/test_universe_builder_integration.py -v

Notes:
- The test database `filings_analysis_test` is created and initialized automatically
  from the SQL files in the `sql/` directory when the Docker container is first started.
- You do not need to install PostgreSQL locally with Homebrew or run `scripts/setup_test_db.sh`
  when using the Docker setup.
- Integration tests will still be skipped if `TEST_DATABASE_URL` is not set or the database is unreachable.
```

### Run All Tests

```bash
pytest -v
```

**Note:** Integration tests will be skipped if PostgreSQL is not available.

## Project Structure

```
filings_reviewer/
├── docs/                          # Design documentation
│   ├── 01_ANALYTIC_REQUIREMENTS.md
│   ├── 02_METRIC_TAXONOMY_AND_DEFINITIONS.md
│   ├── 03_DATA_MODEL_SPEC.md
│   ├── 04_SYSTEM_ARCHITECTURE.md
│   ├── 05_COMPONENT_INTERFACE_SPECS.md
│   ├── 06_QA_AND_QUALITY_MODEL.md
│   ├── 07_TEST_STRATEGY_AND_FIX_PROCESS.md
│   ├── 08_DELIVERY_PLAN_AND_PHASES.md
│   └── 09_DATA_DICTIONARY.md
│
├── src/                           # Source code
│   ├── infra/                    # Infrastructure
│   │   ├── db.py                 # Database adapter
│   │   └── sec_client.py         # SEC EDGAR client
│   │
│   └── universe/                 # UniverseBuilder component
│       ├── classifiers.py        # Classification logic
│       └── universe_builder.py   # Main component
│
├── tests/                         # Tests
│   ├── unit/
│   │   └── universe/
│   │       ├── test_classifiers.py
│   │       └── test_universe_builder.py
│   │
│   └── integration/              # (To be implemented)
│
├── sql/                          # Database schemas
│   └── 01_create_schema.sql
│
├── examples/                     # Example scripts
│   └── build_universe_example.py
│
├── requirements.txt              # Python dependencies
├── pytest.ini                    # Pytest configuration
└── README.md                     # This file
```

## Architecture

### Components

| Component | Status | Description |
|-----------|--------|-------------|
| UniverseBuilder | ✅ | Discovers S-1/F-1 filings, classifies SPACs and first-time issuers |
| FilingFetcher | ✅ | Downloads and caches filing HTML from SEC EDGAR |
| HTMLSegmenter | ✅ | Splits filings into paragraphs, tables, sections |
| MetricClassifier | ✅ | Identifies segments containing customer metrics |
| ValueExtractor | ✅ | Extracts numeric values from segments |
| DefinitionExtractor | ✅ | Extracts metric definitions and methodologies |
| QualityScorer | ✅ | Scores disclosure quality (0-3 scale) |
| LLM Integration | 🔲 | Enhanced extraction using OpenAI (planned) |

See [docs/04_SYSTEM_ARCHITECTURE.md](docs/04_SYSTEM_ARCHITECTURE.md) for detailed architecture diagrams.

### Data Model

**companies**
- Issuer metadata (CIK, name, ticker, industry)

**filings**
- Filing documents with classification flags:
  - `is_in_scope_phase1`: In Phase 1 universe?
  - `is_first_time_issuer`: First-time public equity issuer?
  - `is_spac`: SPAC (excluded from Phase 1)?
  - `offering_type`: Primary, secondary, or mixed?
  - `processing_status`: Current pipeline status

## Classification Logic

### SPAC Detection
Detects SPACs by:
- Company name patterns: "Acquisition Corp", "Blank Check", "SPAC"
- Filing text keywords: "blank check company", "special purpose acquisition"

### First-Time Issuer
- Checks database for prior S-1/F-1 filings for the same CIK
- First filing for a CIK = first-time issuer

### Offering Type
- Primary: Company issuing new shares
- Secondary: Existing shareholders selling shares
- Mixed: Both primary and secondary shares

### Phase 1 Scope
In scope if:
- ✅ Form type is S-1 or F-1 (including amendments)
- ✅ First-time issuer
- ✅ Not a SPAC
- ✅ Not secondary-only offering

## Idempotency

All operations are idempotent:
- Running `build_universe` multiple times with the same date range is safe
- Companies and filings are upserted (INSERT ... ON CONFLICT UPDATE)
- Re-running does not create duplicates

## Known Limitations

1. **Rule-based extraction**: Current extraction uses pattern matching. LLM integration (Phase 3) will improve accuracy for complex disclosures.

2. **SPAC Detection**: Heuristic-based. Uses conservative "require BOTH" signals (SIC code + name pattern) to minimize false positives.

3. **No real-time updates**: System processes filings in batch mode, not streaming.

## Development Workflow

Common commands via Makefile:

```bash
make help           # Show all available commands
make test           # Run tests
make coverage       # Run tests with coverage report
make lint           # Run linter (ruff)
make format         # Format code (black)
make docs-check     # Verify documentation is in sync with code
```

**Git hooks** (install once with `make hooks-install`):
- Pre-commit hook validates docs freshness and warns about potential issues

**CI/CD**: GitHub Actions automatically validates documentation on PRs and updates coverage on merge to main.

## Documentation

**Project tracking:**
- [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) - Sprint tracking, progress, and roadmap
- [PHASE1_UNIVERSE_BUILD_REPORT.md](PHASE1_UNIVERSE_BUILD_REPORT.md) - Universe statistics and analysis

**Design documentation** (in `docs/`):
- [Analytic Requirements](docs/01_ANALYTIC_REQUIREMENTS.md)
- [Metric Taxonomy](docs/02_METRIC_TAXONOMY_AND_DEFINITIONS.md)
- [Data Model](docs/03_DATA_MODEL_SPEC.md)
- [System Architecture](docs/04_SYSTEM_ARCHITECTURE.md) - Includes architecture diagram
- [Component Interfaces](docs/05_COMPONENT_INTERFACE_SPECS.md)
- [Quality Model](docs/06_QA_AND_QUALITY_MODEL.md)
- [Test Strategy](docs/07_TEST_STRATEGY_AND_FIX_PROCESS.md)

## Contributing

This is a research project for CMASB. For questions or contributions, please contact the project owner.

## License

See LICENSE file.
