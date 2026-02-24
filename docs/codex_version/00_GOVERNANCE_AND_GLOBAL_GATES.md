# 00 - Governance and Global Gates

## Objective
Define non-negotiable engineering rigor for all production-readiness workstreams.

## Core Principles
1. Safety first: no destructive data behavior in default production paths.
2. Determinism first: reruns must be idempotent unless explicitly documented otherwise.
3. Observability first: every new high-risk path must emit measurable health signals.
4. Rollback first: each change requires explicit rollback instructions.
5. Evidence first: acceptance criteria require reproducible artifacts.

## Global Non-Negotiables
1. Database migrations must be forward-only in production and CI pathways.
2. Browser review flows must use session + CSRF auth in production mode.
3. Request success paths must not be blocked by non-critical writes (for example audit logging).
4. Review APIs/routes must avoid unbounded full-list loads by default.
5. Canonical production extraction flow must be V2 batch orchestration.
6. Test suite must include production-like auth, failure-injection, and scalability coverage.
7. Extraction quality must meet explicit parity thresholds before release.

## Global Performance and Reliability Budgets
1. Review endpoint p95 latency budget under normal load must be defined and tracked per endpoint.
2. Audit logging degradation must not consume business request latency beyond configured timeout budget.
3. V2 persistence throughput must materially improve over baseline and preserve idempotency.
4. V2 extraction runtime guardrail: target <30s median per filing on standard benchmark fixture set.

## Required Evidence Artifacts
1. `artifacts/readiness/migrations.md` with idempotency, checksum drift, and rollback proof.
2. `artifacts/readiness/auth.md` with V1/V2/image browser flow proof in production config.
3. `artifacts/readiness/scalability.md` with explain plans and large-fixture behavior.
4. `artifacts/readiness/orchestration.md` with interruption/resume/retry evidence.
5. `artifacts/readiness/performance.md` with before/after throughput and runtime deltas.
6. `artifacts/readiness/quality.md` with gold-standard precision/recall/F1 and runtime results.
7. `artifacts/readiness/release-checklist.md` summarizing all gates.

## Release Gates
1. Gate A - Safety and Security: WS-01, WS-02, WS-03, WS-04, WS-08 merged and validated.
2. Gate B - Scale and Throughput: WS-05 and WS-06 merged; staged batch dry-run completed.
3. Gate C - Reliability and Quality: WS-07 and WS-10 green in CI/scheduled suites.
4. Gate D - Operability: rollback/runbook/docs sign-off completed.

## Definition of Done (Global)
1. Workstream acceptance criteria are met with linked evidence.
2. Required tests pass at required tier (unit/integration/perf/gold).
3. Rollout and rollback instructions are complete and reviewed.
4. No unresolved Sev-1/Sev-2 defects in touched areas.

## Exclusions
1. No unplanned schema redesigns unless explicitly approved as follow-up work.
2. No broad framework rewrites during this hardening phase.
