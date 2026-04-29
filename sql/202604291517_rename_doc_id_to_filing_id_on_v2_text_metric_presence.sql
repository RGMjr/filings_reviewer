-- Migration 202604291517: rename doc_id → filing_id on v2_text_metric_presence
--
-- BIGINT FK to filings(filing_id) was named doc_id — same naming smell fixed
-- for v2_segments, v2_tables, v2_image_assets, v2_metric_definitions in
-- migration 202604291308 (gh-324). Idempotent: information_schema guard.

BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'v2_text_metric_presence' AND column_name = 'doc_id'
  ) THEN
    ALTER TABLE v2_text_metric_presence RENAME COLUMN doc_id TO filing_id;
  END IF;
END $$;

ALTER INDEX IF EXISTS idx_v2_text_metric_presence_doc RENAME TO idx_v2_text_metric_presence_filing;

COMMIT;
