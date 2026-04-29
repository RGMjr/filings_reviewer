-- Migration 202604282225: rename v2_metric_facts.doc_id to filing_id
--
-- The column is BIGINT REFERENCES filings(filing_id) (sql/09_v2_schema.sql:18)
-- but its name suggests v2_documents.doc_id (UUID). The mismatch caused a
-- prod-only `operator does not exist: uuid = bigint` bug in onboarding's
-- count_review_decisions query (commit c353e83). Rename the column so the
-- name matches its type and FK target. Postgres views store column refs as
-- attnums, so the v_v2_review_decisions view in sql/09 keeps working without
-- recreation; pg_get_viewdef will display the new name. See legacy-038.
--
-- Idempotent: information_schema existence guard. EXCEPTION WHEN
-- undefined_column would swallow real errors, so use EXISTS instead.

BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'v2_metric_facts' AND column_name = 'doc_id'
  ) THEN
    ALTER TABLE v2_metric_facts RENAME COLUMN doc_id TO filing_id;
  END IF;
END $$;

ALTER INDEX IF EXISTS idx_v2_metric_facts_doc_id RENAME TO idx_v2_metric_facts_filing_id;

COMMIT;
