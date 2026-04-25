# CMASB Disclosures Review

**Version:** 2.8
**Status:** In process (presence-pivot mid-rollout)
**Last Updated:** 2026-04-25

A system for systematically analyzing SEC filings to assess how companies disclose customer-related metrics. As of 2026-04, the system's primary output is **metric presence** — a per-(filing, metric) signal aggregated from text, charts, and metric definitions, with full provenance back to source segments and images. Per-value extraction continues as advisory evidence; CMASB-required values are entered manually via `POST /api/v2/missed-metric`.

> **Pivot status (2026-04-25):** Chart-presence pivot is **live** (#86, 2026-04-23). Text-presence PR1 **landed** (#182, 2026-04-16). PR2 (gold-standard derivation + Tier-1 gate flip), PR3 (reviewer UI for text presence), PR4–PR5 are pending. Known gaps: legacy-097 (residual chart facts), legacy-098 (validator `presence_f1` not yet populated). See [`docs/operations/text-pipeline-presence-pivot-plan.md`](docs/operations/text-pipeline-presence-pivot-plan.md) for the rollout plan and authoritative interface contract.

## Project Overview

This project supports the Customer Metrics Accounting Standards Board (CMASB) initiative by:
- Discovering and classifying S-1/F-1 IPO filings from SEC EDGAR
- **Detecting metric presence** in filings (text + charts + definitions) and tracking provenance from each presence claim back to source evidence
- Capturing values as advisory evidence and supporting manual value entry where CMASB needs them
- Extracting metric definitions and methodologies
- Assessing disclosure quality and comparability
- Providing human-in-the-loop review (image presence confirmations; text-fact decisions; per-metric skip/undo)
- Demonstrating the need for standardized customer metrics disclosure

## Current Status

| Component | Status |
|-----------|--------|
| Universe Builder | Complete |
| Filing Fetcher | Complete |
| V2 Extraction Pipeline (incl. `MetricPresenceStage`) | Complete |
| Text-presence persistence (`v2_text_metric_presence`) | PR1 landed (#182); PR2–PR5 pending |
| Chart-presence pivot (`v2_image_assets.detected_metrics`, `v2_image_metric_confirmations`) | Live (#86, 2026-04-23) |
| Vision metric-classifier (`ENABLE_METRIC_CLASSIFY`, `v2_image_classifications`) | Live |
| LLM & Vision Integration | Complete |
| Gold Standard Validation (presence-F1) | In progress (legacy-098 open) |
| Unified Review UI (`/v2/review/<filing_id>`) | Complete; text-presence reviewer surface lands in PR3 |
| Manual value entry (`POST /api/v2/missed-metric`) | Live |
| Transcripts & Presentations | Complete (beyond SEC) |

**Coverage target:** 80% overall minimum (enforced per CLAUDE.md).

**Corpus:** ~7,300 in-scope S-1/F-1 filings (2015-2025), plus earnings call transcripts and investor presentations.

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
├── extraction_v2/  # V2 metric extraction pipeline (segmentation, candidates, binding, FP filter)
├── review/         # Human-in-the-loop review system
├── web/            # Flask web application
├── llm/            # OpenAI + vision client integration
├── gold_standard/  # Gold standard validation framework
└── shared/         # Shared utilities across pipeline stages
```

**Pipeline Flow (V2):**
```
UniverseBuilder → FilingFetcher → V2Pipeline → V2PersistenceAdapter → Database
```

**V2 pipeline stages** (in `src/extraction_v2/stages/`): ingestion, section_classification, table_reconstruction, image_triage, ocr_extraction, image_classify (Vision metric-classifier, gated by `ENABLE_METRIC_CLASSIFY`), `CandidateGenerationStage`, `ValueBindingStage`, false_positive_filter, period_inference, fact_construction, `DefinitionExtractionStage`, deduplication, validation, chart_fact_bridge (chart **presence** signals to `v2_image_assets.detected_metrics`, no per-value chart facts), and **`MetricPresenceStage`** (final stage; aggregates text facts, chart detections, and definitions into per-`(doc_id, canonical_metric_id)` rows in `v2_text_metric_presence`).

## Documentation

Comprehensive documentation is available in the `docs/` directory:

| Category | Document | Description |
|----------|----------|-------------|
| **Start Here** | [docs/README.md](docs/README.md) | Documentation index and quick links |
| **Pivot plan** | [docs/operations/text-pipeline-presence-pivot-plan.md](docs/operations/text-pipeline-presence-pivot-plan.md) | Authoritative rollout plan + PR1 interface contract for downstream PRs |
| **Architecture** | [docs/architecture/system-overview.md](docs/architecture/system-overview.md) | System architecture and components |
| | [docs/architecture/extraction-pipeline.md](docs/architecture/extraction-pipeline.md) | Extraction pipeline details (incl. `MetricPresenceStage`) |
| | [docs/architecture/data-model.md](docs/architecture/data-model.md) | Database schema and tables (incl. `v2_text_metric_presence`, `v2_image_metric_confirmations`, `v2_image_classifications`) |
| | [docs/architecture/llm-integration.md](docs/architecture/llm-integration.md) | OpenAI + Vision metric-classifier integration |
| **Development** | [docs/development/metrics-taxonomy.md](docs/development/metrics-taxonomy.md) | Canonical metric definitions |
| | [docs/development/quality-model.md](docs/development/quality-model.md) | Quality scoring (presence-F1 primary; value-correctness advisory under the pivot) |
| | [docs/development/testing.md](docs/development/testing.md) | Test strategy and coverage |
| **Operations** | [docs/operations/setup-guide.md](docs/operations/setup-guide.md) | Environment setup |
| **Review System** | [docs/HUMAN_REVIEW_SYSTEM.md](docs/HUMAN_REVIEW_SYSTEM.md) | DEPRECATED — V1 review system; see pivot plan for the active V2 unified review UI and image-presence confirmations |

## Project Structure

```
filings_reviewer/
├── src/                    # Source code
│   ├── infra/             # Infrastructure (db.py, sec_client.py)
│   ├── universe/          # Filing discovery
│   ├── filing_fetcher/    # Document retrieval
│   ├── extraction_v2/     # V2 extraction pipeline
│   ├── review/            # Human review system
│   ├── web/               # Flask application
│   ├── llm/               # LLM + vision integration
│   ├── gold_standard/     # Gold standard validation
│   └── shared/            # Shared utilities
├── tests/                  # Test suite
│   ├── unit/              # Fast unit tests
│   ├── integration/       # Database integration tests
│   └── performance/       # Performance benchmarks
├── docs/                   # Documentation
│   ├── analysis/          # Task outputs, audits, evaluations
│   ├── architecture/      # Technical design
│   ├── development/       # Development guides
│   ├── operations/        # Operations guides
│   ├── requirements/      # Business requirements
│   └── archive/           # Historical documents
├── sql/                    # Database schema — legacy integer-prefix range 00-47 frozen; new migrations use timestamp filenames (see `.claude/rules/sql.md`)
├── scripts/               # Utility scripts
├── CLAUDE.md              # Claude Code instructions
└── docker-compose.yml     # Docker configuration
```

## Key Design Decisions

1. **Presence-first, values advisory**: The primary scoring surface is per-`(doc_id, canonical_metric_id)` presence — aggregated from text facts, chart detections, the Vision metric-classifier, and metric definitions. Per-value extraction continues as advisory evidence; CMASB-required values are entered manually via `POST /api/v2/missed-metric`. See [`docs/operations/text-pipeline-presence-pivot-plan.md`](docs/operations/text-pipeline-presence-pivot-plan.md).
2. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
3. **Provenance tracking**: Every presence row points back to its evidence — `evidence_segment_ids` and `advisory_fact_ids` (JSONB arrays on `v2_text_metric_presence`) for text; `v2_image_metric_confirmations` joined to `v2_image_assets` for charts; `v2_image_classifications` for the Vision-API audit trail. The `advisory_*` columns are non-FK pointers, allowing facts to be re-extracted (`force=True`) without cascading to presence.
4. **Idempotent operations**: Re-running any stage is safe (upserts). Presence rows are upserted on `(doc_id, canonical_metric_id)`; `updated_at` advances on re-extraction. Reviewer-decision tables are append-only/decision-only; the audit trail lives in `v2_audit_log` + the decision tables, not in presence-row history.
5. **Conservative classification**: "Require BOTH" signals to minimize false positives. Chart signals are presence-only — no per-value chart facts emitted at extraction time.
6. **Human-in-the-loop**: Unified review UI at `/v2/review/<filing_id>` surfaces text facts (advisory) and per-image presence detections; reviewers confirm via `v2_image_metric_confirmations` (accept / reject / correct / add / skip). Reviewed-filing guard prevents silent CASCADE-destruction of reviewer work.

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
