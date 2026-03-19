# Customer Metrics Filings Analysis

**Version:** 2.2
**Status:** In process
**Last Updated:** 2026-03-15

A system for systematically analyzing SEC filings to assess how companies disclose customer-related metrics.

## Project Overview

This project supports the Customer Metrics Accounting Standards Board (CMASB) initiative by:
- Discovering and classifying S-1/F-1 IPO filings from SEC EDGAR
- Extracting customer metrics, definitions, and methodologies
- Assessing disclosure quality and comparability
- Providing human-in-the-loop review for quality assurance
- Demonstrating the need for standardized customer metrics disclosure

## Current Status

| Component | Status | Test Coverage |
|-----------|--------|---------------|
| Universe Builder | ✅ Complete | 93% |
| Filing Fetcher | ✅ Complete | 94% |
| HTML Segmenter | ✅ Complete | 85% |
| Metric Classifier | ✅ Complete | 98% |
| Value Extractor | ✅ Complete | 66% |
| Definition Extractor | ✅ Complete | 89% |
| Quality Scorer | ✅ Complete | 100% |
| Extraction Pipeline | ✅ Complete | 91% |
| LLM Integration | ✅ Complete | 88% |
| Human Review System | ✅ Complete | 95-100% |

**Overall:** 87% overall test coverage (3,150+ tests)

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
pip install -r requirements.txt

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

## Architecture

```
src/
├── infra/          # Database, SEC API client, validation
├── universe/       # Filing discovery and classification
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction pipeline
├── review/         # Human-in-the-loop review system
├── web/            # Flask web application
└── llm/            # OpenAI GPT-4o-mini integration
```

**Pipeline Flow:**
```
UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier
                                        ↓
                              ValueExtractor + DefinitionExtractor
                                        ↓
                                  QualityScorer → Database
```

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
│   ├── extraction/        # Metric extraction
│   ├── review/            # Human review system
│   ├── web/               # Flask application
│   └── llm/               # LLM integration
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
├── sql/                    # Database schema (01-07)
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
black src/ tests/

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
