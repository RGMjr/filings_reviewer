-- V2 Documents Transcript Column Migration
-- Version: 12
-- Date: 2026-02-28
-- Purpose: Add document-type-aware columns to v2_documents so the V2 layer
--          can identify the document type and transcript source without
--          joining back through filings.

-- Document type discriminator (sec_filing, earnings_call, investor_presentation)
ALTER TABLE v2_documents
    ADD COLUMN IF NOT EXISTS document_type VARCHAR(50) NOT NULL DEFAULT 'sec_filing';

-- Ticker symbol (denormalized from filings/companies for fast transcript queries)
ALTER TABLE v2_documents
    ADD COLUMN IF NOT EXISTS ticker VARCHAR(10);

-- Document date (earnings call date for transcripts; same as filing_date for SEC docs)
ALTER TABLE v2_documents
    ADD COLUMN IF NOT EXISTS document_date DATE;

-- Source identifier for transcript data (e.g., "fmp:financialmodelingprep.com")
ALTER TABLE v2_documents
    ADD COLUMN IF NOT EXISTS transcript_source VARCHAR(200);

-- Index to support filtering by document type
CREATE INDEX IF NOT EXISTS idx_v2_documents_document_type
    ON v2_documents(document_type);

-- Index to support filtering by ticker (for transcript dedup)
CREATE INDEX IF NOT EXISTS idx_v2_documents_ticker
    ON v2_documents(ticker) WHERE ticker IS NOT NULL;

-- Index for deduplication: (ticker, document_date) uniqueness check
CREATE INDEX IF NOT EXISTS idx_v2_documents_ticker_date
    ON v2_documents(ticker, document_date) WHERE ticker IS NOT NULL;

-- Comments
COMMENT ON COLUMN v2_documents.document_type IS
    'Document type: sec_filing (default), earnings_call, investor_presentation';

COMMENT ON COLUMN v2_documents.ticker IS
    'Stock ticker symbol (denormalized for transcript deduplication)';

COMMENT ON COLUMN v2_documents.document_date IS
    'Canonical document date (earnings call date for transcripts)';

COMMENT ON COLUMN v2_documents.transcript_source IS
    'Source system identifier for transcripts (e.g., fmp:financialmodelingprep.com)';
