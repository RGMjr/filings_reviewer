# Customer Metrics Filings Analysis - Documentation

**Project:** SEC Filings Customer Metrics Extraction System
**Version:** 2.4
**Status:** Production Ready
**Last Updated:** 2026-03-22

---

## Overview

This system analyzes SEC S-1/F-1 filings to assess how companies disclose customer-related metrics, supporting the Customer Metrics Accounting Standards Board (CMASB) initiative to establish standardized customer metrics disclosure practices.

### Quick Links

| For... | Start Here |
|--------|------------|
| **New developers** | [System Architecture](architecture/system-overview.md) |
| **Analysts/Researchers** | [Analytic Requirements](requirements/analytic-requirements.md) |
| **Project managers** | [System Architecture](architecture/system-overview.md) → Success Criteria |
| **Quality assurance** | [Testing Strategy](development/testing.md) → [Quality Model](development/quality-model.md) |
| **Data users** | [Data Model](architecture/data-model.md) → Analysis Views |

---

## Documentation Structure

### Architecture (Technical Design)

Core system architecture and design specifications.

| Document | Description | Audience |
|----------|-------------|----------|
| **[system-overview.md](architecture/system-overview.md)** | Complete system architecture, components, data flow | Everyone - START HERE |
| **[data-model.md](architecture/data-model.md)** | Database schema, table specifications, relationships | Developers, Analysts |
| **[extraction-pipeline.md](architecture/extraction-pipeline.md)** | Extraction pipeline stages, components, interfaces | Developers |
| **[llm-integration.md](architecture/llm-integration.md)** | OpenAI GPT-4o-mini integration, costs, prompts | Developers |

### Requirements (Business Needs)

Business requirements and metric definitions.

| Document | Description | Audience |
|----------|-------------|----------|
| **[analytic-requirements.md](requirements/analytic-requirements.md)** | Core business requirements, research questions, hypotheses | All stakeholders |
| **[CMASB_PRIORITY_METRICS_PHASE1.md](requirements/CMASB_PRIORITY_METRICS_PHASE1.md)** | Priority metrics for initial analysis | Analysts, PMs |

### Development (Implementation Guidance)

Guidance for developers implementing or extending the system.

| Document | Description | Audience |
|----------|-------------|----------|
| **[metrics-taxonomy.md](development/metrics-taxonomy.md)** | Canonical metric definitions and taxonomy | Developers, Analysts |
| **[metric-lifecycle-process.md](development/metric-lifecycle-process.md)** | Adding, deprecating, and removing metrics | Developers |
| **[quality-model.md](development/quality-model.md)** | Quality scoring framework (0-3 scale) | Developers, QA |
| **[testing.md](development/testing.md)** | Test strategy, coverage requirements | Developers, QA |

### Operations (Running the System)

Instructions for setting up, running, and maintaining the system.

| Document | Description | Audience |
|----------|-------------|----------|
| **[setup-guide.md](operations/setup-guide.md)** | Environment setup, dependencies, configuration | Developers, DevOps |
| **[cloud-deployment-runbook.md](operations/cloud-deployment-runbook.md)** ⭐ | **Render + Neon DB: start command, env vars, migrations, troubleshooting** | DevOps |
| **[deployment-guide.md](operations/deployment-guide.md)** | Legacy deployment guide (local/batch processing era) | Archive |
| **[extraction-runbook.md](operations/extraction-runbook.md)** ⭐ | **Re-extraction, re-segmentation, candidate regeneration** | Developers, DevOps |

### Human Review System (✅ COMPLETE - Production Ready)

Human-in-the-loop system for validating and improving extraction quality.

| Document | Description | Audience |
|----------|-------------|----------|
| **[HUMAN_REVIEW_SYSTEM.md](HUMAN_REVIEW_SYSTEM.md)** | System design, usage, configuration | Developers |

### Reference Plans

Completed and in-progress improvement plans for reference.

| Document | Description | Audience |
|----------|-------------|----------|
| **[GOLDMINE_REMEDIATION_PLAN.md](GOLDMINE_REMEDIATION_PLAN.md)** | ✅ CLOSED — All 18 tasks complete (80% recall, 95% precision) | Developers |
| **[HUMAN_REVIEW_VALIDATION_PLAN.md](HUMAN_REVIEW_VALIDATION_PLAN.md)** | ✅ CLOSED — All 6 HRV tasks complete | Developers |
| **[PROJECT_TASK_INVENTORY.md](PROJECT_TASK_INVENTORY.md)** | Active task inventory across all workstreams | Developers |
| **[analysis/GR-FINAL_VALIDATION.md](analysis/GR-FINAL_VALIDATION.md)** | **Final validation report: 80% recall, 95% precision** | Everyone |
| **[PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md)** | Performance benchmarks and profiling | Developers |
| **[KNOWN_ISSUES.md](KNOWN_ISSUES.md)** | Known issues and limitations | Developers |

### Archive (Historical Reference)

Historical documents for reference only. Not part of current operations.

| Category | Contents |
|----------|----------|
| **[archive/improvement-plans-completed/](archive/improvement-plans-completed/)** | Completed improvement plans |
| **[archive/historical/](archive/historical/)** | Historical process documentation and task inventory |
| **[archive/workstreams/](archive/workstreams/)** | Legacy workstream documentation |

### Additional Documentation Directories

Task output and reference documents organized by type.

| Directory | Description |
|-----------|-------------|
| **[completion/](completion/)** | Task completion summary reports (DUP-2, HRV-16, IMG-1-1, IMG-1-2, etc.) |
| **[investigation/](investigation/)** | Deep-dive investigation reports on extraction failures and edge cases |
| **[reports/](reports/)** | Metric consistency audits, chart extraction results, and validation reports |
| **[research/](research/)** | Chart extraction research and GPT-4o vision validation results |

### Operational Templates (Worker Prompts)

Templates and generators for structured task execution via Claude Code.

| File | Description |
|------|-------------|
| **[WORKER_PROMPT_GENERATOR.md](WORKER_PROMPT_GENERATOR.md)** | Meta-prompt for generating new worker prompts using Claude Code headless mode |
| **[WORKER_PROMPT_RALPH.md](WORKER_PROMPT_RALPH.md)** | Streamlined template for autonomous Ralph Loop task execution |
| **[WORKER_PROMPT_TEMPLATE.md](WORKER_PROMPT_TEMPLATE.md)** | Full worker prompt template (v2.6) for M/L/XL tasks (15 min – 5 hours) |
| **[WORKER_PROMPT_TEMPLATE_LITE.md](WORKER_PROMPT_TEMPLATE_LITE.md)** | Lightweight template for XS/S tasks under 2 hours (bug fixes, minor changes) |

---

## Key System Characteristics

### Scale & Scope

- **Corpus Size:** 7,304 in-scope S-1/F-1 filings (2015-2025)
- **Processing Time:** ~9-17 seconds per filing
- **Expected Runtime:** 2-5 days for full corpus (with parallelization)
- **Database:** PostgreSQL with 7 core tables

### Technology Stack

- **Language:** Python 3.11+
- **Database:** PostgreSQL (via psycopg3)
- **LLM:** OpenAI GPT-4o-mini
- **Parsing:** BeautifulSoup4, lxml
- **Testing:** pytest (75%+ coverage, 3,129 tests)

### Cost Profile

- **Rule-based extraction:** $0 (50-70% of metrics)
- **LLM extraction:** ~$0.10 per filing average
- **Total projected cost:** $500-$1,000 for full corpus

---

## Implementation Status

| Component | Status | Test Coverage | Documentation |
|-----------|--------|---------------|---------------|
| Universe Builder | ✅ Complete | 93% | [System Overview](architecture/system-overview.md) |
| Filing Fetcher | ✅ Complete | 94% | [System Overview](architecture/system-overview.md) |
| HTML Segmenter | ✅ Complete | 80% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| Metric Classifier | ✅ Complete | 98% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| Segment Enricher | ✅ Complete | 98% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| Cohort Chart Detector | ✅ Complete | 100% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| Value Extractor | ✅ Complete | 66% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| Definition Extractor | ✅ Complete | 89% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| Quality Scorer | ✅ Complete | 100% | [Quality Model](development/quality-model.md) |
| Extraction Pipeline | ✅ Complete | 91% | [Extraction Pipeline](architecture/extraction-pipeline.md) |
| OpenAI Client | ✅ Complete | 88% | [LLM Integration](architecture/llm-integration.md) |
| Database Schema | ✅ Complete | N/A | [Data Model](architecture/data-model.md) |
| Review Candidate Generator | ✅ Complete | 98% | [Human Review](HUMAN_REVIEW_SYSTEM.md) |
| Review Feature Extractor | ✅ Complete | 100% | [Human Review](HUMAN_REVIEW_SYSTEM.md) |
| Review Routes (D1) | ✅ Complete | 94% | [Human Review](HUMAN_REVIEW_SYSTEM.md) |
| API Routes (D2) | ✅ Complete | 97% | [Human Review](HUMAN_REVIEW_SYSTEM.md) |
| Pattern Analyzer (E1) | ✅ Complete | 97% | [Human Review](HUMAN_REVIEW_SYSTEM.md) |
| Rule Applicator (E2) | ✅ Complete | 100% | [Human Review](HUMAN_REVIEW_SYSTEM.md) |

**Overall Status:** ✅ **Production Ready** (87% test coverage, 3,150+ tests)

---

## Getting Started

### For New Team Members

1. **Read the Overview**
   - Start with [System Overview](architecture/system-overview.md)
   - Understand the problem: [Analytic Requirements](requirements/analytic-requirements.md)

2. **Understand the Data**
   - Review [Data Model](architecture/data-model.md)
   - Review [Metrics Taxonomy](development/metrics-taxonomy.md)

3. **Learn the Pipeline**
   - Study [Extraction Pipeline](architecture/extraction-pipeline.md)
   - Review [LLM Integration](architecture/llm-integration.md)

4. **Set Up Your Environment**
   - Follow [Setup Guide](operations/setup-guide.md)
   - Run tests: `pytest -v`

### For Analysts

1. **Understand the Data Model**
   - Review [Data Model](architecture/data-model.md) - especially analysis views
   - Review [Quality Model](development/quality-model.md) for scoring

2. **Understand Metrics**
   - [Metrics Taxonomy](development/metrics-taxonomy.md) - canonical definitions
   - [Analytic Requirements](requirements/analytic-requirements.md) - research questions

3. **Access the Data**
   - Connect to PostgreSQL database
   - Use analysis views: `v_filing_metric_incidence`, `v_metric_values_cohort`

---

## Common Tasks

### Running Extraction on Sample Filings

```bash
# See setup-guide.md for detailed instructions
python scripts/run_extraction_pipeline.py
```

### Running Tests

```bash
# All tests
pytest -v

# Specific module
pytest tests/unit/extraction/test_value_extractor.py -v

# With coverage
pytest --cov=src --cov-report=html
```

### Building the Universe

```bash
# See setup-guide.md for database setup first
python scripts/build_universe_real.py --start-date 2015-01-01 --end-date 2025-12-31
```

### Querying Results

```sql
-- Filing-level incidence by year
SELECT
    EXTRACT(YEAR FROM filing_date) AS year,
    metric_id,
    COUNT(*) FILTER (WHERE metric_disclosed_flag) AS disclosed_count,
    COUNT(*) AS total_filings
FROM v_filing_metric_incidence
WHERE is_in_scope_phase1
GROUP BY year, metric_id
ORDER BY year, metric_id;
```

---

## Key Concepts

### Metrics

Standardized customer-related measurements (e.g., new customers acquired, revenue by cohort). See [Metrics Taxonomy](development/metrics-taxonomy.md).

### Segments

Atomic units of filing content (paragraphs, tables, footnotes) from which metrics are extracted. See [Extraction Pipeline](architecture/extraction-pipeline.md).

### Incidence

Whether a metric is disclosed in a filing (binary: yes/no). See [Analytic Requirements](requirements/analytic-requirements.md).

### Quality Score

0-3 scale assessment of disclosure quality. See [Quality Model](development/quality-model.md).

### Alignment

How closely an issuer's metric definition matches the CMASB canonical definition. See [Quality Model](development/quality-model.md).

### Cohort

Group of customers by acquisition period or tenure. See [Metrics Taxonomy](development/metrics-taxonomy.md).

---

## Troubleshooting

### Common Issues

**"Module not found" errors**
- Ensure you're in the project root directory
- Verify virtual environment is activated: `source venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

**Database connection errors**
- Check `DATABASE_URL` in `.env` file
- Ensure PostgreSQL is running (use Docker: `docker compose up -d`)
- Verify connection: `psql $DATABASE_URL`

**LLM extraction failures**
- Check `OPENAI_API_KEY` in `.env` file
- Verify API key is valid
- Check rate limits and costs in OpenAI dashboard

**Low extraction quality**
- Review [Quality Model](development/quality-model.md)
- Check QA warnings in database
- Run sample extractions and compare to source

### Getting Help

1. **Check Documentation:** Start with [System Overview](architecture/system-overview.md)
2. **Review Tests:** Look at test files for usage examples
3. **Check Logs:** Review `logs/` directory for error details
4. **Ask the Team:** Contact project maintainers

---

## Contributing

### Documentation Updates

When updating documentation:
1. Keep this README.md synchronized
2. Update version and date in modified files
3. Ensure cross-references are valid
4. Follow existing structure and style

### Code Changes

1. Write tests for new code
2. Maintain >75% test coverage
3. Update relevant documentation
4. Follow existing code patterns

### Adding New Metrics

1. Add to `metrics` table
2. Update [Metrics Taxonomy](development/metrics-taxonomy.md)
3. Update classifier patterns
4. Add tests

---

## Claude Code Context System

The project uses a structured `.claude/` directory for AI-assisted development. This system provides context-specific rules, slash commands, and reusable skills.

### Context-Specific Rules (`.claude/rules/`)

Rules that auto-load when working with specific file paths:

| Rule File | Path Pattern | Purpose |
|-----------|--------------|---------|
| `extraction.md` | `src/extraction/**`, `config/metric_keywords.yaml` | Core principles, gold standard validation requirements |
| `testing.md` | `tests/**` | Test conventions, coverage requirements |
| `gold-standard.md` | Gold standard files | Validation workflow and thresholds |

Rules are applied automatically based on which files are being edited.

### Slash Commands (`.claude/commands/`)

Workflow commands for common tasks:

| Command | Purpose |
|---------|---------|
| `/task-create [ID]` | Generate a worker prompt for a task (does NOT execute) |
| `/task-run [ID]` | Execute an existing worker prompt with approval gates |
| `/ralph [mode]` | Start Ralph Loop for autonomous execution |
| `/metric-lifecycle` | Guidance for adding, deprecating, or removing metrics |
| `/commit` | Safe commit: runs ruff + pytest before committing |
| `/merge-check` | Thorough merge readiness assessment (CI, migrations, imports, tests) |
| `/ci-fix` | Autonomous CI fix loop: iterates ruff → mypy → pytest until all pass |
| `/plan-execute` | Execute a multi-phase plan with parallel sub-agents per independent wave |
| `/doc-audit` | Run documentation freshness audit (reports staleness, does not auto-fix) |

### Skills (`.claude/skills/`)

Internal prompt templates for consistent, efficient task execution. Skills reduce context usage and ensure consistency.

| Skill | Purpose |
|-------|---------|
| `implementation-planner.md` | Generate structured plans with A/B/C streams |
| `flask-api-builder.md` | Generate Flask routes, validation, tests |
| `code-module-grader.md` | Evaluate modules A+ to F with improvements |
| `test-coverage-analyzer.md` | Find gaps, generate tests |
| `database-migration-helper.md` | Generate SQL migrations + db.py methods |
| `refactor-evaluator.md` | Evaluate refactoring safety and impact |
| `completion-report-generator.md` | Generate task completion reports |
| `documentation-sync-validator.md` | Check documentation accuracy |

See [CLAUDE_SKILLS_QUICKSTART.md](CLAUDE_SKILLS_QUICKSTART.md) for detailed usage.

---

## Version History

### Version 2.4 (Current - 2026-03-22)
- ✅ Fresh mode validation: `test_gold_standard_regression.py` now supports `--gold-standard-mode=fresh` (no DB required)
- ✅ `scripts/apply_all_migrations.py` added — applies all 14 SQL migrations in canonical order
- ✅ Neon (cloud PostgreSQL) documented as production DB in CLAUDE.md and `.env.template`
- ✅ `*.dump` added to `.gitignore` to prevent accidental production data commits
- ✅ Issue #9 partially resolved: validation DB dependency eliminated; Snap CIK fix still pending
- ✅ `baseline.json` and `baseline_metrics.json` synced to stable fresh-mode metrics (P:84.1%, R:73.0%, F1:78.1%)

### Version 2.3 (2026-03-16)
- ✅ Cloud deployment runbook added (Render + Neon DB)
- ✅ FilingFetcher directory URL bug fix (Issue #6)
- ✅ GR-16 complete: Snowflake/DocuSign goldmine labels added
- ✅ Goldmine remediation plan (GR) closed: all 18 tasks complete
- ✅ Human review validation plan (HRV) closed: all 6 tasks complete
- ✅ `/commit` skill enhanced with doc freshness checks and auto-push

### Version 2.2 (2025-12-29)
- ✅ Goldmine remediation complete (80% recall, 95% precision, 87% F1)
- ✅ HRV-1 through HRV-5 validation complete
- ✅ Performance optimizations (+33% throughput)
- ✅ Documentation reorganized and archive consolidated
- ✅ Cohort chart image detection (segment-level + filing-level)

### Version 2.1 (2025-12-14)
- ✅ Human review system (COMPLETE - Production Ready)
- ✅ Review models: ReviewCandidate, ReviewDecision, LearnedPattern, CandidateFeatures
- ✅ Candidate generation with modular architecture (B1: 98% coverage)
- ✅ Feature extraction (B2: 100% coverage, 115 tests)
- ✅ Review routes (D1: 94% coverage, 28 tests, 7 production improvements)
- ✅ API routes (D2: 97% coverage, 35 tests)
- ✅ Pattern analyzer (E1: 97% coverage, 85 tests, production-ready)
- ✅ Rule applicator (E2: 100% coverage, 22 tests, production-ready)

### Version 2.0 (2025-12-09)
- ✅ Complete pipeline implementation
- ✅ LLM integration (GPT-4o-mini)
- ✅ Quote verification
- ✅ 77% test coverage
- ✅ Production-ready system

### Version 1.0 (2024-11)
- Initial implementation
- Universe building
- Basic extraction
- Database schema

---

## Project Team

**Owner:** Rob Markey
**Organization:** CMASB (Customer Metrics Accounting Standards Board)

---

## License & Contact

For questions about this system or the CMASB initiative:
- Contact: Rob Markey

---

**Quick Navigation:**
[Architecture](architecture/) | [Requirements](requirements/) | [Development](development/) | [Operations](operations/) | [Archive](archive/)
