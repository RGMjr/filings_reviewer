-- Migration: Store filing HTML/TXT content directly in database
-- This enables cloud deployments where local filesystem is ephemeral

ALTER TABLE filings ADD COLUMN IF NOT EXISTS html_content TEXT;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS txt_content TEXT;

COMMENT ON COLUMN filings.html_content IS 'Filing HTML document content stored directly in database';
COMMENT ON COLUMN filings.txt_content IS 'Filing complete text content stored directly in database';
