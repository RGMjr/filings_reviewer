-- Migration 202605051429: drop_html_content_column
--
-- R2 soak window complete (gh-314). Drop the DB-blob fallback column that was
-- retained after gh-300 (PR #316). All active code now reads from R2 /
-- local filesystem; no call site reads filings.html_content anymore.

BEGIN;

ALTER TABLE filings DROP COLUMN IF EXISTS html_content;

COMMIT;
