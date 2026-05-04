# Review UI Authorization — Rollout Implementation Plan

## Purpose

Operational tracking doc for implementing the authorization rollout. The **authoritative requirements** live in `docs/requirements/review-ui-authorization-spec.md`. This doc translates the spec into a dependency-ordered list of PRs, identifies which can be developed in parallel, and lists the verification-checklist item each PR satisfies.

If anything in this doc contradicts the spec, the spec wins.

## Stage map at a glance

| Stage | Theme | Flag state at end of stage | PR count |
|---|---|---|---|
| A | Foundation | `google_login_enabled=false`, `auth_enforcement_enabled=false` | 8 |
| B | Shadow Mode | `google_login_enabled=true`, `auth_enforcement_enabled=false` | 1 (flag flip + verify) |
| C | Staged Enforcement | `auth_enforcement_enabled=true`, same-origin API-key bypass removed | 2 |
| D | Legacy Retirement | Standard fallback flag retired by 2026-05-10 | 1 (flag flip + verify) |
| E | Post-cutover Cleanup | Transitional code removed, follow-on planned | 2+ (deferred) |

Stages B and D are primarily flag flips against an already-deployed system; the engineering effort is concentrated in Stages A and C.

## Stage A — Foundation: PR catalog

PRs are labeled `A1`–`A8`. Dependencies are explicit. Files touched are listed so parallel-dispatched worktrees can spot rebase conflicts before they happen.

### Dependency graph

```
A1 (schema) ─┬─> A2 (permissions/authz)
             ├─> A3 (session store)
             ├─> A7 (seed scripts)
             └─> A8 (readiness report) ─── (also depends on A5)
A3 ──────────┴─> A5 (OAuth flow)
A4 (CSRF middleware)        ── independent ──
A6 (dev-bypass guard)       ── independent ──
```

**Wave 1 (must merge first):** A1 — every other DB-touching PR rebases on it.
**Wave 2 (parallel, dispatch after A1 merges):** A2, A3, A4, A6, A7. A4 and A6 don't actually depend on A1; they're grouped here only to avoid `src/web/app.py` rebase storms while A1 is settling.
**Wave 3 (after A3 merges):** A5.
**Wave 4 (after A5 merges):** A8.

Realistic timing: with the May-10 deadline (10 days from 2026-05-01), Wave 1 should land within 48 hours, Waves 2–4 over the following ~5 days, then Stage B flag flip and burn-in.

### A1 — Schema migrations and seed-data tables

**Scope.** All auth tables, additive only. Permits zero behavior change in app.

**Files (new).**
- `sql/<ts>_create_auth_users.sql`
- `sql/<ts>_create_auth_sessions.sql`
- `sql/<ts>_create_auth_access_entries.sql`
- `sql/<ts>_create_auth_legacy_aliases.sql`
- `sql/<ts>_create_feature_flags.sql`
- `sql/<ts>_create_admin_audit_log.sql`
- `sql/<ts>_add_user_id_to_v2_review_decisions.sql` (nullable FK to `auth_users.id`)
- `sql/<ts>_add_user_id_to_v2_image_metric_confirmations.sql` (nullable FK)
- `sql/<ts>_add_user_id_to_v2_ingest_batches.sql` (nullable FK)

**Files (modified).**
- `CLAUDE.md` — add new tables to the V2 tables list under "Database".

**Constraints.**
- `auth_users.disabled_at` CHECK: NOT NULL when `account_status='disabled'`, NULL when `'active'`.
- Unique indexes: `auth_users(google_sub)`, `auth_users(normalized_email)`, `auth_access_entries(normalized_email)`.
- `feature_flags(key)` UNIQUE; `expires_at` nullable.
- `admin_audit_log` is append-only by convention; no app code issues UPDATE/DELETE against it.
- Use `scripts/new_migration.py` for filename allocation per `.claude/rules/sql.md`.

**Verification.**
- All 9 migrations apply cleanly on a fresh DB and on an existing prod-shape DB (verify via `scripts/check_migrations.py` or equivalent).
- Pre-existing tests still pass; no behavior change.

**Verification-checklist items satisfied.** "Schema added with additive migrations only" (Stage A acceptance).

**Critical files to read first.** `sql/` directory layout, `.claude/rules/sql.md`, `CLAUDE.md` Database section, `src/infra/db.py` if migrations are registered there.

### A2 — Permission catalog and authorization middleware

**Scope.** The `require(<permission>)` mechanism, the role→permission map, the session-load resolver. No call sites yet; existing routes don't change.

**Files (new).**
- `src/auth/__init__.py`
- `src/auth/permissions.py` — permission constants, role→permission map (mirrors the table in spec §Permission Catalog).
- `src/auth/middleware.py` — `require(permission)` decorator factory; reads `g.user` populated by session-load (added in A3).
- `tests/unit/auth/test_permissions.py`

**Files (modified).** None of the existing route modules; routes get switched over during Stage C.

**Verification.**
- Unit tests confirm: `admin` resolves to all permissions; `reviewer` lacks `decision.undo.any`, `metric.add_missed`, `ingest.run`, `users.manage`, `flags.manage`, `audit.read`; `viewer` lacks `decision.write` and `decision.undo.own`.
- A no-op `g.user=None` request to a `require('protected.read')`-decorated test route returns 401 (HTML) or 401 JSON depending on `Accept`.

**Verification-checklist items satisfied.** "Role restrictions behave correctly" (functional); enables A5 / Stage C.

### A3 — DB-backed session store and cookie attributes

**Scope.** Server-side session table reads/writes; cookie issuance; logout.

**Files (new).**
- `src/auth/sessions.py` — create / lookup / extend / revoke. 24h sliding, 30d absolute.
- `src/web/middleware.py` — extend with `load_session_user` `before_request` hook (sets `g.user` from cookie).
- `tests/unit/auth/test_sessions.py`

**Files (modified).**
- `src/web/app.py` — register `before_request`. (**Conflict surface with A4, A6.**)
- `requirements.txt` — only if a new lib is needed; prefer Flask built-ins.

**Cookie config.**
- Name: `auth_session_<env>` (env-isolated per spec).
- Attributes: `Secure`, `HttpOnly`, `SameSite=Lax`.
- Signing key from env var `AUTH_SESSION_SECRET` (separate per environment).

**Verification.**
- Cookie attribute test: response sets `Secure; HttpOnly; SameSite=Lax`.
- Session-id rotation: a logged-out session id is not valid after re-login (negative-path checklist item).
- Cross-env isolation: a cookie signed by staging key fails in prod.

**Verification-checklist items satisfied.** "Logout invalidates server-side session"; enables A5.

### A4 — CSRF middleware

**Scope.** One CSRF mechanism, fully wired but only effective once `auth_enforcement_enabled=true`. Choose mechanism (per spec §CSRF Protection):

**Recommended:** `Sec-Fetch-Site: same-origin` + `Origin` header check, since the existing same-origin API-key bypass already does origin-aware logic — we can reuse that helper. Fall back to per-session CSRF token only if the Sec-Fetch-Site approach proves brittle on a Flask version we're stuck on.

**Files (new).**
- `src/auth/csrf.py`
- `tests/unit/auth/test_csrf.py`

**Files (modified).**
- `src/web/app.py` — register middleware. (**Conflict surface with A3, A6.**)
- `src/web/middleware.py` — extend if existing helper is reused.

**Verification.**
- Negative test: cross-site POST returns 403 before any handler runs.
- Positive test: same-origin POST succeeds.
- OAuth callback path is exempt (validated via `state` instead).

**Verification-checklist items satisfied.** "CSRF attempt from cross-origin page rejected" (negative-path).

### A5 — Google OAuth flow

**Scope.** Login entrypoint, callback handler, allowlist check, auto-provision, session creation. Gated by `google_login_enabled` (default false). Also folds in three Wave-2 carry-overs that are load-bearing for A5: `load_session_user` registration in `create_app()`, `dev_bypass_user()` returning a real `SessionUser`, and missing `AUTH_SESSION_*` env-template entries.

**Files (new).**
- `src/auth/oauth.py` — Authorization-Code-with-PKCE flow (PKCE, state/nonce gen, auth-URL builder, code exchange).
- `src/auth/oidc_validate.py` — ID-token validation (signature/aud/exp via `google-auth`, then iss/nonce/email_verified application checks).
- `src/auth/feature_flags.py` — generic `is_enabled(key)` reader with 5 s TTL cache; mirrors A4's `_read_enforcement_flag` SQL pattern.
- `src/web/routes/auth.py` — `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/denied`. Blueprint registered conditionally on `google_login_enabled` at app boot.
- `src/web/templates/auth/login.html`, `src/web/templates/auth/denied.html`, `src/web/templates/errors/403.html`.
- `tests/integration/auth/conftest.py`, `tests/integration/auth/test_oauth_flow.py`.
- `tests/unit/auth/test_oauth_url_validation.py`, `tests/unit/auth/test_oidc_validate.py`, `tests/unit/auth/test_feature_flags.py`.

**Files (modified).**
- `src/web/app.py` — register `load_session_user` (Wave-2 carry-over) before `csrf_protect`; conditionally register `auth_bp` after blueprints. (**Conflict surface.**)
- `src/auth/dev_bypass.py` — return a real `SessionUser` (Wave-2 carry-over).
- `tests/unit/auth/test_dev_bypass_guard.py` — assertion update for the new return type.
- `.env.template` — add `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `AUTH_SESSION_COOKIE_NAME`, `AUTH_SESSION_INACTIVITY_HOURS`, `AUTH_SESSION_ABSOLUTE_DAYS`. (No `AUTH_SESSION_SECRET` — Flask reuses the existing `SECRET_KEY` env var for the OAuth-flow signed-cookie session; one signing key, one source.)
- `requirements.txt` — add `google-auth>=2.27,<3` (already in `requirements.lock` transitively via `google-genai`).
- `CLAUDE.md` — auth-tables note updated for first-login auto-provisioning.

**Validation requirements (from spec §OAuth Implementation Requirements).**
- ID-token signature against Google JWKS (via `google.oauth2.id_token.verify_oauth2_token`; the `Request` transport is cached at module level so JWKS fetches are amortized).
- `iss`, `aud == client_id`, `exp`, `nonce`, `email_verified == true`.
- `state` parameter validated against the value stashed at `/auth/login`.
- Scopes `openid email profile` only.
- Trust ID-token claims; no `userinfo` refetch.

**Auto-provision.**
- Successful login + allowlist match → upsert `auth_users` row using `ON CONFLICT (normalized_email) DO UPDATE` (NOT `google_sub`, which is nullable on seeded rows). Sets `google_sub` only when the existing row's value was NULL; refreshes `display_name`; sets `first_login_at` only if NULL; always updates `last_login_at`.
- Allowlist miss → deny + audit `auth.login_denied` with reason `not_allowlisted`. User-visible page wording is identical to `email_unverified` to avoid leaking which accounts are allowlisted.
- `email_verified=false` → deny + audit `auth.login_denied` with reason `email_unverified`.

**Runtime semantics.**
- The conditional blueprint registration is read once at app boot. A flag flip via `feature_flags` requires a deploy/restart to take effect — Stage B's flip is paired with a deploy anyway.
- The Flask framework session (signed by `SECRET_KEY`) holds short-lived per-flow values (`state`/`nonce`/`code_verifier`) between `/auth/login` and `/auth/callback`. The long-lived `auth_session` cookie (set by A3's `set_session_cookie`) holds the opaque session id and is unrelated.
- CSRF middleware (A4) already exempts paths under `/auth/`, so the OAuth callback is not blocked when `auth_enforcement_enabled` flips on later.

**Verification.**
- Integration tests for: success, not-allowlisted, email-unverified, state-mismatch, invalid-id-token, callback-without-code, disabled-user-with-allowlist, pending-allowlist-entry, logout. All run with stubbed Google client (no real network).
- Unit tests for: `_validate_next` (open-redirect bypass attempts), `validate_id_token` (per-claim failure modes), `is_enabled` (cache hit/miss/expiry), updated `dev_bypass_user` assertions.
- Login event audit rows present in `admin_audit_log` with correct `action_type`/`error` codes.

**Verification-checklist items satisfied.** "Google login works in production"; "non-allowlisted Google account is denied correctly"; "`email_verified=false` Google account is denied correctly"; OAuth-failure audit reasons; "Account-mismatch and unverified-email messages do not leak which accounts are allowlisted".

### A6 — Production dev-bypass startup guard

**Scope.** The startup assertion that prevents `FLASK_ENV=production` AND `AUTH_DEV_BYPASS=1` from coexisting.

**Files (new).**
- `src/auth/dev_bypass.py` — guard logic + the bypass identity provider used in dev/test.
- `tests/unit/auth/test_dev_bypass_guard.py` — loads production config and asserts boot fails.

**Files (modified).**
- `src/web/app.py` — call `verify_dev_bypass_safe()` at startup. (**Conflict surface.**)

**Verification.**
- Production-config + `AUTH_DEV_BYPASS=1` → app refuses to boot, fatal error to stderr.
- Production-config + bypass unset → app boots normally.
- Dev-config + bypass set → app boots, bypass identity available.

**Verification-checklist items satisfied.** "Production dev-bypass startup guard refuses to boot when both `FLASK_ENV=production` and `AUTH_DEV_BYPASS=1`" (negative-path).

### A7 — Seed scripts

**Scope.** Idempotent scripts to seed initial users, allowlist, and alias mappings per spec §Initial Seed Data.

**Files (new).**
- `scripts/seed_auth_users.py` — creates `auth_users` rows for `rgmarkey@gmail.com`, `rob.markey@cmasb.org` (admins), `mayujoiner@gmail.com` (reviewer); also writes corresponding `auth_access_entries` rows.
- `scripts/seed_auth_legacy_aliases.py` — `RGM` → `rgmarkey@gmail.com`, `Mayu` → `mayujoiner@gmail.com`.
- `tests/integration/auth/test_seed_scripts.py` — runs each script twice, verifies idempotency.

**Files (modified).**
- `CLAUDE.md` — admin operations section, list seed scripts.

**Verification.**
- Running the script twice produces the same DB state on the second run as on the first.
- A new admin or reviewer added to the script later inserts cleanly without disturbing prior rows.

**Verification-checklist items satisfied.** "Seeded admin / second admin / reviewer can log in successfully" (functional, gated on A5).

### A8 — Readiness report script

**Status:** ✓ shipped 2026-05-04 — Stage A is complete.

**Scope.** Cutover-readiness CLI report per spec §Readiness Reporting.

**Files (new).**
- `scripts/auth_readiness_report.py` — prints allowlisted users + roles + first/last login + unresolved alias mappings + flag state (incl. `expires_at`) + dev-bypass guard verification.
- `tests/integration/auth/test_readiness_report.py`
- `docs/operations/auth-stage-b-runbook.md` — operator runbook for the Stage-B activation flip; bundled with A8 so the script's `--check` semantics and the runbook's pre-flip gate ship together.

**Files (modified).**
- `CLAUDE.md` — admin operations section.

**Verification.**
- Report runs against an empty DB (post-A1 only) and renders with explicit zeros / no-rows messaging.
- Report after A5 + A7 shows admins and reviewer with no `last_login_at` (none have logged in) and unresolved alias mappings until apply step runs.

**Verification-checklist items satisfied.** "Readiness report works" (Stage B acceptance).

## Stage B — Shadow Mode: PR catalog

`auth_readiness_report.py` (shipped in A8) is the operator's pre-flip gate; see `docs/operations/auth-stage-b-runbook.md`.

### B1 — Flag flip and burn-in

**Scope.** No code change. Flip `google_login_enabled=true` in production via the admin script (or direct SQL on `feature_flags`). Run readiness report. Verify all four seed users can log in. Run a 24–48h burn-in with no enforcement.

**Verification-checklist items satisfied.** Stage B Complete: "Users can sign in with Google in production"; "Allowlisted users are auto-provisioned on first login"; "First and last login tracking works"; "No reviewer disruption from login availability alone".

**Exit criterion.** All readiness criteria from spec §Cutover Gate are met.

## Stage C — Staged Enforcement: PR catalog

### C1 — Switch routes to centralized authorization

**Scope.** Replace the existing API-key `before_request` hook on `/api/v2/*` with `require(<permission>)` decorators on each route. Same for `/v2/review/*`, `/ingest/*`, `/api/ingest/*`, `/review/pres-images/*`, and image-serving endpoints. The same-origin API-key bypass is removed in this PR.

**Files (modified).** Most route modules under `src/web/routes/`.

**Verification.**
- Every protected route covered by a `require(...)` annotation (CI rule: lint that fails the build if a route module is missing the decorator).
- Same-origin POST without session cookie returns 401 / 403 (the bypass is gone).
- Image endpoint without session cookie returns 401.

**Verification-checklist items satisfied.** "Role restrictions behave correctly"; "Same-origin API-key bypass is gone from `/api/v2/*` after `auth_enforcement_enabled=true`"; "Image-serving endpoints honor auth"; "URL-redirect bypass attempts rejected"; "Role-escalation attempt rejected".

### C2 — Backfill apply step + flag flip

**Scope.** Run the legacy-alias backfill apply step (sets `user_id` on historical rows for `RGM` / `Mayu` aliases). Verify via readiness report. Flip `auth_enforcement_enabled=true`.

**Files (new).**
- `scripts/backfill_legacy_reviewer_aliases.py` (preview + apply modes; idempotent).
- `tests/integration/auth/test_backfill.py`

**Files (modified).** None for the apply itself; the flag flip is a feature_flags row.

**Verification.**
- Preview report matches expected counts before apply.
- Apply is idempotent.
- After flag flip, legacy sessions are forcibly invalidated within 4 hours (negative-path: stale-session test).

**Verification-checklist items satisfied.** "Legacy backfill preview report is correct"; "Legacy backfill apply step is idempotent"; "Stale-session-after-disable rejected"; Stage C acceptance.

## Stage D — Legacy Retirement

### D1 — Standard fallback flag retired

**Scope.** On 2026-05-10, ensure `legacy_emergency_access_enabled=false` and the flag has an audit-trail entry. Document the post-deadline override path (operational runbook, not code).

**Files (new).**
- `docs/operations/auth-emergency-override-runbook.md`

**Verification-checklist items satisfied.** Stage D acceptance.

## Stage E — Post-Cutover Cleanup

Deferred until Stage C is stable for at least one week. Tracking placeholders only:

- E1 — Remove transitional dual-write to legacy reviewer text columns (after a soak window).
- E2 — Plan admin UI and request-access workflow as separate cycles.

## Parallel-dispatch guidance

After A1 merges, A2 / A3 / A4 / A6 / A7 are all dispatchable as parallel worktree agents. Use:

```
/plan-execute  # if a multi-PR dispatch skill is desired
```

or dispatch each as its own worktree session manually. Each PR's "Files (modified)" list flags which ones contend on `src/web/app.py` — those should rebase serially even if they're started in parallel. The other content (new files, test files, sql migrations) is conflict-free.

Supervision after dispatch:

```
/loop 5m /supervise-prs <pr-numbers>
```

## Operating notes

- Every PR uses `/commit-proj` from a `ccw` / `EnterWorktree` worktree. The PreToolUse guard blocks `git checkout -b` in the primary tree.
- Migrations follow the timestamp-named pattern (`scripts/new_migration.py`) per `.claude/rules/sql.md`. The integer-prefix range `00-47` is frozen.
- For PRs that touch `src/web/app.py`, do the wiring change in a self-contained block (registration call, import) rather than threading state through existing helpers — this minimizes rebase pain when multiple Wave-2 PRs land in sequence.
- Each PR's commit message should reference the PR id from this doc (e.g., `feat(auth): A1 schema migrations`) so the rollout history is traceable.

## Decision log

- 2026-05-01 — Second admin: `rob.markey@cmasb.org`. Resolves the `[DECISION]` placeholder in the spec.
- 2026-05-01 — Staging environment: none; accepted risk. Validation surface is local dev + CI integration tests; rollback surface is the emergency-fallback flag and the bounded legacy-session window.
- 2026-05-01 — CSRF mechanism: tentatively `Sec-Fetch-Site: same-origin` + `Origin` check (reuses existing helper). Reconsider if Flask version proves incompatible.

## Related documents

- `docs/requirements/review-ui-authorization-spec.md` — authoritative requirements.
- `.claude/rules/sql.md` — migration filename and ordering rules.
- `.claude/rules/web.md` — current web-route + reviewer-identity contract.
- `CLAUDE.md` — project-wide rules.
