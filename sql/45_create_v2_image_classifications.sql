-- ============================================================================
-- Migration 45: Create v2_image_classifications
-- Purpose: Audit trail for Vision API metric-classify output per image.
--
-- Distinct from:
--   - v2_image_assets.detected_metrics (JSONB) — rule-based keyword match,
--     write-once at extraction (see sql/42, PR #147)
--   - v2_image_metric_confirmations — reviewer adjudication decisions
--     (accept/reject/correct/add) on the predictions shown to them
--     (see sql/43, PR #151)
--
-- This table captures the raw Vision API output: which metrics the model
-- predicted, its confidence, reasoning (for audit), and cost/latency/provider
-- metadata. Append-only — multiple rows per img_id are expected (reruns keep
-- history; "latest" via DISTINCT ON (img_id) ORDER BY created_at DESC).
--
-- Wired in by src/extraction_v2/stages/image_classify.py and persisted by
-- src/extraction_v2/persistence.py when ENABLE_METRIC_CLASSIFY=true.
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_image_classifications (
    classification_id BIGSERIAL PRIMARY KEY,

    img_id UUID NOT NULL
        REFERENCES v2_image_assets(img_id) ON DELETE CASCADE,

    predicted_metrics JSONB NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    rejection_reason TEXT,
    reasoning TEXT,

    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version SMALLINT NOT NULL DEFAULT 1,

    cost_usd NUMERIC(10, 6) NOT NULL,
    latency_ms INTEGER NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT check_v2_image_classifications_confidence
        CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT check_v2_image_classifications_rejection_reason CHECK (
        rejection_reason IS NULL OR
        rejection_reason IN (
            'decorative',
            'not_a_chart',
            'wrong_subject',
            'duplicate',
            'unreadable',
            'table_handled_elsewhere',
            'other'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_v2_image_classifications_img
    ON v2_image_classifications(img_id);

CREATE INDEX IF NOT EXISTS idx_v2_image_classifications_latest
    ON v2_image_classifications(img_id, created_at DESC);

COMMENT ON TABLE v2_image_classifications IS
    'Vision API metric-classify audit trail. Append-only; see also v2_image_assets.detected_metrics (rule-based) and v2_image_metric_confirmations (reviewer decisions).';
