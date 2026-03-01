-- Transcript Section Types Migration
-- Version: 13
-- Date: 2026-03-01
-- Purpose: Extend v2_segments section_type CHECK constraint to include
--          transcript-specific section types added in Phase B.

-- Drop and recreate the check constraint with expanded allowed values.
-- New values: prepared_remarks, qa, operator, disclaimer

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
        -- Transcript section types (Phase B)
        'prepared_remarks'::text,
        'qa'::text,
        'operator'::text,
        'disclaimer'::text
    ]));

COMMENT ON CONSTRAINT v2_segments_section_type_check ON v2_segments IS
    'Allowed section types: SEC filing sections (cover, mda, etc.) and transcript sections (prepared_remarks, qa, operator, disclaimer)';
