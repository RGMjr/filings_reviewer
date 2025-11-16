# Customer Metrics Filings Analysis

A system for systematically analyzing SEC filings to assess how companies disclose customer-related metrics.

## Project Overview

This project supports the Customer Metrics Accounting Standards Board (CMASB) initiative by:
- Discovering and classifying S-1 IPO filings
- Extracting customer metrics from SEC filings
- Assessing disclosure quality and comparability
- Demonstrating the need for standardized customer metrics disclosure

## Current Status: UniverseBuilder v0.1

The first component, **UniverseBuilder**, is now implemented. It discovers and classifies S-1/F-1 filings for Phase 1 analysis.

### What's Implemented

✅ **Database Schema**
- `companies` table: Issuer metadata
- `filings` table: SEC filing documents with classification flags

✅ **SEC Client Abstraction**
- Interface for querying EDGAR
- Mock client for testing
- Rate limiting and polite access

✅ **Classification Logic**
- SPAC detection (by company name and filing text)
- First-time issuer detection
- Offering type classification (primary/secondary/mixed)
- Phase 1 scope determination

✅ **UniverseBuilder Component**
- Discovers filings in date ranges
- Classifies and stores in database
- Idempotent operations
- Coverage statistics

✅ **Tests**
- Unit tests for classification logic
- Unit tests for UniverseBuilder
- Example scripts

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

### Run All Tests

```bash
pytest
```

### Run Specific Test Suites

```bash
# Unit tests only
pytest tests/unit/

# Classification tests
pytest tests/unit/universe/test_classifiers.py

# UniverseBuilder tests
pytest tests/unit/universe/test_universe_builder.py
```

### Run with Coverage

```bash
pytest --cov=src --cov-report=html
```

Coverage report will be in `htmlcov/index.html`.

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

**UniverseBuilder** (✅ Implemented)
- Discovers S-1/F-1 filings from EDGAR
- Classifies filings (SPAC, first-time issuer, offering type)
- Populates `companies` and `filings` tables

**Future Components** (Planned)
- FilingFetcher: Download and cache raw filings
- Segmenter: Split filings into structured segments
- TableExtractor: Extract metrics from tables
- TextMetricExtractor: Extract metrics from narrative text
- QAEngine: Assess disclosure quality

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

## Known Limitations (v0.1)

1. **SEC Client**: Simplified implementation. For production, use SEC RSS feeds or bulk downloads for better performance.

2. **Offering Type Classification**: Without fetching full filing text, offering type may be `uncertain` and require manual review.

3. **SPAC Detection**: Heuristic-based. Some edge cases may need manual review.

4. **Industry Classification**: Stubbed in v0.1. Future versions will add SIC/GICS codes.

## Next Steps

Per the GitHub issue roadmap:

1. **Integration Tests**: Add tests using cached real EDGAR fixtures
2. **SEC Client Enhancement**: Implement RSS feed or bulk download approach
3. **Filing Text Fetching**: Enhance offering type classification
4. **Manual Review Workflow**: Add tooling for uncertain classifications

## Documentation

Full design documentation is in the `docs/` directory:

- [Analytic Requirements](docs/01_ANALYTIC_REQUIREMENTS.md)
- [Metric Taxonomy](docs/02_METRIC_TAXONOMY_AND_DEFINITIONS.md)
- [Data Model](docs/03_DATA_MODEL_SPEC.md)
- [System Architecture](docs/04_SYSTEM_ARCHITECTURE.md)
- [Component Interfaces](docs/05_COMPONENT_INTERFACE_SPECS.md)
- [Quality Model](docs/06_QA_AND_QUALITY_MODEL.md)
- [Test Strategy](docs/07_TEST_STRATEGY_AND_FIX_PROCESS.md)

## Contributing

This is a research project for CMASB. For questions or contributions, please contact the project owner.

## License

See LICENSE file.
