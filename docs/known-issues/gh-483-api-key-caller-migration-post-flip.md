---
id: 483
source: gh
slug: api-key-caller-migration-post-flip
title: "auth: API-key-caller migration plan for post-flip (Stage D adjacent)"
status: resolved
severity: medium
autonomy: skip
estimated: M
touches:
  - src/auth/service_account.py
  - src/auth/load_user.py
  - src/web/app.py
  - tests/unit/auth/test_load_api_key_user.py
  - tests/deployment/test_smoke.py
  - docs/operations/auth-stage-c-runbook.md
discovered: 2026-05-04
updated: 2026-05-05
gh_issue: 483
pr_refs:
  - 479
note: shipped Option A — load_api_key_user() before_request hook in src/auth/load_user.py synthesizes an admin SessionUser (src/auth/service_account.py) for valid-API-key requests so post-flip @require() decorators pass; runbook §4 claim is now accurate, smoke tests re-enabled
---

### Problem

PR-C1 (#479) replaced the blueprint-wide `register_api_auth` gate with per-route `@require(<perm>)` decorators that read `g.user`. `_verify_api_key()` validates the API key but does not populate `g.user`, so once `auth_enforcement_enabled=true`, a valid `Authorization: ApiKey ...` request to `/api/v2/*` is rejected by `@require()` with a 401. The Stage-C runbook (`docs/operations/auth-stage-c-runbook.md`) currently claims "API-key-only callers still work via Authorization: ApiKey header" in the post-flip verification — that claim only holds if a service-account bridge is added before the flip. The smoke test `tests/deployment/test_smoke.py::TestApiAuth::test_api_accepts_valid_key` will fail post-flip without it.

### Next Steps

- Pick one of three options before the operator flips the flag: (1) service-account bridge in `_verify_api_key()` that synthesizes a `SessionUser` when api-key validates, (2) migrate external callers to session tokens via OAuth or a service-account login, or (3) drop the api-key path entirely (Stage D scope).
- Audit external callers: Render cron jobs (nightly sweeper, onboarding watcher) and any hand-rolled integrations against `/api/v2/*`.
- Update `docs/operations/auth-stage-c-runbook.md` post-flip-verification step to reflect the chosen option.
- Re-enable the smoke tests at `tests/deployment/test_smoke.py::TestApiAuth` (currently `pytest.skip`'d with a pointer to this issue).
