# Auth Stage C — Staged Enforcement Activation Runbook

**Scope:** Operator runbook for activating auth enforcement (`auth_enforcement_enabled=true`).
This is the flip that makes authentication mandatory — do not proceed until all prerequisites
are met and both PR-C1 and PR-C2 have merged.
**Last updated:** 2026-05-04

---

## Status

| Item | Detail |
|------|--------|
| Stage A (foundation) | ✓ shipped (PRs #403, #409–#414, #423, #443) |
| Stage B (shadow mode) | ✓ shipped — see `docs/operations/auth-stage-b-runbook.md` |
| Stage C — PR-C1 (route migration + bypass removal) | Pending merge |
| Stage C — PR-C2 (backfill + runbook) | Pending merge |
| Stage C (enforcement flip) | Pending operator activation (this runbook) |
| Stage D (legacy retirement) | Future cycle — deadline 2026-05-10 |
| Authoritative spec | `docs/requirements/review-ui-authorization-spec.md` |
| Authoritative plan | `docs/architecture/auth-rollout-implementation-plan.md` |

---

## 1. Purpose

Stage C is **full enforcement**: routes now gate on `require(<permission>)` (PR-C1), the
same-origin API-key bypass has been permanently removed (PR-C1), and after this runbook's
flag flip `auth_enforcement_enabled=true`, every request to a protected surface requires a
valid session.

What changes when the flag flips:

- **Routes require authentication.** `require(<permission>)` decorators on every protected
  route become active. Unauthenticated requests receive 401 (JSON endpoints) or a redirect to
  `/auth/login` (HTML pages).
- **Role-based access is enforced.** `reviewer` cannot trigger ingest. `viewer` cannot write
  decisions. `admin` can do everything.
- **Same-origin API-key bypass is gone — permanently.** PR-C1 deleted this bypass from
  `src/web/middleware.py`. Browser traffic must authenticate via session cookie. There is no
  code path to restore the bypass without reverting the PR-C1 commit. See **Rollback** section
  for critical implications.
- **4-hour legacy-session bound.** Sessions created before this flip are forcibly invalidated
  at most 4 hours after the flag is set. After 4 hours all users must re-authenticate.
- **CSRF middleware activates.** Cross-origin POST requests to state-changing endpoints are
  rejected.

Existing API-key callers using `Authorization: ApiKey ...` headers continue to work; the
API key still authenticates non-browser clients that pass the header explicitly.

---

## 2. Prerequisites checklist

All items must be confirmed before proceeding to activation.

1. **PR-C1 merged.** Route migration + same-origin bypass removal + 4-hour legacy-session
   bound are live in production.

2. **PR-C2 merged.** This runbook and the backfill script (`scripts/backfill_legacy_reviewer_aliases.py`)
   are live in production.

3. **Stage B has soaked for at least 24 hours.** Every active reviewer has been able to log
   in under shadow mode. No lingering session or login issues reported.

4. **Every active reviewer has logged in at least once.** Verify via the readiness report:
   Section 2 shows non-NULL `last_login_at` for all `reviewer`-role rows. An enforcement
   flip before first login would lock out an active reviewer immediately.

   ```bash
   python3 scripts/auth_readiness_report.py
   # Check Section 2 — "Per-user login state". All reviewers should show
   # last_login_at as a timestamp, not "never".
   ```

5. **Backfill `--preview` run and inspected.** The script output should be reviewed before
   applying. Counts should match the number of historical `RGM` and `Mayu` decisions in the
   three target tables. Zero counts are also acceptable (means all rows were written
   post-Stage-B and already have `user_id` set).

   ```bash
   python3 scripts/backfill_legacy_reviewer_aliases.py --preview
   ```

6. **`auth_legacy_aliases` rows are present and active.** Check readiness report Section 4.
   Both `RGM` and `Mayu` aliases should appear with `active=True`. If missing, run
   `python3 scripts/seed_auth_legacy_aliases.py` first.

---

## 3. Activation steps

### Step 1 — Run the backfill

```bash
# Inspect preview first.
python3 scripts/backfill_legacy_reviewer_aliases.py --preview
# Review the output. Verify counts look reasonable (no unexpected zeros or large numbers).

# Apply. This is not reversible without manual SQL.
python3 scripts/backfill_legacy_reviewer_aliases.py --apply --confirm
```

Verify the audit log row was written:

```sql
SELECT action_type, before_state, after_state, created_at
FROM admin_audit_log
WHERE action_type = 'auth.backfill_legacy_aliases'
ORDER BY created_at DESC LIMIT 1;
-- expect: one row, after_state.dry_run = false, counts visible
```

### Step 2 — Run the readiness report (post-backfill)

```bash
python3 scripts/auth_readiness_report.py
```

Confirm:
- Section 1: all three users listed with valid roles.
- Section 2: all reviewers show non-NULL `last_login_at`.
- Section 4: both aliases present and active.
- Section 5: `auth_enforcement_enabled` absent or `value='false'` (about to flip).
- Section 6: dev-bypass guard is PASS.

### Step 3 — Flip `auth_enforcement_enabled`

```bash
psql "$DATABASE_URL" -c "
INSERT INTO feature_flags (key, value)
VALUES ('auth_enforcement_enabled', 'true')
ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW();
"
```

### Step 4 — Restart the Render web service

The flag is read at boot (for blueprint registration) but the `require()` decorator reads it
per-request via `is_enabled('auth_enforcement_enabled')`. Enforcement activates immediately
after the flag update — a restart is NOT strictly required for the enforcement itself, but
**restart anyway** to ensure the CSRF middleware and any other boot-time logic also activates
cleanly.

Render dashboard → filings-reviewer → Manual Deploy → Clear Cache & Restart.

### Step 5 — Smoke test

```bash
# Unauthenticated request should be rejected (401 or login redirect).
curl -I https://<prod-domain>/v2/review/
# expect: 302 redirect to /auth/login  (HTML page)

curl -I https://<prod-domain>/api/v2/decisions
# expect: 401 JSON

# Authenticated request via session cookie (get cookie value from browser).
curl -I -H "Cookie: <session-cookie>" https://<prod-domain>/v2/review/
# expect: 200
```

Then complete a manual browser review workflow:
- Log in as `rgmarkey@gmail.com`.
- Navigate to a filing review page.
- Accept or reject one decision.
- Verify the decision is persisted in the DB.

---

## 4. Verification (post-flip)

- **Normal reviewer workflow works.** A reviewer can log in, submit text decisions, and
  submit image confirmations without error.
- **API-key-only callers still work.** A second `before_request` hook
  (`load_api_key_user` in `src/auth/load_user.py`) populates `flask.g.user` with the synthetic
  admin service account from `src/auth/service_account.py` whenever the request carries a valid
  `Authorization: ApiKey <key>`, `X-API-Key` header, or `?api_key=` arg. Per-route
  `@require(<perm>)` decorators then see `role='admin'` and pass. Test with a known automation
  call. **Service-account scope.** The bridge resolves to `email='api-key@service.local'`,
  `id='00000000-0000-0000-0000-000000000000'`, `role='admin'`. The id is a sentinel — it
  does NOT exist in `auth_users`, so allowlist management does not affect API-key callers. To
  tighten scope (e.g. drop `ingest.run`), edit `_SERVICE_ACCOUNT.role` in
  `src/auth/service_account.py`. `v2_audit_log.session_id` is `NULL` for these calls (no Flask
  session) so they are identifiable as automation in retrospective queries.
- **Same-origin browser requests without session are rejected.** A `curl` without a session
  cookie to a protected endpoint returns 401 / 302.
- **Role restrictions work.** A `reviewer` cannot hit ingest endpoints (expects 403). A
  `viewer` cannot submit decisions (expects 403).
- **Legacy sessions expire within 4 hours.** Sessions that existed before the flag flip will
  be rejected at most 4 hours after `auth_enforcement_enabled` was set to `true`. Users will
  see a re-login prompt; this is expected behavior.
- **`/health` still returns 200** without authentication (public endpoint).

---

## 5. Rollback procedure

> **CRITICAL WARNING — read before rolling back.**
>
> Stage C rollback is **not a simple flag flip**. PR-C1 permanently deleted the same-origin
> API-key bypass from `src/web/middleware.py`. There is no code path left that allows
> browser traffic to bypass authentication — even with `auth_enforcement_enabled=false`, the
> bypass code does not exist.
>
> **Consequence:** If you flip the flag back to `false`, the `require()` decorators become
> no-ops (behavior reverts to pre-enforcement), BUT browser traffic that relied on the
> same-origin bypass (e.g., a user with the API key in their browser session but no session
> cookie) will now receive 401 from the missing bypass — not from the decorators.
>
> **Incomplete rollback** = `auth_enforcement_enabled=false` with bypass deleted = browser
> sessions without session cookies get 401 unexpectedly.
>
> **If browser traffic must be fully restored:** The only complete rollback is reverting the
> PR-C1 commit. Coordinate with the team before proceeding.

### Flag-only rollback (partial — use only if all active users have valid session cookies)

```bash
# Disable enforcement.
psql "$DATABASE_URL" -c "
UPDATE feature_flags SET value='false', updated_at=NOW()
WHERE key='auth_enforcement_enabled';
"

# Restart the Render web service.
```

After restart:
- `require()` decorators become no-ops; existing session-cookie users are unaffected.
- Users without session cookies to API-key-gated endpoints receive 401 (bypass is gone).
- The backfill applied to `user_id` columns is **not reversed** by this flag flip.

### Full rollback (restores browser API-key bypass)

Revert the PR-C1 commit and deploy the reverted code. Steps:
1. `git revert <pr-c1-merge-sha>` on a new branch.
2. Open a PR and merge it.
3. After deployment, flip `auth_enforcement_enabled` to `false` via SQL + restart.

---

## 6. Troubleshooting

- **All requests returning 401 immediately after flip.** Session cookies may be present but
  `load_session_user` is failing. Check `auth_sessions` has rows and `expires_at > NOW()`.
  Check that `AUTH_SESSION_COOKIE_NAME` env var matches what the app expects.

- **Reviewer reports 403 on decision submission.** Confirm the reviewer's `auth_users.role`
  is `reviewer` (not `viewer`). Run `python3 scripts/auth_readiness_report.py` to inspect.

- **Readiness report shows `last_login_at=never` for an active reviewer.** That reviewer has
  not completed a login under Stage B shadow mode. Do NOT flip the enforcement flag until
  every active reviewer has logged in. Contact the reviewer directly.

- **`/auth/login` returns 404.** `google_login_enabled` flag is `false` or the app hasn't
  been restarted since Stage B. Confirm the flag is `true` and the app was restarted.

- **Legacy session not expiring within 4 hours.** The 4-hour bound is enforced in
  `src/auth/load_user.py`. Confirm PR-C1 is fully deployed. Check the `auth_enforcement_enabled`
  flag's `updated_at` timestamp — the 4-hour clock starts from that value, not from the
  most recent restart.

- **Backfill script reports non-zero remaining rows after apply.** Some `reviewer_id` values
  do not match any active alias. This is expected for rows written before the alias seeding
  or with non-standard reviewer strings. Unmapped rows remain with `user_id=NULL`; they will
  not be able to use `decision.undo.own` for those historical decisions. Document which
  reviewer_id values are unmapped if this is a concern.

- **Backfill preview shows 0 rows to update.** This is normal if all rows were written
  post-Stage-B (they already have `user_id` set from the dual-write in PR-C1). Proceed to
  the flag flip.
