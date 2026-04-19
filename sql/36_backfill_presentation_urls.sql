-- Migration 36: Backfill cik + sec_html_url for investor-presentation filings.
--
-- Context: scripts/ingest_presentations.py inserts rows with cik=NULL and
-- sec_html_url=NULL, encoding the SEC location inside accession_number as
-- "presentation:<cik>/<accession>/<filename>". This broke the review UI's
-- "View source" link (hidden when sec_filing_url is None) and the image-cache
-- proxy URL (which relies on a clean cik + dash-stripped accession).
--
-- This migration extracts the embedded cik/accession/filename from the
-- accession_number, populates filings.cik (keeping leading zeros for
-- consistency with other rows), and builds the real SEC EDGAR file URL.
--
-- Format assumption: 166/166 rows verified to match
--   ^presentation:[0-9]+/[0-9]+-[0-9]+-[0-9]+/[^/]+$
-- on 2026-04-19. Idempotent: guarded by NULL check + WHERE clause.

UPDATE filings
SET cik = split_part(substring(accession_number FROM 14), '/', 1),
    sec_html_url = 'https://www.sec.gov/Archives/edgar/data/'
      || ltrim(split_part(substring(accession_number FROM 14), '/', 1), '0')
      || '/'
      || replace(split_part(substring(accession_number FROM 14), '/', 2), '-', '')
      || '/'
      || split_part(substring(accession_number FROM 14), '/', 3)
WHERE document_type = 'investor_presentation'
  AND accession_number LIKE 'presentation:%'
  AND (cik IS NULL OR sec_html_url IS NULL OR sec_html_url = '');
