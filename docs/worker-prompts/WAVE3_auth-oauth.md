You are the implementer for **Wave 3 of the review-UI authorization rollout**: a single PR (PR-A5) that ships the Google OAuth flow. Wave 1 (PR-A1 schema #403) and Wave 2 (PRs #409 A6, #410 A4, #411 A7, #413 A3, #414 A2) are landed. After Wave 3 lands, only Wave 4 (A8 readiness report) remains before the rollout enters Stage B (shadow mode).

Read the entire prompt before doing anything.

## Source of truth (read these first, in order)

1. `docs/architecture/auth-rollout-implementation-plan.md` — authoritative PR catalog. PR-A5 has a section under "Stage A — Foundation: PR catalog".
2. `docs/requirements/review-ui-authorization-spec.md` — authoritative requirements. Especially **§Authentication Source → OAuth/OIDC Implementation Requirements**, §Access Model, §Account Status, §Auditing Requirements → Authentication Event Auditing.
3. `CLAUDE.md` (project root) — Pre-Implementation Gate, Implementation Rules, Workflow (PR-required, worktree-first), Database section (now lists `auth_users`, `auth_sessions`, `auth_access_entries`).
4. `~/.claude/CLAUDE.md` (global) — Pre-Implementation Gate item 6 (worktree mandatory), Implementation Rules ("execute ONLY specified steps").
5. Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
6. `.claude/rules/web.md` — current web-route + reviewer-identity contract; especially the same-origin API-key bypass section (A5 does not change this; route migration is Stage C).
7. `docs/worker-prompts/WAVE2_auth-foundation.md` — for context on what Wave 2 was supposed to ship; cross-reference against actual landed code (see "Wave-2 deviations to fold in" below).

## What's done

- **PR-A1 (#403, merged 2026-05-01)** — schema foundation. All six auth tables exist; nullable `user_id UUID REFERENCES auth_users(id)` columns on the three reviewer/ingest tables.
- **Wave 2** (all merged):
  - **#409 A6** — `src/auth/dev_bypass.py` with `verify_dev_bypass_safe()` (called at top of `create_app()`), `is_dev_bypass_enabled()`, `dev_bypass_user()`. Env var: `AUTH_DEV_BYPASS=1`.
  - **#410 A4** — `src/auth/csrf.py` with `csrf_protect()` registered as `before_request`. Gated on `auth_enforcement_enabled` flag (currently off → no-op).
  - **#411 A7** — `scripts/seed_auth_users.py` and `scripts/seed_auth_legacy_aliases.py`. Default seed: `rgmarkey@gmail.com` (admin), `rob.markey@cmasb.org` (admin), `mayujoiner@gmail.com` (reviewer); aliases `RGM`/`Mayu`.
  - **#413 A3** — `src/auth/sessions.py`, `src/auth/cookies.py`, `src/auth/load_user.py`. Public functions and dataclass below.
  - **#414 A2** — `src/auth/permissions.py` (10 permission constants + `ROLE_PERMISSIONS` map), `src/auth/middleware.py` with `require(permission)` decorator. Decorator is currently a no-op until `auth_enforcement_enabled=true` (Stage C).

## Wave-2 deviations to fold into A5

The orchestrator that shipped Wave 2 left three small loose ends. They are **load-bearing for A5**, so fold them into this PR rather than filing follow-ups:

1. **`load_session_user` is NOT registered in `src/web/app.py`.** A3 shipped the function in `src/auth/load_user.py` but didn't wire it into `create_app()`. Without it, even after a successful OAuth callback creates a session and sets the cookie, no request will populate `g.user` from the cookie — the OAuth flow would appear to succeed and then immediately "log the user out" on the next request. **A5 must register it as `app.before_request(load_session_user)` in `create_app()`.** Place the registration immediately after `verify_dev_bypass_safe()` at the top of `create_app()`, and **before** the existing `csrf_protect` registration so `g.user` is populated before any CSRF / authz check runs.

2. **`dev_bypass_user()` returns a `SimpleNamespace`, not the real `SessionUser` dataclass.** A6's TODO comment notes this should be fixed once A3 lands. Fix it in this PR: import `SessionUser` from `src/auth/sessions.py` and return one. Field mapping: `id='dev-bypass'` (or a fixed UUID — pick one and put it in a constant), `email='dev@localhost'`, `display_name='Dev Bypass User'`, `role='admin'`, `account_status='active'`. This way the dev-bypass code path produces the same shape as the OAuth path, and any downstream consumer (tests, future routes calling `g.user.role`) doesn't need to special-case dev-bypass.

3. **`AUTH_SESSION_INACTIVITY_HOURS`, `AUTH_SESSION_ABSOLUTE_DAYS`, and `AUTH_SESSION_COOKIE_NAME` are not in `.env.template`.** Add them with the documented defaults (24, 30, `auth_session_dev`) so operators can see they're tunable. Group them with the new `GOOGLE_OAUTH_*` and `AUTH_SESSION_SECRET` vars you'll add for A5.

These three are the only Wave-2 carry-overs in scope. Do not "tidy" anything else from Wave 2.

## Scope of PR-A5

**Branch:** `claude/auth-pr-a5-oauth`.

**Goal.** Ship Google OAuth Authorization-Code-with-PKCE flow, gated by `google_login_enabled=false` (default off — does not affect production traffic). Allowlisted users who log in get an `auth_users` row created/activated and a session cookie set. Non-allowlisted or unverified-email users get a clear denial with the same UX (no info leak about which accounts are allowlisted). Login attempts (success and denied with reason codes) are written to `admin_audit_log`.

After this PR merges, the only remaining Stage A work is **A8 readiness report**, then Stage B is a flag flip (`google_login_enabled=true`) and burn-in.

### Files (new)

- `src/auth/oauth.py` — Authorization Code + PKCE flow client. Builds the auth URL with `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`. Exchanges the auth code for tokens. Returns the validated ID token claims. Reads `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` from env. Stores `state`, `nonce`, `code_verifier` in the Flask session (the framework's signed-cookie session, separate from `auth_sessions` — these are short-lived per-flow values). Use `secrets.token_urlsafe()` for `state` and `nonce`.
- `src/auth/oidc_validate.py` — ID token validation per spec §OAuth/OIDC Implementation Requirements: signature against Google JWKS, `iss` is `https://accounts.google.com` or `accounts.google.com`, `aud == client_id`, `exp` in the future, `nonce` matches the value the app generated for this login attempt, `email_verified == true`. Use `google.oauth2.id_token.verify_oauth2_token` from `google-auth` (preferred) — do not roll JWT validation by hand. Returns the validated claims dict on success; raises a typed exception on failure (`OidcValidationError` with a `reason` code matching the audit reasons below).
- `src/web/routes/auth.py` — Flask blueprint registered at `/auth`. Routes:
  - `GET /auth/login?next=<path>` — generates `state`, `nonce`, PKCE pair; stashes them in the Flask session; redirects to Google's OAuth endpoint. Validates `next` per spec §UI Identity redirect-target rules (must start with `/`, not start with `//`, no `\`, no colon before first `/`, decode to a known route prefix; default `/v2/review/`).
  - `GET /auth/callback?code=...&state=...` — handles the callback. Validates `state`, exchanges code for tokens, validates the ID token, runs the allowlist check, upserts `auth_users` (sets `google_sub`, `display_name`, updates `last_login_at`; sets `first_login_at` if NULL), creates a session via `auth.sessions.create_session()`, sets the cookie via `auth.cookies.set_session_cookie()`, audits the success, redirects to the validated `next` URL.
  - `POST /auth/logout` — revokes the current session, clears the cookie, audits the logout, redirects to `/`. POST so it can't be CSRF'd via a `<a>` link or `<img>` tag (logout-CSRF is annoying but not security-critical; still better hygiene).
  - `GET /auth/denied?reason=<code>` — renders the access-denied page. Reasons: `not_allowlisted`, `email_unverified`, `account_disabled`, `oauth_state_mismatch`, `oauth_callback_error`, `oauth_id_token_invalid`. Page wording is identical for `not_allowlisted` and `email_unverified` (no leak about which one applies); other reasons can be more specific since they're not allowlist-related.
- `src/web/templates/auth/login.html` — minimal "Sign in with Google" page. One button. Used when an unauthenticated user hits a protected page (Stage C will add the redirect — for now just provide the template so it exists).
- `src/web/templates/auth/denied.html` — access-denied page parameterized on the `reason` query param.
- `src/web/templates/errors/403.html` — A2 expected this template (`require()` decorator falls back to JSON if missing). Tiny stub: "Forbidden" + a logout link.
- `tests/integration/auth/test_oauth_flow.py` — exercises:
  - Happy path: stubbed Google response → callback → `auth_users` row created with correct role from allowlist → session cookie set → `g.user` populated on subsequent request.
  - `email_verified=false` denial.
  - Allowlist miss denial.
  - `state` mismatch denial.
  - `nonce` mismatch denial (replayed callback).
  - Expired ID token denial.
  - Disabled-user-with-allowlist denial (rare: account got disabled between allowlist add and login).
  - Audit-log row written for each path with the correct reason code.
- `tests/unit/auth/test_oauth_url_validation.py` — tests for the redirect-target validator. Positive cases: `/v2/review/`, `/ingest/`. Negative cases: `//evil.com`, `\\evil.com`, `%2F%2Fevil.com`, `https://evil.com/`, `javascript:alert(1)`, `/foo/../../bar` (path traversal — should normalize before checking; reject if it escapes known prefixes).
- `tests/unit/auth/test_oidc_validate.py` — unit tests for `OidcValidator` with monkeypatched JWKS / clock.

### Files (modified)

- `src/web/app.py` — three changes:
  1. Add `app.before_request(load_session_user)` immediately after `verify_dev_bypass_safe()`, **before** the existing `csrf_protect` registration. (Wave-2 deviation #1.)
  2. Register the new `auth_bp` blueprint **conditionally** on `feature_flags.google_login_enabled`. Read the flag at app construction (acceptable to read once at boot — the flag is rolled out via deploy + flag flip in Stage B). If the flag is missing or false, do not register the blueprint and a request to `/auth/login` returns 404. This keeps the blueprint dormant until shadow mode begins.
  3. Ensure Flask's `SECRET_KEY` is read from `AUTH_SESSION_SECRET` env var (or wherever the project already wires it — check existing `app.py`; if there's no current secret-key wiring, add one). The framework's signed-cookie session needs this to stash `state`/`nonce`/`code_verifier` between login and callback.
- `src/auth/dev_bypass.py` — Wave-2 deviation #2: change `dev_bypass_user()` to return a real `SessionUser`. Drop the local `_DevBypassUser` dataclass.
- `requirements.txt` — add `google-auth >= 2.27,<3` (the `verify_oauth2_token` API and Google JWKS handling). If the project already has `google-auth` for an unrelated reason, just verify the version works.
- `.env.template` — add a section:
  ```
  # Auth (review UI)
  GOOGLE_OAUTH_CLIENT_ID=
  GOOGLE_OAUTH_CLIENT_SECRET=
  GOOGLE_OAUTH_REDIRECT_URI=http://localhost:5000/auth/callback
  AUTH_SESSION_SECRET=
  AUTH_SESSION_COOKIE_NAME=auth_session_dev
  AUTH_SESSION_INACTIVITY_HOURS=24
  AUTH_SESSION_ABSOLUTE_DAYS=30
  # AUTH_DEV_BYPASS=1   # local dev only — never set in production
  ```
  The first four (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `AUTH_SESSION_SECRET`) are real secrets / config; the others have defaults but should be visible.
- `CLAUDE.md` — Database section: brief note that `auth_users` rows are created on first successful OAuth callback for allowlisted users (was already mentioned that they exist; add the population semantic). Workflow section: nothing to add — `/commit-proj` flow is unchanged.

### Audit-log integration

Every login attempt writes one row to `admin_audit_log`. Use the following `action_type` and `error` values so the readiness report (PR-A8) and any future alerting can key off them:

| Outcome | `action_type` | `success` | `error` |
|---|---|---|---|
| Successful login | `auth.login` | TRUE | NULL |
| Logout | `auth.logout` | TRUE | NULL |
| Allowlist miss | `auth.login_denied` | FALSE | `not_allowlisted` |
| `email_verified=false` | `auth.login_denied` | FALSE | `email_unverified` |
| Disabled user logging in | `auth.login_denied` | FALSE | `account_disabled` |
| `state` parameter mismatch | `auth.login_denied` | FALSE | `oauth_state_mismatch` |
| Generic OAuth callback error | `auth.login_denied` | FALSE | `oauth_callback_error` |
| ID token validation failure | `auth.login_denied` | FALSE | `oauth_id_token_invalid` |

`actor_user_id` is NULL for denied login attempts (no user row yet). `actor_email` is the email from the (rejected) ID token claim if present, else NULL. `before_state` and `after_state` JSONB are populated for `auth.login` (snapshot of the `auth_users` row before/after upsert) and left NULL for denials.

### Conditional blueprint registration

The `auth_bp` blueprint should not register when `google_login_enabled=false`. Implementation:

```python
# in create_app(), after blueprints
from src.infra.feature_flags import is_enabled  # or equivalent — check what exists
if is_enabled("google_login_enabled"):
    from src.web.routes.auth import auth_bp
    app.register_blueprint(auth_bp)
```

If no `feature_flags` reader exists yet (likely — no Wave-2 PR added one), write a minimal one in `src/auth/feature_flags.py` as part of A5: a single function `is_enabled(key: str) -> bool` that reads the row from the `feature_flags` table, treats expired flags as off, and caches for ~5 seconds (the same TTL pattern A4's CSRF middleware uses; check that file for the precedent and reuse if possible). Don't build a flag-management UI; that's Stage E.

### Verification

- **Unit tests:** `pytest -x -q tests/unit/auth/`. All new tests pass; existing Wave-2 unit tests still pass.
- **Integration tests:** `pytest -x -q tests/integration/auth/`. The OAuth flow tests use a stubbed Google client (don't make real HTTP calls in tests); precedent for stubbing in this codebase is pytest fixtures that monkeypatch the relevant module-level callable.
- **Manual smoke (optional, requires Google OAuth credentials):** set the four env vars locally, set `google_login_enabled=true` in the dev DB, hit `/auth/login`, complete the Google flow, verify `auth_users` row exists, verify cookie is set, verify `g.user` is populated on `/v2/review/` (still public for now — A5 does not enforce auth on existing routes).
- **Required CI checks:** Lint, Unit Tests, Vulnerability Scan, Integration Tests, UI E2E (Playwright). UI E2E should not be affected by this PR — `google_login_enabled` defaults to false so no behavior changes for unauthenticated traffic.

### Verification-checklist items satisfied

(per spec §Verification Checklist)
- "Google login works in production" — gated; the test verifies the flow with stubbed Google.
- "Seeded admin / second admin / reviewer can log in successfully" — once the flag is flipped, but the test exercises the auto-provision logic with a stubbed allowlist.
- "Non-allowlisted Google account is denied correctly".
- "`email_verified=false` Google account is denied correctly".
- "Account-mismatch and unverified-email messages do not leak which accounts are allowlisted".

## Out of scope (do NOT expand into)

- **Route migration to `require()`** — Stage C / PR-C1.
- **Removing the same-origin API-key bypass** — Stage C / PR-C1.
- **`auth_enforcement_enabled` flag flip** — Stage C / PR-C2.
- **Backfill of legacy reviewer aliases** — Stage C / PR-C2.
- **Admin UI for users / flags / sessions** — deferred per spec §Deferred Follow-On Work.
- **Force-logout-all-on-disable** — deferred per spec.
- **Per-session CSRF token (rather than `Sec-Fetch-Site`)** — A4 chose `Sec-Fetch-Site`; revisit in Stage C only if needed.
- **Tidying anything else from Wave 2** beyond the three deviations enumerated above. If you spot another Wave-2 issue, file as `gh-N-<slug>` per `.claude/commands/commit-proj.md` step 9.

## Pre-implementation gate

This PR touches 8+ new files and modifies 4 existing ones (well past the 3-file threshold) AND involves auth/migration adjacent infrastructure (gate fires regardless). Run the full Pre-Implementation Gate from `~/.claude/CLAUDE.md`:

1. **Assumption audit.** Verify each assumption in this brief against current code. Specifically:
   - Does the project already have a `feature_flags` reader? Grep `src/` and `src/auth/` for `feature_flags` table reads. If A4's CSRF middleware reads it, you can reuse that helper.
   - What's the current `SECRET_KEY` source in `src/web/app.py`? Don't double-define.
   - Confirm Wave-2 deviation #1 (load_session_user not registered): `grep -n "load_session_user\|app.before_request" src/web/app.py`.
2. **Scope check.** Confirm only the listed files are touched. The "Wave-2 deviations to fold in" are the only deviation work; nothing else.
3. **Rules compliance.** Worktree (yes — touches 3+ files), `/commit-proj` for the PR, conventional commit message, no `--no-verify`, no force-push to main.
4. **Risk assessment.** Specific risks:
   - **`SECRET_KEY` change.** If the project already wires Flask's secret key from a different env var, changing it would invalidate any in-flight Flask session cookies (used today only for view-state restoration; check if anything in production relies on signed-cookie session state). Either wire `AUTH_SESSION_SECRET` as a NEW addition without changing the existing `SECRET_KEY` source (preferred), or document the rotation.
   - **Conditional blueprint registration.** The flag is read at app boot. If `google_login_enabled` is flipped at runtime, the blueprint won't appear until the next deploy. This is acceptable for Stage B (flag flip is paired with a deploy); document it.
   - **`auth_users` upsert race.** Two simultaneous logins from the same Google account would each try to upsert the row. PG handles this with `ON CONFLICT (normalized_email) DO UPDATE`; just make sure the upsert uses `normalized_email` as the conflict key, not `google_sub` (since `google_sub` is nullable for seeded rows, which would silently insert a duplicate row for the seeded admin on first login).
   - **`google-auth` library.** `verify_oauth2_token` can make a network call to Google's JWKS endpoint. Cache the verifier instance to avoid hammering the endpoint per request. Check the library's docs for the recommended caching pattern.
   - **CSRF on OAuth callback.** A4's CSRF middleware exempts `/auth/` paths (per the Wave-2 brief). Verify this exemption is actually in `src/auth/csrf.py`. If not, add it explicitly so the callback isn't blocked.
5. **Minimal path.** The brief is already minimal — no extra files beyond what's needed for the OAuth flow + tests + 3 deviation fixes.
6. **Worktree check.** `EnterWorktree` or `ccw claude/auth-pr-a5-oauth` before any edits.

Present the completed gate checklist to the user (the human in the session) for approval before implementing.

## Workflow

1. Worktree-first.
2. Pre-implementation gate (above), present, wait for approval.
3. Implement in dependency order:
   - First: `src/auth/oauth.py` and `src/auth/oidc_validate.py` (no Flask coupling; pure Python).
   - Then: `src/web/routes/auth.py` (depends on the above plus `src/auth/sessions.py`, `src/auth/cookies.py`).
   - Then: templates.
   - Then: `src/web/app.py` wiring (registration + load_session_user + conditional blueprint).
   - Then: dev-bypass fix.
   - Then: `.env.template` and `requirements.txt`.
   - Then: tests.
4. Run `pytest -x -q tests/unit/auth/ tests/integration/auth/` locally — must be green before commit.
5. `/commit-proj`. Out-of-scope triage step in `/commit-proj` — none expected, but if the implementation surfaced anything (e.g., a missing `feature_flags` reader was filed as a follow-on), include it as a separate fragment.
6. Auto-merge enabled via `gh pr merge --auto --squash`.
7. After merge, report:
   - PR number + commit SHA.
   - Confirm `pytest -x -q tests/unit/auth tests/integration/auth` is green on `origin/main`.
   - Confirm the `feature_flags` row for `google_login_enabled` exists or document that Stage B will need to seed it before flipping.
   - Recommend the next move: **Wave 4 = PR-A8 readiness report**, then Stage B flag flip.

## Risks worth flagging at execution time

- **Render env-group is invisible to git audit** (per memory `project_render_env_invisible_to_git_audit.md`). The four new env vars (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `AUTH_SESSION_SECRET`) must be added to the Render env group **before** Stage B can begin. Surface this in your final report.
- **Google Cloud Console OAuth client setup** is a manual prerequisite. The implementer doesn't do this — but the user does need to: (a) create an OAuth 2.0 client in Google Cloud Console, (b) add `https://<prod-domain>/auth/callback` and `http://localhost:5000/auth/callback` as authorized redirect URIs, (c) provide the client ID/secret to Render env group. Mention in the final report.
- **Flask session cookie vs auth_session cookie.** They are different things. The Flask framework cookie holds short-lived OAuth state (`state`, `nonce`, `code_verifier`). The `auth_session_dev` cookie (set by A3's `set_session_cookie`) holds the long-lived session id. Don't conflate them. If the project doesn't currently use Flask's framework session at all, this PR introduces it — that's fine.

## Reporting back

When PR-A5 is merged, provide:
- PR number, commit SHA, merge timestamp.
- Test status: `pytest -x -q tests/unit/auth tests/integration/auth` exit code.
- The five `[DECISION]`-equivalent items the user must complete before Stage B flag flip:
  1. Google OAuth client created in Google Cloud Console.
  2. `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` added to Render env group.
  3. `GOOGLE_OAUTH_REDIRECT_URI` set to the production callback URL in Render env group.
  4. `AUTH_SESSION_SECRET` set to a strong random value in Render env group.
  5. `feature_flags` row for `google_login_enabled` seeded as `false` (or stays absent and reads default-false).
- Recommend Wave 4 as the next session's task.

## What you (implementer) do NOT do

- Do not flip `google_login_enabled=true` in any environment. That's a Stage B operator action.
- Do not modify the spec or implementation plan except to record `[DECISION]` resolutions or correct factual errors discovered during implementation.
- Do not change `auth_enforcement_enabled` semantics. A5 is shadow-mode-eligible only.
- Do not delete or rename anything Wave 2 shipped (other than the 3 enumerated deviations).

Good luck.
