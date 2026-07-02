---
id: 481
source: gh
slug: route-enforcement-integration-test
title: "auth: add tests/integration/auth/test_route_enforcement.py (deferred from PR-C1)"
status: archived
severity: low
autonomy: skip
estimated: M
touches:
  - tests/integration/auth/test_route_enforcement.py
discovered: 2026-05-04
updated: 2026-05-07
gh_issue: 481
pr_refs:
  - 479
  - 519
note: Integration suite shipped in PR #519 (`315e68a8`, "test(auth): integration suite for @require flag-on enforcement (gh-481)"); `tests/integration/auth/test_route_enforcement.py` exists on main. Fragment was stale — pr_refs never updated past the deferral PR.
---

### Problem

PR-C1 (#479) added `@require(<perm>)` to 39 routes across 6 modules. The brief required `tests/integration/auth/test_route_enforcement.py` to exercise the flag-on enforcement contract end-to-end against a real DB, but the test was deferred — unit tests in `tests/unit/auth/test_require_flag_aware.py` and `test_legacy_session_bound.py` already pin the decorator behavior in isolation. Without an integration suite, removing a decorator or wiring the wrong permission on a future route would not be caught by tests.

### Next Steps

- For each protected route module (`api_unified`, `api_ingest`, `ingest`, `review_unified`, `review_pres_images`, `image_cache`): assert that an unauthenticated request returns 401/redirect, viewer→`decision.write` returns 403, reviewer→`decision.undo.any` returns 403, admin→200, with `auth_enforcement_enabled=true` forced via monkeypatch.
- Use the dev-bypass route or monkeypatch to set `g.user`; force `feature_flags.is_enabled('auth_enforcement_enabled')=True` per test via the same fixture pattern as `tests/unit/auth/test_middleware.py`.
- Run via `pytest tests/integration/auth/test_route_enforcement.py` and ensure CI's Integration Tests job picks it up.
