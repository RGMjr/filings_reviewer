You are the implementer for **Wave 4 of the review-UI authorization rollout**: a single PR that ships **PR-A8 (readiness report)** plus the **Stage-B operator runbook**. This is the last Stage-A deliverable. After this lands, every Stage-A acceptance criterion is satisfied and Stage B becomes a flag-flip + restart operation gated on operator prerequisites.

Read the entire prompt before doing anything.

## Source of truth (read these first, in order)

1. `docs/architecture/auth-rollout-implementation-plan.md` — authoritative PR catalog. PR-A8 has a section under "Stage A — Foundation: PR catalog". Stage B's brief lives under "Stage B — Shadow Mode: PR catalog → B1".
2. `docs/requirements/review-ui-authorization-spec.md` — authoritative requirements. Especially **§Readiness Reporting** (mandates the report's six sections) and **§Cutover Gate** (defines the readiness criteria — note these mix Stage-B and Stage-C prerequisites; see "Stage B vs Stage C readiness" below).
3. `CLAUDE.md` (project root) — Pre-Implementation Gate, Implementation Rules, Workflow, Database section.
4. `~/.claude/CLAUDE.md` (global) — Pre-Implementation Gate item 6 (worktree mandatory for 3+ files), Implementation Rules ("execute ONLY specified steps"), Subagent Model Selection.
5. Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
6. `.claude/rules/scripts.md` — testing convention for DB-touching CLI scripts (write integration tests at `tests/integration/test_<script>.py`, not under `tests/unit/scripts/`).
7. `docs/worker-prompts/WAVE3_auth-oauth.md` and `docs/worker-prompts/PREWAVE4_auth-followups.md` — context on what the auth surface looks like today.

## What's done

- **PR-A1 (#403)** — schema foundation.
- **Wave 2** — A2/A3/A4/A6/A7 (PRs #409–#414).
- **Wave 3 / PR-A5 (#423)** — Google OAuth Authorization-Code-with-PKCE flow, gated by `google_login_enabled=false`.
- **Pre-Wave-4 follow-ups (#443)** — dev-bypass wiring into `load_session_user`, `last_login_at` ordering fix, `target_entity` populated in audit, `aud`-mismatch and `expires_at` test gaps closed.

After Wave 4 lands, **Stage A is complete**. Stage B is a flag-flip + restart operation (the runbook this PR ships). Stage C (route migration to `require()`, same-origin API-key bypass removal, enforcement flag flip) is a future cycle.

## What this PR ships

A single PR with **5 files** (3 new + 2 modified). **Branch:** `claude/auth-pr-a8-readiness`.

---

### File 1 (new): `scripts/auth_readiness_report.py`

A CLI script for cutover readiness reporting. Mirrors the argparse + `DatabaseAdapter` pattern from `scripts/seed_auth_users.py`.

**CLI surface:**

```
python3 scripts/auth_readiness_report.py             # human-readable text report (default)
python3 scripts/auth_readiness_report.py --json      # JSON output (machine-readable)
python3 scripts/auth_readiness_report.py --check     # exit 0 if Stage-B-ready, 1 otherwise (silent on success)
```

**Exit-code semantics for `--check`:**
- `0` — Stage-B readiness criteria all met.
- `1` — one or more criteria not met. Prints which to stderr.
- `2` — script error (DB connection failure, env var missing).

**Six required sections (per spec §Readiness Reporting):**

1. **Allowlisted users + roles.** `SELECT normalized_email, intended_role, status, created_at FROM auth_access_entries WHERE status='approved' ORDER BY normalized_email`.
2. **Per-user login state.** `LEFT JOIN` to `auth_users` on `normalized_email`; show `display_name`, `first_login_at`, `last_login_at`, `account_status`. Render NULL timestamps as `"never"`. The text report puts this in a tabular section keyed by email.
3. **Active sessions count.** `SELECT COUNT(*) FROM auth_sessions WHERE expires_at > NOW()`.
4. **Legacy alias mappings.** `SELECT legacy_reviewer_string, target_email, active, created_at FROM auth_legacy_aliases WHERE active = TRUE ORDER BY legacy_reviewer_string`.
5. **Rollout flag state.** `SELECT key, value, expires_at, actor, updated_at FROM feature_flags ORDER BY key`. Include rows with non-NULL `expires_at` (and a remaining-time computation in the text format, e.g., `"expires in 3h 22m"`).
6. **Production dev-bypass guard verification.** Inspect `os.environ.get("APP_ENV")` and `os.environ.get("AUTH_DEV_BYPASS")`. Report `PASS` if not (`APP_ENV == "production"` AND `AUTH_DEV_BYPASS == "1"`); `FAIL` otherwise. This is a runtime self-check (the actual production guard is at app boot in `verify_dev_bypass_safe()`); the readiness report exposes the same predicate so the operator can confirm before flip.

**`--check` evaluation logic:**

`--check` returns 0 only when all of these are true:

- Section 1 is non-empty (at least one allowlisted user exists).
- Every allowlisted user has a valid `role` set (not NULL, must be one of `admin`/`reviewer`/`viewer`).
- Section 6 (dev-bypass guard) is `PASS`.
- No row in Section 5 has `expires_at < NOW()` AND `value = 'true'` (no expired-but-still-treated-as-on emergency flags, since those would be a misconfiguration even if `_read_flag_from_db` filters them out at runtime).

**Stage B vs Stage C readiness — important distinction.** Spec §Cutover Gate lists five readiness criteria, including "all active reviewers have successfully logged in at least once". That criterion is for the **Stage B → Stage C** cutover, not for Stage A → B. Users cannot log in until shadow mode is enabled, so requiring `last_login_at` to be non-NULL pre-Stage-B is circular. The `--check` mode reports per-user login state in the human-readable report (informational, useful when later evaluating Stage C readiness) but **does NOT fail when `last_login_at IS NULL`**. Don't bake the Stage-C criterion into the Stage-B gate.

**Implementation notes:**

- Use the existing `src/infra/db.py::DatabaseAdapter` pattern. Do NOT open psycopg connections directly.
- Reuse the `_row_to_dict` helper convention from `scripts/seed_auth_users.py` (UUID and datetime serialisation).
- Keep the script under ~400 LOC. One file. Don't introduce a `src/auth/readiness.py` module — the logic is straightforward enough to keep inside the script. (If a future caller needs to import these checks, refactor then.)
- The text formatter should produce output that's reasonable for a 100-char terminal. Use `tabulate` only if it's already in `requirements.txt`; otherwise hand-roll fixed-width columns.

---

### File 2 (new): `tests/integration/auth/test_readiness_report.py`

Per `.claude/rules/scripts.md` testing convention, DB-touching CLI scripts get integration tests in `tests/integration/`. Precedent: `tests/integration/test_onboard_tickers_cli.py` (loads the script via `importlib`).

**Test cases:**

- **Empty DB.** Run against a freshly-migrated DB with no auth_access_entries / auth_users rows. Expect: text mode renders explicit zero/none messaging (not blank); `--check` exits 1 (no allowlisted users); `--json` produces valid JSON with empty arrays.
- **After seed (post-A7).** Run `seed_auth_users.py` and `seed_auth_legacy_aliases.py` first, then the readiness report. Expect: 3 allowlisted users, 2 alias mappings, 0 active sessions, 0 feature flags (no rows yet), dev-bypass guard PASS. `--check` exits 0.
- **Mid-shadow simulation.** Insert a row directly into `auth_users` simulating a successful first login (set `first_login_at`, `last_login_at`, `google_sub`). Confirm the report shows the user as "logged in" with timestamps.
- **Disabled user.** Insert a row with `account_status='disabled'`, `disabled_at` set. Confirm the report shows the disabled status. `--check` should still pass (disabled users don't fail Stage-B readiness).
- **Expired emergency flag.** Insert `feature_flags(key='legacy_emergency_access_enabled', value='true', expires_at=NOW() - INTERVAL '1 minute')`. Expect `--check` to exit 1 with stderr citing the expired-but-active flag.
- **Dev-bypass guard FAIL.** Use `monkeypatch.setenv("APP_ENV", "production")` and `monkeypatch.setenv("AUTH_DEV_BYPASS", "1")`. Expect Section 6 = FAIL; `--check` exits 1.
- **JSON shape.** Run with `--json` and assert the top-level keys: `allowlisted`, `users`, `active_sessions`, `legacy_aliases`, `flags`, `dev_bypass_guard`. Each is a structured array/object — implementer's choice on exact shape, but document it in the script's docstring.

Use the project's `clean_db` and `test_db_adapter` fixtures from `tests/integration/conftest.py`.

---

### File 3 (new): `docs/operations/auth-stage-b-runbook.md`

Operator-facing runbook. Style precedent: `docs/operations/cloud-deployment-runbook.md` (status table at top, "Last updated" date, numbered sections).

**Sections:**

#### 1. Purpose

Define what Stage B is (shadow mode: `google_login_enabled=true`, `auth_enforcement_enabled=false`) and what it isn't (Stage C is the enforcement flip — separate runbook, future cycle). Reference the spec at `docs/requirements/review-ui-authorization-spec.md` and the implementation plan.

#### 2. Prerequisites checklist

Five items (must all be ✓ before activation):

1. **Google Cloud Console OAuth 2.0 client created.** Web-application type. Authorised redirect URIs include `https://<prod-domain>/auth/callback` AND `http://localhost:5000/auth/callback` (for local-dev validation). Capture the client id and client secret.
2. **`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` added to the Render env group** for the web service. The redirect URI must match exactly what's registered in Cloud Console.
3. **`SECRET_KEY` ≥ 32 characters in Render env group.** Production already enforces this at boot via `ProductionConfig`'s validation; A5 now also uses this key for the OAuth-flow signed-cookie session that holds `state`/`nonce`/`code_verifier` between `/auth/login` and `/auth/callback`. If `SECRET_KEY` is regenerated, in-flight OAuth login attempts will fail; coordinate with users.
4. **Seed scripts run against the production DB.**
   ```bash
   python3 scripts/seed_auth_users.py
   python3 scripts/seed_auth_legacy_aliases.py
   ```
   Both are idempotent. Verify via `auth_readiness_report.py` (Section 1 should show all three users; Section 4 should show both aliases).
5. **`feature_flags.google_login_enabled` row absent or set to `'false'`.** Verify via the readiness report Section 5. Default-off behavior is correct for Stage A.

#### 3. Activation steps

```bash
# 1. Pre-flight: readiness check
python3 scripts/auth_readiness_report.py --check
# expect: exit 0

# 2. Enable the flag in production DB (via Render shell or DBA)
psql "$DATABASE_URL" -c "
INSERT INTO feature_flags (key, value)
VALUES ('google_login_enabled', 'true')
ON CONFLICT (key) DO UPDATE SET value='true', updated_at=NOW();
"

# 3. Restart the Render web service so create_app() re-runs and registers the auth blueprint.
#    (Render dashboard → Service → Manual Deploy → Clear Cache & Restart, or trigger any redeploy.)

# 4. Smoke test
curl -I https://<prod-domain>/auth/login
# expect: 302 redirect to https://accounts.google.com/o/oauth2/v2/auth?...
```

Then complete a Google login as `rgmarkey@gmail.com`. Verify in DB:

```sql
SELECT normalized_email, last_login_at FROM auth_users WHERE normalized_email = 'rgmarkey@gmail.com';
-- expect: last_login_at within the last few minutes

SELECT action_type, success, error, target_entity FROM admin_audit_log
WHERE action_type = 'auth.login' ORDER BY created_at DESC LIMIT 1;
-- expect: success=true, error=NULL
```

#### 4. Verification (post-flip)

- Re-run `python3 scripts/auth_readiness_report.py` (no `--check`). At least one user shows non-NULL `last_login_at`.
- `admin_audit_log` shows the `auth.login` row with the right `actor_email` and `target_entity`.
- Existing routes (`/v2/review/`, `/api/v2/*`) still behave as today (enforcement is still off via `auth_enforcement_enabled=false`, so unchanged behavior — verify by hitting `/health` and a sample API route with the existing API key).
- No spike in 4xx/5xx responses on the web service for ~15 minutes after the restart.

#### 5. Rollback procedure

```bash
# 1. Disable the flag
psql "$DATABASE_URL" -c "UPDATE feature_flags SET value='false', updated_at=NOW() WHERE key='google_login_enabled';"

# 2. Restart the Render web service
```

After restart:

- `auth_bp` blueprint is **not** registered. `/auth/login` returns 404. New logins are blocked.
- **Existing `auth_sessions` rows are NOT deleted by this rollback.** `load_session_user` is registered unconditionally and continues to populate `g.user` from any valid session cookie. This is harmless **today** because no current route consumes `g.user` (routes still gate on `FILINGS_API_KEY` until Stage C). If a future Stage C migration has happened and you need to invalidate every shadow-mode session, also run:
  ```sql
  DELETE FROM auth_sessions;
  ```
  This forces every browser to re-authenticate on its next request.
- For Stage B specifically (this runbook's scope), the `DELETE FROM auth_sessions` step is **optional cleanup**, not a correctness requirement.

#### 6. Troubleshooting

- **`/auth/login` returns 404 after activation.** The flag wasn't read at boot. Confirm Render actually restarted (check the deploy log timestamp) and the `feature_flags` row really has `value='true'` (re-run readiness report).
- **Google OAuth callback returns "redirect_uri_mismatch".** The `GOOGLE_OAUTH_REDIRECT_URI` env var doesn't match what's registered in Cloud Console. Verify both end with `/auth/callback` exactly (no trailing slash differences, no scheme mismatches).
- **`/auth/callback` returns 500.** Check `admin_audit_log` for the most recent `auth.login_denied` row; the `error` field will be one of `oauth_state_mismatch`, `oauth_callback_error`, `oauth_id_token_invalid`, etc.
- **First login succeeds but subsequent requests don't see the user.** `load_session_user` is failing silently. Confirm `auth_sessions` has the row, confirm the cookie is being sent (Network tab), confirm `AUTH_SESSION_COOKIE_NAME` matches between cookie and code.

---

### File 4 (modify): `CLAUDE.md`

Update the admin-operations / database section to list the readiness-report script alongside the seed scripts. Append a short bullet near the existing `seed_auth_users.py` reference:

> - `scripts/auth_readiness_report.py` — pre-flip readiness check for Stage B. `--check` returns exit 0 if ready. See `docs/operations/auth-stage-b-runbook.md`.

Don't restructure the section.

### File 5 (modify): `docs/architecture/auth-rollout-implementation-plan.md`

Mark A8 as shipped. Specifically:

- In the **A8 — Readiness report script** section, prepend a status line: `**Status:** ✓ shipped 2026-05-04 (PR #<this-PR-number>).`
- In the "Stage map at a glance" table, update the Stage A row's "Flag state at end of stage" column if needed (no change expected — flag state is unchanged).
- Optionally append a one-line note under the Stage B section header: "`auth_readiness_report.py` (shipped in A8) is the operator's pre-flip gate; see `docs/operations/auth-stage-b-runbook.md`."

These updates keep the plan doc honest about what's landed; future sessions reading the plan should see Stage A as complete.

---

## Out of scope (do NOT expand into)

- **Stage C work.** Route migration to `require(<permission>)`, same-origin API-key bypass removal, `auth_enforcement_enabled` flip.
- **Backfill of legacy reviewer aliases.** Stage C / PR-C2.
- **Admin UI for users / flags / sessions.** Deferred follow-on per spec §Deferred Follow-On Work.
- **Automated CI step that runs `auth_readiness_report.py --check`.** Operator-only tool for now; a CI gate is a Stage-D consideration at earliest.
- **Slack / email alerting on readiness failures.** Out of scope.
- **Force-logout-all-on-disable.** Deferred per spec.
- **Adding a `--reset` or destructive-action flag to the readiness script.** Read-only tool by design.
- **Tidying anything else from prior waves** beyond the two doc files explicitly listed above.

If you spot another issue while implementing, file as `gh-N-<slug>` per `.claude/commands/commit-proj.md` step 9 — don't expand the PR.

## Pre-implementation gate

This PR touches 5 files (3 new + 2 modified) — past the 3-file threshold AND involves auth-adjacent script + operator-facing docs. Run the full Pre-Implementation Gate from `~/.claude/CLAUDE.md`:

1. **Assumption audit.** Verify each assumption against current code:
   - `scripts/seed_auth_users.py` exists and uses argparse + `DatabaseAdapter` (the pattern this script mirrors).
   - `tests/integration/test_onboard_tickers_cli.py` exists and shows the importlib-loaded-CLI test pattern.
   - `tests/integration/conftest.py` provides `clean_db` and `test_db_adapter` fixtures.
   - The 6 schema tables referenced (`auth_access_entries`, `auth_users`, `auth_sessions`, `auth_legacy_aliases`, `feature_flags`, `admin_audit_log`) exist with the columns this script reads. If any column was renamed in a follow-up that wasn't tracked, fix that first.
2. **Scope check.** Only the 5 listed files. The runbook is bundled deliberately; resist the urge to also touch the spec or any auth code.
3. **Rules compliance.** Worktree (yes — touches 5 files), `/commit-proj` for the PR, conventional commit message, no `--no-verify`, no force-push to main.
4. **Risk assessment.** Specific risks:
   - **Read-only script invariant.** The script must NOT issue any UPDATE/INSERT/DELETE except potentially writing an audit row. Actually — given this is a *read* tool, **don't write any audit row**; the audit log is for actions, not reads. Verify your INSERT count is zero.
   - **`--check` exit semantics drift.** The runbook quotes "exit 0 = ready". If `--check` returns 0 in unintended cases (or fails to return 0 in correct cases), the runbook becomes wrong. Test the exit semantics explicitly.
   - **Connection pooling vs script context.** `DatabaseAdapter` may try to use the app's connection pool. From a CLI script (no Flask app context), pooling is N/A — confirm the script can construct a `DatabaseAdapter` directly with `DATABASE_URL` and no pool. Precedent: `scripts/seed_auth_users.py` does this.
   - **Output volume on large auth_users tables.** Today there are 3 rows. If/when this grows to dozens, the text report should still be readable. Don't worry about huge scale — but don't write code that explodes at 100 rows either.
5. **Minimal path.** 5-file change, no new modules, no new dependencies. Already minimal.
6. **Worktree check.** `EnterWorktree` or `ccw claude/auth-pr-a8-readiness` before any edits.

Present the completed gate checklist for orchestrator (user) approval before implementing.

## Workflow

1. Worktree-first.
2. Pre-implementation gate (above), present, wait for approval.
3. Implement in this order:
   - File 1 (`auth_readiness_report.py`) — the core deliverable.
   - File 2 (`test_readiness_report.py`) — exercise it as you build.
   - File 3 (Stage-B runbook) — references the script's CLI surface, so write after the script's surface is stable.
   - Files 4 + 5 (`CLAUDE.md`, plan doc) — small text edits, last.
4. Run `pytest -x -q tests/integration/auth/test_readiness_report.py` locally — must be green.
5. Run `python3 scripts/auth_readiness_report.py` against your local DB; sanity-check the output.
6. `/commit-proj`. Out-of-scope triage step — flag any unrelated issues found while implementing.
7. Auto-merge enabled via `gh pr merge --auto --squash`.
8. After merge, report:
   - PR number + commit SHA.
   - Confirm `pytest -x -q tests/unit/auth tests/integration/auth` is green on `origin/main`.
   - Manual sample of the readiness-report output (paste into the report-back, redacting any sensitive details).
   - **Stage A is now complete.** Hand back to the user for Stage B operator work (the runbook is the next surface they'll touch).

## Risks worth flagging at execution time

- **Pre-existing failing test (gh-262).** Known-failing and unrelated to this PR. Skip via `--deselect` if it stops your run.
- **Renaming `--check` later.** The runbook hard-codes `--check`. If you decide on a different flag name during implementation, update the runbook in the same PR — don't ship a runbook that references a flag that doesn't exist.
- **`tabulate` dependency temptation.** If `tabulate` is not already in `requirements.txt`, do NOT add it — hand-roll fixed-width columns. Adding a new dep for a script-only nicety isn't worth the supply-chain churn.

## What you (implementer) do NOT do

- Do not flip any feature flag in any environment.
- Do not run the readiness report against production from this PR — local DB only for the implementation. The runbook is for the operator to use post-merge.
- Do not modify the spec.
- Do not add Stage-C scaffolding (no `require()` decorator usage on routes, no API-key bypass changes).
- Do not delete or rename anything from prior waves.

Good luck — and report back when Stage A is done.
