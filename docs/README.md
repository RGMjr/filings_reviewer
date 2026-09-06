# Customer Metrics Filings Analysis - Documentation

**Project:** SEC Filings Customer Metrics Extraction System
**Version:** 2.9
**Status:** Production Ready (presence-pivot mid-rollout)
**Last Updated:** 2026-09-06

---

> **Pivot status (2026-04-25):** The system is mid-pivot from value-extraction-as-primary to **presence-as-primary** — the canonical scoring surface is now per-`(doc_id, canonical_metric_id)` detection, with values demoted to advisory evidence and a manual-entry path (`POST /api/v2/missed-metric`) when CMASB needs them. Chart-presence pivot is **live** (#86, 2026-04-23). Text-presence PR1 **landed** (#182, 2026-04-16). PR2 (gold-standard derivation + Tier-1 gate flip), PR3 (reviewer UI for text presence), PR4–PR5 are pending. Known gaps: legacy-097 (residual chart facts), legacy-098 (validator `presence_f1` not yet populated). See [`operations/text-pipeline-presence-pivot-plan.md`](operations/text-pipeline-presence-pivot-plan.md) for the rollout plan and authoritative interface contract.
>
> **LLM presence classifier rollout: CLOSED (2026-05-15).** The phase-2 quantitative gate verdict was NO-GO on both live evaluation runs (2026-05-11 and 2026-05-14); the classifier catches zero positives the keyword path missed across all 10 enrolled Tier-1 metrics. `presence_classifier_enabled` stays `False` indefinitely. Code is retained as dormant infrastructure. Full record: [`analysis/llm-presence-classifier-rollout-closeout-20260515.md`](analysis/llm-presence-classifier-rollout-closeout-20260515.md).

## Overview

This system analyzes SEC S-1/F-1 filings to assess how companies disclose customer-related metrics, supporting the Customer Metrics Accounting Standards Board (CMASB) initiative to establish standardized customer metrics disclosure practices. The primary output of the V2 pipeline is **presence**: a per-(filing, metric) signal aggregated from text facts, chart detections, and metric definitions, with full provenance back to source segments and images.

### Quick Links

| For... | Start Here |
|--------|------------|
| **New developers** | [System Architecture](architecture/system-overview.md) → [Presence-pivot plan](operations/text-pipeline-presence-pivot-plan.md) |
| **Analysts/Researchers** | [Analytic Requirements](requirements/analytic-requirements.md) |
| **Project managers** | [System Architecture](architecture/system-overview.md) → Success Criteria |
| **Quality assurance** | [Testing Strategy](development/testing.md) → [Quality Model](development/quality-model.md) |
| **Data users** | [Data Model](architecture/data-model.md) → Analysis Views |
| **Anyone tracing a presence claim back to source** | [Presence-pivot plan](operations/text-pipeline-presence-pivot-plan.md) → [Data Model](architecture/data-model.md) provenance section |

---

## Documentation Structure

### Architecture (Technical Design)

Core system architecture and design specifications.

| Document | Description | Audience |
|----------|-------------|----------|
| **[system-overview.md](architecture/system-overview.md)** | Complete system architecture, components, data flow | Everyone - START HERE |
| **[data-model.md](architecture/data-model.md)** | Database schema, table specifications, relationships | Developers, Analysts |
| **[extraction-pipeline.md](architecture/extraction-pipeline.md)** | Extraction pipeline stages, components, interfaces | Developers |
| **[extraction-decisions.md](architecture/extraction-decisions.md)** | Key extraction design decisions and rationale | Developers |
| **[llm-integration.md](architecture/llm-integration.md)** | OpenAI GPT-4o-mini integration, costs, prompts | Developers |
| **[image-storage.md](architecture/image-storage.md)** | Image storage (R2/local filesystem) architecture and key paths | Developers, DevOps |
| **[image-decision-revalidation-design.md](architecture/image-decision-revalidation-design.md)** | Design for admin re-review / decision override on image confirmations | Developers |
| **[per-metric-image-classifier.md](architecture/per-metric-image-classifier.md)** | Per-metric Vision classifier design and rollout plan | Developers |
| **[auth-rollout-implementation-plan.md](architecture/auth-rollout-implementation-plan.md)** | Stage-by-stage PR plan for the review-UI authorization rollout | Developers, DevOps |

### Requirements (Business Needs)

Business requirements and metric definitions.

| Document | Description | Audience |
|----------|-------------|----------|
| **[analytic-requirements.md](requirements/analytic-requirements.md)** | Core business requirements, research questions, hypotheses | All stakeholders |
| **[review-ui-authorization-spec.md](requirements/review-ui-authorization-spec.md)** | Auth requirements and access-control spec for the review UI | Developers, DevOps |
| **[text-candidate-review-analysis-improvement-spec.md](requirements/text-candidate-review-analysis-improvement-spec.md)** | Spec for improving text-candidate review UI and analysis tools | Developers |
| **[text-decision-analysis-improvement-spec.md](requirements/text-decision-analysis-improvement-spec.md)** | Spec for improving text-decision analysis and pattern recommendations | Developers |

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
| **[deployment-guide-pre-v2.md](archive/ops/deployment-guide-pre-v2.md)** | Legacy deployment guide (local/batch processing era, pre-V2) | Archive |
| **[extraction-runbook.md](operations/extraction-runbook.md)** ⭐ | **Re-extraction, re-segmentation, candidate regeneration** | Developers, DevOps |
| **[TICKER_ONBOARDING.md](operations/TICKER_ONBOARDING.md)** | Onboard SEC filings filtered by industry / year / form-type via `scripts/onboard_tickers.py` | Developers, DevOps |
| **[gold-standard-runbook.md](operations/gold-standard-runbook.md)** | Gold standard validation, baseline update, regression workflow | Developers |
| **[text-pattern-recommendations-runbook.md](operations/text-pattern-recommendations-runbook.md)** | Translate accepted Suggested-actions cards on `/v2/review/stats` into keyword / FP-filter PRs | Developers |
| **[image-model-training-runbook.md](operations/image-model-training-runbook.md)** | Image relevance model: export → train → score pipeline | Developers |
| **[analytics-ui-runbook.md](operations/analytics-ui-runbook.md)** | Read-only BI role, `v_analytics_*` views, Metabase deployment plan | Developers, Analysts |
| **[BATCH_INGESTION.md](operations/BATCH_INGESTION.md)** | Batch ingestion runbook: queuing, monitoring, and error recovery | Developers, DevOps |
| **[github-org-transfer.md](operations/github-org-transfer.md)** | Decision record + runbook: when/how to migrate from user repo to GitHub org (unlocks merge queue, teams, org rulesets) | DevOps |
| **[ci-branch-protection.md](operations/ci-branch-protection.md)** | CI branch-protection rules: required checks, rulesets, and admin override policy | DevOps |
| **[auth-stage-b-runbook.md](operations/auth-stage-b-runbook.md)** | Auth Stage B: enabling Google login, seeding users, pre-flip readiness check | Developers, DevOps |
| **[auth-stage-c-runbook.md](operations/auth-stage-c-runbook.md)** | Auth Stage C: route-level enforcement, `FILINGS_API_KEY` gate removal | Developers, DevOps |
| **[full-page-ocr-runbook.md](operations/full-page-ocr-runbook.md)** | Full-page OCR pipeline: enabling, running, and troubleshooting | Developers, DevOps |
| **[metric-classify-pipeline.md](operations/metric-classify-pipeline.md)** | `ENABLE_METRIC_CLASSIFY` pipeline: enabling Vision classifier, running, reviewing output | Developers |
| **[metabase-tier1-reporting.md](operations/metabase-tier1-reporting.md)** | Metabase Tier-1 reporting: dashboard setup, `v_analytics_*` views, BI deployment | Analysts, DevOps |
| **[llm-presence-classifier-phase1-eval-runbook.md](operations/llm-presence-classifier-phase1-eval-runbook.md)** | Phase 1 LLM presence classifier evaluation runbook (archive reference — rollout closed 2026-05-15) | Developers |
| **[llm-presence-classifier-phase2-quantitative-eval-runbook.md](operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md)** | Phase 2 quantitative evaluation runbook (archive reference — rollout closed 2026-05-15) | Developers |
| **[vision-model-selection.md](operations/vision-model-selection.md)** | Vision model selection decision record and bakeoff results | Developers |
| **[text-pipeline-presence-pivot-plan.md](operations/text-pipeline-presence-pivot-plan.md)** | Text-extraction pivot to per-(doc, metric) presence: rollout plan + PR1 landed-interface contract for downstream PRs | Developers |

### Human Review System (✅ COMPLETE - Production Ready)

Human-in-the-loop system for validating and improving extraction quality.

| Document | Description | Audience |
|----------|-------------|----------|
| **[HUMAN_REVIEW_SYSTEM.md](HUMAN_REVIEW_SYSTEM.md)** | System design, usage, configuration | Developers |

### Reference Plans

Active and historical plans for reference.

| Document | Description | Audience |
|----------|-------------|----------|
| **[known-issues/](known-issues/)** | Known issues (source-of-truth fragments). Rendered rollup is published as a CI build artifact on every main build — see `known-issues-rollup` on the Actions tab. | Developers |

### Archive (Historical Reference)

Historical documents for reference only. Not part of current operations.

| Category | Contents |
|----------|----------|
| **[archive/improvement-plans-completed/](archive/improvement-plans-completed/)** | Completed improvement plans |
| **[archive/historical/](archive/historical/)** | Historical process documentation, task inventory, and performance baselines |
| **[archive/workstreams/](archive/workstreams/)** | Legacy workstream documentation |

### Operational Templates

Worker prompt templates are archived at `archive/historical/process/`. Use the Agent tool with sub-agents in `.claude/agents/` for structured task execution.

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
- **Testing:** pytest (80%+ coverage, 4,500+ tests)
- **Error Monitoring:** Sentry (`sentry-sdk`; configured via `SENTRY_DSN` env var; wired into web, worker, and extraction — see `src/infra/sentry.py`)

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
| Image Review UI (IMG-1) | ✅ Complete | N/A | [Human Review](HUMAN_REVIEW_SYSTEM.md) |
| Image Stats Dashboard | ✅ Complete | N/A | [Human Review](HUMAN_REVIEW_SYSTEM.md) |

**Overall Status:** ✅ **Production Ready** (87% test coverage, 4,500+ tests)

> **Pivot note (2026-04-25):** The component table above is structurally correct, but the `Value Extractor` entry should now be read as **advisory evidence**, not the headline output. The headline output is the **MetricPresenceStage** (final V2 stage; aggregates facts/charts/definitions into per-`(doc_id, metric_id)` presence rows in `v2_text_metric_presence`). See [`extraction-pipeline.md`](architecture/extraction-pipeline.md) and the [presence-pivot plan](operations/text-pipeline-presence-pivot-plan.md).

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
python3 scripts/run_v2_extraction.py
```

### Running Tests

```bash
# All tests
pytest -v

# Specific module
pytest tests/unit/extraction_v2/test_candidate_generation.py -v

# With coverage
pytest --cov=src --cov-report=html
```

### Building the Universe

```bash
# See setup-guide.md for database setup first
python scripts/build_universe_real.py --start-date 2015-01-01 --end-date 2025-12-31
```

### Querying Results

Presence-first (current; recommended):

```sql
-- Per-filing presence with provenance for one Tier-1 metric
SELECT
    p.doc_id,
    p.canonical_metric_id,
    p.score,
    p.detected_at_stage,
    p.evidence_segment_ids,
    p.advisory_fact_ids,
    p.advisory_value_count
FROM v2_text_metric_presence p
WHERE p.canonical_metric_id = 'cm_net_revenue_retention'
ORDER BY p.score DESC;

-- Reverse-trace from a presence row to source segment text
SELECT s.segment_id, s.section_name, s.text
FROM v2_segments s
WHERE s.segment_id = ANY (
    SELECT jsonb_array_elements_text(p.evidence_segment_ids)::int
    FROM v2_text_metric_presence p
    WHERE p.doc_id = $1 AND p.canonical_metric_id = $2
);
```

Legacy V1 incidence (retained for backwards compatibility):

```sql
-- Filing-level incidence by year (V1 view, value-extraction era)
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

### Presence

Per-`(doc_id, canonical_metric_id)` detection signal — the **primary scoring surface** under the 2026-04 pivot. Aggregated from text facts (`v2_metric_facts`), chart detections (`v2_image_assets.detected_metrics`), Vision classifier output (`v2_image_classifications`), and metric definitions. Persisted to `v2_text_metric_presence` (text grain) and `v2_image_metric_presence` (image grain, lands with image-review Wave 2); union-readable via `v_doc_metric_presence`. See [Presence-pivot plan](operations/text-pipeline-presence-pivot-plan.md) and [`MetricPresenceStage`](architecture/extraction-pipeline.md).

### Provenance / Audit Trail

Every presence row points back to its evidence: `evidence_segment_ids` and `advisory_fact_ids` (JSONB arrays on `v2_text_metric_presence`) for text; `v2_image_metric_confirmations` joined to `v2_image_assets` for charts. Reviewer decisions are captured in `v2_image_metric_confirmations` (accept / reject / correct / add / skip) and `v2_review_decisions` (text facts; until PR3 lands `v2_text_presence_confirmations`). The `advisory_*` columns are JSONB pointers, **not** foreign keys — facts may be deleted on `force=True` re-extraction without cascading to presence rows, since presence is a doc-level claim independent of which specific fact rows currently back it.

### Segments

Atomic units of filing content (paragraphs, tables, footnotes) from which metrics are extracted. See [Extraction Pipeline](architecture/extraction-pipeline.md).

### Incidence

Whether a metric is disclosed in a filing (binary: yes/no). Operationalized as **presence** in V2; `v_filing_metric_incidence` is a legacy V1 view kept for backwards compatibility. See [Analytic Requirements](requirements/analytic-requirements.md).

### Quality Score

0-3 scale assessment of disclosure quality. See [Quality Model](development/quality-model.md). **Note:** under the presence pivot, value-correctness has been demoted to advisory; the primary quality dimension for chart-native metrics is now **presence-F1**.

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
2. Maintain >80% test coverage
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
| `/cleanup` | Project-local: prune merged branches, stale remote-tracking refs, and dead Claude worktrees. Safe to re-run. |
| `/commit-proj` | Project-local: auto-branch off main, commit, push, open PR, enable auto-merge. Renamed from `/commit` to disambiguate from the global skill of the same name. See [CONTRIBUTING.md](development/CONTRIBUTING.md#committing-via-commit-claude-code). |
| `/doc-audit` | Run documentation freshness audit (reports staleness, does not auto-fix) |
| `/learn [cleanup]` | End-of-session lesson capture into project agent memory, or audit/prune existing memory entries (`cleanup` mode). |
| `/metric-lifecycle` | Guidance for adding, deprecating, or removing metrics |
| `/monitor-prs` | Project-local: thin wrapper around `/supervise-prs` that discovers open non-draft PRs dynamically. Compose with `/loop 8m /monitor-prs` for continuous supervision. |
| `/pick-issues` | Project-local: select and brief known-issue fragments as worker prompts. Supports `count`, `strategy` (highest-impact / parallel-safe / xs-only / tier1-recall-gap), and `--no-write`. |
| `/project-tutorial [lesson]` | Interactive project lessons with live codebase walkthroughs (10 topics) |
| `/supervise-prs` | Project-local: single-shot PR-cohort status check; compose with `/loop <interval> /supervise-prs <prs>` to poll merges, dispatch `/ci-fix` on required-check failures, and hand off to `/cleanup`. |
| `/sweep` | Project-local: manual invoke of the nightly known-issues sweeper (same flow as the Render cron). |
| `/ci-fix` | Global/plugin: iterate ruff / mypy / pytest to green on a red PR, then defer to `/commit-proj`. |
| `/merge-check` | Global/plugin: pre-merge sanity sweep (CI status, migrations, import integrity, tests, type check, branch freshness). |
| `/plan-review` | Global/plugin: review and critique a plan before execution. |

> **Note:** `/cleanup`, `/commit-proj`, `/doc-audit`, `/metric-lifecycle`, `/project-tutorial`, and `/supervise-prs` are project-local command files under `.claude/commands/`. `/ci-fix`, `/merge-check`, and `/plan-review` are delivered via Claude Code skills/plugins rather than project-local files. `/commit-proj` was renamed from `/commit` to disambiguate from the global skill of the same name.

### Sub-Agents (`.claude/agents/`)

Specialized sub-agents invoked via the Claude Code Agent tool for targeted tasks:

| Agent | Purpose |
|-------|---------|
| `dev-implementer` | General-purpose implementation (web routes, database, infra, scripts) |
| `extraction-implementer` | Implements extraction code changes (keywords, classifiers, FP rules) |
| `extraction-reviewer` | Reviews extraction changes against project rules before committing |
| `gold-standard-validator` | Runs gold standard validation, compares against baseline, diagnoses regressions |
| `keyword-config-checker` | Validates `metric_keywords.yaml` changes for regex errors and pattern overlaps |
| `pipeline-debugger` | Traces V2 extraction results to diagnose false positives and regressions |
| `test-runner` | Runs pytest, interprets failures, and re-runs targeted subsets |

---

## Version History

### v2.9 — 2026-09-06 — Documentation audit: index catch-up, Sentry, classifier closeout

- **LLM presence classifier rollout closed (2026-05-15):** Added banner to Overview section noting the phase-2 NO-GO verdict and permanent `presence_classifier_enabled: False` status. Full closeout record at [`analysis/llm-presence-classifier-rollout-closeout-20260515.md`](analysis/llm-presence-classifier-rollout-closeout-20260515.md).
- **Sentry error monitoring added to Technology Stack (PR #657, 2026-05-22):** Wired into web, worker, and extraction layers via `src/infra/sentry.py`. Configured via `SENTRY_DSN` env var — see `operations/setup-guide.md` for configuration details.
- **Architecture index expanded:** Added `extraction-decisions.md`, `image-storage.md`, `image-decision-revalidation-design.md`, `per-metric-image-classifier.md` — all four were present in `docs/architecture/` but unlisted.
- **Requirements index expanded:** Added `review-ui-authorization-spec.md`, `text-candidate-review-analysis-improvement-spec.md`, `text-decision-analysis-improvement-spec.md`.
- **Operations index expanded (10 additional entries):** `BATCH_INGESTION.md`, `auth-stage-b-runbook.md`, `auth-stage-c-runbook.md`, `ci-branch-protection.md`, `full-page-ocr-runbook.md`, `metric-classify-pipeline.md`, `metabase-tier1-reporting.md`, `vision-model-selection.md`, and the two phase-1/2 LLM-classifier eval runbooks (archive-reference only, rollout closed).
- **Slash commands table expanded:** Added `/learn`, `/monitor-prs`, `/pick-issues`, `/sweep` — all four have command files in `.claude/commands/` but were not listed in the README.
- **Coverage requirement corrected:** Changed "Maintain >75% test coverage" to ">80%" to match the enforced minimum in `CLAUDE.md` and `pyproject.toml`.

### v2.8 — 2026-04-25 — Documentation aligned with presence pivot

- Top-of-funnel docs (this file, root `README.md`, `MANUAL_TESTING_GUIDE.md`) updated to lead with **presence** as the primary scoring surface.
- New Key Concepts: **Presence**, **Provenance / Audit Trail**.
- `Querying Results` example now leads with a presence-with-provenance query against `v2_text_metric_presence`; the legacy `v_filing_metric_incidence` query retained for backwards compatibility.
- Implementation Status table annotated to clarify that `Value Extractor` outputs are advisory under the pivot; the headline V2 output is `MetricPresenceStage`.
- Architecture, operations, and development docs landed alongside the top-of-funnel updates in [PR #210](https://github.com/RGMjr/filings_reviewer/pull/210) (commits `461d94d` PR 1, `3caaa67` PR 2, `524cd5d` PR 3):
  - **Architecture (PR 2):** `system-overview`, `data-model`, `extraction-pipeline`, `llm-integration` rev'd to 3.1 with the pivot status banner, presence-with-provenance reverse-trace SQL, and stages 5a / 5b / 14 (`ChartFactBridgeStage`, `ImageClassifyStage`, `MetricPresenceStage`).
  - **Operations (PR 3):** `extraction-runbook` rewritten against V2 tables (V1 candidate/segment flow retired); `gold-standard-runbook` adds Section 7a for presence-derived metrics (gate flip pending text-presence PR2); `analytics-ui-runbook`, `setup-guide`, `full-page-ocr-runbook` get the pivot status banner and `ENABLE_METRIC_CLASSIFY`.
  - **Development (PR 3):** `quality-model` (presence-F1 primary), `testing` (presence-provenance test pattern), `metrics-taxonomy`, `metric-lifecycle-process`, `CONTRIBUTING` get the pivot status banner.
  - **Module docstrings (PR 2):** `src/extraction_v2/__init__.py`, `pipeline.py`, `persistence.py`, plus `src/web/routes/api_unified.py` and `src/review/README.md`.
  - **Archive (PR 3):** Pre-pivot `docs/HUMAN_REVIEW_SYSTEM.md` moved to `docs/archive/historical/HUMAN_REVIEW_SYSTEM-pre-presence.md`; the original path now holds a thin pointer to the V2 unified review UI.

### v2.7 — 2026-04-16 — Tier 1 Recall — Text Pipeline Concluded

- `dd5c90a`: Add `_WIDER_PROXIMITY_METRICS` frozenset in `value_binding.py:46-52` — 200-char window for cm_balance_by_cohort, cm_gross_margin_by_cohort, cm_ltv_to_cac_ratio, cm_ltv_to_cac_ratio_by_cohort, cm_cac_payback_period. Add `cm_large_customers_period_end` table FP exemption at `false_positive_filter.py:1211-1215`.
- `09a8f64`: Add `specific_patterns` confidence boost for cm_ltv_to_cac_ratio in `config/metric_keywords.yaml`. F1 46%→50%.
- `v2_baseline.json` updated: P=68.06%, R=63.36%, F1=65.63% (15 companies, V2 SEC methodology).
- Remaining Tier 1 gains on chart-native metrics (cm_revenue_by_cohort, cm_balance_by_cohort, cm_gross_margin_by_cohort) accrue via **presence-F1** after the 2026-04-23 chart-presence pivot (#86): the chart pipeline writes `detected_metrics` on `v2_image_assets`, reviewers confirm via `v2_image_metric_confirmations`. Text-pipeline Tier 1 recall work is concluded.

### Version 2.6 (Current - 2026-04-08)
- ✅ Gold standard expanded to 15 companies (467 GS entries); `golden_set_260408.csv` is now the authoritative CSV
- ✅ `baseline_metrics.json` updated: P:67.5%, R:80.2%, F1:73.3% (15 companies, `validate_against_gold_standard.py` regression guard)
- ✅ `v2_baseline.json` updated: P:60.9%, R:64.0%, F1:62.4% (15 companies, V2-only SEC methodology)
- ✅ FP filter improvements: NRR context check narrowed to 80-char window; magnitude guard for `cm_large_customers_period_end` in tables
- ✅ Presentation baseline: P:46.6%, R:74.5%, F1:57.3% (230 annotations, 15 companies)
- ✅ Transcript baseline: P:74.2%, R:75.8%, F1:75.0% (91 annotations, 20 files)

### Version 2.5 (2026-03-30)
- ✅ Migration 15 (`15_rename_cohort_heatmap_to_parfait.sql`): renames `cohort_heatmap` → `cohort_parfait` in `check_chart_type` constraint
- ✅ Migration 16 (`16_add_8k_form_type.sql`): adds `'8-K'` to `check_form_type` constraint so presentation ingestion no longer fails
- ✅ `_is_title_slide()` heuristics simplified — fewer false suppressions of content slides (e.g., "Revenue Discussion", "Customer Metrics")
- ✅ `_DOLLAR_REJECT_METRICS` extended with 4 additional count-only metrics; `deduplicated_facts` changed to `list | None` (`None` = stage not yet run, `[]` = ran, found nothing)
- ✅ `SECPresentationSource`: `_cik_to_ticker_cache` moved to instance level; `SEC_USER_AGENT` env var used for default user-agent
- ✅ `presentation_converter.py`: `fitz_doc` now closed in `try/finally` block (resource safety)
- ✅ `ingest_transcripts.py` / `ingest_presentations.py`: pipeline now runs once with the real `filing_id` (previously ran twice)
- ✅ Image review system complete: `/review/images/stats` dashboard, `scripts/export_image_decisions.py`, and 4 new DB stats methods

### Version 2.6 (2026-04-08)
- ✅ Image relevance model: logistic regression trained on 584 labeled images (AUC-ROC 0.771); review queue now sorted by `predicted_relevance DESC` so likely-relevant images surface first
- ✅ Migration 19 (`19_add_predicted_relevance.sql`): adds `predicted_relevance` column to `image_review_candidates`
- ✅ New scripts: `export_image_training_data.py` (unified SEC + presentation label export), `train_image_relevance_model.py`, `score_image_candidates.py` — full retrain pipeline
- ✅ Fix `/review/pres-images/` index: was redirecting to DB-backed filing list (returned nothing); now renders file-based `pres_image_filing_list.html` with all 21 presentation filings

### Version 2.4 (2026-03-22)
- ✅ Fresh mode validation: `test_gold_standard_regression.py` now supports `--gold-standard-mode=fresh` (no DB required)
- ✅ `scripts/apply_all_migrations.py` added — applies all 14 SQL migrations in canonical order
- ✅ Neon (cloud PostgreSQL) documented as production DB in CLAUDE.md and `.env.template`
- ✅ `*.dump` added to `.gitignore` to prevent accidental production data commits
- ✅ Issue #9 partially resolved: validation DB dependency eliminated; Snap CIK fix still pending
- ✅ `baseline_metrics.json` synced to stable fresh-mode metrics (P:84.1%, R:73.0%, F1:78.1%)

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
