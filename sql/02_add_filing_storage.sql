-- ============================================================================
-- Migration: Add Filing Storage Tracking
-- Purpose: Track locally cached HTML/TXT filing content
-- Date: 2025-11-16
-- ============================================================================

-- Add columns for tracking local storage
ALTER TABLE filings
ADD COLUMN IF NOT EXISTS html_storage_path TEXT,
ADD COLUMN IF NOT EXISTS txt_storage_path TEXT,
ADD COLUMN IF NOT EXISTS html_fetched_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS html_fetch_error TEXT;

-- Create index for finding unfetched filings
CREATE INDEX IF NOT EXISTS idx_filings_html_fetched
ON filings(html_fetched_at)
WHERE html_fetched_at IS NULL AND is_in_scope_phase1 = TRUE;

-- Comments
COMMENT ON COLUMN filings.html_storage_path IS 'Local file path to cached HTML filing document';
COMMENT ON COLUMN filings.txt_storage_path IS 'Local file path to cached complete text filing';
COMMENT ON COLUMN filings.html_fetched_at IS 'Timestamp when HTML was successfully downloaded and cached';
COMMENT ON COLUMN filings.html_fetch_error IS 'Error message if HTML fetch failed';
