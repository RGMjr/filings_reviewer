-- ============================================================================
-- Migration 16: Add '8-K' to check_form_type constraint
-- ============================================================================
-- Migration 11 added the transcript/presentation document types but omitted
-- '8-K'. ingest_presentations.py inserts filings with form_type='8-K'
-- (investor presentations are filed as 8-K exhibits). Without this fix,
-- every presentation ingestion fails with a CHECK constraint violation.

ALTER TABLE filings
    DROP CONSTRAINT IF EXISTS check_form_type;

ALTER TABLE filings
    ADD CONSTRAINT check_form_type CHECK (
        form_type IN (
            'S-1', 'S-1/A', 'F-1', 'F-1/A', '10-K', '10-K/A', '8-K',
            'earnings_call', 'investor_presentation'
        )
    );
