# Customer Metrics Filings Analysis - Documentation

**Project:** SEC Filings Customer Metrics Extraction System
**Version:** 2.1
**Status:** Production Ready
**Last Updated:** 2025-12-24

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
| **[quality-model.md](development/quality-model.md)** | Quality scoring framework (0-3 scale) | Developers, QA |
| **[testing.md](development/testing.md)** | Test strategy, coverage requirements | Developers, QA |

### Operations (Running the System)

Instructions for setting up, running, and maintaining the system.

| Document | Description | Audience |
|----------|-------------|----------|
| **[setup-guide.md](operations/setup-guide.md)** | Environment setup, dependencies, configuration | Developers, DevOps |
| **[deployment-guide.md](operations/deployment-guide.md)** | Deployment procedures, monitoring | DevOps, PMs |
| **[extraction-runbook.md](operations/extraction-runbook.md)** ⭐ | **Re-extraction, re-segmentation, candidate regeneration** | Developers, DevOps |

### Human Review System (✅ COMPLETE - Production Ready)

Human-in-the-loop system for validating and improving extraction quality.

| Document | Description | Audience |
|----------|-------------|----------|
| **[HUMAN_REVIEW_SYSTEM.md](HUMAN_REVIEW_SYSTEM.md)** | System design, usage, configuration | Developers |

### Active Improvement Plans

Current improvement work in progress.

| Document | Description | Audience |
|----------|-------------|----------|
| **[PROJECT_TASK_INVENTORY.md](PROJECT_TASK_INVENTORY.md)** | **Master task inventory with parallel execution plan** | Everyone |
| **[GOLDMINE_REMEDIATION_PLAN.md](GOLDMINE_REMEDIATION_PLAN.md)** | Goldmine improvement plan (18 tasks, 1 complete, 1 partial) | Developers |
| **[IMPROVE_SEGMENTATION_PLAN_A.md](IMPROVE_SEGMENTATION_PLAN_A.md)** | Segmentation improvements for Farfetch/Samsara | Developers |
| **[PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md)** | Performance benchmarks and profiling | Developers |
| **[MERGE_FIX_PLAN_2025-12-24.md](MERGE_FIX_PLAN_2025-12-24.md)** | Merge remediation plan (tests, schema, seeds, CI gates) | Developers |

### Archive (Historical Reference)

Historical documents for reference only. Not part of current operations.

| Category | Contents |
|----------|----------|
| **[archive/2025-12-extraction/](archive/2025-12-extraction/)** | EI-1 to EI-6 extraction improvement completions |
| **[archive/2025-12-goldmine-analysis/](archive/2025-12-goldmine-analysis/)** | GI-1 to GI-8 goldmine analysis artifacts |
| **[archive/improvement-plans-completed/](archive/improvement-plans-completed/)** | Completed improvement plans |
| **[archive/worker-prompts/](archive/worker-prompts/)** | Completed task worker prompts |
| **[archive/workstreams/](archive/workstreams/)** | Historical workstream documentation |

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
- **Testing:** pytest (82% overall coverage, 1,627 tests)

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

**Overall Status:** ✅ **Production Ready** (82% test coverage, 1,627 tests)

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
python scripts/run_extraction_sample.py
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

## Version History

### Version 2.1 (Current - 2025-12-14)
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
