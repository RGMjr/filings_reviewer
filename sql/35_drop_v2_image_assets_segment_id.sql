-- Migration 35: Drop dead v2_image_assets.segment_id column.
--
-- Context: segment_id was a legacy FK to V1 source_segments(source_segment_id).
-- The FK constraint was dropped in sql/31_drop_v1_review_tables.sql (line 24)
-- during V1 retirement, and the V1 source_segments table itself is gone.
-- Application code (src/extraction_v2/persistence.py) has written only NULL
-- to this column for months; nothing reads from it. Drop it to remove the
-- misleading schema artifact.
--
-- Idempotent: safe to re-apply. No data migration needed (all rows are NULL).

ALTER TABLE v2_image_assets DROP COLUMN IF EXISTS segment_id;
