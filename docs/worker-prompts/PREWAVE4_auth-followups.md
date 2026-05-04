You are the implementer for **pre-Wave-4 auth follow-ups**: a single bundled PR that addresses four issues identified during the Wave-3 critical evaluation. None are ship-blockers, but they materially harden the surface before PR-A8 (readiness report) lands and before Stage C migrates routes to `require(<permission>)`. Bundle them — they all touch auth code, share review eyes, and total well under 200 LOC.

Read the entire prompt before doing anything.

## Source of truth (read these first, in order)

1. `docs/architecture/auth-rollout-implementation-plan.md` — authoritative PR catalog. This PR is "Wave 3.5" — a follow-up bundle, not a labeled-A entry. Note it in the doc only if you choose to (optional).
2. `docs/requirements/review-ui-authorization-spec.md` — authoritative requirements. Especially **§Auditing Requirements** (Fix 3) and **§Development and Test Environment Strategy** (Fix 1).
3. `CLAUDE.md` (project root) — Pre-Implementation Gate, Implementation Rules, Workflow.
4. `~/.claude/CLAUDE.md` (global) — Pre-Implementation Gate item 6 (worktree mandatory for 3+ files), Implementation Rules ("execute ONLY specified steps").
5. Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
6. `docs/worker-prompts/WAVE3_auth-oauth.md` — for context on what Wave 3 was supposed to ship and what actually landed (the four issues below were surfaced in the post-merge eval).

## What's done

- **PR-A1 (#403)** — schema foundation.
- **Wave 2** — A2/A3/A4/A6/A7 (PRs #409–#414, all merged 2026-05-01).
- **Wave 3 / PR-A5 (#423, merged 2026-05-02)** — Google OAuth Authorization-Code-with-PKCE flow, gated by `google_login_enabled=false` (off by default).

## What this PR ships

A single PR with four scoped changes. **Branch:** `claude/auth-prewave4-followups`.

---

### Fix 1 — Wire `dev_bypass_user()` into `load_session_user`

**File (modify):** `src/auth/load_user.py`.

**Why.** A6 (#409) and A5 (#423) left `dev_bypass_user()` callable but unwired. The moment Stage C migrates routes to `require(<permission>)`, dev environments will break — `g.user` is always `None` unless the developer goes through Google login locally. Production is protected by `verify_dev_bypass_safe()` at app boot (it raises if `APP_ENV=production` AND `AUTH_DEV_BYPASS=1`), so the bypass cannot leak to prod.

**Change.** After the idempotency guard (`if "user" in g: return`), and **before** the cookie lookup, add a short-circuit:

```python
from src.auth.dev_bypass import dev_bypass_user, is_dev_bypass_enabled

# (inside load_session_user, after the idempotency guard)
if is_dev_bypass_enabled():
    g.user = dev_bypass_user()
    return
```

Place the bypass check before the cookie lookup so a stale dev cookie doesn't override bypass. Tests that monkeypatch `g.user` directly are unaffected (the idempotency guard runs first).

**Test:** `tests/integration/auth/test_load_session_user.py` — add three cases:

1. `AUTH_DEV_BYPASS=1` set, no cookie present → `g.user.id == DEV_BYPASS_USER_ID`, `g.user.role == 'admin'`.
2. `AUTH_DEV_BYPASS=1` set, stale cookie present → bypass still wins, `g.user.id == DEV_BYPASS_USER_ID` (no DB lookup happens).
3. `AUTH_DEV_BYPASS` unset, no cookie → existing behavior, `g.user is None`.

Use `monkeypatch.setenv("AUTH_DEV_BYPASS", "1")` and `monkeypatch.delenv("AUTH_DEV_BYPASS", raising=False)`.

---

### Fix 2 — `last_login_at` ordering bug in OAuth callback

**File (modify):** `src/web/routes/auth.py`.

**Why.** Today a disabled user attempting to log in has `last_login_at` updated by `_upsert_user(...)` *before* the account-status check rejects them. Data-quality bug; not security, but pollutes "last attempted login" semantics — a row that shows a recent `last_login_at` looks active when in fact the user has been blocked at every attempt.

**Change.** In the `callback()` handler (around line 558 — after the `pre_rows = db.query(...)` SELECT), check the pre-row's `account_status` BEFORE upserting:

```python
pre_row = pre_rows[0] if pre_rows else None

# Account-status check happens BEFORE upsert so a disabled user's
# last_login_at is not silently bumped on every denied attempt.
if pre_row is not None and pre_row["account_status"] != "active":
    _audit_login(
        action_type=_ACTION_LOGIN_DENIED,
        success=False,
        error="account_disabled",
        actor_user_id=pre_row["id"],
        actor_email=normalized_email,
    )
    return _redirect_to_denied("account_disabled")

user_row = _upsert_user(...)

# (Drop the post-upsert account_status check — the upsert SET clause
# never touches account_status, so a row that was active pre-upsert is
# still active post-upsert; a row that was disabled was already denied.)
```

**Verify the upsert SQL invariant.** Re-read `_upsert_user` to confirm the `ON CONFLICT (normalized_email) DO UPDATE SET ...` clause does not include `account_status`. (At PR-A5 merge time it does not.) If a future change ever adds `account_status` to the SET clause, the post-upsert check would need to come back; flag this in a code comment so future readers don't silently break the invariant.

**Test:** existing `test_disabled_user_denied` in `tests/integration/auth/test_oauth_flow.py` — extend to assert that `last_login_at` is unchanged (or NULL on first attempt) after the denial. Use the pattern:

```python
# Before the disabled login attempt
pre_last_login = oauth_app_db.query(
    "SELECT last_login_at FROM auth_users WHERE normalized_email = %s",
    [disabled_user_email],
)[0]["last_login_at"]

# ... perform the disabled login attempt that we expect to deny ...

post_last_login = oauth_app_db.query(...)[0]["last_login_at"]
assert pre_last_login == post_last_login  # not bumped by denial
```

---

### Fix 3 — Populate `target_entity` in `_audit_login`

**File (modify):** `src/web/routes/auth.py`.

**Why.** Spec §Auditing Requirements says admin audit entries "must capture" target. The seed script `scripts/seed_auth_users.py` already follows this pattern (`_audit(target_entity=ne, ...)` writes the normalized email). The OAuth callback's `_audit_login` helper hard-codes `target_entity = NULL`, leaving login events less queryable than seed events. Tiny change, large readability dividend.

**Change.** In `_audit_login(...)`:

```python
target_entity = actor_email or actor_user_id  # email first per seed-script precedent

db.execute(
    """
    INSERT INTO admin_audit_log (
        actor_user_id,
        actor_email,
        action_type,
        target_entity,
        before_state,
        after_state,
        success,
        error
    ) VALUES (
        %(actor_user_id)s,
        %(actor_email)s,
        %(action_type)s,
        %(target_entity)s,    -- was: NULL
        %(before_state)s::jsonb,
        %(after_state)s::jsonb,
        %(success)s,
        %(error)s
    )
    """,
    {
        ...,
        "target_entity": target_entity,
        ...
    },
)
```

For denial paths where neither `actor_email` nor `actor_user_id` is known (state mismatch, callback error before token validation), `target_entity` resolves to `None` — that's correct.

**No-break risk verified at planning time.** `grep -rn "target_entity" tests/` shows only `tests/integration/auth/test_seed_scripts.py` reads the column, and it never asserts NULL on it. Fix 3 cannot silently break an existing test.

**Test:** in `test_oauth_flow.py`, add `assert row["target_entity"] == normalized_email` to the success-path and known-email-denial-path audit assertions. For denial paths where actor_email is NULL (state mismatch, missing-code), assert `target_entity is None`.

---

### Fix 4 — Test coverage gaps

Two test additions, both in unit tests. Do not add integration tests — the eval flagged a missing nonce-replay integration test on first read but it's redundant: replayed callbacks fail state-mismatch first (state is popped on first callback), and unit-level nonce coverage in `test_oidc_validate.py` already exists.

**File (modify):** `tests/unit/auth/test_oidc_validate.py`.

Add a parametrized test that `validate_id_token` rejects a token with the wrong `aud`. Stub `google.oauth2.id_token.verify_oauth2_token` to raise `ValueError("Could not verify token signature")` — the exact exception google-auth produces on `aud` mismatch. Assert `OidcValidationError` with `reason == "oauth_id_token_invalid"`.

Why: pins behavior that future google-auth library upgrades could regress. Currently this code path is delegated entirely to the library; an explicit test guards against silent semantic drift.

**File (modify):** `tests/unit/auth/test_feature_flags.py`.

Add a test that a row with `value='true'` and `expires_at < NOW()` returns `False` from `is_enabled()`. Two ways to write it:

1. Insert a row directly into `feature_flags` with `expires_at = NOW() - INTERVAL '1 minute'`, then call `is_enabled()` and expect False.
2. Mock `_read_flag_from_db` to return what the SQL filter would return (no rows for an expired flag) and assert `is_enabled()` returns False.

Option 1 exercises the actual SQL filter — preferred.

Why: spec §Emergency Legacy Fallback's post-May-10 break-glass override hinges on `expires_at` enforcement. Currently the SQL filter (`expires_at IS NULL OR expires_at > NOW()`) is implemented in `_read_flag_from_db` but never asserted. Pinning it now prevents silent breakage when Stage D's emergency path is exercised.

---

## Out of scope (do NOT expand into)

- **Stage B operator runbook.** Lives with A8 (Wave 4) since A8's readiness report is the runbook's primary consumer.
- **Login CSRF protection.** Minor, not exploitable for account takeover. Defer.
- **Audit-row noise on logout-with-no-session.** Cosmetic. Defer.
- **`feature_flags` row seeding for `google_login_enabled`.** Stage B's flip is an operational INSERT + restart, not a code change.
- **Anything Stage C** (route migration to `require()`, same-origin API-key bypass removal, `auth_enforcement_enabled` flip, backfill).
- **Wave 4 (PR-A8 readiness report).** Different prompt, different session.

If you spot another Wave-3 issue while implementing, file as `gh-N-<slug>` per `.claude/commands/commit-proj.md` step 9 — don't expand the PR.

## Pre-implementation gate

This PR touches 5 files (3 src, 2 tests modified) — past the 3-file threshold AND involves auth-adjacent changes. Run the full Pre-Implementation Gate from `~/.claude/CLAUDE.md`:

1. **Assumption audit.** Verify each assumption against current code:
   - `src/auth/load_user.py` — confirm the idempotency guard is at the top and that `from src.auth.dev_bypass import ...` doesn't create a circular import.
   - `_upsert_user` SQL in `src/web/routes/auth.py` — confirm the `ON CONFLICT (normalized_email) DO UPDATE SET ...` clause does NOT include `account_status` (Fix 2's safety hinges on this).
   - `_audit_login` signature in `src/web/routes/auth.py` — confirm `actor_email` is already a kwarg.
   - `tests/integration/auth/test_load_session_user.py` and `test_oauth_flow.py` — confirm fixtures (`auth_db_clean`, `oauth_app`, `stub_google_oauth`) are reusable for the new cases.
2. **Scope check.** Confirm only the listed files are touched. The four fixes are the entire PR; no tidying.
3. **Rules compliance.** Worktree (yes — touches 5 files), `/commit-proj` for the PR, conventional commit message, no `--no-verify`, no force-push to main.
4. **Risk assessment.** Specific risks:
   - **Circular import** between `src/auth/load_user.py` and `src/auth/dev_bypass.py`. `dev_bypass.py` imports `SessionUser` from `src/auth/sessions.py`; `load_user.py` already imports from `sessions.py`. Adding `dev_bypass` import to `load_user` is fine (no circular path).
   - **Test isolation** — `monkeypatch.setenv` resets between tests; verify the env-var leakage pattern doesn't bleed between tests by running the load_user test file twice in a row (`pytest tests/integration/auth/test_load_session_user.py -x -q && pytest tests/integration/auth/test_load_session_user.py -x -q`).
   - **`pre_row["account_status"]` access** in Fix 2 — confirm the SELECT in `pre_rows = db.query(...)` includes `account_status` in the column list. If not, extend the SELECT.
   - **`last_login_at` test assertion** in Fix 2 — first-attempt denial means `pre_row` is None and the early check is skipped, so the upsert runs anyway. If you want this case to also not bump `last_login_at`, the change is bigger (you'd need to skip the upsert entirely for first-attempt denials). The eval flagged the existing-disabled-user case specifically; first-attempt denials of someone-not-yet-in-auth_users aren't really a "last login" issue because the row is freshly created. Scope: keep the fix narrow — only the existing-disabled-user case.
5. **Minimal path.** Five-file change, no new files. Already minimal.
6. **Worktree check.** `EnterWorktree` or `ccw claude/auth-prewave4-followups` before any edits.

Present the completed gate checklist for orchestrator (user) approval before implementing.

## Workflow

1. Worktree-first.
2. Pre-implementation gate (above), present, wait for approval.
3. Implement in this order (smallest-change-first to keep diffs reviewable):
   - Fix 3 (target_entity) — single-line change in `_audit_login` plus test assertions.
   - Fix 2 (last_login_at) — block move + drop redundant check + test extension.
   - Fix 1 (dev_bypass wiring) — small addition to `load_session_user` + new tests.
   - Fix 4 (test additions) — two unit tests.
4. Run `pytest -x -q tests/unit/auth/ tests/integration/auth/` locally — must be green before commit.
5. `/commit-proj`. Out-of-scope triage step in `/commit-proj` — flag any unrelated issues found while implementing.
6. Auto-merge enabled via `gh pr merge --auto --squash`.
7. After merge, report:
   - PR number + commit SHA.
   - Confirm `pytest -x -q tests/unit/auth tests/integration/auth` is green on `origin/main`.
   - Recommend the next move: **Wave 4 = PR-A8 readiness report**, planning to be done in a separate session.

## Risks worth flagging at execution time

- **Circular import.** If `from src.auth.dev_bypass import ...` at module top of `load_user.py` causes a circular import (it shouldn't, but worth checking), do the import inside `load_session_user()` instead — the function-local import pattern is already used in `src/web/app.py:233` (`from src.auth.dev_bypass import verify_dev_bypass_safe`) for the same reason.
- **Pre-existing test failure (gh-262).** `test_e2e_persistence_roundtrip` is known-failing and unrelated to this PR. If your `pytest -x -q` stops on it, run `pytest --deselect tests/path/to/that_test.py` or skip past it for the auth-tests-only run.
- **No new env vars.** This PR doesn't introduce any new env vars or `feature_flags` rows. `.env.template` and Render env-group are untouched.

## What you (implementer) do NOT do

- Do not flip any feature flag.
- Do not modify the spec or the implementation plan doc except to record `[DECISION]` resolutions or correct factual errors discovered during implementation.
- Do not add Stage-B operator documentation (that's Wave 4).
- Do not migrate any existing routes to `require()` (that's Stage C).

Good luck.
