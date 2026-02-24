# Codex Production Readiness Master Spec (Best-of-Best)

## Status
- Version: 1.0
- Date: 2026-02-24
- Owner: Engineering
- Supersedes: `docs/production_readiness_specs/*` and `docs/WORKER_PROMPT_PRD-1.md` through `docs/WORKER_PROMPT_PRD-4.md`

## Purpose
This package is the canonical execution plan for production hardening of the filings reviewer platform. It combines:
1. The system hardening depth of the production readiness workstreams.
2. The measurable quality gate discipline from the PRD worker prompts.
3. A single, conflict-resolved dependency and release model.

## What Changed vs Prior Plans
1. Migration strategy is now strictly forward-only everywhere, including test initialization.
2. One canonical V2 production runner is required (`run_v2_batch_extraction.py`) with resumability and explicit failure handling; default mode is safe (`--workers 1`).
3. Legacy V1 work is constrained to compatibility and de-risking only; no net-new V1 production features.
4. Extraction quality parity (F1/precision/recall/runtime) is a first-class release gate.
5. Engineering rigor is standardized with global gates, RWLO loops, and required evidence artifacts.

## File Index
1. `00_GOVERNANCE_AND_GLOBAL_GATES.md`
2. `01_WS-01_MIGRATION_SAFETY.md`
3. `02_WS-02_WEB_AUTH_ALIGNMENT.md`
4. `03_WS-03_AUDIT_LOGGING_RESILIENCE.md`
5. `04_WS-04_REVIEW_QUERY_SCALABILITY.md`
6. `05_WS-05_V2_BATCH_ORCHESTRATION_AND_DOCS.md`
7. `06_WS-06_V2_PERSISTENCE_THROUGHPUT.md`
8. `07_WS-07_TEST_RELIABILITY_AND_CI_GATES.md`
9. `08_WS-08_OCR_IMAGE_PATH_ROBUSTNESS.md`
10. `09_WS-09_DB_ADAPTER_MODULARIZATION.md`
11. `10_WS-10_EXTRACTION_QUALITY_PARITY_GATE.md`
12. `11_PARALLEL_EXECUTION_AND_DEPENDENCIES.md`
13. `12_RWLO_EXECUTION_INSTRUCTIONS.md`
14. `13_PR_TEMPLATE_AND_EVIDENCE_CHECKLIST.md`

## Execution Order
Use `11_PARALLEL_EXECUTION_AND_DEPENDENCIES.md` for staffing and merge sequencing. All workstreams must follow `12_RWLO_EXECUTION_INSTRUCTIONS.md`.

## Production Cutover Rule
No production cutover is allowed until global gates in `00_GOVERNANCE_AND_GLOBAL_GATES.md` are satisfied.
