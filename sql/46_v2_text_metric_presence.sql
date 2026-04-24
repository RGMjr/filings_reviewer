-- ============================================================================
-- Migration 46: Create v2_text_metric_presence
-- Purpose: Per-(doc, metric) presence records emitted by MetricPresenceStage.
--
-- Part of the text-presence pivot — see docs/operations/text-pipeline-presence-pivot-plan.md.
-- Mirrors the chart-presence pivot (#147, sql/42) but on a dedicated table
-- rather than a JSONB column: text presence needs FK-reachable evidence
-- segment IDs + advisory fact back-refs + reviewer confirmation joins
-- (PR3 adds v2_text_presence_confirmations → presence_id).
--
-- Upsert keyed on (doc_id, canonical_metric_id); re-extraction overwrites
-- the row rather than appending history. No DELETE path; persistence uses
-- INSERT ... ON CONFLICT DO UPDATE and never touches v2_metric_facts, so
-- this table is safe to populate on reviewed filings (PR2 backfill runs
-- with presence_only=True, which short-circuits _persist_facts_in_tx).
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_text_metric_presence (
    presence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    doc_id BIGINT NOT NULL
        REFERENCES filings(filing_id) ON DELETE CASCADE,
    canonical_metric_id TEXT NOT NULL,

    score DOUBLE PRECISION NOT NULL,
    detected_at_stage TEXT NOT NULL,

    evidence_segment_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    advisory_value_count INTEGER NOT NULL DEFAULT 0,
    advisory_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,

    pipeline_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_v2_text_metric_presence_doc_metric
        UNIQUE (doc_id, canonical_metric_id),
    CONSTRAINT check_v2_text_metric_presence_score
        CHECK (score >= 0 AND score <= 1),
    CONSTRAINT check_v2_text_metric_presence_advisory_count
        CHECK (advisory_value_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_v2_text_metric_presence_doc
    ON v2_text_metric_presence(doc_id);

CREATE INDEX IF NOT EXISTS idx_v2_text_metric_presence_metric
    ON v2_text_metric_presence(canonical_metric_id);

COMMENT ON TABLE v2_text_metric_presence IS
    'Per-(doc, metric) presence records emitted by MetricPresenceStage. Primary scoring surface for Tier 1 regression gate under the presence-first pivot. See docs/operations/text-pipeline-presence-pivot-plan.md.';
