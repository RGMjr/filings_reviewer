You are the orchestrator for **Stage C of the review-UI authorization rollout** — Staged Enforcement. This is the cycle that finally turns the auth surface from "shadow mode" into actual enforcement: routes start gating on `require(<permission>)` instead of `FILINGS_API_KEY`, the same-origin API-key bypass is removed, and `auth_enforcement_enabled` flips to `true`. Stage A and Stage B are done. Stage D (legacy retirement post-May-10) is a future cycle.

This is a multi-PR orchestration task. Read the entire prompt before doing anything.

## Source of truth (read these first, in order)

1. `docs/architecture/auth-rollout-implementation-plan.md` — authoritative PR catalog. Stage C has its own section (`Stage C — Staged Enforcement: PR catalog`) listing C1 (route migration) and C2 (backfill + flag flip).
2. `docs/requirements/review-ui-authorization-spec.md` — authoritative requirements. Especially **§Cutover Rules** (Stage-C readiness criteria + 4-hour legacy-session bound), **§Permission Catalog**, **§Backfill Strategy**, **§Cutover Rules → Existing Open Pages at Enforcement Time**.
3. `docs/operations/auth-stage-b-runbook.md` — Stage B runbook (already shipped). Stage C's runbook (this PR) follows the same template.
4. `CLAUDE.md` (project root) — Pre-Implementation Gate, Implementation Rules, Workflow, Database section, Reviewer-identity invariant in `.claude/rules/web.md`.
5. `~/.claude/CLAUDE.md` (global) — Pre-Implementation Gate item 6 (worktree mandatory for 3+ files), Subagent Model Selection (use `sonnet` for code-writing subagents).
6. Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
7. `.claude/rules/web.md` — current web-route + reviewer-identity contract. **Especially the same-origin API-key bypass section** (`src/web/middleware.py` lines 27–73) — Stage C removes it.
8. `docs/worker-prompts/WAVE4_auth-readiness.md` — most recent precedent for handoff structure.

## What's done

- **Stage A** (PRs #403 / Wave 2 / Wave 3 / pre-Wave-4 follow-ups / Wave 4): foundation, OAuth flow, sessions, CSRF, permission catalog, dev-bypass, seed scripts, readiness report, Stage-B runbook.
- **Stage B** (operator activation per `docs/operations/auth-stage-b-runbook.md`): assumed to be in progress or complete by the time you start work — confirm with the user before flipping `auth_enforcement_enabled`.

## A8 follow-ups (out of scope for this cycle)

The Wave-4 critical eval surfaced three minor issues in `scripts/auth_readiness_report.py` that are NOT required for Stage C:

1. Dev-bypass guard verifies the local env, not production env (limitation of running `--check` from a dev machine).
2. The dev-bypass predicate is duplicated instead of importing `is_dev_bypass_enabled()`.
3. JSON serialization is only tested with empty data.

Don't fix these inside Stage C — file as `gh-N` per `.claude/commands/commit-proj.md` step 9 if you have cycles.

## What Stage C ships

Two PRs. The dependency between them is **the operator's flag-flip step**, not a code dependency — both can be developed in parallel. C1 must merge first because C2's runbook references the route-migration outcome.

| PR | Theme | Files touched | Conflict surface |
|---|---|---|---|
| **C1** | Route migration to `require()` + same-origin API-key bypass removal + 4-hour legacy-session bound | ~8 route modules, `src/web/middleware.py`, `src/auth/load_user.py`, route + auth tests | `src/web/middleware.py` (single file, single PR); modest test reshuffles |
| **C2** | Backfill apply script + Stage-C operator runbook | `scripts/backfill_legacy_reviewer_aliases.py` (new), `tests/integration/auth/test_backfill.py` (new), `docs/operations/auth-stage-c-runbook.md` (new), `CLAUDE.md` (modify) | none |

Behaviour change in C1 is **gated on `auth_enforcement_enabled`**: when the flag is off (default), the existing API-key path remains active and `require()` decorators are no-ops via the existing decorator pass-through. When the flag flips on (operator action, post-merge of both PRs), enforcement begins. This means **C1 is safe to merge before Stage B has finished soaking** — no behavior change until the operator flips the flag.

### Dispatch strategy

Two parallel worktree agents. Spawn them in a single `Agent` call message with `isolation: "worktree"`, `subagent_type: "dev-implementer"`, `model: "sonnet"`. Each gets the per-PR brief below as a self-contained prompt.

Supervise via `/loop 5m /supervise-prs <c1-pr> <c2-pr>`.

After both PRs merge AND Stage B has soaked (operator confirms), the user runs through `docs/operations/auth-stage-c-runbook.md` (shipped by C2) for the actual flag flip.

---

## PR-C1 brief — Route migration + bypass removal + legacy-session bound

**Branch:** `claude/auth-pr-c1-route-migration`.

### Scope

Three intertwined changes in one PR (they all touch `src/web/middleware.py` and the auth surface, so bundling avoids rebase storms):

1. **Apply `require(<permission>)` decorators to every protected route.** Stage C is when shadow-mode auth becomes real auth. Routes currently gate on `FILINGS_API_KEY` via `_check_api_key` `before_request`; replace that with per-route `@require(...)` calls. The decorator already exists from PR-A2 — just call it.

2. **Remove the same-origin API-key bypass.** `src/web/middleware.py` lines 62–73 currently let same-origin browser requests skip the API key. With session auth in place, this bypass is redundant and dangerous (browser cookies auto-fill, so any same-origin XSS becomes a fully-authenticated request). Delete the bypass branch; the API key now only authenticates `Authorization: ApiKey ...` headers from non-browser callers.

3. **Add the 4-hour legacy-session bound.** Per spec §Cutover Rules → Existing Open Pages at Enforcement Time: legacy sessions created before the enforcement flip are forcibly invalidated 4 hours after the flip. Implement in `src/auth/load_user.py`: when looking up a session, also fetch `feature_flags WHERE key='auth_enforcement_enabled' AND value='true'`. If the flag row exists and `session.created_at < flag.updated_at` and `(NOW() - flag.updated_at) > 4 hours`, return None (session rejected). The session row stays in the table; the request gets 401.

### Files (modified)

- `src/web/routes/review_unified.py` — HTML pages → `@require('protected.read')` on GETs.
- `src/web/routes/api_unified.py` — the bulk of the work:
  - GET endpoints (reads): `@require('protected.read')`.
  - POST `/api/v2/decisions` and image-decision endpoints: `@require('decision.write')`.
  - DELETE undo endpoints: `@require('decision.undo.own')` PLUS handler-level ownership check (resolve `g.user.id` against the row's `user_id` or via the legacy alias table; if not owned AND user lacks `decision.undo.any`, return 403). Admins bypass via the `undo.any` permission grant.
  - POST `/api/v2/missed-metric`: `@require('metric.add_missed')`.
  - Read `g.user.id` and write it to the row's `user_id` column on every state-changing endpoint. **Continue dual-writing** the legacy `reviewer_id` text field (per spec §Compatibility Requirements; PR-A5 already established email as the value).
- `src/web/routes/ingest.py` — `@require('ingest.run')`.
- `src/web/routes/api_ingest.py` — `@require('ingest.run')`.
- `src/web/routes/review_pres_images.py` — `@require('decision.write')` on writes; `@require('protected.read')` on the index page.
- `src/web/routes/image_cache.py` — `@require('protected.read')` (per spec §Protected Surface Scope: image endpoints are no longer a public exception).
- `src/web/routes/_metrics.py` — leave as-is unless it's user-facing. If it's a Prometheus exporter on a separate port/host, document the exclusion. If it's behind the regular HTTP server, decide whether `protected.read` or no auth is appropriate.
- `src/web/routes/review.py` — legacy V1 redirect shim. No decorator needed (it just 301s to V2).
- `src/web/middleware.py` — delete the same-origin bypass (lines ~62–73 of current file). Keep `require_api_key` for non-browser callers via `Authorization: ApiKey` header. Remove the blueprint-wide `_check_api_key` `before_request` registration (`register_api_auth`).
- `src/auth/load_user.py` — add the 4-hour legacy-session bound check. Use `src/auth/feature_flags.py::is_enabled(...)` would NOT work here (it returns bool, not the timestamp); use a new helper or inline the SELECT against `feature_flags`.

**Optional but recommended:** add `src/auth/enforcement.py` with a single helper `enforcement_started_at() -> datetime | None` so the legacy-session check has a clean home.

### Tests

- `tests/integration/auth/test_route_enforcement.py` (new) — for each protected route module, test:
  - Unauthenticated request → 401 (JSON) or login redirect (HTML).
  - Authenticated `viewer` to a `decision.write` route → 403.
  - Authenticated `reviewer` to a `decision.undo.any` route → 403.
  - Authenticated `admin` to anything → 200.
- Exercise via `monkeypatch`-set `g.user` and the dev-bypass route.
- `tests/unit/auth/test_legacy_session_bound.py` (new) — `lookup_session` returns None when session predates `auth_enforcement_enabled` flip and 4h has elapsed; returns the session normally when within the 4h grace OR flag is off.
- Existing tests should mostly keep passing. Update any test that relied on the same-origin bypass (the `_is_same_origin()` helper test, if it exists).

### Conflict-surface notes

- All three sub-changes touch `src/web/middleware.py` and `src/auth/load_user.py` — keep them in one PR to avoid rebase pain.
- `src/web/app.py` may need adjustment if `register_api_auth` was called from there for any blueprint; verify and update.
- The CSRF middleware (PR-A4) reads `auth_enforcement_enabled` to gate itself. Confirm it still behaves correctly post-migration: when the flag flips on, CSRF middleware activates AND the `require()` decorators activate together. Both are on/off based on the same flag.

### Pre-implementation gate

This PR touches 10+ files. The gate fires. Run the full Pre-Implementation Gate checklist:

1. **Assumption audit.**
   - Confirm `src/web/middleware.py` line numbers are still ~62–73 for the bypass (re-grep before editing — line numbers drift).
   - Confirm `_check_api_key` `before_request` registration sites — there might be more than one (per-blueprint or per-app).
   - Confirm the permission constants in `src/auth/permissions.py` match what you're using (`PROTECTED_READ`, `DECISION_WRITE`, etc.).
   - Confirm `g.user` is populated by `load_session_user` (registered in `create_app()` post-PR-#443).
2. **Scope check.** No spec/plan-doc edits beyond marking PR-C1 shipped. No backfill code (that's C2). No flag flip.
3. **Rules compliance.** Worktree, `/commit-proj`, conventional commit, no `--no-verify`.
4. **Risk assessment.**
   - **`auth_enforcement_enabled=false` invariant.** While the flag is off, behavior must be unchanged. The `require()` decorator from PR-A2 is documented as a no-op when the flag is off — verify this is still true. If it's not (i.e., decorators always enforce), you must either add a flag-aware shim or accept that merging C1 immediately changes behavior — do NOT do the latter without coordinating with the user.
   - **API-key removal blast radius.** Any external caller that relies on the same-origin bypass breaks. Audit `.claude/rules/web.md` and the codebase for callers that depend on it. Render's nightly cron jobs / external integrations may depend on the API key — those should keep working via the `Authorization: ApiKey` header, but verify.
   - **Test isolation.** The `require()` decorator reads `g.user`. Test fixtures must set `g.user` correctly; otherwise tests pass for the wrong reason (anonymous → fall-through, not enforcement).
5. **Minimal path.** Don't refactor unrelated code. The temptation will be high — resist.
6. **Worktree check.** Mandatory.

### Verification

- `pytest -x -q tests/unit/auth tests/integration/auth tests/integration/web` locally — must be green.
- Manual smoke (with `auth_enforcement_enabled=false` in the dev DB):
  - Existing API-key flow still works (`curl -H 'X-API-Key: ...' /v2/review/`).
  - Browser flow with valid session still works.
  - Browser flow without session (and without API key) — depends on PR-A2's flag-aware behavior; verify.
- Manual smoke (with `auth_enforcement_enabled=true` in the dev DB):
  - Reviewer can submit decisions.
  - Reviewer cannot undo another reviewer's decisions.
  - Admin can override.
  - Cross-origin POST is rejected by CSRF.

### Verification-checklist items satisfied

(per spec §Verification Checklist)
- "Role restrictions behave correctly for `admin`, `reviewer`, and `viewer`."
- "Reviewer own-decision undo rules work."
- "Admin any-decision override works."
- "Same-origin API-key bypass is gone from `/api/v2/*` after `auth_enforcement_enabled=true`."
- "Image-serving endpoints honor auth."
- "Stale-session-after-disable rejected" (handled by `lookup_session`'s existing disabled-user check).
- Negative-path: legacy session rejected after 4h post-flip.

### Out of scope for PR-C1

- **Backfill of legacy reviewer-id rows.** C2.
- **Flag flip.** Operator action via runbook from C2.
- **Admin UI for flag/user management.** Deferred per spec.
- **A8 follow-ups.** Separate `gh-N`.
- **Tidying anything else from prior waves.**

---

## PR-C2 brief — Legacy-alias backfill + Stage-C operator runbook

**Branch:** `claude/auth-pr-c2-backfill-and-runbook`.

### Scope

1. **Backfill script** (`scripts/backfill_legacy_reviewer_aliases.py`). Preview-then-apply per spec §Backfill Strategy. Sets `user_id` on existing rows in `v2_review_decisions`, `v2_image_metric_confirmations`, `v2_ingest_batches` based on the `reviewer_id` text + `auth_legacy_aliases` mapping + `auth_users.normalized_email`.
2. **Stage-C operator runbook** (`docs/operations/auth-stage-c-runbook.md`). Activation steps for the enforcement flip.

### Files (new)

- `scripts/backfill_legacy_reviewer_aliases.py` — argparse CLI (`--preview`, `--apply`). Both modes are read-only by default; `--apply` requires explicit `--confirm` to perform UPDATEs. Mirrors the seed-script CLI pattern (`scripts/seed_auth_users.py`).
- `tests/integration/auth/test_backfill.py` — runs preview against a fixture DB, asserts expected row counts; runs apply twice, asserts idempotency (second run is a no-op); confirms unmapped `reviewer_id` values are untouched.
- `docs/operations/auth-stage-c-runbook.md` — see structure below.

### Files (modified)

- `CLAUDE.md` — admin-operations section: list the backfill script alongside the readiness/seed scripts.
- `docs/architecture/auth-rollout-implementation-plan.md` — mark C1 and C2 as shipped under "Stage C — Staged Enforcement: PR catalog".

### Backfill SQL design

Three UPDATEs, one per target table. Run inside a transaction. Pattern:

```sql
UPDATE v2_review_decisions vd
SET user_id = au.id
FROM auth_legacy_aliases la
JOIN auth_users au ON au.normalized_email = la.target_email
WHERE vd.reviewer_id = la.legacy_reviewer_string
  AND la.active = TRUE
  AND vd.user_id IS NULL;       -- idempotent: skip already-backfilled rows
```

Same shape for `v2_image_metric_confirmations` and `v2_ingest_batches` (substitute table name).

**Preview mode** runs the same query as a SELECT (no UPDATE); reports per-table counts of rows that WOULD be updated.

**Idempotency:** the `vd.user_id IS NULL` clause makes re-runs a no-op for already-backfilled rows.

**Reversibility:** none. The implementer should call this out in the script docstring. To "undo" a backfill, the operator would have to NULL out the `user_id` columns based on which rows were backfilled — there's no audit trail of which rows the script touched. For Stage C this is acceptable because the backfill is data correction, not behavior change.

**Audit trail:** writes a single `admin_audit_log` row per script invocation with `action_type='auth.backfill_legacy_aliases'`, `before_state={preview_counts}`, `after_state={apply_counts}`. NOT per-row — that would be high-volume and unnecessary.

### Stage-C operator runbook structure

Mirror the Stage-B runbook (`docs/operations/auth-stage-b-runbook.md`):

1. **Status table** at top.
2. **Purpose** — Stage C is enforcement. Spell out what changes (routes gate on `require()`, same-origin bypass gone, 4h legacy-session bound).
3. **Prerequisites checklist:**
   - Stage B has soaked for at least 24 hours (operator judgement).
   - Every active reviewer has logged in at least once (verify via `auth_readiness_report.py` Section 2 — every row shows non-NULL `last_login_at`).
   - PR-C1 + PR-C2 are merged.
   - Backfill `--preview` has been run and inspected.
4. **Activation steps:**
   - Run `python3 scripts/backfill_legacy_reviewer_aliases.py --preview`. Inspect counts.
   - Run `python3 scripts/backfill_legacy_reviewer_aliases.py --apply --confirm`. Verify the audit row.
   - Run `python3 scripts/auth_readiness_report.py --check` (will need a Stage-C-aware extension or new flag — you decide).
   - INSERT/UPSERT `feature_flags(key='auth_enforcement_enabled', value='true')`.
   - Restart Render web service.
   - Smoke test: hit `/v2/review/` without a session cookie → expect 401/redirect. Hit with a valid session → expect 200.
5. **Verification (post-flip):**
   - Reviewer can do their normal workflow.
   - API-key-only callers still work via `Authorization: ApiKey` header.
   - Same-origin browser requests without session cookie are rejected.
   - Legacy sessions (created pre-flip) get rejected 4h after the flip; users see a re-login prompt.
6. **Rollback procedure:**
   - `UPDATE feature_flags SET value='false' WHERE key='auth_enforcement_enabled';`
   - Restart Render.
   - `require()` decorators become no-ops; same-origin bypass is GONE permanently from this PR's deletion (rollback does NOT restore it). Browser traffic falls back to API-key auth which the bypass used to fix — so without the bypass AND without enforcement, browser traffic that doesn't supply the API key gets 401. **This is a meaningful operational concern**: Stage C rollback is incomplete unless paired with restoring the bypass. The runbook should note this and recommend, if rollback is truly needed, reverting the relevant commit instead of just flipping the flag.
7. **Troubleshooting.**

### Pre-implementation gate

This PR touches 5 files (3 new + 2 modified). The gate fires. Run the full checklist with extra attention to:

- **Backfill correctness.** The SQL must NOT touch rows where `user_id IS NOT NULL` (those were set by post-Stage-B fresh writes). The `auth_legacy_aliases.active = TRUE` filter must hold.
- **Test fixture setup.** Tests need pre-existing rows in the three target tables with `reviewer_id='RGM'`/`'Mayu'` and `user_id IS NULL`. Insert directly in test setup; don't rely on the V2 pipeline to produce them.
- **Idempotency.** The test that runs apply twice is the canonical idempotency proof; make sure both runs assert the same final state.

### Out of scope for PR-C2

- **Doing the actual flag flip.** Operator runbook step.
- **Anything PR-C1 covered** (route migration, bypass removal, 4h bound).
- **Backfill of `disabled_at`, `display_name`, or any other non-`user_id` field.** Just the FK linkage.

---

## Out of scope for the entire Stage C cycle

- **Stage D work.** Standard legacy fallback retirement on May 10. Separate cycle.
- **Admin UI.** Deferred follow-on.
- **Force-logout-all on user disable.** Deferred per spec.
- **Tidying anything else from prior waves.** File `gh-N` for follow-ups.

## Reporting back

When both PR-C1 and PR-C2 are merged:
- PR numbers + commit SHAs.
- Confirm `pytest -x -q tests/unit/auth tests/integration/auth tests/integration/web` is green on `origin/main`.
- Surface any operator-facing gotchas discovered during implementation (especially around the rollback-without-bypass-restore concern in the runbook).
- Recommend the next move: **operator runs `docs/operations/auth-stage-c-runbook.md`** to perform the flip.

## Risks worth flagging at orchestration time

- **`require()` decorator behavior under `auth_enforcement_enabled=false`.** If the decorator does NOT no-op when the flag is off, merging PR-C1 immediately changes behavior. Verify A2's implementation. If it does enforce regardless of the flag, either add flag-awareness to the decorator (small change) or coordinate the merge with the flag flip.
- **Render env-group invisible to git audit** (per memory `project_render_env_invisible_to_git_audit.md`). Stage C doesn't add new env vars but does require the operator to flip a DB flag and restart — surface this clearly in the runbook.
- **Existing tests that lean on the same-origin bypass.** Some integration tests probably issue same-origin requests without a session/API key and expect success. Update them to either set a session via the dev-bypass fixture or supply the API key explicitly.
- **PR-C1 is large.** ~10 files, behavior-gated. If the implementer wants to split it (one PR per route module + a final structural PR for bypass removal + 4h bound), allow that — just hold the flag flip until ALL parts have merged.
- **Permission mapping decisions.** The brief above proposes a mapping per route module; the implementer should validate each against the spec's permission catalog and confirm with the orchestrator before applying. Ambiguous cases (e.g., should `viewer` see the `/ingest/` history page?) should be raised.

## What you (orchestrator) do NOT do

- Do not flip `auth_enforcement_enabled` in any environment.
- Do not run the backfill script against any environment from this PR — local DB only for testing.
- Do not modify the spec.
- Do not start Stage D work.

Good luck — and report back when both PRs are merged so the user can run the operator runbook.
