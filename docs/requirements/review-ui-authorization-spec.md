# Review UI Authorization Design Spec

## Document Status

- Status: Draft for implementation
- Last updated: 2026-05-01
- Intended audience: application developers and operators
- Scope: human review UI authorization rollout for the Flask web app

## Summary

Introduce authenticated user access and role-based authorization for the review application using Google personal accounts, a manual allowlist, and app-managed roles. The rollout must be staged, backward-compatible, and designed to avoid interrupting current reviewer work. Legacy unauthenticated access must be fully retired by **May 10, 2026**, with only a separately logged break-glass override available after that date.

The spec is delivered in a single integrated cycle. Items the implementation must deliver:

- Google sign-in for human users
- Allowlist-based access control with explicit `email_verified` requirement
- Coarse app roles: `admin`, `reviewer`, `viewer`, mediated by a centralized permission catalog
- Authenticated session enforcement across all human-facing and write-capable surfaces
- CSRF protection on every state-changing endpoint
- Compatibility with legacy reviewer history and reviewer-facing workflows
- Staged cutover (Stage A → E below) with shadow mode and bounded emergency fallback
- Strong auditability for admin, override, and authentication events

The rollout is sequenced into stages **A (Foundation) → B (Shadow) → C (Enforcement) → D (Retirement) → E (Cleanup)**. The "Phase 1 / 2 / 3" numbering used in earlier drafts is replaced; rollout stages are letters, deliverable phases are not numbered.

## Goals

- Prevent unauthorized access to the human review UI
- Replace untrusted browser-supplied reviewer identity with trusted authenticated identity
- Support a low-disruption cutover for existing reviewers
- Preserve continuity for existing review history and reviewer workflows
- Enable future expansion to request-access and more granular analytics permissions

## Non-Goals

- Building local email/password authentication
- Shipping a self-service request-access workflow in this cycle
- Shipping a full admin UI in this cycle
- Redesigning analytics permissions in this cycle
- Rewriting all historical reviewer data into a perfect normalized user model

## Threat Model

**Actors in scope.** Unauthenticated external user reaching the public app surface; non-allowlisted Google user attempting to log in; allowlisted reviewer with a leaked or stolen session cookie; allowlisted user whose account has been disabled; a malicious or compromised browser tab on a reviewer's machine attempting CSRF; internal misconfiguration (e.g., dev bypass leaking into production, env-group drift between Render and code).

**Assets.** Filing content (some pre-IPO confidential, hosted in Cloudflare R2 and reachable via image-serving endpoints); reviewer decision history (`v2_review_decisions`, `v2_image_metric_confirmations`, `v2_image_review_decisions`); audit log integrity; admin-only operations including ingest, allowlist management, role/status/flag changes, and break-glass override management.

**Out of scope.** Compromise of Google itself; compromise of the production database host (Render-managed Postgres) at the OS or DBA layer; a malicious admin acting in bad faith with valid credentials. The spec defends against admin *misconfiguration* and *mistakes* via auditability, not against admin *malice*.

## Security Properties (MUST NOT)

These are the negative properties the system must enforce. Each maps to a verification-checklist item below.

- An unauthenticated user MUST NOT read any `/v2/review/*` page or hit any `/api/v2/*` non-public endpoint, including via the same-origin API-key bypass that exists today.
- A non-allowlisted authenticated user MUST NOT auto-provision, gain any data access, or learn anything from error messages beyond "this account is not authorized."
- A `viewer` MUST NOT write a decision, trigger ingest, or access any admin endpoint.
- A `reviewer` MUST NOT undo another reviewer's decisions (modulo legacy alias mappings, which scope ownership to a single human via the alias table), access admin endpoints, or bypass the `email_verified` check.
- A user with `account_status='disabled'` MUST NOT successfully complete any authenticated request after the next request boundary following the disable.
- A leaked session cookie MUST NOT be reusable after logout, after user disable, after the 24-hour inactivity timeout, after the 30-day absolute timeout, or in a different environment (prod cookies must not validate in staging and vice versa; separate cookie names and separate signing keys).
- A compromised browser tab MUST NOT successfully CSRF a write, nor complete a login redirect to an attacker-controlled URL.
- A non-browser caller MUST NOT exercise human-reviewer permissions via the API key. API-key callers receive scoped non-human attribution in the audit log.

## Current State

The current app does not have trusted user identity:

- HTML review pages are public application routes
- API endpoints are guarded primarily by a shared API key model
- Same-origin browser requests can reach decision APIs without manually supplying the API key (`src/web/middleware.py`)
- Reviewer identity is collected from browser `localStorage` and posted as free text
- Decision and ingest records store `reviewer_id` as plain text
- Audit logs track anonymous session and request context, not a trusted user record

This means the app can label actions with a reviewer string, but it cannot prove who performed them or enforce per-user permissions.

## Decisions

### Authentication Source

- Use Google sign-in with personal Google accounts.
- Do not build local password auth.

#### OAuth/OIDC Implementation Requirements

- **Flow:** server-side **Authorization Code with PKCE**. No Implicit flow, no token-from-fragment.
- **ID-token validation:** verify signature against Google's JWKS, `iss` is `https://accounts.google.com` or `accounts.google.com`, `aud == client_id`, `exp` is in the future, `nonce` matches the value the app generated for this login attempt. Use a maintained library (e.g. `google-auth` or `Authlib`); do not roll JWT validation by hand.
- **State:** `state` parameter required and validated on callback; mismatched or missing `state` rejects the login.
- **Email verification:** the `email_verified` claim must be `true`; otherwise deny with the same UX as a non-allowlisted account.
- **Scopes:** request only `openid email profile`.
- **Trust model:** trust the validated ID-token claims; do not refetch from the `userinfo` endpoint on each login.

### Access Model

- This cycle uses a manual allowlist.
- Future request-access must build on the same access-record model rather than replace it.
- Allowlist matching uses **exact** email match after normalization.
- Email normalization: lowercase plus Unicode NFC. **No** Gmail dot-or-plus alias normalization.
- Allowlist match additionally requires `email_verified == true` from the validated Google ID token.

### Canonical Identity

- Internal canonical identity: Google subject ID (`google_sub`).
- Admin-facing and allowlist identity: normalized email address.
- UI-friendly identity: display name.

### Roles

Each user has exactly one role:

- `admin`
- `reviewer`
- `viewer`

### Account Status

Users must also have explicit account status:

- `active`
- `disabled`

Access and active status must be checked on every request, not only at login.

**Disabled-user behavior.** Disabling a user causes all subsequent requests authenticated as that user to receive 401 / redirect to login. Active in-flight requests complete normally; the session-lookup-per-request pattern enforces the disable on the next request boundary. This cycle does **not** implement proactive force-logout-all; the inactivity and absolute-lifetime timeouts (see Session Behavior) bound worst-case dwell time of a leaked-cookie session belonging to a since-disabled user.

### Permission Catalog

Authorization is mediated by a small, centralized permission catalog. Routes call `require(<permission>)`; routes do **not** call `require_role(<role>)` directly. This is the structural change that lets viewer expansion (analytics-oriented permissions) happen later without refactoring every route.

Permission names:

- `decision.write` — submit text or image review decisions
- `decision.undo.own` — undo decisions whose `user_id` resolves to the current user, including via legacy alias mapping
- `decision.undo.any` — undo any decision regardless of authorship
- `metric.add_missed` — manually add a missed metric (`POST /api/v2/missed-metric`)
- `ingest.run` — start, resume, or reextract ingest batches
- `users.manage` — modify allowlist, roles, account status
- `flags.manage` — modify rollout and emergency flags
- `audit.read` — read audit-log surfaces
- `readiness.read` — read readiness and stats surfaces
- `protected.read` — read protected pages (review UI, stats UI, ingest history UI)

Role-to-permission map:

| Permission | `admin` | `reviewer` | `viewer` |
|---|---|---|---|
| `protected.read` | yes | yes | yes |
| `readiness.read` | yes | yes | yes |
| `decision.write` | yes | yes | no |
| `decision.undo.own` | yes (subsumed by `undo.any`) | yes | no |
| `decision.undo.any` | yes | no | no |
| `metric.add_missed` | yes | no | no |
| `ingest.run` | yes | no | no |
| `users.manage` | yes | no | no |
| `flags.manage` | yes | no | no |
| `audit.read` | yes | no | no |

### Viewer Future-Proofing

Authorization checks must be centralized so later analytics-oriented permissions can be added without redesigning identity fundamentals. The later desired direction is broader sample and metric-analysis viewing capability with narrower detailed-action controls. The permission-catalog structure above is the enabling primitive for that expansion.

### Session Behavior

- **Storage:** **DB-backed** session store. The signed cookie holds only a session id; user identity, role, and disabled-status are looked up server-side per request. This survives deploys, supports admin-disable invalidation, and supports logout-revokes-everywhere.
- **Cookie attributes:** `Secure`, `HttpOnly`, `SameSite=Lax` on the main session cookie. If the OAuth callback uses a separate cookie, that cookie is `SameSite=Strict`.
- **Sliding inactivity timeout:** 24 hours. Sessions renew on activity within this window.
- **Absolute lifetime:** 30 days. After 30 days the user must re-authenticate even if continuously active.
- **Logout:** invalidates the server-side session row and clears the cookie. A request bearing a cookie whose session id is not found in the store returns 401 (HTML) or 401 JSON (API).
- **Environment isolation:** prod, staging, and dev use distinct cookie names and distinct signing keys so a cookie issued in one environment cannot validate in another.
- Session timeout values must be configurable later without schema redesign.
- Logout must be visible in the UI.

### Error Behavior

- Protected page request, unauthenticated: redirect to login.
- Protected page request, authenticated but unauthorized: render access-denied page.
- Protected API request, unauthenticated: return `401` JSON.
- Protected API request, authenticated but unauthorized: return `403` JSON.
- Session cookie present but session id not found: treated as unauthenticated.
- Session cookie present but `account_status='disabled'`: treated as unauthorized; render access-denied with the same wording as the not-allowlisted case to avoid leaking account state.

### CSRF Protection

All state-changing endpoints (POST / PUT / PATCH / DELETE) on protected surfaces require CSRF protection. Acceptable mechanisms (implementer's choice, but pick exactly one and document it):

- Per-session CSRF token issued at login, validated on every state-changing request via signed header (e.g. `X-CSRF-Token`) with double-submit cookie; or
- Framework-level verification of `Sec-Fetch-Site: same-origin` plus `Origin` header presence and match.

Cross-site requests are rejected before authorization checks run. The OAuth callback is exempt from this check (it relies on the `state` parameter for CSRF protection of its own flow).

### UI Identity

- Normal users see display name in the UI.
- Email remains available for admin/reporting contexts.
- UI must show who the user is logged in as, plus a logout control.
- The app must preserve return-to-origin behavior after login for protected pages.

**Redirect target validation.** Return-to-origin redirect targets must:

1. Start with a single `/`.
2. Not start with `//` (protocol-relative URL).
3. Not contain `\` (backslash variants used to bypass naive validators).
4. Not contain a colon before the first `/`.
5. After URL-decoding, resolve to a path within the app's known route prefixes.

If validation fails, redirect to the safe default `/v2/review/`. Validation runs on the decoded value, not the raw value, to avoid encoded-bypass attacks (e.g. `%2F%2Fevil.com`).

## Protected Surface Scope

Authorization must cover all human-facing and write-capable surfaces:

- `/v2/review/*`
- `/api/v2/*`
- `/ingest/*`
- `/api/ingest/*`
- `/review/pres-images/*`
- Image-serving and image-cache endpoints (see decision below).

Public/exception surfaces:

- `/health` remains public.

**Image endpoints decision.** Image cache and image-serving endpoints **require session authentication**. They serve filing-derived content (some pre-IPO confidential) and have no operational reason to be public. If a future workflow needs a public-link share (e.g. emailing a chart to legal), introduce signed time-bound URLs at that point, not as a phase-1 carve-out. Authentication on these endpoints uses the same session-cookie path as the rest of the protected surface.

The presentation-image review area must use the same auth and role model in this cycle even if its persistence remains file-based.

## Rollout Strategy

### Requirements

- Rollout must be backward-compatible and near-zero-downtime.
- Schema changes must be additive first.
- Old and new app versions must be able to coexist during rollout.
- Destructive cleanup must be deferred until after stable cutover.
- **Migration deploy ordering.** Code that reads or writes a column deploys **after** the migration that adds it. A migration that drops a column deploys **after** the code that stops reading and writing it. Use timestamp-named migrations from `scripts/new_migration.py` per `.claude/rules/sql.md`.

### Stages

#### Stage A — Foundation

- Add user and auth-related schema (auth_users, auth_access_entries, auth_legacy_aliases, feature_flags, admin_audit_log).
- Add Google OAuth integration code, gated by `google_login_enabled=false` initially.
- Add local dev/test auth stubs (gated by `AUTH_DEV_BYPASS=1`; never present in production).
- Implement permission catalog and centralized authorization middleware (off path until enforcement).
- Implement DB-backed session store, cookie attributes, CSRF middleware (latent until login enabled).
- Implement readiness-report script.
- Seed initial users and alias mappings.

#### Stage B — Shadow Mode

- Enable Google login in production (`google_login_enabled=true`).
- Do **not** require login yet (`auth_enforcement_enabled=false`).
- Allowlist and role model are active for signed-in users; non-allowlisted Google logins are denied at the callback.
- Capture first-login and last-login tracking on `auth_users`.
- Operators verify seeded users and initial mappings via the readiness report.
- Reviewers can continue current work without interruption.

#### Stage C — Staged Enforcement

- Enable auth enforcement for protected surfaces (`auth_enforcement_enabled=true`).
- Same-origin API-key bypass is removed at this point (see API Key Handling).
- Keep emergency legacy fallback available behind a separate admin-controlled flag with bounded scope.
- Already-open legacy pages are subject to graceful enforcement (see Cutover Rules); legacy sessions are forcibly invalidated at most 4 hours after the enforcement flag flips.
- Require authentication for all new entry into protected surfaces.

#### Stage D — Legacy Retirement

- Standard legacy fallback expires on **May 10, 2026**.
- After **May 10, 2026**, legacy access is unavailable unless a separately logged emergency override is activated.
- Post-deadline override must be temporary, explicit, time-bounded, and auditable.

#### Stage E — Post-Cutover Cleanup

- Remove transitional compatibility logic only after cutover is stable.
- Optionally ship admin UI and request-access workflow.
- Optionally tighten permissions for analytics surfaces.

## Cutover Rules

### Shadow Mode Requirement

Stage B (shadow mode) is required before Stage C (enforcement).

### Cutover Gate

Cutover uses a hybrid rule:

- Target final legacy date: **May 10, 2026**.
- Enforcement should happen on or before that date only when readiness criteria are met, or an admin explicitly approves proceeding (admin approval is recorded in `admin_audit_log`).

Readiness criteria:

- All active reviewers are seeded or allowlisted with roles.
- All active reviewers have successfully logged in at least once.
- Legacy alias mappings for `RGM` and `Mayu` are verified **and the apply step has been run** so historical decisions carry `user_id` before reviewers depend on `decision.undo.own` permission.
- Emergency fallback flag behavior has been tested by admins.
- Production dev-bypass startup guard has been verified to refuse boot with `FLASK_ENV=production` and `AUTH_DEV_BYPASS=1`.

### Existing Open Pages at Enforcement Time

Use graceful enforcement:

- Already-open legacy pages may remain usable briefly.
- The next meaningful protected transition forces authentication.
- Meaningful transitions include:
  - protected write action
  - protected navigation
  - protected page reload or fresh page entry
- **Hard upper bound.** Legacy sessions are forcibly invalidated at most **4 hours** after `auth_enforcement_enabled` flips to `true`, regardless of activity. Implementation: each request compares the session's `created_at` against `auth_enforcement_enabled_at`; sessions predating the enforcement flip are rejected once the 4-hour grace expires.

## Emergency Legacy Fallback

### General Rules

- Fallback is controlled by a dedicated database-backed flag.
- Fallback flag schema includes `expires_at` (NULLable for the standard pre-May-10 fallback; **NOT NULL** for any post-May-10 break-glass override).
- The flag-read path treats `expires_at < NOW()` as off.
- Fallback is for continuity of core reviewer workflows only.
- Fallback must not reopen admin operations or ingest.
- Fallback usage must be auditable (every flip writes to `admin_audit_log` with actor, before, after, timestamp).
- Renewal of an expired override requires a new audit-logged flag-set action.

### Scope

Emergency fallback may temporarily restore:

- Core filing review access.
- Core review decision workflows needed to keep reviewers moving.

Emergency fallback must not restore:

- Allowlist management.
- Role/status changes.
- Rollout flag changes.
- Ingest administration.
- Break-glass override management itself.

### Expiry

- Standard legacy fallback expires on **May 10, 2026**.
- After that date, only a separately logged emergency override can re-enable it.
- Post-May-10 override **must** be set with a TTL ≤ **4 hours**. Renewal is explicit and audited; there is no auto-renewal.

## Identity and Data Model

### New Core Tables

The exact table names may vary, but this cycle must introduce equivalents for:

- `auth_users`
  - internal user id
  - `google_sub`
  - normalized email
  - display name
  - role (one of `admin`, `reviewer`, `viewer`)
  - `account_status` (one of `active`, `disabled`)
  - `first_login_at`
  - `last_login_at`
  - `created_at`
  - `updated_at`
  - `disabled_at` — **NOT NULL** when `account_status='disabled'`, NULL when `active`. Enforced by CHECK constraint.
- `auth_sessions`
  - session id (opaque random; the value placed in the cookie)
  - foreign key to `auth_users`
  - `created_at`
  - `last_seen_at`
  - `expires_at`
  - optional `user_agent`, `ip_first_seen`
- `auth_access_entries` (allowlist; future-request-friendly)
  - normalized email
  - intended role
  - status
  - timestamps
  - optional notes/source metadata
- `auth_legacy_aliases`
  - legacy reviewer string (e.g. `RGM`, `Mayu`)
  - **`target_email`** (text, normalized). Resolved to `auth_users.id` lazily at backfill time and at runtime own-undo permission checks. Email-only avoids requiring a user row to exist before the alias is seeded.
  - active flag
  - timestamps
- `feature_flags` (or `app_settings`)
  - key
  - value
  - `expires_at` (nullable; required for emergency-override flags)
  - actor (FK to `auth_users` — who set the flag)
  - `created_at`
  - `updated_at`
- `admin_audit_log`
  - actor user id and email
  - action type
  - target entity
  - before state
  - after state
  - success/failure
  - timestamp
  - Append-only by convention; no UPDATE or DELETE in normal app code paths.

### Existing Tables

Existing reviewer text fields must remain supported during the transition.

This cycle must not destructively remove legacy reviewer text columns from:

- `v2_review_decisions`
- `v2_image_review_decisions`
- `v2_ingest_batches`
- Any related reporting paths that depend on reviewer text.

### New Identity Fields on Review and Audit Records

For new authenticated activity, store trusted user identity separately from display-oriented fields.

Required direction:

- Decision records capture authenticated user identity in a stable linked form.
- Decision records continue to store a legacy-compatible reviewer display field during transition (see Compatibility Requirements below for the exact value to write).
- Audit logs capture authenticated user identity as a first-class field.

Suggested implementation:

- Add nullable `user_id` foreign key fields where practical.
- Preserve legacy `reviewer_id` text for compatibility.
- Store display name snapshot and/or email snapshot if needed for human-readable history.

## Provisioning Model

### Initial Provisioning

Allowlist-first, auto-create-on-first-login:

- An approved access record exists before first login.
- On first successful Google login with an allowlisted email, the app creates or activates the user record.
- If the email is not allowlisted, access is denied.

### Initial Seed Data

Initial users and alias mappings must be seeded by script or SQL before rollout:

- `rgmarkey@gmail.com` → role `admin`
- `mayujoiner@gmail.com` → role `reviewer`
- **`[DECISION]` second admin** — TBD second admin email, role `admin`. Required so the system has a break-glass path if `rgmarkey@gmail.com` is unavailable on cutover day. User must fill in before Stage A applies.

Initial legacy alias mappings:

- `RGM` → `rgmarkey@gmail.com`
- `Mayu` → `mayujoiner@gmail.com`

### Allowlist Denial Behavior

If a user signs into Google with a non-approved account:

- Deny access.
- Show a clear account-mismatch message naming the signed-in email.
- Provide a visible logout/switch-account path.

The same denial UX is used for `email_verified == false` accounts; the message says the account is not authorized rather than that the email is unverified, to avoid leaking which accounts are allowlisted.

## Legacy History and Backfill

### Historical Data Policy

Legacy history is not fully rewritten in this cycle. Mixed history is expected.

### Backfill Strategy

Use preview-then-apply backfill only.

Rules:

- No heuristic matching.
- No fuzzy matching.
- Use the explicit alias mapping table only.
- Unmapped legacy values remain untouched.
- Apply step is idempotent — running it twice is a no-op for already-mapped rows.

### Ownership Semantics

Mapped legacy decisions count as owned by the authenticated user for `decision.undo.own` permission purposes.

Examples:

- Legacy decisions mapped from `Mayu` are treated as owned by `mayujoiner@gmail.com`.
- Legacy decisions mapped from `RGM` are treated as owned by `rgmarkey@gmail.com`.

Admin override (`decision.undo.any`) still applies globally:

- Admins can change any decision.
- Admins can undo any decision.

## Compatibility Requirements

During the transition, new authenticated writes must use dual-write compatibility behavior:

- Write the new trusted user-linked identity (`user_id` foreign key).
- Continue populating the legacy-compatible reviewer text field.

**Legacy reviewer text field value.** For new authenticated writes, populate the legacy reviewer text field with the user's email (e.g. `mayujoiner@gmail.com`). Email is stable across display-name changes and satisfies the `_require_reviewer_id` blocklist documented in `.claude/rules/web.md`. The 2026-04-23 historical rewrite to `RGM`/`Mayu` is preserved; new authenticated rows are not retroactively re-aliased to those legacy strings.

Reads and reports must tolerate:

- Legacy-only rows.
- Authenticated rows.
- Partially backfilled legacy rows.

## API Key Handling

The existing API key remains only for limited non-interactive or administrative use where still needed.

Rules:

- Browser review traffic must authenticate through Google session auth.
- API key must not remain a substitute for human reviewer login.
- **When `auth_enforcement_enabled=true`, the same-origin API-key bypass is removed.** Browser traffic authenticates by session cookie only. The same-origin path no longer bypasses authentication.
- The API key continues to authenticate non-browser clients via explicit `Authorization: ApiKey …` header. Audit-log entries from API-key calls are attributed as `api_key:<scope>` rather than to a human reviewer, so per-human accountability is preserved.
- API-key callers cannot exercise `decision.write` against the human review APIs; the `_require_reviewer_id` gate still applies, and a future scope-narrowing pass should restrict API-key calls to the surfaces that genuinely need them.
- Any retained API-key use cases must be explicitly scoped and documented.

## Feature Flags

Use database-backed flags that can be changed without redeploy.

Minimum required flags:

- `google_login_enabled`
- `auth_enforcement_enabled`
- `legacy_emergency_access_enabled`

Optional additional flags may be added if developers need isolated rollout by surface, but the flag set should stay small.

Flag rows include `expires_at`, actor, and timestamps as specified in the data model. The flag-read path treats `expires_at < NOW()` as off.

## Administration Model

This cycle's administration is script/database-driven, not UI-driven.

Required admin operations:

- Seed initial users.
- Update allowlist/access records.
- Change roles.
- Change account status.
- Inspect and update rollout flags.
- Run backfill preview and apply steps.
- Generate readiness reports.

Admin scripts are checked into the repo, validate input, and write to `admin_audit_log` on every state-changing action. They share code paths with what a future admin UI will call so audit attribution is uniform.

An in-app admin UI is explicitly deferred to a later phase.

## Auditing Requirements

### Review and Decision Auditing

New authenticated review activity must capture:

- Trusted user identity.
- Relevant display identity.
- Timestamp.
- Target record.
- Action taken.

Where practical, before/after state for decision changes is captured.

### Authentication Event Auditing

The following events must be audited:

- Successful login.
- Logout (including session expiry treated as logout).
- Denied login, with one of the reasons: `not_allowlisted`, `email_unverified`, `account_disabled`, `oauth_state_mismatch`, `oauth_callback_error`, `oauth_id_token_invalid`.

These are the highest-signal events for spotting attacks and misconfiguration; they are required, not best-effort.

### Admin and Rollout Auditing

The following must be audited (actor, action, target, before state, after state, result, timestamp — all required, not "where practical"):

- Allowlist additions/removals.
- Role changes.
- Status changes.
- Rollout flag changes.
- Emergency legacy fallback activations.
- Post-**May 10, 2026** break-glass override activations.
- Legacy alias backfill executions.

## Privacy and Retention

- Google profile data (`google_sub`, normalized email, display name) is retained for the lifetime of the account.
- On disable, the user row is soft-deleted (status flip, `disabled_at` set); no row removal.
- `auth_sessions` rows for a disabled user are deleted at disable time.
- Audit-log entries are preserved indefinitely; they reference users by id and email snapshot so deletion of a user row would not break historical audit reads (deletion is not part of this cycle).
- Application logs must redact `google_sub` and full email beyond first character + domain when logging at debug level.

## Development and Test Environment Strategy

- Production-like environments use real Google auth.
- Development and test environments use controlled local bypass / mock identities.
- **Production must not allow dev/test bypass behavior.** Specific guard:
  - Bypass is gated by environment variable `AUTH_DEV_BYPASS=1`.
  - The application **asserts at startup** that not (`FLASK_ENV == 'production'` AND `AUTH_DEV_BYPASS == '1'`); refuses to boot otherwise with a fatal error to stderr.
  - Render env groups must not define `AUTH_DEV_BYPASS`.
  - A unit test loads the production config and verifies the boot-time guard rejects the unsafe combination.
- Tests must include role-aware fixtures for `admin`, `reviewer`, and `viewer`.
- **Staging environment.** `[DECISION]` — confirm whether a staging environment exists separate from production. If yes, each stage flip (B → C, C → D) must validate in staging before prod. If no, this is documented as accepted risk in the cutover gate.

## Implementation Guidance

### Auth Flow

Developers should implement:

- Login entrypoint.
- Google callback handling (with `state` and ID-token validation per OAuth Implementation Requirements).
- Allowlist check and `email_verified` gate.
- Auto-provision on first approved login.
- Session creation in `auth_sessions`; cookie issuance with the documented attributes.
- User/session load on each request (lookup by session id; reject if missing, expired, or owned by a disabled user).
- Logout (delete `auth_sessions` row, clear cookie, log audit event).
- Return-to-origin redirect handling (with the validation rules in UI Identity).

### Authorization Structure

Permission checks live in middleware and are addressed by permission name (`require('decision.write')`), not by role name. The `role → permissions` resolution happens once at session-load time; routes do not interrogate role.

### CSRF Implementation

Pick exactly one of the two mechanisms in the CSRF Protection section. Document the choice in the implementation. Tests must include a positive case (legitimate request succeeds) and a negative case (cross-site attempt fails).

### UI Changes

Replace the current browser-only reviewer-name flow with:

- Authenticated session identity.
- Server-derived reviewer identity for writes (the legacy `reviewer_id` text field is now populated server-side from the session, never from the browser).
- Visible logged-in user display name.
- Logout control.

The browser must never again be the trusted source of `reviewer_id` for decision writes.

## Readiness Reporting

This cycle must ship a script/report, not an admin UI page, for cutover readiness.

The report must show:

- Allowlisted users and assigned roles.
- Whether each user has logged in successfully.
- First login time.
- Last login time.
- Unresolved legacy alias mappings.
- Current rollout flag state, including any flag with a non-NULL `expires_at`.
- Production dev-bypass guard verification result.

## Verification Checklist

Developers must provide and pass a formal pre-cutover verification checklist before enabling enforcement.

Functional items:

- Google login works in production.
- Seeded admin can log in successfully.
- Seeded second admin can log in successfully.
- Seeded reviewer can log in successfully.
- Non-allowlisted Google account is denied correctly.
- `email_verified=false` Google account is denied correctly.
- Account-mismatch and unverified-email messages are clear and do not leak which accounts are allowlisted.
- Role restrictions behave correctly for `admin`, `reviewer`, and `viewer` (drive from the permission catalog).
- Reviewer own-decision undo rules work, including for legacy alias-mapped decisions.
- Admin any-decision override works.
- Presentation-image review surface honors auth.
- Image-serving endpoints honor auth.
- Ingest surface honors auth and role restrictions.
- Return-to-origin after login works.
- Readiness report works.
- Feature flags can be changed without redeploy.
- Emergency legacy fallback works as designed.
- Post-**May 10, 2026** override path is separately logged and TTL-bounded.
- Legacy backfill preview report is correct.
- Legacy backfill apply step is idempotent.

Negative-path items (these prove the MUST NOTs):

- URL-redirect bypass attempts rejected (`//evil.com`, `\\evil.com`, `%2F%2Fevil.com`, mixed-case scheme prefixes).
- Role-escalation attempt rejected (`viewer` POST to a `decision.write` endpoint returns 403).
- Stale-session-after-disable rejected (active session, admin disables user, next request returns 401).
- CSRF attempt from cross-origin page rejected (negative test for the chosen CSRF mechanism).
- Production dev-bypass startup guard refuses to boot when both `FLASK_ENV=production` and `AUTH_DEV_BYPASS=1`.
- Cookie issued in staging fails to validate against production session store and vice versa.
- Same-origin API-key bypass is gone from `/api/v2/*` after `auth_enforcement_enabled=true`.
- Logged-out session id cannot be re-used after a subsequent fresh login (session ids are not reused).

## Acceptance Criteria by Stage

Each outcome ties to a verification-checklist item.

### Stage A Complete

- Schema added with additive migrations only. → verified by: migration files reviewed, additive only.
- Google auth integration exists behind flags (`google_login_enabled=false`). → verified by: integration tests with flag off.
- Dev/test bypass exists and is isolated from production. → verified by: Production dev-bypass startup guard refuses to boot when both `FLASK_ENV=production` and `AUTH_DEV_BYPASS=1`.
- Permission catalog and centralized authorization middleware are in place. → verified by: unit tests on the catalog and middleware.
- DB-backed session store, cookie attributes, CSRF middleware are in place. → verified by: cookie attribute test; CSRF negative test.

### Stage B Complete

- Users can sign in with Google in production. → verified by: Google login works in production.
- Allowlisted users are auto-provisioned on first login. → verified by: Seeded admin / second admin / reviewer can log in successfully.
- First and last login tracking works. → verified by: readiness report shows first/last login.
- Readiness report works. → verified by: Readiness report works.
- No reviewer disruption from login availability alone. → verified by: shadow-mode soak with no reviewer-reported regression.

### Stage C Complete

- Protected surfaces require authenticated access when enforcement flag is on. → verified by: Role restrictions behave correctly; same-origin API-key bypass is gone.
- Roles are enforced correctly. → verified by: Role-escalation attempt rejected.
- Open legacy pages degrade gracefully at enforcement time. → verified by: 4-hour hard upper bound on legacy session validity.
- Emergency legacy fallback is narrow and controlled. → verified by: Emergency legacy fallback works as designed.

### Stage D Complete

- Standard legacy fallback is retired by **May 10, 2026**. → verified by: `legacy_emergency_access_enabled=false` post-deadline; flag has audit trail.
- Any post-deadline override is explicit, temporary, and audited. → verified by: Post-May 10, 2026 override path is separately logged and TTL-bounded.

### Stage E Complete

- Transitional compatibility logic is reviewed for safe removal. → verified by: code search for legacy reviewer-text writes; coverage report on removed paths.
- Follow-on work is planned for admin UI and request-access workflow.

## Deferred Follow-On Work

- Admin status/management UI.
- Request-access workflow.
- Finer-grained analytics permissions.
- Post-cutover simplification of legacy compatibility fields.
- Potential analytics-facing viewer role expansion.
- Proactive force-logout-all on user disable (currently relies on next-request boundary plus inactivity timeout).

## Open Implementation Notes

- Exact table and column names are left to developers, but the data responsibilities above are mandatory.
- If developers retain any API-key-based operational access, it must be intentionally segregated from human browser auth.
- Image-serving endpoints are no longer a public exception; if any operational need surfaces, address it via signed time-bound URLs rather than a public carve-out.
- `[DECISION]` markers (second admin email, staging-environment policy) must be resolved before Stage A applies.
