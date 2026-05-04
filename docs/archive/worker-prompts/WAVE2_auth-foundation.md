You are the orchestrator for **Wave 2 of the review-UI authorization rollout**. PR-A1 (schema foundation) shipped in PR #403 (merged 2026-05-01). Your job is to ship the five Wave-2 PRs (A2, A3, A4, A6, A7) — they unlock A5 (OAuth, Wave 3) and A8 (readiness, Wave 4).

This is a multi-PR orchestration task. Read the entire prompt before doing anything.

## Source of truth (read these first, in this order)

1. `docs/architecture/auth-rollout-implementation-plan.md` — authoritative PR catalog, dependency graph, file-touch lists per PR. Every Wave-2 PR has a section.
2. `docs/requirements/review-ui-authorization-spec.md` — authoritative requirements. The spec is "draft for implementation" status; implementers should not re-derive security primitives.
3. `CLAUDE.md` (project root) — read in full; especially Pre-Implementation Gate, Implementation Rules, Database section (now lists the auth tables from PR #403), Workflow (PR-required, worktree-first).
4. `~/.claude/CLAUDE.md` (global) — Pre-Implementation Gate item 6 (worktree mandatory for 3+ files), Subagent Model Selection, Implementation Rules.
5. Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully, apply.
6. `.claude/rules/web.md` — current web-route + reviewer-identity contract (lots of constraints; especially `_require_reviewer_id` and same-origin API-key bypass behavior — both relevant to A4 and indirectly to A2/A3).
7. `.claude/rules/sql.md` — only relevant if any Wave-2 PR needs an unexpected migration (none planned; if one is needed, that's a scope alarm).

## What's done

- **PR-A1 (#403, merged 2026-05-01).** Schema foundation: `auth_users`, `auth_sessions`, `auth_access_entries`, `auth_legacy_aliases`, `feature_flags`, `admin_audit_log`, plus nullable `user_id UUID REFERENCES auth_users(id)` on `v2_review_decisions`, `v2_image_metric_confirmations`, `v2_ingest_batches`. Zero behavior change. App code does not reference any of the new tables yet.
- **Two `[DECISION]` markers in the spec are resolved** (PR #401, merged): second admin email is `rob.markey@cmasb.org`; staging is none / accepted risk.

## What Wave 2 ships

Five PRs in parallel after PR-A1 is the dependency:

| PR | Theme | Schema dep | Conflict on `src/web/app.py` |
|---|---|---|---|
| **A2** | Permission catalog + authorization middleware | none (pure code, but spec says routes should call `require(<permission>)` later) | yes (registers nothing in app.py for this PR — but A5 will, so A2 can stay app.py-free) |
| **A3** | DB-backed session store + cookie attributes + `load_session_user` before_request | yes (`auth_users`, `auth_sessions`) | yes (registers `before_request` hook) |
| **A4** | CSRF middleware (gated; effective only when `auth_enforcement_enabled=true`) | none | yes (registers middleware) |
| **A6** | Production dev-bypass startup guard (`AUTH_DEV_BYPASS=1` + startup assertion) | none | yes (calls `verify_dev_bypass_safe()` at startup) |
| **A7** | Seed scripts (initial users, allowlist, alias mappings) | yes (`auth_users`, `auth_access_entries`, `auth_legacy_aliases`) | none (scripts only) |

After Wave 2 merges, **Wave 3** is **A5 (OAuth)** which depends on A3. **Wave 4** is **A8 (readiness)** which depends on A5. Both are explicitly OUT OF SCOPE for this task.

## Dispatch strategy

You are a single orchestrator session. Dispatch the five PRs as **parallel worktree agents**, NOT by opening five `ccw` tabs and asking the user. Per global CLAUDE.md and the implementation plan's "Parallel-dispatch guidance" section.

**Concrete dispatch:** spawn five `Agent` calls in a single message, each with `isolation: "worktree"` and `subagent_type: "dev-implementer"` (the project has this agent for non-extraction implementation work; if not present, fall back to `general-purpose`). Use **`model: "sonnet"`** explicitly — these are code-writing tasks per global CLAUDE.md "Subagent Model Selection". Each agent prompt should be a self-contained brief built from one of the per-PR sections below.

**After dispatch, supervise** via `/loop 5m /supervise-prs <pr-numbers>`. Don't sleep, don't poll manually — the loop fires every 5 minutes until you stop it.

**Conflict-surface handling on `src/web/app.py`.** Four of the five PRs (A2 may be exempt — see below) modify `src/web/app.py`. Strategy:
- All five agents start in parallel against `origin/main` (post-A1 merge).
- The first PR to land merges cleanly.
- Subsequent PRs encounter rebase conflicts on `src/web/app.py` — these are usually trivial (each PR adds a one-line registration in the same `create_app()` function). **You** (orchestrator) handle the rebase as each PR's auto-merge fails.
- Order PRs by smallest `app.py` footprint first when resolving rebase conflicts: A6 (1 line) < A4 (1–2 lines) < A3 (2–3 lines).
- A2 is the exception: don't wire it into `app.py` in this PR. The `require()` decorator only matters when routes start using it (Stage C). For Wave 2, A2 is just code in `src/auth/` plus unit tests.

**Pre-implementation gate** must run inside each agent for its own PR scope (3+ files in every Wave-2 PR; the gate fires). Each agent presents its checklist to YOU (the orchestrator) before implementing. You are the user for those agents.

## Per-PR briefs

Each agent receives the corresponding section below as its prompt, prefaced with a self-contained "you are working PR-AX" framing and the source-of-truth list above (without the orchestration text). Keep agent prompts focused on their PR; do not include the orchestration logic.

---

### PR-A2: Permission catalog + authorization middleware

**Branch:** `claude/auth-pr-a2-permission-catalog`.

**Scope.** Build the centralized permission catalog and `require(<permission>)` decorator. No route changes (Stage C does that). No `src/web/app.py` changes (nothing to register yet — the decorator is invoked per-route and looked up off `g.user`, which A3 populates).

**Files (new).**
- `src/auth/__init__.py` — empty or re-exports.
- `src/auth/permissions.py` — permission name constants and `ROLE_PERMISSIONS: dict[str, frozenset[str]]` map. Source: spec §Permission Catalog. Exact permissions: `decision.write`, `decision.undo.own`, `decision.undo.any`, `metric.add_missed`, `ingest.run`, `users.manage`, `flags.manage`, `audit.read`, `readiness.read`, `protected.read`. Exact role mapping: per the table in spec §Permission Catalog.
- `src/auth/middleware.py` — `require(permission: str)` decorator factory. Looks up `g.user` (set by A3's load handler — until A3 lands, in tests use a fixture that monkey-patches `g.user`). On unauthenticated: 401 (HTML redirect to `/auth/login` if `Accept: text/html`, else JSON). On authenticated-but-unauthorized: 403. Use `flask.g`.
- `tests/unit/auth/__init__.py`
- `tests/unit/auth/test_permissions.py` — assert role × permission map matches the spec table cell-by-cell. Negative tests for typos.
- `tests/unit/auth/test_middleware.py` — fixture sets `g.user = SimpleNamespace(role='reviewer')`. Decorated test route returns 200 for an allowed permission, 403 for a disallowed one. Unauthenticated (`g.user = None`) returns 401 JSON for `Accept: application/json` and a redirect for `Accept: text/html`.

**Files (modified).** None (no app.py wiring). If the test framework needs `src/auth` on the import path, that should already work via standard Python packaging.

**Verification.**
- `pytest -x -q tests/unit/auth/` — both files pass.
- The role-permission table in `permissions.py` must structurally match the spec's table (author the test by reading the spec, not by reading the code under test).

**Verification-checklist items satisfied.** "Role restrictions behave correctly" (functional, full coverage in Stage C); enables A5 and Stage C.

**Out of scope:** route-level decorator application, session loading (A3), `app.py` registration (Stage C/A5).

**Estimated size:** ~150 LOC code + ~150 LOC tests.

---

### PR-A3: DB-backed session store + load_session_user middleware

**Branch:** `claude/auth-pr-a3-session-store`.

**Scope.** The session table reads/writes, cookie issuance helpers, and the `before_request` hook that populates `g.user` from the session cookie. Sliding inactivity (24h) and absolute expiry (30d) per spec §Session Behavior.

**Files (new).**
- `src/auth/sessions.py` — `create_session(user_id) -> session_id`, `lookup_session(session_id) -> SessionUser | None`, `extend_session(session_id)`, `revoke_session(session_id)`, `revoke_all_for_user(user_id)`. `SessionUser` is a small dataclass with `id`, `email`, `display_name`, `role`, `account_status`. Lookup returns None if session expired, user disabled, or session id not in `auth_sessions`. Lookup also enforces the 30-day absolute lifetime by comparing `auth_sessions.created_at` to NOW().
- `src/auth/cookies.py` — `set_session_cookie(response, session_id)` and `clear_session_cookie(response)`. Cookie name from `AUTH_SESSION_COOKIE_NAME` env var (default `auth_session_dev`); attributes hard-coded `Secure`, `HttpOnly`, `SameSite=Lax`. **In dev (when `FLASK_ENV != 'production'`), `Secure` may be `False`** so cookies work on `http://localhost`. Document this in the function docstring.
- `src/auth/load_user.py` — `load_session_user()` Flask `before_request` callback. Reads cookie, looks up session, sets `g.user = SessionUser` or `g.user = None`. Idempotent / safe on every request.
- `tests/unit/auth/test_sessions.py` — create / lookup / extend / revoke happy paths; expired session returns None; disabled user returns None; absolute-lifetime cap enforced.
- `tests/unit/auth/test_cookies.py` — cookie attributes test (`Secure; HttpOnly; SameSite=Lax` in prod-config; `Secure=False` in dev-config).
- `tests/integration/auth/test_load_session_user.py` — end-to-end: create_session → set cookie → request with cookie → `g.user` populated → request without cookie → `g.user is None` → revoke session → request with same cookie → `g.user is None`.

**Files (modified).**
- `src/web/app.py` — register `load_session_user` as a `before_request` on the app (or on each blueprint that needs auth — single app-level registration is simpler).
- `.env.template` — `AUTH_SESSION_COOKIE_NAME`, `AUTH_SESSION_SECRET`, `AUTH_SESSION_INACTIVITY_HOURS=24`, `AUTH_SESSION_ABSOLUTE_DAYS=30`.
- `CLAUDE.md` — auth section: note that `g.user` is set per-request once `auth_enforcement_enabled` flips on (currently flag is off, so `g.user` is always None in production until Stage C).

**Conflict surface.** `src/web/app.py` — adds one `before_request` registration. Will conflict with A4 and A6's `app.py` edits when the second PR rebases.

**Verification.**
- `pytest -x -q tests/unit/auth/test_sessions.py tests/unit/auth/test_cookies.py tests/integration/auth/test_load_session_user.py`.
- Session id rotation test: a session id obtained from `create_session()` is not reused after `revoke_session()` (no cache hit on lookup).
- Cross-env test: a cookie signed with one `AUTH_SESSION_SECRET` cannot be decoded with another. (If cookies are signed; if the cookie holds only the session id and signing happens via Flask's `itsdangerous` or similar, this test naturally falls out.)

**Verification-checklist items satisfied.** "Logout invalidates server-side session"; cookie attribute test; enables A5 (OAuth callback creates a session).

**Out of scope:** OAuth flow (A5), `g.user` consumption by routes (Stage C), CSRF (A4).

**Implementation notes.**
- `auth_sessions.id` is UUID per A1 schema. App can use `gen_random_uuid()` via DB DEFAULT or generate Python-side via `uuid.uuid4()`.
- Session store should use the existing `src/infra/db.py` `DatabaseAdapter` pattern — do NOT spin up a parallel connection layer.
- For `last_seen_at` updates: extend on every successful lookup. Be aware this is a write per request — cheap but not free. Note in the docstring; future optimization could batch / TTL these updates.

**Estimated size:** ~250 LOC code + ~300 LOC tests.

---

### PR-A4: CSRF middleware

**Branch:** `claude/auth-pr-a4-csrf`.

**Scope.** CSRF protection middleware for state-changing endpoints, gated such that it does NOT block today's traffic but WILL block cross-site requests once `auth_enforcement_enabled=true`.

**Mechanism.** Use **`Sec-Fetch-Site` + `Origin` header verification** (per spec §CSRF Protection and the Wave-2 plan's recommendation). This reuses the existing same-origin helper logic in `src/web/middleware.py` (see `.claude/rules/web.md` line 43 — there's already an Origin/Referer comparator). Do not introduce a per-session CSRF token in this PR.

**Files (new).**
- `src/auth/csrf.py` — `csrf_protect()` `before_request` hook. On state-changing methods (POST/PUT/PATCH/DELETE), if `Sec-Fetch-Site: same-origin` is missing AND `Origin` does not match the current host (scheme-independent), return 403 JSON. Exempt:
  - GET/HEAD/OPTIONS requests.
  - The OAuth callback path (will be `/auth/callback` once A5 lands; for Wave 2, exempt by path prefix `/auth/`).
  - When `auth_enforcement_enabled` flag is **off** (read from `feature_flags`), the middleware is a no-op. This keeps current behavior intact.
- `tests/unit/auth/test_csrf.py` — positive: same-origin POST passes. Negative: cross-origin POST returns 403. Exemption: GET passes regardless. Exemption: when `auth_enforcement_enabled=false`, cross-origin POST passes.

**Files (modified).**
- `src/web/app.py` — register `csrf_protect` as `before_request`.
- `src/web/middleware.py` — if the existing Origin-comparator helper isn't already a separately-callable function, refactor it into one so `csrf.py` can reuse it. Otherwise no edit.

**Conflict surface.** `src/web/app.py` (one line). Possibly `src/web/middleware.py` if helper-extraction is needed.

**Verification.**
- Tests above, all passing.
- Manual sanity: flip `auth_enforcement_enabled=true` in a dev DB and confirm a POST to `/api/v2/<anything>` from an unrelated localhost port returns 403 (curl with `--header "Origin: http://other:8080"`).

**Verification-checklist items satisfied.** "CSRF attempt from cross-origin page rejected" (negative-path).

**Out of scope:**
- Per-session CSRF tokens (defer if Sec-Fetch-Site approach proves brittle).
- Removing the same-origin API-key bypass — that happens in Stage C / PR-C1, not here. Wave 2 does not change auth enforcement on routes.

**Implementation notes.**
- Read the `auth_enforcement_enabled` flag inside the middleware (not at app boot) so an admin flag flip takes effect on the next request.
- Cache the flag value briefly (~5 seconds) to avoid hammering the DB on every request — but keep this cache trivial; no fancy invalidation.
- `Sec-Fetch-Site` is sent by all modern browsers (Chrome ≥ 76, Firefox ≥ 90, Safari ≥ 16). For older clients, fall back to `Origin` header equality with the request host. Document the fallback in the docstring.

**Estimated size:** ~120 LOC code + ~150 LOC tests.

---

### PR-A6: Production dev-bypass startup guard

**Branch:** `claude/auth-pr-a6-dev-bypass-guard`.

**Scope.** A startup assertion that prevents `FLASK_ENV=production` AND `AUTH_DEV_BYPASS=1` from coexisting. The dev-bypass identity provider (used by tests and local dev) is also defined here so future PRs can import it.

**Files (new).**
- `src/auth/dev_bypass.py`:
  - `verify_dev_bypass_safe() -> None` — reads `os.environ`, raises `RuntimeError` and writes a fatal message to stderr if production+bypass coexist.
  - `is_dev_bypass_enabled() -> bool` — single source of truth.
  - `dev_bypass_user() -> SessionUser` — returns a synthetic admin SessionUser when bypass is on. Used by tests and local dev to skip Google login.
- `tests/unit/auth/test_dev_bypass_guard.py`:
  - Production config + bypass set → `verify_dev_bypass_safe()` raises.
  - Production config + bypass unset → `verify_dev_bypass_safe()` returns None.
  - Dev config + bypass set → `verify_dev_bypass_safe()` returns None.
  - Use `monkeypatch.setenv` / `monkeypatch.delenv` to control state.

**Files (modified).**
- `src/web/app.py` — call `verify_dev_bypass_safe()` once at app construction (top of `create_app()` or wherever the app factory lives).
- `.env.template` — `AUTH_DEV_BYPASS` (commented out by default with explanatory line).
- `CLAUDE.md` — Workflow / dev-environment section: note the env var's existence and the guard.

**Conflict surface.** `src/web/app.py` (one line; should be at the very top of `create_app()`).

**Verification.**
- Tests above, all passing.
- Manually: `FLASK_ENV=production AUTH_DEV_BYPASS=1 python3 -c "from src.web.app import create_app; create_app()"` exits non-zero with a clear stderr message.

**Verification-checklist items satisfied.** "Production dev-bypass startup guard refuses to boot when both `FLASK_ENV=production` and `AUTH_DEV_BYPASS=1`" (negative-path).

**Out of scope:**
- Routes / decorators that USE `dev_bypass_user()` — that's wired into A3's `load_session_user` or A5's OAuth flow, not here.
- Tests that exercise the bypass identity end-to-end through a route — Stage C work.

**Implementation notes.**
- Detect production via `os.environ.get("FLASK_ENV")`. The project's existing convention may use a different env var (check `src/web/app.py` for what `app.config['ENV']` maps from). Match the existing pattern.
- Render env groups must NOT define `AUTH_DEV_BYPASS`. The PR doesn't enforce this server-side — it's a documentation thing in the env file.

**Estimated size:** ~80 LOC code + ~100 LOC tests.

---

### PR-A7: Seed scripts (users + allowlist + alias mappings)

**Branch:** `claude/auth-pr-a7-seed-scripts`.

**Scope.** Idempotent seed scripts so admins can populate `auth_users`, `auth_access_entries`, and `auth_legacy_aliases` without hand-editing SQL.

**Files (new).**
- `scripts/seed_auth_users.py` — argparse CLI. Default invocation seeds the spec's three users (idempotent UPSERT on `normalized_email`):
  - `rgmarkey@gmail.com` → role `admin`
  - `rob.markey@cmasb.org` → role `admin`
  - `mayujoiner@gmail.com` → role `reviewer`
  Also writes corresponding `auth_access_entries` rows. Optional flags: `--add EMAIL ROLE`, `--remove EMAIL`, `--list`. Writes to `admin_audit_log` with `action_type='seed_users'`.
- `scripts/seed_auth_legacy_aliases.py` — argparse CLI. Default invocation seeds:
  - `RGM` → `rgmarkey@gmail.com`
  - `Mayu` → `mayujoiner@gmail.com`
  Optional flags: `--add LEGACY EMAIL`, `--remove LEGACY`, `--list`.
- `tests/integration/auth/test_seed_scripts.py` — load each script via `importlib` (per `.claude/rules/scripts.md` testing convention; precedent: `tests/integration/test_onboard_tickers_cli.py`). Run twice; verify second run is a no-op (no duplicate rows, no errors). Run with `--add` and verify new row appears. Run `--remove` and verify (soft delete or row removal — pick one and document; for `auth_users`, prefer `account_status='disabled'`; for aliases, prefer hard delete since they're easy to recreate).

**Files (modified).**
- `CLAUDE.md` — admin operations section: document the new scripts and how to run them.

**Conflict surface.** None (scripts only, no shared code, no `src/web/app.py`).

**Verification.**
- `pytest -x -q tests/integration/auth/test_seed_scripts.py`.
- Manual: `python3 scripts/seed_auth_users.py` against a dev DB; `psql -c "SELECT normalized_email, role, account_status FROM auth_users;"` shows the three seeded users.

**Verification-checklist items satisfied.** "Seeded admin / second admin / reviewer can log in successfully" (functional; gated on A5 for actual login).

**Out of scope:**
- A backfill script for legacy reviewer-id rows — that's Stage C / PR-C2.
- Bulk-import from CSV — overkill for three users.

**Implementation notes.**
- Use the existing `src/infra/db.py` `DatabaseAdapter` and its connection pooling. Do NOT open new psycopg connections by hand.
- Prefer `INSERT ... ON CONFLICT (normalized_email) DO UPDATE SET role = EXCLUDED.role` so re-running with a different role updates correctly.
- The audit-log entry should include `before_state` and `after_state` JSONB for the user row, populated only when the row actually changed.

**Estimated size:** ~250 LOC code (across 2 scripts) + ~200 LOC tests.

---

## Out of scope for Wave 2 (do NOT expand into)

- **A5 (OAuth flow).** Wave 3. Depends on A3.
- **A8 (readiness report).** Wave 4. Depends on A5.
- **C1 / C2 (route migration to `require()`, backfill, flag flip).** Stage C.
- **Removing the same-origin API-key bypass.** Stage C / PR-C1.
- **Admin UI.** Deferred follow-on per spec §Deferred Follow-On Work.
- **Force-logout-all on user disable.** Deferred per spec §Decisions → Account Status.

If something tempts you, file as `gh-N-<slug>` per `.claude/commands/commit-proj.md` step 9 (out-of-scope triage). Do not silently expand a Wave-2 PR.

## Pre-implementation gate per PR

Each PR independently triggers the gate (3+ files in every Wave-2 PR; the gate fires regardless on auth/migration changes).

When you spawn each agent, instruct it to:
1. Sync against latest `origin/main` (post-A1 + any earlier-Wave-2 PR that landed).
2. Verify the assumptions in its brief against current code.
3. Present its completed Pre-Implementation Gate checklist for orchestrator approval (you, the orchestrator session, are the user for that agent).
4. Implement only after you approve.
5. Commit + open PR via `/commit-proj`.
6. Enable auto-merge.

## Supervision

After all five agents are dispatched and their PRs are open:

```
/loop 5m /supervise-prs <pr-A2> <pr-A3> <pr-A4> <pr-A6> <pr-A7>
```

Per loop iteration:
- Check each PR's check status.
- If any check is red, run `/ci-fix` on that branch.
- If any merge fails because of an `app.py` rebase conflict, do the rebase manually (the conflict is one-line registration in `create_app()`; trivial). Force-push with `--force-with-lease` to the PR branch.
- When all five PRs are merged, exit the loop and report.

## Reporting back

When Wave 2 is complete:
- Confirm each PR merged (PR numbers + commit SHAs).
- Confirm the resulting `src/web/app.py` registers `verify_dev_bypass_safe()` (A6), `load_session_user` `before_request` (A3), and `csrf_protect` `before_request` (A4) — and that the auth blueprint scaffold exists for A5 to plug into.
- Confirm `python3 -m pytest -x -q tests/unit/auth tests/integration/auth` passes locally on `origin/main`.
- Note any out-of-scope items filed (`gh-N-<slug>` issues).
- Recommend the next move (Wave 3 = A5 OAuth, depends on A3 which is now landed).

## Risks worth flagging at orchestration time

- **`src/web/app.py` rebase conflicts** are the highest-friction item. Three of the five PRs add a registration line. Plan to rebase 2 of the 3 manually.
- **`AUTH_SESSION_SECRET` env var** is needed by A3 in production. Ensure it's added to the Render env group **before** A3 lands (it doesn't have to be present at boot for the app to start — sessions just won't be signable — but it's a deploy-time gotcha).
- **Render env-group is invisible to git audit** (per memory `project_render_env_invisible_to_git_audit.md`). Document the new env vars in `.env.template`, but the actual production env-group update requires a manual step. Surface this in the final report.
- **`auth_enforcement_enabled` flag is read by A4's CSRF middleware.** The flag row must exist in `feature_flags` before A4 deploys, OR A4's middleware must default to "off" when the row is missing. Pick the default-off approach to avoid a deploy-order coupling.
- **Test isolation under pytest-xdist.** Each integration test gets its own DB (per `tests/integration/conftest.py`). The seed scripts in A7 must work against a freshly-migrated empty DB — don't assume the spec's three users are already present.

## What you (orchestrator) do NOT do

- Do not pick up A5 or A8 in this session, even if Wave 2 finishes early. Stop and hand back to the user.
- Do not modify the spec or the implementation plan doc except to record `[DECISION]` resolutions or correct factual errors discovered during implementation.
- Do not commit anything in the orchestrator session itself. All commits happen inside the spawned worktree agents via `/commit-proj`.
- Do not attempt to delete the `auth_*` tables created by A1, even if a test seems to leave them in a broken state. Investigate; fix forward.

Good luck.
