-- Migration 202604291308: rename doc_id → filing_id on v2_segments, v2_tables,
-- v2_image_assets, v2_metric_definitions
--
-- All four columns are BIGINT REFERENCES filings(filing_id) but were named
-- doc_id, suggesting a UUID reference to v2_documents.doc_id. Same trap
-- class as v2_metric_facts.doc_id (fixed in migration 202604282225 / legacy-038).
-- Postgres views in sql/09 and sql/38 use attnums — no view recreation needed.
--
-- Idempotent: information_schema existence guard per table. See legacy-038.

BEGIN;

-- v2_segments
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'v2_segments' AND column_name = 'doc_id'
  ) THEN
    ALTER TABLE v2_segments RENAME COLUMN doc_id TO filing_id;
  END IF;
END $$;

-- v2_tables
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'v2_tables' AND column_name = 'doc_id'
  ) THEN
    ALTER TABLE v2_tables RENAME COLUMN doc_id TO filing_id;
  END IF;
END $$;

-- v2_image_assets
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'v2_image_assets' AND column_name = 'doc_id'
  ) THEN
    ALTER TABLE v2_image_assets RENAME COLUMN doc_id TO filing_id;
  END IF;
END $$;

-- v2_metric_definitions
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'v2_metric_definitions' AND column_name = 'doc_id'
  ) THEN
    ALTER TABLE v2_metric_definitions RENAME COLUMN doc_id TO filing_id;
  END IF;
END $$;

-- Rename indices that embed the old column name
ALTER INDEX IF EXISTS idx_v2_segments_doc_id        RENAME TO idx_v2_segments_filing_id;
ALTER INDEX IF EXISTS idx_v2_tables_doc_id           RENAME TO idx_v2_tables_filing_id;
ALTER INDEX IF EXISTS idx_v2_image_assets_doc_id     RENAME TO idx_v2_image_assets_filing_id;
ALTER INDEX IF EXISTS idx_v2_metric_definitions_doc  RENAME TO idx_v2_metric_definitions_filing;

COMMIT;
