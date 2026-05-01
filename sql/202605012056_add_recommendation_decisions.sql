-- Migration 202605012056: add_recommendation_decisions
--
-- Adds text_pattern_recommendation_decisions to track admin actions on
-- the Suggested-actions surface in /v2/review/stats. Each row is one
-- (metric, rule, decision_key, reviewer) tuple, upserted whenever an
-- admin clicks Accept / Dismiss / Defer or undoes a prior decision.
--
-- decision_key is the stable identifier across analysis runs:
--   exclusion_pattern: the phrase (e.g. "accounts receivable")
--   keyword_overlap:   the target metric_id (e.g. "cm_active_customers_total")
--   fp_filter_gap:     literal "wrong_value"
--
-- pr_number / pr_url are populated only when an exclusion_pattern accept
-- triggers an auto-PR (Stage 2 / PR 2 of the rollout). They stay NULL
-- through PR 1 (bookkeeping-only).

BEGIN;

CREATE TABLE IF NOT EXISTS text_pattern_recommendation_decisions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_id     TEXT NOT NULL,
    rule          TEXT NOT NULL
        CHECK (rule IN ('exclusion_pattern', 'keyword_overlap', 'fp_filter_gap')),
    decision_key  TEXT NOT NULL,
    decision      TEXT NOT NULL
        CHECK (decision IN ('accepted', 'dismissed', 'deferred')),
    reviewer_id   TEXT NOT NULL,
    reviewer_note TEXT,
    pr_number     INTEGER,
    pr_url        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tprd_unique
    ON text_pattern_recommendation_decisions
    (metric_id, rule, decision_key, reviewer_id);

CREATE INDEX IF NOT EXISTS idx_tprd_reviewer
    ON text_pattern_recommendation_decisions (reviewer_id);

COMMIT;
