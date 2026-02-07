-- V2 Extraction Pipeline Schema
--
-- This schema supports the V2 unified extraction pipeline with:
-- - Full table reconstruction (colspan/rowspan, header_path/stub_path)
-- - Image/chart extraction
-- - MetricFact with complete provenance
-- - Evidence packs for audit
--
-- Design source: Claude V2 PRD + GPT-5.2 PRD synthesis
-- See: /Users/rgmarkey/.claude/plans/deep-conjuring-treehouse.md

-- ============================================================================
-- V2 METRIC FACTS (Primary extraction output)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_metric_facts (
    fact_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    canonical_metric_id TEXT NOT NULL REFERENCES metrics(metric_id),

    -- Value
    value               NUMERIC,
    value_raw           TEXT NOT NULL,  -- Original text, e.g., "112%"
    unit                TEXT NOT NULL CHECK (unit IN ('percent', 'currency', 'count', 'ratio', 'basis_points', 'other')),
    currency            TEXT,  -- ISO code if unit='currency'

    -- Time dimension
    period_type         TEXT CHECK (period_type IN ('annual', 'quarterly', 'trailing', 'ytd', 'point_in_time', 'other')),
    period_start        DATE,
    period_end          DATE,

    -- Scope dimensions
    scope               TEXT DEFAULT 'company' CHECK (scope IN ('company', 'segment', 'geography', 'product', 'customer_type', 'cohort', 'other')),
    scope_detail        TEXT,  -- Segment name if scope='segment'
    cohort_def          TEXT,  -- "Customers acquired in 2022"
    customer_type       TEXT,  -- "Enterprise", "SMB"

    -- Provenance (non-negotiable)
    source_type         TEXT NOT NULL CHECK (source_type IN ('html_table', 'ocr_table', 'text', 'chart')),
    source_locator      JSONB NOT NULL DEFAULT '{}',  -- SourceLocator as JSON

    -- Evidence pack (for human review)
    evidence_pack       JSONB NOT NULL DEFAULT '{}',  -- EvidencePack as JSON

    -- Quality signals
    confidence          NUMERIC NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    extraction_method   TEXT NOT NULL DEFAULT 'exact_match' CHECK (extraction_method IN ('exact_match', 'alias_match', 'embedding', 'llm', 'manual')),
    requires_review     BOOLEAN NOT NULL DEFAULT TRUE,
    review_reason       TEXT,
    review_status       TEXT NOT NULL DEFAULT 'pending_review' CHECK (review_status IN ('auto_accepted', 'pending_review', 'accepted', 'rejected', 'corrected')),

    -- Deduplication
    alternate_evidence  UUID[],  -- Other fact_ids merged into this one
    primary_fact_id     UUID REFERENCES v2_metric_facts(fact_id),  -- If this is a duplicate, points to primary

    -- Metadata
    pipeline_version    TEXT NOT NULL DEFAULT '2.0.0',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT valid_period CHECK (period_start IS NULL OR period_end IS NULL OR period_start <= period_end),
    CONSTRAINT valid_currency CHECK (unit != 'currency' OR currency IS NOT NULL)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_doc_id ON v2_metric_facts(doc_id);
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_metric_id ON v2_metric_facts(canonical_metric_id);
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_review_status ON v2_metric_facts(review_status);
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_source_type ON v2_metric_facts(source_type);
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_period ON v2_metric_facts(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_confidence ON v2_metric_facts(confidence);

-- Deduplication identity index (for finding duplicates)
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_identity ON v2_metric_facts(
    canonical_metric_id, period_start, period_end, unit, scope, cohort_def, customer_type
);

-- GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_evidence ON v2_metric_facts USING GIN (evidence_pack);
CREATE INDEX IF NOT EXISTS idx_v2_metric_facts_locator ON v2_metric_facts USING GIN (source_locator);

-- ============================================================================
-- V2 TABLES (Reconstructed tables with full structure)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_tables (
    table_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    segment_id          UUID REFERENCES v2_segments(segment_id) ON DELETE SET NULL,

    -- DOM location
    dom_locator         TEXT NOT NULL,  -- XPath

    -- Section context
    section_path        TEXT[],
    section_type        TEXT CHECK (section_type IN ('cover', 'risk_factors', 'mda', 'business', 'financials', 'notes', 'exhibits', 'signatures', 'other', 'unknown')),

    -- Structure
    row_count           INTEGER NOT NULL,
    col_count           INTEGER NOT NULL,
    header_rows         INTEGER NOT NULL DEFAULT 0,
    stub_cols           INTEGER NOT NULL DEFAULT 0,

    -- Raw HTML (for re-processing if needed)
    raw_html            TEXT,

    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_tables_doc_id ON v2_tables(doc_id);
CREATE INDEX IF NOT EXISTS idx_v2_tables_section_type ON v2_tables(section_type);

-- ============================================================================
-- V2 TABLE CELLS (Individual cells with header_path/stub_path)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_table_cells (
    cell_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id            UUID NOT NULL REFERENCES v2_tables(table_id) ON DELETE CASCADE,

    -- Position (0-indexed, after span resolution)
    row_idx             INTEGER NOT NULL,
    col_idx             INTEGER NOT NULL,

    -- Content
    cell_text           TEXT NOT NULL,

    -- Structural flags
    is_header           BOOLEAN NOT NULL DEFAULT FALSE,
    is_stub             BOOLEAN NOT NULL DEFAULT FALSE,

    -- Computed paths (for binding)
    header_path         TEXT[],  -- All headers above this cell
    stub_path           TEXT[],  -- All stubs to left of this cell

    -- Original span info (for audit)
    rowspan             INTEGER NOT NULL DEFAULT 1,
    colspan             INTEGER NOT NULL DEFAULT 1,

    -- DOM locator
    dom_locator         TEXT,

    -- Unique constraint on (table_id, row_idx, col_idx)
    CONSTRAINT v2_table_cells_unique_position UNIQUE (table_id, row_idx, col_idx)
);

CREATE INDEX IF NOT EXISTS idx_v2_table_cells_table_id ON v2_table_cells(table_id);
CREATE INDEX IF NOT EXISTS idx_v2_table_cells_position ON v2_table_cells(table_id, row_idx, col_idx);
CREATE INDEX IF NOT EXISTS idx_v2_table_cells_header_path ON v2_table_cells USING GIN (header_path);
CREATE INDEX IF NOT EXISTS idx_v2_table_cells_stub_path ON v2_table_cells USING GIN (stub_path);

-- ============================================================================
-- V2 IMAGE ASSETS (Extracted images with classification)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_image_assets (
    img_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    segment_id          UUID REFERENCES v2_segments(segment_id) ON DELETE SET NULL,

    -- File info
    filename            TEXT NOT NULL,
    file_path           TEXT,  -- Path to extracted image file
    width               INTEGER,
    height              INTEGER,

    -- DOM location
    dom_locator         TEXT NOT NULL,

    -- Context
    nearby_text         TEXT,  -- Caption + surrounding paragraphs
    section_path        TEXT[],
    section_type        TEXT CHECK (section_type IN ('cover', 'risk_factors', 'mda', 'business', 'financials', 'notes', 'exhibits', 'signatures', 'other', 'unknown')),

    -- Classification
    classification      TEXT NOT NULL DEFAULT 'unknown' CHECK (classification IN ('chart', 'table_image', 'decorative', 'logo', 'signature', 'unknown')),
    relevance_score     NUMERIC DEFAULT 0 CHECK (relevance_score >= 0 AND relevance_score <= 1),

    -- OCR results (if processed)
    ocr_text            TEXT,
    ocr_table_id        UUID REFERENCES v2_tables(table_id),  -- If OCR produced a table

    -- Chart results (if chart)
    chart_type          TEXT CHECK (chart_type IN ('bar', 'line', 'pie', 'stacked_bar', 'area', 'unknown')),
    chart_data          JSONB,  -- ChartData as JSON

    -- Processing status
    processed           BOOLEAN NOT NULL DEFAULT FALSE,
    confidence          NUMERIC DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    requires_manual     BOOLEAN NOT NULL DEFAULT FALSE,  -- True if values couldn't be extracted

    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_image_assets_doc_id ON v2_image_assets(doc_id);
CREATE INDEX IF NOT EXISTS idx_v2_image_assets_classification ON v2_image_assets(classification);
CREATE INDEX IF NOT EXISTS idx_v2_image_assets_relevance ON v2_image_assets(relevance_score);
CREATE INDEX IF NOT EXISTS idx_v2_image_assets_processed ON v2_image_assets(processed);

-- ============================================================================
-- V2 SEGMENTS (DOM-native content blocks with section classification)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_segments (
    segment_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,

    -- Type and content
    segment_type        TEXT NOT NULL CHECK (segment_type IN ('heading', 'paragraph', 'table', 'image_ref', 'caption', 'list', 'footnote', 'definition', 'methodology', 'other')),
    segment_text        TEXT NOT NULL,

    -- DOM location
    dom_locator         TEXT NOT NULL,

    -- Section context (enhanced from V1)
    section_path        TEXT[],  -- Hierarchical labels, e.g., ["Item 7", "MD&A"]
    section_type        TEXT CHECK (section_type IN ('cover', 'risk_factors', 'mda', 'business', 'financials', 'notes', 'exhibits', 'signatures', 'other', 'unknown')),

    -- Document order
    sequence_idx        INTEGER NOT NULL,

    -- Context links
    prev_segment_id     UUID REFERENCES v2_segments(segment_id),
    next_segment_id     UUID REFERENCES v2_segments(segment_id),

    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_segments_doc_id ON v2_segments(doc_id);
CREATE INDEX IF NOT EXISTS idx_v2_segments_type ON v2_segments(segment_type);
CREATE INDEX IF NOT EXISTS idx_v2_segments_section ON v2_segments(section_type);
CREATE INDEX IF NOT EXISTS idx_v2_segments_sequence ON v2_segments(doc_id, sequence_idx);

-- ============================================================================
-- V2 DOCUMENTS (Filing-level processing metadata)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_documents (
    doc_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id           BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,

    -- Processing metadata
    parse_version       TEXT NOT NULL DEFAULT '2.0.0',

    -- Computed statistics
    segment_count       INTEGER DEFAULT 0,
    table_count         INTEGER DEFAULT 0,
    image_count         INTEGER DEFAULT 0,
    fact_count          INTEGER DEFAULT 0,

    -- Processing status
    status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'parsing', 'extracting', 'reviewing', 'complete', 'failed')),
    error_message       TEXT,

    -- Timing
    parse_started_at    TIMESTAMPTZ,
    parse_completed_at  TIMESTAMPTZ,
    extract_started_at  TIMESTAMPTZ,
    extract_completed_at TIMESTAMPTZ,

    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT v2_documents_unique_filing UNIQUE (filing_id)
);

CREATE INDEX IF NOT EXISTS idx_v2_documents_filing_id ON v2_documents(filing_id);
CREATE INDEX IF NOT EXISTS idx_v2_documents_status ON v2_documents(status);

-- ============================================================================
-- V2 REVIEW DECISIONS (Human review tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_review_decisions (
    decision_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id             UUID NOT NULL REFERENCES v2_metric_facts(fact_id) ON DELETE CASCADE,

    -- Decision
    decision            TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'correct')),
    assigned_metric_id  TEXT REFERENCES metrics(metric_id),  -- If corrected to different metric
    corrected_value     NUMERIC,  -- If value was corrected

    -- Rejection details
    rejection_reason    TEXT,
    rejection_category  TEXT CHECK (rejection_category IN ('wrong_metric', 'not_a_metric', 'wrong_value', 'wrong_period', 'duplicate', 'other')),

    -- Reviewer metadata
    reviewer_id         TEXT NOT NULL,
    reviewer_notes      TEXT,
    review_time_seconds INTEGER,

    -- Metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT v2_review_decisions_unique_fact UNIQUE (fact_id)
);

CREATE INDEX IF NOT EXISTS idx_v2_review_decisions_decision ON v2_review_decisions(decision);
CREATE INDEX IF NOT EXISTS idx_v2_review_decisions_reviewer ON v2_review_decisions(reviewer_id);

-- ============================================================================
-- TRIGGER: Update updated_at timestamps
-- ============================================================================

CREATE OR REPLACE FUNCTION v2_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS v2_metric_facts_updated_at ON v2_metric_facts;
CREATE TRIGGER v2_metric_facts_updated_at
    BEFORE UPDATE ON v2_metric_facts
    FOR EACH ROW
    EXECUTE FUNCTION v2_update_timestamp();

DROP TRIGGER IF EXISTS v2_documents_updated_at ON v2_documents;
CREATE TRIGGER v2_documents_updated_at
    BEFORE UPDATE ON v2_documents
    FOR EACH ROW
    EXECUTE FUNCTION v2_update_timestamp();

-- ============================================================================
-- TRIGGER: Update review_status when decision is made
-- ============================================================================

CREATE OR REPLACE FUNCTION v2_update_fact_review_status()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE v2_metric_facts
    SET review_status = CASE
        WHEN NEW.decision = 'accept' THEN 'accepted'
        WHEN NEW.decision = 'reject' THEN 'rejected'
        WHEN NEW.decision = 'correct' THEN 'corrected'
    END,
    updated_at = NOW()
    WHERE fact_id = NEW.fact_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS v2_review_decision_updates_fact ON v2_review_decisions;
CREATE TRIGGER v2_review_decision_updates_fact
    AFTER INSERT ON v2_review_decisions
    FOR EACH ROW
    EXECUTE FUNCTION v2_update_fact_review_status();

-- ============================================================================
-- VIEWS for common queries
-- ============================================================================

-- View: Facts pending review
CREATE OR REPLACE VIEW v2_facts_pending_review AS
SELECT
    f.fact_id,
    f.doc_id,
    fi.accession_number,
    c.company_name,
    f.canonical_metric_id,
    f.value,
    f.value_raw,
    f.unit,
    f.period_start,
    f.period_end,
    f.source_type,
    f.confidence,
    f.review_reason,
    f.evidence_pack,
    f.created_at
FROM v2_metric_facts f
JOIN filings fi ON f.doc_id = fi.filing_id
JOIN companies c ON fi.company_id = c.company_id
WHERE f.review_status = 'pending_review'
ORDER BY f.confidence DESC, f.created_at;

-- View: Extraction summary by document
CREATE OR REPLACE VIEW v2_extraction_summary AS
SELECT
    d.doc_id,
    d.filing_id,
    fi.accession_number,
    c.company_name,
    d.status,
    d.segment_count,
    d.table_count,
    d.image_count,
    d.fact_count,
    COUNT(CASE WHEN f.review_status = 'pending_review' THEN 1 END) AS pending_review_count,
    COUNT(CASE WHEN f.review_status = 'accepted' THEN 1 END) AS accepted_count,
    COUNT(CASE WHEN f.review_status = 'rejected' THEN 1 END) AS rejected_count,
    d.parse_completed_at,
    d.extract_completed_at
FROM v2_documents d
JOIN filings fi ON d.filing_id = fi.filing_id
JOIN companies c ON fi.company_id = c.company_id
LEFT JOIN v2_metric_facts f ON f.doc_id = d.filing_id
GROUP BY d.doc_id, d.filing_id, fi.accession_number, c.company_name,
         d.status, d.segment_count, d.table_count, d.image_count, d.fact_count,
         d.parse_completed_at, d.extract_completed_at;

-- ============================================================================
-- COMMENTS for documentation
-- ============================================================================

COMMENT ON TABLE v2_metric_facts IS 'Primary output of V2 extraction pipeline. Every extracted metric with full provenance.';
COMMENT ON TABLE v2_tables IS 'Reconstructed tables with colspan/rowspan resolution.';
COMMENT ON TABLE v2_table_cells IS 'Individual table cells with header_path and stub_path for binding.';
COMMENT ON TABLE v2_image_assets IS 'Extracted images with classification and OCR/chart results.';
COMMENT ON TABLE v2_segments IS 'DOM-native content blocks with semantic section classification.';
COMMENT ON TABLE v2_documents IS 'Filing-level processing metadata for V2 pipeline.';
COMMENT ON TABLE v2_review_decisions IS 'Human review decisions for V2 facts.';

COMMENT ON COLUMN v2_metric_facts.source_locator IS 'JSON object with segment_id, table_id, cell_row/col, text_span, img_id, bbox, dom_locator';
COMMENT ON COLUMN v2_metric_facts.evidence_pack IS 'JSON object with snippet_html, header_path, stub_path, context_before/after, screenshot_path';
COMMENT ON COLUMN v2_table_cells.header_path IS 'Array of all column header texts above this cell';
COMMENT ON COLUMN v2_table_cells.stub_path IS 'Array of all row stub texts to the left of this cell';
