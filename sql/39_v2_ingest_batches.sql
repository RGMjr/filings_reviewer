-- 39_v2_ingest_batches.sql
-- Adds two tables for the web-UI batch ingestion feature.
-- v2_ingest_batches tracks each onboarding/populate batch submitted by a reviewer.
-- v2_ingest_batch_filings tracks per-filing state within a batch (queued → persisted/failed/skipped).

CREATE TABLE v2_ingest_batches (
  batch_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            TEXT        NOT NULL CHECK (kind IN ('onboard', 'populate')),
  reviewer_id     TEXT        NOT NULL,
  criteria        JSONB       NOT NULL,       -- raw user-submitted criteria
  resolved_query  JSONB       NOT NULL,       -- expanded SIC/form/year
  limits          JSONB       NOT NULL,       -- volume band, thresholds snapshot
  total_filings   INT,
  status          TEXT        NOT NULL CHECK (status IN ('queued','running','complete','failed','cancelled')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ,
  cancelled_at    TIMESTAMPTZ,
  run_lock_until  TIMESTAMPTZ,
  error           TEXT
);

CREATE INDEX idx_v2_ingest_batches_status ON v2_ingest_batches(status);

CREATE TABLE v2_ingest_batch_filings (
  batch_id        UUID    NOT NULL REFERENCES v2_ingest_batches(batch_id) ON DELETE CASCADE,
  filing_id       BIGINT  NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
  initial_bucket  TEXT    NOT NULL CHECK (initial_bucket IN ('new','reextract','reextract_reviewed')),
  current_status  TEXT    NOT NULL CHECK (current_status IN ('queued','fetching','extracting','persisted','failed','skipped','cancelled')),
  fact_count      INT,
  error           TEXT,
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ,
  PRIMARY KEY (batch_id, filing_id)
);

CREATE INDEX idx_v2_ingest_batch_filings_status ON v2_ingest_batch_filings(batch_id, current_status);
