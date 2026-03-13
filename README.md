# Customer Metrics Filings Analysis

**Version:** 2.7
**Status:** Production Ready
**Last Updated:** 2026-03-12

A system for systematically analyzing SEC filings to assess how companies disclose customer-related metrics.

## Project Overview

This project supports the Customer Metrics Accounting Standards Board (CMASB) initiative by:
- Discovering and classifying S-1/F-1 IPO filings from SEC EDGAR
- Extracting customer metrics, definitions, and methodologies
- Assessing disclosure quality and comparability
- Providing human-in-the-loop review for quality assurance
- Demonstrating the need for standardized customer metrics disclosure

## Current Status

### V2 Pipeline (Primary)

| Component | Status | Notes |
|-----------|--------|-------|
| Ingestion (lxml) | ✅ Complete | 10x faster than V1 |
| Section Classification | ✅ Complete | |
| Table Reconstruction | ✅ Complete | header_path/stub_path binding |
| Image Triage + OCR | ✅ Complete | Chart extraction |
| Candidate Generation | ✅ Complete | |
| Value Binding | ✅ Complete | Stable XPath locators |
| False Positive Filter | ✅ Complete | |
| Period Inference | ✅ Complete | |
| Fact Construction | ✅ Complete | EvidencePack with highlighted HTML |
| Definition Extraction | ✅ Complete | Stage 9.5 |
| Deduplication | ✅ Complete | |
| Validation + Persistence | ✅ Complete | |
| Batch Runner | ✅ Complete | `scripts/batch_v2_extraction.py` |

**Gold Standard (V2):** Precision=95.0%, Recall=83.5%, F1=88.9%

### Infrastructure

| Component | Status | Test Coverage |
|-----------|--------|---------------|
| Universe Builder | ✅ Complete | 93% |
| Filing Fetcher | ✅ Complete | 94% |
| LLM Integration | ✅ Complete | 88% |
| Human Review System | ✅ Complete | 95-100% |

**Overall:** 87% overall test coverage (4,765 tests)

**Corpus:** 7,304 in-scope S-1/F-1 filings identified (2015-2025)

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL (or use Docker)

### Installation

```bash
# Clone and install dependencies
git clone <repository-url>
cd filings_reviewer
uv sync --all-extras

# Configure environment (see .env.template)
cp .env.template .env
# Edit .env with your database credentials
```

### Docker Setup (Recommended)

```bash
# Start PostgreSQL on port 5433
docker compose up -d

# Connection string
DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test
```

### Database Setup

```bash
# Apply database migrations (creates required tables)
python3 scripts/apply_migrations.py
```

### Running Tests

```bash
# All tests
pytest -v

# With coverage
pytest --cov=src --cov-report=html

# Unit tests only (fast)
pytest tests/unit/ -v

# Integration tests (requires database)
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test pytest tests/integration/ -v
```

### Running the V2 Pipeline

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

config = PipelineConfig(enable_image_extraction=True, min_confidence_auto_accept=0.90)
pipeline = V2Pipeline(config=config)
result = pipeline.process(html_path=Path("filing.html"), filing_id=123)

print(f"Extracted {result.fact_count} facts in {result.total_duration_ms}ms")
for fact in result.facts:
    print(f"  {fact.canonical_metric_id}: {fact.value} ({fact.confidence:.1%})")
```

For bulk extraction across many filings, use `scripts/batch_v2_extraction.py`. See [V2 Migration Guide](docs/V2_MIGRATION_GUIDE.md) for full details.

## Architecture

```
src/
├── infra/          # Database, SEC API client, validation
├── universe/       # Filing discovery and classification
├── filing_fetcher/ # Document retrieval and caching
├── extraction_v2/  # V2 extraction pipeline (primary)
├── review/         # Human-in-the-loop review system
├── web/            # Flask web application
├── llm/            # OpenAI GPT-4o-mini integration
└── gold_standard/  # Gold standard validation
```

**V2 Pipeline** (primary, 13 stages + Phase B enhancements):
```
Ingestion → SectionClassification → TableReconstruction → ImageTriage
    → OCR/Chart → CandidateGeneration → ValueBinding → FalsePositiveFilter
    → PeriodInference → FactConstruction → DefinitionExtraction
    → Deduplication → Validation → Persistence
```
See [V2 Migration Guide](docs/V2_MIGRATION_GUIDE.md) for details.

## Documentation

Comprehensive documentation is available in the `docs/` directory:

| Category | Document | Description |
|----------|----------|-------------|
| **Start Here** | [docs/README.md](docs/README.md) | Documentation index and quick links |
| **Architecture** | [docs/architecture/system-overview.md](docs/architecture/system-overview.md) | System architecture and components |
| | [docs/architecture/extraction-pipeline.md](docs/architecture/extraction-pipeline.md) | Extraction pipeline details |
| | [docs/architecture/data-model.md](docs/architecture/data-model.md) | Database schema and tables |
| | [docs/architecture/llm-integration.md](docs/architecture/llm-integration.md) | OpenAI integration |
| **Development** | [docs/development/metrics-taxonomy.md](docs/development/metrics-taxonomy.md) | Canonical metric definitions |
| | [docs/development/quality-model.md](docs/development/quality-model.md) | Quality scoring (0-3 scale) |
| | [docs/development/testing.md](docs/development/testing.md) | Test strategy and coverage |
| **Operations** | [docs/operations/setup-guide.md](docs/operations/setup-guide.md) | Environment setup |
| **Review System** | [docs/HUMAN_REVIEW_SYSTEM.md](docs/HUMAN_REVIEW_SYSTEM.md) | Human review implementation |

## Project Structure

```
filings_reviewer/
├── src/                    # Source code
│   ├── infra/             # Infrastructure (db.py, sec_client.py)
│   ├── universe/          # Filing discovery
│   ├── filing_fetcher/    # Document retrieval
│   ├── extraction_v2/     # V2 extraction pipeline (primary)
│   ├── review/            # Human review system
│   ├── web/               # Flask application
│   ├── llm/               # LLM integration
│   └── gold_standard/     # Gold standard validation
├── tests/                  # Test suite
│   ├── unit/              # Fast unit tests
│   ├── integration/       # Database integration tests
│   └── performance/       # Performance benchmarks
├── docs/                   # Documentation
│   ├── architecture/      # Technical design
│   ├── development/       # Development guides
│   ├── operations/        # Operations guides
│   ├── requirements/      # Business requirements
│   └── archive/           # Historical documents
├── sql/                    # Database schema (00-15)
├── scripts/               # Utility scripts
├── CLAUDE.md              # Claude Code instructions
└── docker-compose.yml     # Docker configuration
```

## Key Design Decisions

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to its source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives
5. **Human-in-the-loop**: Review system for quality validation and pattern learning

## Development

```bash
# Format code
ruff format src/ tests/

# Lint
ruff check src/ tests/

# Type checking (review module)
mypy src/review/ --strict
```

## Contributing

This is a research project for CMASB. For questions or contributions, please contact the project owner.

**Owner:** Rob Markey
**Organization:** Customer Metrics Accounting Standards Board (CMASB)

## License

See LICENSE file.
