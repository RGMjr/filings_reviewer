-- Migration 202605071643: add user_id to v2_audit_log and seed service-account sentinel
--
-- gh-520. Post gh-483, valid `Authorization: ApiKey` requests authenticate as
-- the synthetic admin service account (src/auth/service_account.py), but
-- v2_audit_log rows for those requests had session_id=NULL and no other
-- identifier — making `WHERE session_id IS NULL` the implicit filter for
-- API-key automation traffic. This migration adds the user_id column
-- (mirroring v2_review_decisions / v2_image_metric_confirmations /
-- v2_ingest_batches from sql/202605012028) and seeds the service-account
-- sentinel into auth_users so the FK is satisfied. The new canonical filter
-- for automation traffic is
-- `WHERE user_id = '00000000-0000-0000-0000-000000000000'`.
--
-- Idempotency: ON CONFLICT DO NOTHING on the seed; ADD COLUMN IF NOT EXISTS
-- on the column; CREATE INDEX IF NOT EXISTS on the partial index.

BEGIN;

-- Seed the service-account sentinel into auth_users so the FK on
-- v2_audit_log.user_id can hold the sentinel UUID. Mirrors the SessionUser
-- defined in src/auth/service_account.py (id, normalized_email,
-- display_name, role, account_status). google_sub stays NULL — the service
-- account never logs in via OAuth. created_at/updated_at default to NOW().
INSERT INTO auth_users (id, normalized_email, display_name, role, account_status)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'api-key@service.local',
    'API Key Service Account',
    'admin',
    'active'
)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE v2_audit_log
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth_users(id);

CREATE INDEX IF NOT EXISTS idx_v2_audit_log_user_id
    ON v2_audit_log (user_id) WHERE user_id IS NOT NULL;

COMMIT;
