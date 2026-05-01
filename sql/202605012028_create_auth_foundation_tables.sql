-- Migration 202605012028: create_auth_foundation_tables
--
-- Stage A / PR-A1 of the review-UI authorization rollout. Creates the six
-- foundation tables and adds nullable user_id FK columns to three existing
-- review/ingest tables. Schema-only — no app code references these yet, so
-- this migration is a no-op for application behavior. Wave-2 PRs (A2 perms,
-- A3 sessions, A5 OAuth, A7 seed scripts, A8 readiness) build on top.
--
-- See: docs/architecture/auth-rollout-implementation-plan.md
--      docs/requirements/review-ui-authorization-spec.md (§Identity and Data Model)
--
-- Idempotency: every CREATE TABLE / CREATE INDEX uses IF NOT EXISTS; every
--              ALTER TABLE uses ADD COLUMN IF NOT EXISTS. Re-runs are no-ops.
-- Reversibility: not supported (project policy — see .claude/rules/sql.md).

BEGIN;

-- ==========================================================================
-- auth_users — canonical authenticated user identity
-- ==========================================================================
CREATE TABLE IF NOT EXISTS auth_users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sub          TEXT UNIQUE,                -- nullable: seeded users haven't logged in yet
    normalized_email    TEXT NOT NULL UNIQUE,
    display_name        TEXT,                       -- populated from Google profile on first login
    role                TEXT NOT NULL CHECK (role IN ('admin', 'reviewer', 'viewer')),
    account_status      TEXT NOT NULL DEFAULT 'active'
                        CHECK (account_status IN ('active', 'disabled')),
    first_login_at      TIMESTAMPTZ,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at         TIMESTAMPTZ,
    CONSTRAINT auth_users_disabled_at_consistency
        CHECK (
            (account_status = 'disabled' AND disabled_at IS NOT NULL)
            OR
            (account_status = 'active'   AND disabled_at IS NULL)
        )
);

-- ==========================================================================
-- auth_sessions — DB-backed session store; cookie holds opaque id only
-- ==========================================================================
CREATE TABLE IF NOT EXISTS auth_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ NOT NULL,
    user_agent          TEXT,
    ip_first_seen       INET
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_expires
    ON auth_sessions (user_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
    ON auth_sessions (expires_at);

-- ==========================================================================
-- auth_access_entries — allowlist (also future request-access surface)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS auth_access_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_email    TEXT NOT NULL UNIQUE,
    intended_role       TEXT NOT NULL CHECK (intended_role IN ('admin', 'reviewer', 'viewer')),
    status              TEXT NOT NULL DEFAULT 'approved'
                        CHECK (status IN ('approved', 'pending', 'revoked')),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==========================================================================
-- auth_legacy_aliases — RGM/Mayu → email mapping for backfill + own-undo
-- ==========================================================================
CREATE TABLE IF NOT EXISTS auth_legacy_aliases (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_reviewer_string   TEXT NOT NULL UNIQUE,
    target_email             TEXT NOT NULL,
    active                   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_auth_legacy_aliases_target_email
    ON auth_legacy_aliases (target_email);

-- ==========================================================================
-- feature_flags — DB-backed flags with optional TTL (for emergency overrides)
-- ==========================================================================
CREATE TABLE IF NOT EXISTS feature_flags (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    expires_at  TIMESTAMPTZ,                          -- nullable; required for emergency-override flags
    actor       UUID REFERENCES auth_users(id),       -- nullable for system/seed inserts
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==========================================================================
-- admin_audit_log — append-only audit trail for admin/auth events
-- ==========================================================================
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor_user_id   UUID REFERENCES auth_users(id),   -- nullable: system actions or pre-user events
    actor_email     TEXT,                             -- snapshot for reads after user changes
    action_type     TEXT NOT NULL,
    target_entity   TEXT,
    before_state    JSONB,
    after_state     JSONB,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created
    ON admin_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_actor_created
    ON admin_audit_log (actor_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action_created
    ON admin_audit_log (action_type, created_at DESC);

-- ==========================================================================
-- ALTER existing tables: add nullable user_id FK to auth_users
-- ==========================================================================
ALTER TABLE v2_review_decisions
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth_users(id);
CREATE INDEX IF NOT EXISTS idx_v2_review_decisions_user_id
    ON v2_review_decisions (user_id);

ALTER TABLE v2_image_metric_confirmations
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth_users(id);
CREATE INDEX IF NOT EXISTS idx_v2_image_metric_confirmations_user_id
    ON v2_image_metric_confirmations (user_id);

ALTER TABLE v2_ingest_batches
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth_users(id);
CREATE INDEX IF NOT EXISTS idx_v2_ingest_batches_user_id
    ON v2_ingest_batches (user_id);

COMMIT;
