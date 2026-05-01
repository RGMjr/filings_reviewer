# Review UI Authorization Design Spec

## Document Status

- Status: Draft for implementation
- Last updated: 2026-05-01
- Intended audience: application developers and operators
- Scope: human review UI authorization rollout for the Flask web app

## Summary

Introduce authenticated user access and role-based authorization for the review application using Google personal accounts, a manual allowlist, and app-managed roles. The rollout must be staged, backward-compatible, and designed to avoid interrupting current reviewer work. Legacy unauthenticated access must be fully retired by **May 10, 2026**, with only a separately logged break-glass override available after that date.

Phase 1 must deliver:

- Google sign-in for human users
- allowlist-based access control
- coarse app roles: `admin`, `reviewer`, `viewer`
- authenticated session enforcement across all human-facing and write-capable surfaces
- compatibility with legacy reviewer history and reviewer-facing workflows
- staged cutover with shadow mode and emergency fallback
- strong auditability for admin and override actions

## Goals

- Prevent unauthorized access to the human review UI
- Replace untrusted browser-supplied reviewer identity with trusted authenticated identity
- Support a low-disruption cutover for existing reviewers
- Preserve continuity for existing review history and reviewer workflows
- Enable future expansion to request-access and more granular analytics permissions

## Non-Goals

- Building local email/password authentication
- Shipping a self-service request-access workflow in phase 1
- Shipping a full admin UI in phase 1
- Redesigning analytics permissions in phase 1
- Rewriting all historical reviewer data into a perfect normalized user model

## Current State

The current app does not have trusted user identity:

- HTML review pages are public application routes
- API endpoints are guarded primarily by a shared API key model
- same-origin browser requests can reach decision APIs without manually supplying the API key
- reviewer identity is collected from browser `localStorage` and posted as free text
- decision and ingest records store `reviewer_id` as plain text
- audit logs track anonymous session and request context, not a trusted user record

This means the app can label actions with a reviewer string, but it cannot prove who performed them or enforce per-user permissions.

## Decisions

### Authentication Source

- Use Google sign-in with personal Google accounts
- Do not build local password auth

### Access Model

- Phase 1 uses a manual allowlist
- Future request-access must build on the same access-record model rather than replace it
- Allowlist matching must use exact email match after basic normalization only
- No Gmail-specific alias normalization in phase 1

### Canonical Identity

- Internal canonical identity: Google subject ID (`google_sub`)
- Admin-facing and allowlist identity: normalized email address
- UI-friendly identity: display name

### Roles

Phase 1 uses exactly one primary role per user:

- `admin`
- `reviewer`
- `viewer`

### Account Status

Users must also have explicit account status:

- `active`
- `disabled`

Access and active status must be checked on every request, not only at login.

### Reviewer Permissions

- `admin`
  - full override power across review decisions and related workflows
  - can change any decision
  - can undo any decision
  - can add missed metrics
  - can run ingest
  - can manage allowlist, users, roles, statuses, rollout flags, and break-glass overrides
- `reviewer`
  - can view protected review surfaces
  - can submit review decisions
  - can undo only their own decisions
  - cannot run ingest
  - cannot manage users, roles, or flags
  - manual add missed metric remains admin-only in phase 1
- `viewer`
  - full read-only access to review pages and stats
  - cannot write decisions
  - cannot access ingest or admin functions

### Viewer Future-Proofing

Phase 1 must keep authorization checks centralized so later analytics-oriented permissions can be added without redesigning identity fundamentals. The later desired direction is broader sample and metric-analysis viewing capability with narrower detailed-action controls.

### Session Behavior

- Production sessions use a 24-hour inactivity timeout
- Sessions renew while the user remains active
- Logout must be visible in the UI
- Session timeout must be configurable later without schema redesign

### Error Behavior

- Protected page request, unauthenticated: redirect to login
- Protected page request, authenticated but unauthorized: render access-denied page
- Protected API request, unauthenticated: return `401` JSON
- Protected API request, authenticated but unauthorized: return `403` JSON

### UI Identity

- Normal users see display name in the UI
- Email remains available for admin/reporting contexts
- UI must show who the user is logged in as, plus a logout control
- The app must preserve return-to-origin behavior after login for protected pages
- Redirect targets must be restricted to internal relative destinations only

## Protected Surface Scope

Phase 1 authorization must cover all human-facing and write-capable surfaces:

- `/v2/review/*`
- `/api/v2/*`
- `/ingest/*`
- `/api/ingest/*`
- `/review/pres-images/*`

Public/exception surfaces:

- `/health` remains public
- image cache/image serving endpoints may remain publicly retrievable if needed for authorized pages, but must be explicitly reviewed and documented as an exception

The presentation-image review area must use the same auth and role model in phase 1 even if its persistence remains file-based.

## Rollout Strategy

### Requirements

- rollout must be backward-compatible and near-zero-downtime
- schema changes must be additive first
- old and new app versions must be able to coexist during rollout
- destructive cleanup must be deferred until after stable cutover

### Phases

#### Phase 0: Foundation

- add user and auth-related schema
- add feature-flag storage and admin audit storage
- add Google auth integration behind flags
- add local dev/test auth stubs

#### Phase 1: Shadow Mode

- enable Google login in production
- do not require login yet
- allowlist and role model are active for signed-in users
- capture first-login and last-login tracking
- operators verify seeded users and initial mappings
- reviewers can continue current work without interruption

#### Phase 2: Staged Enforcement

- enable auth enforcement for protected surfaces
- keep emergency legacy fallback available behind a separate admin-controlled flag
- allow already-open legacy pages to continue until the next protected write or navigation boundary
- require authentication for all new entry into protected surfaces

#### Phase 3: Legacy Retirement

- normal legacy fallback expires on **May 10, 2026**
- after **May 10, 2026**, legacy access is unavailable unless a separately logged emergency override is activated
- post-deadline override must be temporary, explicit, and auditable

#### Phase 4: Post-Cutover Cleanup

- remove transitional compatibility logic only after cutover is stable
- optionally ship admin UI and request-access workflow
- optionally tighten permissions for analytics surfaces

## Cutover Rules

### Shadow Mode Requirement

Shadow mode is required before enforcement.

### Cutover Gate

Cutover uses a hybrid rule:

- target final legacy date: **May 10, 2026**
- enforcement should happen on or before that date only when readiness criteria are met, or an admin explicitly approves proceeding

Readiness criteria:

- all active reviewers are seeded or allowlisted with roles
- all active reviewers have successfully logged in at least once
- legacy alias mappings for `RGM` and `Mayu` are verified
- emergency fallback flag behavior has been tested by admins

### Existing Open Pages at Enforcement Time

Use graceful enforcement:

- already-open legacy pages may remain usable briefly
- the next meaningful protected transition forces authentication
- meaningful transitions include:
  - protected write action
  - protected navigation
  - protected page reload or fresh page entry

## Emergency Legacy Fallback

### General Rules

- fallback is controlled by a dedicated database-backed flag
- fallback is for continuity of core reviewer workflows only
- fallback must not reopen admin operations or ingest
- fallback usage must be auditable

### Scope

Emergency fallback may temporarily restore:

- core filing review access
- core review decision workflows needed to keep reviewers moving

Emergency fallback must not restore:

- allowlist management
- role/status changes
- rollout flag changes
- ingest administration
- break-glass override management itself

### Expiry

- standard legacy fallback expires on **May 10, 2026**
- after that date, only a separately logged emergency override can re-enable it

## Identity and Data Model

### New Core Tables

The exact table names may vary, but phase 1 must introduce equivalents for:

- `auth_users`
  - internal user id
  - `google_sub`
  - normalized email
  - display name
  - role
  - account status
  - `first_login_at`
  - `last_login_at`
  - `created_at`
  - `updated_at`
  - optional `disabled_at`
- `auth_access_entries` or equivalent allowlist/future-request table
  - normalized email
  - intended role
  - status
  - timestamps
  - optional notes/source metadata
- `auth_legacy_aliases`
  - legacy reviewer string
  - target user or target email
  - active flag
  - timestamps
- `feature_flags` or `app_settings`
  - key
  - value
  - timestamps
- `admin_audit_log` or equivalent
  - actor user id/email
  - action type
  - target entity
  - before/after snapshot where feasible
  - success/failure
  - timestamp

### Existing Tables

Existing reviewer text fields must remain supported during the transition.

Phase 1 must not destructively remove legacy reviewer text columns from:

- `v2_review_decisions`
- `v2_image_review_decisions`
- `v2_ingest_batches`
- any related reporting paths that depend on reviewer text

### New Identity Fields on Review and Audit Records

For new authenticated activity, store trusted user identity separately from display-oriented fields.

Required direction:

- decision records capture authenticated user identity in a stable linked form
- decision records continue to store a legacy-compatible reviewer display field during transition
- audit logs capture authenticated user identity as a first-class field

Suggested implementation:

- add nullable `user_id` foreign key fields where practical
- preserve legacy `reviewer_id` text for compatibility
- store display name snapshot and/or email snapshot if needed for human-readable history

## Provisioning Model

### Initial Provisioning

Phase 1 uses allowlist-first, auto-create-on-first-login:

- an approved access record exists before first login
- on first successful Google login with an allowlisted email, the app creates or activates the user record
- if the email is not allowlisted, access is denied

### Initial Seed Data

Initial users and alias mappings must be seeded by script or SQL before rollout:

- `rgmarkey@gmail.com` -> role `admin`
- `mayujoiner@gmail.com` -> role `reviewer`

Initial legacy alias mappings:

- `RGM` -> `rgmarkey@gmail.com`
- `Mayu` -> `mayujoiner@gmail.com`

### Allowlist Denial Behavior

If a user signs into Google with a non-approved account:

- deny access
- show a clear account-mismatch message naming the signed-in email
- provide a visible logout/switch-account path

## Legacy History and Backfill

### Historical Data Policy

Legacy history is not fully rewritten in phase 1. Mixed history is expected.

### Backfill Strategy

Use preview-then-apply backfill only.

Rules:

- no heuristic matching
- no fuzzy matching
- use the explicit alias mapping table only
- unmapped legacy values remain untouched

### Ownership Semantics

Mapped legacy decisions count as owned by the authenticated user for reviewer undo-permission purposes.

Examples:

- legacy decisions mapped from `Mayu` are treated as owned by `mayujoiner@gmail.com`
- legacy decisions mapped from `RGM` are treated as owned by `rgmarkey@gmail.com`

Admin override still applies globally:

- admins can change any decision
- admins can undo any decision

## Compatibility Requirements

During the transition, new authenticated writes must use dual-write compatibility behavior:

- write the new trusted user-linked identity
- continue populating the legacy-compatible reviewer text field

This is required so current UI paths, reporting, filtering, and operational habits do not break immediately.

Reads and reports must tolerate:

- legacy-only rows
- authenticated rows
- partially backfilled legacy rows

## API Key Handling

The existing API key should remain only for limited non-interactive or administrative use where still needed.

Rules:

- browser review traffic must authenticate through Google session auth
- API key must not remain a substitute for human reviewer login
- same-origin API-key bypass behavior must be revisited as part of the auth rollout
- any retained API-key use cases must be explicitly scoped and documented

## Feature Flags

Use database-backed flags that can be changed without redeploy.

Minimum required flags:

- `google_login_enabled`
- `auth_enforcement_enabled`
- `legacy_emergency_access_enabled`

Optional additional flags may be added if developers need isolated rollout by surface, but phase 1 should keep the flag set small.

## Administration Model

Phase 1 administration is script/database-driven, not UI-driven.

Required admin operations:

- seed initial users
- update allowlist/access records
- change roles
- change account status
- inspect and update rollout flags
- run backfill preview and apply steps
- generate readiness reports

An in-app admin UI is explicitly deferred to a later phase.

## Auditing Requirements

### Review and Decision Auditing

New authenticated review activity must capture:

- trusted user identity
- relevant display identity
- timestamp
- target record
- action taken

### Admin and Rollout Auditing

Phase 1 must explicitly audit:

- allowlist additions/removals
- role changes
- status changes
- rollout flag changes
- emergency legacy fallback activations
- post-**May 10, 2026** break-glass overrides
- legacy alias backfill executions

Audit entries should capture where practical:

- actor
- action
- target
- before state
- after state
- result
- timestamp

## Development and Test Environment Strategy

- production-like environments use real Google auth
- development and test environments use controlled local bypass/mock identities
- production must not allow dev/test bypass behavior
- tests must include role-aware fixtures for `admin`, `reviewer`, and `viewer`

## Implementation Guidance

### Auth Flow

Developers should implement:

- login entrypoint
- Google callback handling
- allowlist check
- auto-provision on first approved login
- user/session load on each request
- logout
- return-to-origin redirect handling

### Authorization Structure

Permission checks should be centralized rather than scattered in templates and route bodies. Phase 1 uses coarse roles, but the code structure must allow later expansion to analytics-specific permissions.

### UI Changes

Replace the current browser-only reviewer-name flow with:

- authenticated session identity
- server-derived reviewer identity for writes
- visible logged-in user display name
- logout control

The browser must never again be the trusted source of `reviewer_id` for decision writes.

## Readiness Reporting

Phase 1 must ship a script/report, not an admin UI page, for cutover readiness.

The report must show:

- allowlisted users and assigned roles
- whether each user has logged in successfully
- first login time
- last login time
- unresolved legacy alias mappings
- current rollout flag state

## Verification Checklist

Developers must provide and pass a formal pre-cutover verification checklist before enabling enforcement.

Minimum checklist items:

- Google login works in production
- seeded admin can log in successfully
- seeded reviewer can log in successfully
- non-allowlisted Google account is denied correctly
- account-mismatch message is clear
- role restrictions behave correctly for `admin`, `reviewer`, and `viewer`
- reviewer own-decision undo rules work
- admin any-decision override works
- presentation-image review surface honors auth
- ingest surface honors auth and role restrictions
- return-to-origin after login works
- readiness report works
- feature flags can be changed without redeploy
- emergency legacy fallback works as designed
- post-**May 10, 2026** override path is separately logged
- legacy backfill preview report is correct

## Acceptance Criteria by Phase

### Phase 0 Complete

- schema added with additive migrations only
- Google auth integration exists behind flags
- dev/test bypass exists and is isolated from production

### Phase 1 Complete

- users can sign in with Google in production
- allowlisted users are auto-provisioned on first login
- first and last login tracking works
- readiness report works
- no reviewer disruption from login availability alone

### Phase 2 Complete

- protected surfaces require authenticated access when enforcement flag is on
- roles are enforced correctly
- open legacy pages degrade gracefully at enforcement time
- emergency legacy fallback is narrow and controlled

### Phase 3 Complete

- standard legacy fallback is retired by **May 10, 2026**
- any post-deadline override is explicit, temporary, and audited

### Phase 4 Complete

- transitional compatibility logic is reviewed for safe removal
- follow-on work is planned for admin UI and request-access workflow

## Deferred Follow-On Work

- admin status/management UI
- request-access workflow
- finer-grained analytics permissions
- post-cutover simplification of legacy compatibility fields
- potential analytics-facing viewer role expansion

## Open Implementation Notes

- exact table and column names are left to developers, but the data responsibilities above are mandatory
- if developers retain any API-key-based operational access, it must be intentionally segregated from human browser auth
- if image-serving endpoints remain public, they must remain explicitly documented exceptions rather than accidental bypasses
