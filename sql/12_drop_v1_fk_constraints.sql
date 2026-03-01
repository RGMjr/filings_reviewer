-- Migration 12: Drop V1 FK constraints on source_segments
-- Purpose: Remove FK references from V1 review and analysis tables to source_segments,
--          unblocking eventual V1 table removal. Columns and data are preserved.
-- Idempotent: Uses IF EXISTS on all drops.

-- Review tables
ALTER TABLE review_candidates
    DROP CONSTRAINT IF EXISTS review_candidates_source_segment_id_fkey;

ALTER TABLE suppressed_candidates
    DROP CONSTRAINT IF EXISTS suppressed_candidates_source_segment_id_fkey;

ALTER TABLE image_review_candidates
    DROP CONSTRAINT IF EXISTS image_review_candidates_source_segment_id_fkey;

-- Analysis tables
ALTER TABLE metric_values
    DROP CONSTRAINT IF EXISTS metric_values_source_segment_id_fkey;

ALTER TABLE filing_metric_incidence
    DROP CONSTRAINT IF EXISTS filing_metric_incidence_primary_definition_segment_id_fkey;

ALTER TABLE filing_metric_incidence
    DROP CONSTRAINT IF EXISTS filing_metric_incidence_primary_methodology_segment_id_fkey;

ALTER TABLE metric_definitions
    DROP CONSTRAINT IF EXISTS metric_definitions_definition_segment_id_fkey;

ALTER TABLE metric_definitions
    DROP CONSTRAINT IF EXISTS metric_definitions_methodology_segment_id_fkey;


-- ROLLBACK (commented out — run only to re-add constraints if needed)
-- Note: source_segments table must exist and data must be consistent before re-adding.
--
-- ALTER TABLE review_candidates
--     ADD CONSTRAINT review_candidates_source_segment_id_fkey
--     FOREIGN KEY (source_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE suppressed_candidates
--     ADD CONSTRAINT suppressed_candidates_source_segment_id_fkey
--     FOREIGN KEY (source_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE image_review_candidates
--     ADD CONSTRAINT image_review_candidates_source_segment_id_fkey
--     FOREIGN KEY (source_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE metric_values
--     ADD CONSTRAINT metric_values_source_segment_id_fkey
--     FOREIGN KEY (source_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE filing_metric_incidence
--     ADD CONSTRAINT filing_metric_incidence_primary_definition_segment_id_fkey
--     FOREIGN KEY (primary_definition_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE filing_metric_incidence
--     ADD CONSTRAINT filing_metric_incidence_primary_methodology_segment_id_fkey
--     FOREIGN KEY (primary_methodology_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE metric_definitions
--     ADD CONSTRAINT metric_definitions_definition_segment_id_fkey
--     FOREIGN KEY (definition_segment_id) REFERENCES source_segments(segment_id);
--
-- ALTER TABLE metric_definitions
--     ADD CONSTRAINT metric_definitions_methodology_segment_id_fkey
--     FOREIGN KEY (methodology_segment_id) REFERENCES source_segments(segment_id);
