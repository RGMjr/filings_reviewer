# Auth Stage B — Shadow Mode Activation Runbook

**Scope:** Operator runbook for flipping `feature_flags.google_login_enabled` to `true` (Stage B / shadow mode) and rolling back if needed.
**Last updated:** 2026-05-04

---

## Status

| Item | Detail |
|------|--------|
| Stage A (foundation) | ✓ shipped (PRs #403, #409–#414, #423, #443, this PR) |
| Stage B (shadow mode) | Pending operator activation |
| Stage C (enforcement) | Future cycle — separate runbook |
| Authoritative spec | `docs/requirements/review-ui-authorization-spec.md` |
| Authoritative plan | `docs/architecture/auth-rollout-implementation-plan.md` |

---

## 1. Purpose

Stage B is **shadow mode**: Google login is enabled (`google_login_enabled=true`) but route enforcement is still off (`auth_enforcement_enabled=false`, default). After activation:

- Users can authenticate via `/auth/login`. Allowlisted users are auto-provisioned in `auth_users` on first successful login.
- Existing routes (`/api/v2/*`, `/v2/review/*`, ingest, image endpoints) continue to gate on `FILINGS_API_KEY` exactly as today. The migration to `require(<permission>)` decorators happens in Stage C.
- `g.user` is populated from any valid session cookie, but no current route reads it.

This runbook does **not** cover Stage C (the enforcement flip, removal of the same-origin API-key bypass, route migration). That's a separate cycle.

---

## 2. Prerequisites checklist

All five items must be ✓ before proceeding to activation.

1. **Google Cloud Console OAuth 2.0 client created.** Web-application type. Authorised redirect URIs include both:
   - `https://<prod-domain>/auth/callback`
   - `http://localhost:5000/auth/callback` (for local-dev validation)

   Capture the **client id** and **client secret**.

2. **`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` set in the Render env group** for `filings-reviewer`. The redirect URI must match exactly what's registered in Cloud Console (no trailing-slash drift, no http/https mismatch).

3. **`SECRET_KEY` ≥ 32 characters in the Render env group.** `ProductionConfig` validates this at boot. PR-A5 also uses this key for the OAuth-flow signed-cookie session that holds `state` / `nonce` / `code_verifier` between `/auth/login` and `/auth/callback`. If `SECRET_KEY` is regenerated, in-flight OAuth login attempts will fail; coordinate with users.

4. **Seed scripts run against production DB.**

   ```bash
   python3 scripts/seed_auth_users.py
   python3 scripts/seed_auth_legacy_aliases.py
   ```

   Both are idempotent. Verify via `auth_readiness_report.py`: Section 1 should show all three users; Section 4 should show both aliases.

5. **`feature_flags.google_login_enabled` row absent or set to `'false'`.** Verify via Section 5 of the readiness report. Default-off behavior is correct for Stage A.

---

## 3. Activation steps

```bash
# 1. Pre-flight: readiness check
python3 scripts/auth_readiness_report.py --check
# expect: exit 0 (silent on success)
```

If `--check` exits 1, read the `NOT READY:` lines on stderr and resolve before proceeding.

```bash
# 2. Enable the flag in production DB (via Render shell or DBA)
psql "$DATABASE_URL" -c "
INSERT INTO feature_flags (key, value)
VALUES ('google_login_enabled', 'true')
ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW();
"
```

```bash
# 3. Restart the Render web service so create_app() re-runs and registers
#    the auth blueprint conditionally.
#    Render dashboard → filings-reviewer → Manual Deploy → Clear Cache & Restart.
```

```bash
# 4. Smoke test (replace <prod-domain>)
curl -I https://<prod-domain>/auth/login
# expect: 302 redirect to https://accounts.google.com/o/oauth2/v2/auth?...
```

Then complete a Google login as `rgmarkey@gmail.com`. Verify in DB:

```sql
SELECT normalized_email, last_login_at FROM auth_users
WHERE normalized_email = 'rgmarkey@gmail.com';
-- expect: last_login_at within the last few minutes

SELECT action_type, success, error, target_entity FROM admin_audit_log
WHERE action_type = 'auth.login'
ORDER BY created_at DESC LIMIT 1;
-- expect: success=true, error=NULL, target_entity='rgmarkey@gmail.com'
```

---

## 4. Verification (post-flip)

- Re-run `python3 scripts/auth_readiness_report.py` (no `--check`). At least one user shows non-NULL `last_login_at`.
- `admin_audit_log` shows the `auth.login` row with the right `actor_email` and `target_entity`.
- Existing routes (`/v2/review/*`, `/api/v2/*`) still behave as today — enforcement is still off, so reviewer behavior is unchanged. Verify with a sample request using the existing API key.
- `/health` returns 200.
- No spike in 4xx/5xx on the web service for ~15 minutes after the restart.

---

## 5. Rollback procedure

```bash
# 1. Disable the flag
psql "$DATABASE_URL" -c "
UPDATE feature_flags SET value='false', updated_at=NOW()
WHERE key='google_login_enabled';
"

# 2. Restart the Render web service
```

After restart:

- The `auth_bp` blueprint is **not** registered. `/auth/login` returns 404. New logins are blocked.
- **Existing `auth_sessions` rows are NOT deleted by this rollback.** `load_session_user` is still registered unconditionally and continues to populate `g.user` from any valid session cookie. This is harmless **today** because no current route consumes `g.user` (routes still gate on `FILINGS_API_KEY` until Stage C).
- For Stage B specifically (this runbook's scope), purging sessions is **optional cleanup**, not a correctness requirement. If a future Stage C migration has happened and you need to invalidate every shadow-mode session, also run:

  ```sql
  DELETE FROM auth_sessions;
  ```

  This forces every browser to re-authenticate on its next request.

---

## 6. Troubleshooting

- **`/auth/login` returns 404 after activation.** The flag wasn't read at boot. Confirm Render actually restarted (check the deploy log timestamp) and that the `feature_flags` row really has `value='true'` — re-run the readiness report.
- **Google OAuth callback returns "redirect_uri_mismatch".** `GOOGLE_OAUTH_REDIRECT_URI` doesn't match what's registered in Cloud Console. Verify both end with `/auth/callback` exactly (no trailing-slash differences, no scheme mismatches).
- **`/auth/callback` returns 500.** Check `admin_audit_log` for the most recent `auth.login_denied` row; the `error` field will be one of `oauth_state_mismatch`, `oauth_callback_error`, `oauth_id_token_invalid`, etc.
- **First login succeeds but subsequent requests don't see the user.** `load_session_user` is failing silently. Confirm `auth_sessions` has the row, confirm the cookie is being sent (browser Network tab), confirm `AUTH_SESSION_COOKIE_NAME` matches between cookie and code.
- **Readiness `--check` fails on `Dev-bypass guard FAIL`.** `APP_ENV=production` AND `AUTH_DEV_BYPASS=1` are both set in the Render env group. Unset `AUTH_DEV_BYPASS` (it should never be set in prod) and re-deploy.
