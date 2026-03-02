-- Migration 11: V2 Metric Definitions table
-- Stores extracted definition/methodology text per metric per document

CREATE TABLE IF NOT EXISTS v2_metric_definitions (
    definition_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id INTEGER NOT NULL REFERENCES v2_documents(filing_id) ON DELETE CASCADE,
    canonical_metric_id TEXT NOT NULL,
    definition_text TEXT,
    definition_text_normalized TEXT,
    methodology_text TEXT,
    methodology_text_normalized TEXT,
    definition_segment_id UUID REFERENCES v2_segments(segment_id) ON DELETE SET NULL,
    methodology_segment_id UUID REFERENCES v2_segments(segment_id) ON DELETE SET NULL,
    alignment_flag TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(doc_id, canonical_metric_id)
);

CREATE INDEX IF NOT EXISTS idx_v2_metric_definitions_doc
    ON v2_metric_definitions(doc_id);

CREATE INDEX IF NOT EXISTS idx_v2_metric_definitions_metric
    ON v2_metric_definitions(canonical_metric_id);

COMMENT ON TABLE v2_metric_definitions IS
    'Extracted definition and methodology text for metrics found in V2 pipeline';
