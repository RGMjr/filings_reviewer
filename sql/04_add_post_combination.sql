-- Migration: Add is_post_combination field for de-SPAC tracking
-- Date: 2025-11-20
-- Purpose: Track post-combination SPACs (de-SPACs) that should be included in analysis

-- Add is_post_combination column to filings table
ALTER TABLE filings
ADD COLUMN IF NOT EXISTS is_post_combination BOOLEAN NOT NULL DEFAULT FALSE;

-- Add index for post-combination queries
CREATE INDEX IF NOT EXISTS idx_filings_post_combination
ON filings(is_post_combination)
WHERE is_post_combination = TRUE;

-- Add index for SPAC queries (helpful for has_prior_spac_filing lookups)
CREATE INDEX IF NOT EXISTS idx_filings_spac_date
ON filings(cik, is_spac, filing_date)
WHERE is_spac = TRUE;

-- Add comment
COMMENT ON COLUMN filings.is_post_combination IS
'True if filing is a post-combination SPAC (de-SPAC) - operating company that went public via SPAC merger. These should be included in analysis despite having prior SPAC filings under same CIK.';

-- Example of post-combination SPAC:
-- Rover Group (pet sitting platform) - CIK 0001826018
--   - 2020: Filed as "Nebula Caravel Acquisition Corp" (SPAC)
--   - 2021: Filed as "Rover Group, Inc." (post-combination, is_post_combination = TRUE)
