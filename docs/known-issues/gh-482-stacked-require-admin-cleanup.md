---
id: 482
source: gh
slug: stacked-require-admin-cleanup
title: "auth: remove stacked @require_admin from retrain/analysis endpoints (PR-C1 cleanup)"
status: open
severity: low
autonomy: skip
estimated: S
touches:
  - src/web/routes/api_unified.py
  - src/web/middleware.py
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 482
pr_refs:
  - 479
note: four admin endpoints carry both @require_admin and @require(INGEST_RUN); remove the legacy decorator once Stage-C enforcement has soaked
---

### Problem

PR-C1 (#479) added `@require(INGEST_RUN)` to four admin-style endpoints in `src/web/routes/api_unified.py` (`/models/image-classifier/retrain`, `/extraction/analyze-text-decisions`, `/extraction/recommendation-decisions` POST + DELETE) but left the legacy `@require_admin` decorator stacked above them to avoid behavior changes during the transition. Both gates resolve to admin-only, so they're functionally redundant once `auth_enforcement_enabled=true`. `require_admin`'s docstring explicitly says it is meant to be replaced 1:1 by `@require('<permission>')` once Stage A2 lands — Stage A2 has shipped, so this cleanup is unblocked.

### Next Steps

- After Stage-C enforcement has been live for at least one soak window, remove `@require_admin` from the four endpoints above.
- Confirm no other call sites still use `require_admin`; remove the import where it's the only consumer.
- If `ADMIN_USER_IDS` env var is no longer read anywhere, delete `require_admin` from `src/web/middleware.py` entirely.
