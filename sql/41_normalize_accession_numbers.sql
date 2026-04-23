-- Migration 41: Normalize filings.accession_number to the bare SEC token shape.
--
-- Context: a small set of rows (confirmed in production on 2026-04-22 for
-- PayPal 8-K filing_ids 1748–1751) were persisted with the full EDGAR index
-- path embedded in accession_number (e.g., "edgar/data/1633917/0001633917-23-000220.txt")
-- rather than the bare NNNNNNNNNN-NN-NNNNNN token. When the batch runner
-- hands those values to FilingFetcher._get_storage_dir the path-traversal
-- guard at src/filing_fetcher/filing_fetcher.py:109 rejects them and the
-- entire batch fails with
--   ValueError('Invalid accession number: contains path traversal characters')
--
-- The ingestion path (src/infra/db.upsert_filing) now normalizes incoming
-- values via src/infra/validation.normalize_sec_accession; this one-shot
-- backfill fixes any rows already stored with a malformed value.
--
-- Safe to re-run: idempotent. Rows that already match the canonical shape,
-- or that live in the synthetic "presentation:" / "transcript:" namespaces,
-- are untouched.

DO $$
DECLARE
    affected_count int;
BEGIN
    WITH updated AS (
        UPDATE filings
        SET accession_number = substring(accession_number FROM '\d{10}-\d{2}-\d{6}')
        WHERE accession_number IS NOT NULL
          AND accession_number !~ '^\d{10}-\d{2}-\d{6}$'
          AND accession_number NOT LIKE 'presentation:%'
          AND accession_number NOT LIKE 'transcript:%'
          AND substring(accession_number FROM '\d{10}-\d{2}-\d{6}') IS NOT NULL
        RETURNING filing_id
    )
    SELECT count(*) INTO affected_count FROM updated;

    RAISE NOTICE 'accession_number backfill: % row(s) normalized', affected_count;
END;
$$;
