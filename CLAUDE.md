# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

Source lives in `src/` (infra, universe, filing_fetcher, extraction_v2, review, shared, web, llm, gold_standard). Config in `config/metric_keywords.yaml`. See `docs/README.md` for full index.

**Pipeline (V2):** UniverseBuilder → FilingFetcher → V2Pipeline → V2PersistenceAdapter → Database

**Analytics surface:** `v_analytics_*` Postgres views (sql/38) are the canonical shape for BI/reporting queries. Add new reporting views as timestamp-named migrations (see `.claude/rules/sql.md` and `scripts/new_migration.py`) rather than aggregation code in `src/`. See `docs/operations/analytics-ui-runbook.md`.

## Workflow

**PR-required.** `main` is protected — direct pushes are rejected server-side (`enforce_admins: true`). Use `/commit-proj` (project-local): it auto-branches off `main`, commits, pushes the branch, opens a PR via `gh pr create`, and sets `gh pr merge --auto --squash`. GitHub merges when all required checks pass. The global `/commit-user` will also work in a pinch (it now branches + opens a PR), but it does not handle this project's pre-commit framework, fragment-based known-issues, or required-check recital.

**Worktree-first.** Run `/commit-proj` (and any HEAD-moving git work) from a `ccw` worktree, not the primary tree — a PreToolUse guard denies `git checkout`/`switch`/`checkout -b` in the primary tree to protect concurrent sessions. Use `EnterWorktree` inside a session or `ccw [branch]` from the shell. See `docs/development/claude-sessions-and-worktrees.md`.

**Planning rule.** For any plan touching 3+ files or new deps / config, make worktree setup (`EnterWorktree` or `ccw <branch>`) the first step. The `/commit-proj` skill assumes you're in one.

**Patching an existing PR branch:** do not use `EnterWorktree` — it always creates a new branch at the current HEAD. Instead, from within any worktree: `git fetch origin <branch>`, then `git checkout -b <local> origin/<branch>`, fix, and `git push origin <local>:<remote-branch> --force-with-lease`.

Required status checks: **Lint**, **Unit Tests**, **Vulnerability Scan**, **Integration Tests**, **UI E2E (Playwright)**, **Docker Build & Smoke**. Use `/ci-fix` when checks fail; `/merge-check` for a manual pre-merge sweep.

Local guards (`.claude/settings.json`): `git push origin main`, `git push --force*`, and `gh pr merge --admin*` are denied. A PreToolUse hook refuses `git commit` on `main`. Pre-commit framework (`make hooks-install`) runs ruff + the Tier-1 regression / docs-folder guard on every commit.

See `docs/development/CONTRIBUTING.md` for the full flow.

**Nightly autonomous sweeper:** `filings-nightly-sweep` cron runs 06:00 UTC daily, picks up to 5 eligible issues (autonomy `safe`, status `open` or `partially-resolved`) from `docs/known-issues/` fragment frontmatter, auto-merges on green CI, and writes a morning-review digest to `.claude/sweep-digests/`. Gated by `SWEEP_FORCE=1` in Render's `filings-claude-secrets` env group; unset (or set to anything else) to pause. See `docs/operations/nightly-sweep-runbook.md` and the `/sweep` skill for manual runs. The rollup `docs/KNOWN_ISSUES.md` is not tracked in git — CI regenerates it as a build artifact on every run (see `.github/workflows/ci.yml` job `known-issues-artifact`).

**Known-issues fragments use `gh-<issue>-<slug>.md`** — server-allocated GitHub issue numbers, no local coordination, no collisions. The validator rejects any new `legacy-*` filename; the frozen set lives in `docs/known-issues/.legacy-allowlist.txt`. See `docs/development/CONTRIBUTING.md` and `.claude/commands/commit-proj.md` step 9.

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

PostgreSQL. V2 tables: `v2_documents`, `v2_segments`, `v2_metric_facts`, `v2_metric_definitions`, `v2_image_assets`, `v2_image_review_decisions` (legacy, read-only), `v2_image_metric_confirmations`, `v2_image_classifications`, `v2_text_metric_presence`, `v2_tables`, `v2_audit_log`, `v2_ingest_batches`, `v2_ingest_batch_filings`, `model_training_runs`. Auth tables (Stage A / PR-A1): `auth_users`, `auth_sessions`, `auth_access_entries`, `auth_legacy_aliases`, `feature_flags`, `admin_audit_log`. Operator scripts: `scripts/seed_auth_users.py` and `scripts/seed_auth_legacy_aliases.py` seed allowlist + aliases; `scripts/auth_readiness_report.py` is the pre-flip readiness check (`--check` returns exit 0 if Stage-B-ready); `scripts/backfill_legacy_reviewer_aliases.py` sets `user_id` on historical rows via alias mappings (`--preview` to inspect counts, `--apply --confirm` to execute). See `docs/operations/auth-stage-b-runbook.md` (Stage B) and `docs/operations/auth-stage-c-runbook.md` (Stage C enforcement). Post PR-A5, the OAuth login flow auto-provisions/activates `auth_users` rows on first successful login (`ON CONFLICT (normalized_email) DO UPDATE` keyed off `normalized_email`, NOT `google_sub` — seeded rows have NULL `google_sub` until first login); login/logout/denial events write `admin_audit_log` rows. The OAuth blueprint at `/auth/*` is registered conditionally on `feature_flags.google_login_enabled` (read once at app boot — flag flips need a deploy/restart); route-level enforcement on existing routes still uses the legacy `FILINGS_API_KEY` gate and migrates in Stage C / PR-C1. The reviewer/ingest tables `v2_review_decisions`, `v2_image_metric_confirmations`, and `v2_ingest_batches` gained a nullable `user_id UUID REFERENCES auth_users(id)` column in the same migration; population begins in Stage C. `v2_image_metric_confirmations` additionally has `override_reason TEXT` and `supersedes_confirmation_id UUID` (PR #597) used by the admin review tool at `/admin/review` — non-null `override_reason` marks a row as an admin action; `supersedes_confirmation_id` points at the reviewer row being reversed (CHECK constraint enforces `supersedes IS NULL OR override_reason IS NOT NULL`). See `docs/operations/admin-review-runbook.md`. `v2_audit_log.user_id` was added in a later timestamp migration (gh-520) — same shape, populated in `src/web/middleware.py::insert_audit_log_entry` from `flask.g.user.id`; the service-account sentinel (`00000000-0000-0000-0000-000000000000`) is seeded into `auth_users` so the FK can hold it for `Authorization: ApiKey` requests. See `docs/architecture/auth-rollout-implementation-plan.md`. Shared: `companies`, `filings`. V1 review tables (`review_candidates`, `source_segments`, `suppressed_candidates`, `review_decisions`, `learned_patterns`, `review_audit_log`) are retired — drop migration at `sql/31_drop_v1_review_tables.sql`. Schema files in `sql/` — legacy integer-prefix range `00-47` is frozen; new migrations use timestamp filenames (`YYYYMMDDHHMM_description.sql`) generated by `scripts/new_migration.py`, see `.claude/rules/sql.md`. See `.claude/rules/infrastructure.md` when editing infra, Docker, or requirements files.

Image bytes live in Cloudflare R2 (prod) / local filesystem (dev) via `src/infra/image_storage.py`, NOT in Postgres. `v2_image_assets.file_path` stores an opaque storage key (e.g. `pipeline/<cik>/<accession>/<filename>`) — see `.claude/rules/infrastructure.md#image-storage`.

Filing HTML persists the same way via `src/infra/filing_storage.py` (gh-300). `filings.html_storage_path` stores an opaque storage key (e.g. `filings/<cik>/<accession>/primary.htm`). Post-gh-315, the fetcher writes R2 keys directly on every successful fetch; extraction resolves via R2 key or legacy filesystem path (the `html_content` DB-blob fallback was dropped in gh-314). See `.claude/rules/infrastructure.md#filing-html-storage`.

Image-relevance retrain artifacts (model joblib + report + training CSV) persist the same way via `src/infra/model_storage.py` (gh-391). `model_training_runs.model_path` / `report_path` store opaque storage keys (e.g. `models/image_relevance/<run_id>/relevance_model.joblib`); a `models/image_relevance/latest_run_id.txt` pointer drives the loader. See `.claude/rules/infrastructure.md#model-artifact-storage`.

## Testing Standards

- **Coverage**: 80% minimum (enforced)
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
- **Tier 1 presence-recall regression = blocker** under the text-presence pivot (PR #182, PR2 — `docs/operations/text-pipeline-presence-pivot-plan.md`). Enforced by `compare_to_baseline` in `src/gold_standard/baseline.py`, fired by `python3 -m src.gold_standard.v2_validator --fail-on-regression` (local pre-commit hook + CI). The gate uses `tier1_presence_recall` on `data/gold_standard/v2_baseline.json`. **Re-run-on-fail retry (gh-273):** the gate is zero-tolerance, but on first regression the validator re-runs the corpus once and only blocks if the second run also regresses. This automates the manual re-run-once protocol for cache-turnover noise; a real flaky regression that intermittently clears WILL be hidden by this retry. The bet is that real production code regressions are stable across two runs and cache-turnover regressions are not.
- Tier-1 fact-recall + per-company fact-recall + chart presence_f1 are still computed and printed but are **informational only** — they no longer set `has_regression`. The pivot's primary scoring surface is per-(document, metric) presence detection; fact emission is advisory evidence.
- Tier 2 regression = acceptable trade-off if Tier 1 improves; note in PR description
- Extraction improvements (keywords, FP rules, value binding) should prioritize Tier 1 recall gaps first
- Gold standard coverage expansion should target Tier 1 metrics with low coverage
- Tier definitions live in `config/metric_keywords.yaml` (authoritative) and `src/gold_standard/v2_validator.py` (runtime)
- **Phase-2 LLM presence classifier gate** (`scripts/run_phase2_quantitative_eval.py`) must pass (exit 0, go_no_go=GO) before flipping `presence_classifier_enabled` in production; run `python3 scripts/run_phase2_quantitative_eval.py --dry-run --gold-only` to validate corpus/label plumbing without API calls. See `docs/operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md`.

## Core Design Principles

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives. Chart signals are presence-only — the chart pipeline writes `(metric_id, score)` pairs to `v2_image_assets.detected_metrics` (keyword rules) and `v2_image_classifications.predicted_metrics` (Vision classifier, when `ENABLE_METRIC_CLASSIFY=true`). Reviewers confirm metric coverage per image via `v2_image_metric_confirmations` (accept / reject / correct / add / skip). An accept/correct/add promotes a value-less chart `v2_metric_facts` row (one per `(filing_id, metric_id)`, `review_status='accepted'`); reject/skip/undo roll it back when no other accepting confirmation remains. A "Reject all (no relevant metrics)" decision on an image with zero keyword-detected metrics writes a sentinel `v2_image_metric_confirmations` row with NULL `detected_metric_id` and NULL `confirmed_metric_id` (decision `'reject'`, rejection_reason `'no_relevant_metrics'`) so the ML training signal is preserved; sentinel rows do not promote a fact row (`_promote_chart_fact` early-returns on NULL `metric_id`). Values, when CMASB needs them, come through the existing manual entry path (`POST /api/v2/missed-metric`). The pipeline does not auto-emit per-value chart `v2_metric_facts` rows at extraction time (chart-presence pivot, #86, 2026-04-23). Table-image presence (TABLE_IMAGE assets scored via `score_ocr_table`) flows through the same `v2_image_assets.detected_metrics` JSONB column — not a separate stream.
5. **Image pipeline is active**: Do not delete image-processing code (`src/llm/vision_client.py`, `src/extraction_v2/` image/OCR stages, `src/web/routes/review_unified.py` + `api_unified.py` image endpoints, image scripts). The image review system is complete and in use.
6. **Reviewed-filing guard**: Re-extraction of a filing with human review decisions requires explicit `force=True` / `--force-reextract`. Enforced in `V2PersistenceAdapter._persist_facts_in_tx` (text-fact `v2_review_decisions`) and by a secondary check on `v2_image_metric_confirmations` in the same method; `_persist_images_in_tx` additionally blocks re-classification of confirmed images into a hidden class. All three raise `ReviewedFilingError` otherwise. Prevents silent CASCADE-destruction of reviewer work via `v2_review_decisions.fact_id ON DELETE CASCADE`.

## Hooks

A PreToolUse hook nudges `/simplify` when 3+ files are modified before `/commit-proj` (or `/commit-user`) — see `.claude/hooks/precommit-simplify-check.sh`.

## Compact Instructions

When compacting, preserve: modified file paths, current test/gold-standard validation status, extraction pipeline decisions made this session, and any active task checklist.
