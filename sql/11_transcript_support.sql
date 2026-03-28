-- Transcript Support Schema Migration
-- Version: 11
-- Date: 2026-02-16
-- Purpose: Enable earnings call transcripts and investor presentations
--          alongside SEC filings in the same database schema.

-- ============================================================================
-- 1. Add document-type columns to filings
-- ============================================================================

-- Document type discriminator (sec_filing, earnings_call, investor_presentation)
ALTER TABLE filings
    ADD COLUMN IF NOT EXISTS document_type TEXT NOT NULL DEFAULT 'sec_filing';

-- Ticker (denormalized from companies for transcript lookups)
-- Companies table already has ticker, but transcripts may not have a company_id yet
ALTER TABLE filings
    ADD COLUMN IF NOT EXISTS ticker TEXT;

-- Document date (for transcripts: the earnings call date, distinct from filing_date)
ALTER TABLE filings
    ADD COLUMN IF NOT EXISTS document_date DATE;

-- Source identifier for transcripts (e.g., "huggingface:kurry/sp500_earnings_transcripts")
ALTER TABLE filings
    ADD COLUMN IF NOT EXISTS transcript_source TEXT;

-- ============================================================================
-- 2. Relax NOT NULL constraints for non-SEC documents
-- ============================================================================
-- SEC filings require cik, accession_number, sec_html_url.
-- Transcripts may not have these fields.

ALTER TABLE filings
    ALTER COLUMN cik DROP NOT NULL;

ALTER TABLE filings
    ALTER COLUMN accession_number DROP NOT NULL;

ALTER TABLE filings
    ALTER COLUMN sec_html_url DROP NOT NULL;

-- ============================================================================
-- 3. Update form_type constraint to include new document types
-- ============================================================================

ALTER TABLE filings
    DROP CONSTRAINT IF EXISTS check_form_type;

ALTER TABLE filings
    ADD CONSTRAINT check_form_type CHECK (
        form_type IN (
            'S-1', 'S-1/A', 'F-1', 'F-1/A', '10-K', '10-K/A',
            'earnings_call', 'investor_presentation'
        )
    );

-- ============================================================================
-- 4. Add unique index on companies.ticker (for transcript company matching)
-- ============================================================================

-- Only create if not already present (companies table may already have idx_companies_ticker)
-- Using CREATE INDEX IF NOT EXISTS for safety
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_ticker_unique
    ON companies(ticker) WHERE ticker IS NOT NULL;

-- ============================================================================
-- 5. Add index on filings.document_type for filtering
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_filings_document_type
    ON filings(document_type);

CREATE INDEX IF NOT EXISTS idx_filings_ticker
    ON filings(ticker) WHERE ticker IS NOT NULL;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON COLUMN filings.document_type IS
    'Document type: sec_filing (default), earnings_call, investor_presentation';

COMMENT ON COLUMN filings.ticker IS
    'Stock ticker symbol (denormalized for transcript matching)';

COMMENT ON COLUMN filings.document_date IS
    'Document date (for transcripts: earnings call date; for SEC: same as filing_date)';

COMMENT ON COLUMN filings.transcript_source IS
    'Source identifier for transcript data (e.g., huggingface dataset name)';
