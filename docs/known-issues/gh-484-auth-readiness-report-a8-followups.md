---
id: 484
source: gh
slug: auth-readiness-report-a8-followups
title: "auth: three A8 follow-ups in auth_readiness_report.py"
status: resolved
severity: low
autonomy: skip
estimated: S
touches:
  - scripts/auth_readiness_report.py
  - tests/unit/auth/test_readiness_report.py
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 484
pr_refs:
  - 479
note: dev-bypass guard checks local env not prod, dev-bypass predicate duplicated instead of imported, JSON serialization only tested with empty data
---

### Problem

Three minor issues in `scripts/auth_readiness_report.py` were surfaced during the Wave-4 critical eval and explicitly deferred out of Stage C per the orchestrator brief. (1) `--check` reads dev-bypass env vars from the local environment running the script — when operators run from a dev machine before flipping the flag, the check passes locally even if dev-bypass would be on in prod. (2) The dev-bypass predicate is re-implemented inline rather than importing `src.auth.dev_bypass.is_dev_bypass_enabled()`; the two implementations could drift. (3) Unit tests for `--json` output only exercise the empty-DB case — schema or serialization regressions in the populated case won't be caught.

### Next Steps

- Add a `--target-env` flag that reads env vars from a deploy config (or document the limitation and tell operators to run `--check` from inside the production container).
- Replace the inline dev-bypass predicate with `from src.auth.dev_bypass import is_dev_bypass_enabled` and a single call.
- Add a unit test that seeds 2-3 `auth_users` and 1-2 `auth_legacy_aliases`, runs `--json`, and asserts the output shape matches the expected schema.

### Resolution

- Issue 1: Added stderr warning in `--check` mode when `APP_ENV != 'production'`; updated `--check` help text and `docs/operations/auth-stage-b-runbook.md` with operator guidance to run from inside the prod container.
- Issue 2: Replaced inline bypass predicate in `evaluate_dev_bypass_guard()` with a call to `is_dev_bypass_enabled()` imported from `src.auth.dev_bypass`. JSON output shape unchanged.
- Issue 3: Added `test_populated_json_shape` integration test seeding 3 users + 2 aliases and asserting all six top-level JSON keys and sub-field sets. Tests live at `tests/integration/auth/test_readiness_report.py` (the fragment cited a non-existent unit-test path — integration path is correct per `.claude/rules/scripts.md`).
