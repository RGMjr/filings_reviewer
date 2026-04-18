# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

Source lives in `src/` (infra, universe, filing_fetcher, extraction_v2, review, shared, web, llm, gold_standard). Config in `config/metric_keywords.yaml`. See `docs/README.md` for full index.

**Pipeline (V2):** UniverseBuilder → FilingFetcher → V2Pipeline → V2PersistenceAdapter → Database

## Key Commands

```bash
uv pip install -r requirements.txt # Install dependencies
pytest -v                          # Run all tests
pytest --cov=src --cov-report=html # Run with coverage
black src/ tests/                  # Format code
ruff check src/ tests/             # Lint
mypy src/review/ --strict          # Type checking
```

## Database

PostgreSQL. V2 tables: `v2_documents`, `v2_segments`, `v2_metric_facts`, `v2_metric_definitions`, `v2_image_assets`, `v2_image_review_decisions`, `v2_tables`. Shared: `companies`, `filings`. Legacy V1 tables still present (not yet migrated): `review_candidates`, `source_segments`, `suppressed_candidates`, `review_decisions` — see `docs/architecture/v1-table-deprecation-plan.md`. Schema files in `sql/` (00-30). See `.claude/rules/infrastructure.md` when editing infra, Docker, or requirements files.

## Testing Standards

- **Coverage**: 75% minimum (enforced)
- **Type safety**: `src/review/` passes `mypy --strict`
- **Before committing**: Run `pytest -x -q` when staged changes include code files (`src/`, `tests/`, `scripts/`, `config/`, `sql/`, `pyproject.toml`, `requirements.txt`). Docs-only and `.claude/`-only commits may skip lint and tests. If fixing one failure breaks others, continue iterating until all pass in a single run before committing.
- **Pre-existing failures**: When a test fails during implementation, check whether it was already failing before your changes (`git stash && pytest <failing_test> -x -q && git stash pop`). Do not spend time debugging failures that predate the current work — note them and move on.

## Metric Priority Tiers

Metrics are classified into importance tiers based on analytical value. These tiers govern regression policy, extraction prioritization, and gold standard coverage priorities.

**Tier 1 (must-not-miss):** Cohorted data, retention, LTV/CAC, revenue concentration, customer counts.
- `cm_customer_retention_rate`, `cm_net_revenue_retention`, `cm_gross_revenue_retention`
- `cm_revenue_by_cohort`, `cm_transactions_by_cohort`, `cm_balance_by_cohort`, `cm_gross_margin_by_cohort`
- `cm_revenue_concentration`
- `cm_lifetime_value_per_customer`, `cm_customer_acquisition_cost`, `cm_ltv_to_cac_ratio`, `cm_ltv_to_cac_ratio_by_cohort`
- `cm_large_customers_period_end`, `cm_new_customers_acquired`, `cm_customers_period_end_by_tenure`

**Tier 2 (nice-to-have):** Customer counts, engagement, unit economics.
- All other `cm_*` metrics (customer counts, MAU/DAU, ARPU, AOV, etc.)

**Rules:**
- Tier 1 regression in gold standard validation = blocker, must fix before commit
- Tier 2 regression = acceptable trade-off if Tier 1 improves; note in commit message
- Extraction improvements (keywords, FP rules, value binding) should prioritize Tier 1 recall gaps first
- Gold standard coverage expansion should target Tier 1 metrics with low coverage
- Tier definitions live in `config/metric_keywords.yaml` (authoritative) and `src/gold_standard/v2_validator.py` (runtime)

## Core Design Principles

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives
5. **Image pipeline is active**: Do not delete image-processing code (`src/llm/vision_client.py`, `src/extraction_v2/` image/OCR stages, `src/web/routes/review_unified.py` + `api_unified.py` image endpoints, image scripts). The image review system is complete and in use.

## Compact Instructions

When compacting, preserve: modified file paths, current test/gold-standard validation status, extraction pipeline decisions made this session, and any active task checklist.
