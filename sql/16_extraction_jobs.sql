-- Migration 16: Extraction jobs table for cloud-triggered extraction
-- Provides DB-backed job queue for the extraction worker.

CREATE TABLE IF NOT EXISTS extraction_jobs (
    id              BIGSERIAL PRIMARY KEY,
    filing_id       INTEGER NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'complete', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error           TEXT
);

CREATE INDEX IF NOT EXISTS extraction_jobs_filing_id_idx ON extraction_jobs(filing_id);
CREATE INDEX IF NOT EXISTS extraction_jobs_status_idx ON extraction_jobs(status);
CREATE INDEX IF NOT EXISTS extraction_jobs_created_at_idx ON extraction_jobs(created_at);
