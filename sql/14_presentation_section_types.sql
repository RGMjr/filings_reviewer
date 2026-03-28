-- Presentation Section Types Migration
-- Version: 14
-- Date: 2026-03-02
-- Purpose: Extend v2_segments section_type CHECK constraint to include
--          presentation-specific section types added in M3.

-- Drop and recreate the check constraint with expanded allowed values.
-- New values: title_slide, key_metrics, financial_overview, guidance, appendix

ALTER TABLE v2_segments
    DROP CONSTRAINT IF EXISTS v2_segments_section_type_check;

ALTER TABLE v2_segments
    ADD CONSTRAINT v2_segments_section_type_check
    CHECK (section_type = ANY (ARRAY[
        -- Original SEC filing section types
        'cover'::text,
        'risk_factors'::text,
        'mda'::text,
        'business'::text,
        'financials'::text,
        'notes'::text,
        'exhibits'::text,
        'signatures'::text,
        'other'::text,
        'unknown'::text,
        -- Transcript section types (Phase B, migration 13)
        'prepared_remarks'::text,
        'qa'::text,
        'operator'::text,
        'disclaimer'::text,
        -- Presentation slide types (Phase B, migration 14)
        'presentation_slide'::text,
        'title_slide'::text,
        'key_metrics'::text,
        'financial_overview'::text,
        'guidance'::text,
        'appendix'::text
    ]));

COMMENT ON CONSTRAINT v2_segments_section_type_check ON v2_segments IS
    'Allowed section types: SEC filing sections (cover, mda, etc.), transcript sections (prepared_remarks, qa, operator, disclaimer), and presentation slide sections (presentation_slide, title_slide, key_metrics, financial_overview, guidance, appendix)';

-- Extend v2_tables section_type CHECK constraint to match v2_segments.
ALTER TABLE v2_tables
    DROP CONSTRAINT IF EXISTS v2_tables_section_type_check;

ALTER TABLE v2_tables
    ADD CONSTRAINT v2_tables_section_type_check
    CHECK (section_type = ANY (ARRAY[
        'cover'::text, 'risk_factors'::text, 'mda'::text, 'business'::text,
        'financials'::text, 'notes'::text, 'exhibits'::text, 'signatures'::text,
        'other'::text, 'unknown'::text,
        'prepared_remarks'::text, 'qa'::text, 'operator'::text, 'disclaimer'::text,
        'presentation_slide'::text, 'title_slide'::text, 'key_metrics'::text,
        'financial_overview'::text, 'guidance'::text, 'appendix'::text
    ]));

-- Extend v2_image_assets section_type CHECK constraint to match v2_segments.
ALTER TABLE v2_image_assets
    DROP CONSTRAINT IF EXISTS v2_image_assets_section_type_check;

ALTER TABLE v2_image_assets
    ADD CONSTRAINT v2_image_assets_section_type_check
    CHECK (section_type = ANY (ARRAY[
        'cover'::text, 'risk_factors'::text, 'mda'::text, 'business'::text,
        'financials'::text, 'notes'::text, 'exhibits'::text, 'signatures'::text,
        'other'::text, 'unknown'::text,
        'prepared_remarks'::text, 'qa'::text, 'operator'::text, 'disclaimer'::text,
        'presentation_slide'::text, 'title_slide'::text, 'key_metrics'::text,
        'financial_overview'::text, 'guidance'::text, 'appendix'::text
    ]));
