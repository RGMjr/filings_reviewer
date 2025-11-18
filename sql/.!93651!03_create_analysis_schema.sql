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
