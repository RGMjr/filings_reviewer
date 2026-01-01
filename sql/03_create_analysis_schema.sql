-- ============================================================================
-- Migration: Create Analysis Schema
-- Purpose: Create tables for metric extraction, classification, and storage
-- Date: 2025-11-17
-- Based on: 03_DATA_MODEL_SPEC.md v0.1
-- ============================================================================

-- Drop tables if they exist (for development)
DROP TABLE IF EXISTS metric_definitions CASCADE;
DROP TABLE IF EXISTS filing_metric_incidence CASCADE;
DROP TABLE IF EXISTS metric_values CASCADE;
DROP TABLE IF EXISTS source_segments CASCADE;
DROP TABLE IF EXISTS metrics CASCADE;

-- ============================================================================
-- TABLE: metrics
-- ============================================================================
-- Grain: One row per canonical metric ID in the taxonomy
-- Purpose: Dimension table for metrics; ties DB to 02_METRIC_TAXONOMY_AND_DEFINITIONS.md

CREATE TABLE metrics (
    -- Primary key
    metric_id TEXT PRIMARY KEY,  -- Canonical ID, e.g., 'cm_new_customers_acquired'

    -- Display and classification
    display_name TEXT NOT NULL,
    metric_class TEXT NOT NULL,  -- 'core', 'extended', 'future'
    description TEXT,
    primary_concept TEXT,  -- e.g., 'acquisition', 'cohort_revenue'

    -- Status and versioning
    status TEXT NOT NULL DEFAULT 'active',  -- 'active', 'deprecated', 'experimental'
    version INTEGER NOT NULL DEFAULT 1,  -- Metric definition version

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_metric_class CHECK (metric_class IN ('core', 'extended', 'future')),
    CONSTRAINT check_metric_status CHECK (status IN ('active', 'deprecated', 'experimental'))
);

-- Indices
CREATE INDEX idx_metrics_class ON metrics(metric_class);
CREATE INDEX idx_metrics_status ON metrics(status);

-- Comments
COMMENT ON TABLE metrics IS 'Dimension table of canonical metrics from taxonomy (02_METRIC_TAXONOMY_AND_DEFINITIONS.md)';
COMMENT ON COLUMN metrics.metric_id IS 'Canonical metric ID (lower_snake_case), e.g., cm_new_customers_acquired';
COMMENT ON COLUMN metrics.metric_class IS 'Phase 1 classification: core, extended, or future';
COMMENT ON COLUMN metrics.version IS 'Metric definition version; increment when definition changes affect comparability';

-- ============================================================================
-- TABLE: source_segments
-- ============================================================================
-- Grain: One row per segment of a filing (paragraph, table, footnote, etc.)
-- Purpose: Provide audit trail and anchor for all extracted metrics and definitions

CREATE TABLE source_segments (
    -- Primary key
    source_segment_id BIGSERIAL PRIMARY KEY,

    -- Foreign key
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,

    -- Segment metadata
    segment_type TEXT NOT NULL,  -- 'paragraph', 'table', 'footnote', 'definition_block', 'methodology_block', 'other'
    section_path TEXT,  -- Logical item path, e.g., "Item 1. Business > Customers"
    section_heading TEXT,  -- Human-readable heading text
    sequence_index INTEGER NOT NULL,  -- Order of segment within the filing (0-based)

    -- Location / provenance
    html_selector TEXT,  -- XPath, CSS selector, or internal pointer
    char_start_offset INTEGER,  -- Start character index in normalized filing text
    char_end_offset INTEGER,  -- End character index
    page_number INTEGER,  -- If mapped to PDF pages

    -- Content
    raw_text TEXT NOT NULL,  -- Normalized visible text
    raw_html TEXT,  -- Original HTML snippet (optional; can be large)

    -- LLM / classification metadata
    candidate_metric_ids TEXT[],  -- List of possible metric IDs mentioned (from classifier)
    contains_definition_flag BOOLEAN NOT NULL DEFAULT FALSE,
    contains_methodology_flag BOOLEAN NOT NULL DEFAULT FALSE,
    contains_numeric_disclosure_flag BOOLEAN NOT NULL DEFAULT FALSE,
    classifier_confidence NUMERIC,  -- 0-1

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_segment_type CHECK (segment_type IN ('paragraph', 'table', 'footnote', 'definition_block', 'methodology_block', 'other'))
);

-- Indices
CREATE INDEX idx_source_segments_filing ON source_segments(filing_id);
CREATE INDEX idx_source_segments_type ON source_segments(segment_type);
CREATE INDEX idx_source_segments_sequence ON source_segments(filing_id, sequence_index);
CREATE INDEX idx_source_segments_flags ON source_segments(filing_id)
    WHERE contains_definition_flag OR contains_methodology_flag OR contains_numeric_disclosure_flag;

-- Comments
COMMENT ON TABLE source_segments IS 'Segmented units of each filing (paragraphs, tables, footnotes) - the atomic source units for audit trails';
COMMENT ON COLUMN source_segments.segment_type IS 'Type of segment: paragraph, table, footnote, definition_block, methodology_block, other';
COMMENT ON COLUMN source_segments.raw_text IS 'Normalized visible text extracted from the segment';
COMMENT ON COLUMN source_segments.candidate_metric_ids IS 'Array of metric IDs that may be disclosed in this segment (from initial classifier)';

-- ============================================================================
-- TABLE: metric_values
-- ============================================================================
-- Grain: One row per filing x metric x period x cohort x segment value
-- Purpose: Main fact table for quantitative analysis of disclosed metrics

CREATE TABLE metric_values (
    -- Primary key
    metric_value_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),  -- Denormalized for convenience
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id),
    source_segment_id BIGINT NOT NULL REFERENCES source_segments(source_segment_id) ON DELETE CASCADE,

    -- Provenance
    source_type TEXT NOT NULL,  -- 'table', 'text', 'footnote', 'other'
    extraction_method TEXT NOT NULL,  -- 'rule_table', 'llm_table', 'llm_text', 'manual_review'

    -- Value
    value_numeric NUMERIC,  -- Primary numeric value
    value_text TEXT,  -- If value is not purely numeric, or for safety copies
    unit TEXT,  -- 'count', '%', 'usd', 'basis_points', 'per_customer'
    currency TEXT,  -- ISO code when monetary

    -- Time dimensions
    period_start DATE,
    period_end DATE,
    period_type TEXT,  -- 'fy', 'quarter', 'month', 'ttm', 'since_inception'

    -- Cohort dimensions
    cohort_type TEXT,  -- 'acquisition', 'tenure', 'other'
    cohort_bucket_raw TEXT,  -- Issuer's label, e.g., "2021 Cohort", "0-1 years"
    cohort_bucket_normalized TEXT,  -- Normalized form if we standardize buckets

    -- Customer segmentation dimensions (optional)
    segment_dimension TEXT,  -- e.g., 'customer_type', 'product', 'geography'
    segment_value TEXT,  -- e.g., 'enterprise', 'SMB', 'US'

    -- Quality / alignment
    qa_status TEXT NOT NULL DEFAULT 'unreviewed',  -- 'unreviewed', 'pass', 'warning', 'fail'
    qa_notes TEXT,
    alignment_flag TEXT,  -- 'aligned', 'partial', 'not_aligned', 'unknown'

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_source_type CHECK (source_type IN ('table', 'text', 'footnote', 'other')),
    CONSTRAINT check_extraction_method CHECK (extraction_method IN ('rule_table', 'rule_text_smart', 'llm_table', 'llm_text', 'manual_review')),
    CONSTRAINT check_period_type CHECK (period_type IS NULL OR period_type IN ('fy', 'quarter', 'month', 'ttm', 'since_inception', 'other')),
    CONSTRAINT check_cohort_type CHECK (cohort_type IS NULL OR cohort_type IN ('acquisition', 'tenure', 'other')),
    CONSTRAINT check_qa_status CHECK (qa_status IN ('unreviewed', 'pass', 'warning', 'fail')),
    CONSTRAINT check_alignment CHECK (alignment_flag IS NULL OR alignment_flag IN ('aligned', 'partial', 'not_aligned', 'unknown'))
);

-- Indices
CREATE INDEX idx_metric_values_filing ON metric_values(filing_id);
CREATE INDEX idx_metric_values_company ON metric_values(company_id);
CREATE INDEX idx_metric_values_metric ON metric_values(metric_id);
CREATE INDEX idx_metric_values_filing_metric ON metric_values(filing_id, metric_id);
CREATE INDEX idx_metric_values_cohort ON metric_values(cohort_type, cohort_bucket_normalized) WHERE cohort_type IS NOT NULL;
CREATE INDEX idx_metric_values_qa ON metric_values(qa_status);

-- Comments
COMMENT ON TABLE metric_values IS 'Fact table for extracted numeric metric values (filing x metric x period x cohort x segment)';
COMMENT ON COLUMN metric_values.extraction_method IS 'Method used to extract value: rule_table, llm_table, llm_text, manual_review';
COMMENT ON COLUMN metric_values.cohort_bucket_raw IS 'Issuer-specific cohort label as disclosed';
COMMENT ON COLUMN metric_values.cohort_bucket_normalized IS 'Standardized cohort bucket for cross-firm comparison';
COMMENT ON COLUMN metric_values.alignment_flag IS 'Alignment with canonical metric definition: aligned, partial, not_aligned, unknown';

-- ============================================================================
-- TABLE: filing_metric_incidence
-- ============================================================================
-- Grain: One row per filing x metric
-- Purpose: Support incidence and quality analyses at the filing-metric level

CREATE TABLE filing_metric_incidence (
    -- Primary key
    filing_metric_incidence_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),  -- Denormalized
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id),

    -- Incidence
    metric_disclosed_flag BOOLEAN NOT NULL,  -- True if any metric_values or definition/methodology segments present
    num_numeric_segments INTEGER NOT NULL DEFAULT 0,  -- Count of distinct segments with numeric disclosures
    num_definition_segments INTEGER NOT NULL DEFAULT 0,  -- Segments containing definitions
    num_methodology_segments INTEGER NOT NULL DEFAULT 0,  -- Segments containing methodology

    -- Primary segments
    primary_definition_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,
    primary_methodology_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,

    -- Quality scores (LLM- or human-derived)
    quality_overall_score INTEGER,  -- 0-3 overall quality score
    quality_definition_score INTEGER,  -- 0-3
    quality_methodology_score INTEGER,  -- 0-3
    quality_completeness_score INTEGER,  -- 0-3
    quality_comparability_score INTEGER,  -- 0-3

    -- Notes and flags
    alignment_flag TEXT,  -- Summary alignment at filing-metric level
    quality_notes TEXT,
    has_cohort_breakdown_flag BOOLEAN NOT NULL DEFAULT FALSE,
    has_tenure_breakdown_flag BOOLEAN NOT NULL DEFAULT FALSE,
    has_acquisition_cohort_flag BOOLEAN NOT NULL DEFAULT FALSE,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    UNIQUE (filing_id, metric_id),  -- One row per filing-metric pair
    CONSTRAINT check_quality_scores CHECK (
        (quality_overall_score IS NULL OR quality_overall_score BETWEEN 0 AND 3) AND
        (quality_definition_score IS NULL OR quality_definition_score BETWEEN 0 AND 3) AND
        (quality_methodology_score IS NULL OR quality_methodology_score BETWEEN 0 AND 3) AND
        (quality_completeness_score IS NULL OR quality_completeness_score BETWEEN 0 AND 3) AND
        (quality_comparability_score IS NULL OR quality_comparability_score BETWEEN 0 AND 3)
    ),
    CONSTRAINT check_alignment CHECK (alignment_flag IS NULL OR alignment_flag IN ('aligned', 'partial', 'not_aligned', 'unknown'))
);

-- Indices
CREATE INDEX idx_filing_metric_incidence_filing ON filing_metric_incidence(filing_id);
CREATE INDEX idx_filing_metric_incidence_metric ON filing_metric_incidence(metric_id);
CREATE INDEX idx_filing_metric_incidence_disclosed ON filing_metric_incidence(metric_disclosed_flag) WHERE metric_disclosed_flag = TRUE;
CREATE INDEX idx_filing_metric_incidence_quality ON filing_metric_incidence(quality_overall_score) WHERE quality_overall_score IS NOT NULL;

-- Comments
COMMENT ON TABLE filing_metric_incidence IS 'Filing x metric level incidence and quality scores';
COMMENT ON COLUMN filing_metric_incidence.metric_disclosed_flag IS 'True if metric is disclosed in any form (values, definitions, or methodology)';
COMMENT ON COLUMN filing_metric_incidence.quality_overall_score IS 'Overall quality score 0-3: 0=not disclosed, 1=minimal, 2=moderate, 3=excellent';
COMMENT ON COLUMN filing_metric_incidence.alignment_flag IS 'Summary alignment with CMASB canonical definition at filing-metric level';

-- ============================================================================
-- TABLE: metric_definitions
-- ============================================================================
-- Grain: One row per filing x metric x definition_version_in_filing
-- Purpose: Capture issuer-specific definitions and methodology text

CREATE TABLE metric_definitions (
    -- Primary key
    metric_definition_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),  -- Denormalized
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id),

    -- Version (if they revise definition within same filing)
    definition_version_in_filing INTEGER NOT NULL DEFAULT 1,

    -- Content
    definition_text_normalized TEXT,  -- Cleaned summary of definition
    methodology_text_normalized TEXT,  -- Cleaned summary of calculation method
    definition_raw_text TEXT,  -- Raw extracted text snippet
    methodology_raw_text TEXT,  -- Raw methodology text

    -- Provenance
    definition_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,
    methodology_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,

    -- Alignment
    alignment_flag TEXT,  -- 'aligned', 'partial', 'not_aligned', 'unknown'
    alignment_notes TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_alignment CHECK (alignment_flag IS NULL OR alignment_flag IN ('aligned', 'partial', 'not_aligned', 'unknown'))
);

-- Indices
CREATE INDEX idx_metric_definitions_filing ON metric_definitions(filing_id);
CREATE INDEX idx_metric_definitions_metric ON metric_definitions(metric_id);
CREATE INDEX idx_metric_definitions_filing_metric ON metric_definitions(filing_id, metric_id);
CREATE INDEX idx_metric_definitions_alignment ON metric_definitions(alignment_flag) WHERE alignment_flag IS NOT NULL;

-- Comments
COMMENT ON TABLE metric_definitions IS 'Issuer-specific metric definitions and calculation methodologies (filing x metric x version)';
COMMENT ON COLUMN metric_definitions.definition_text_normalized IS 'Cleaned and normalized definition text for comparability analysis';
COMMENT ON COLUMN metric_definitions.definition_raw_text IS 'Raw extracted text from the filing (may be truncated)';
COMMENT ON COLUMN metric_definitions.alignment_flag IS 'Alignment with CMASB canonical definition';
