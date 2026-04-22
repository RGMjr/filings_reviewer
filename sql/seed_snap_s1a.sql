-- KNOWN_ISSUES #9: Snap Filing (ID 32/33) mislabeled data.
-- The row currently labeled "Snap" (CIK 0001644378) actually contains RMR Group Inc.
-- content. This seed (a) relabels that company row to its correct issuer name and
-- (b) registers the real Snap S-1/A so it can be fetched + extracted by the normal
-- pipeline. No CASCADE, no v2_* row destruction — the extracted RMR content stays
-- under the corrected label.
--
-- Apply against the LOCAL dev DB only:
--     DATABASE_URL="$TEST_DATABASE_URL" psql "$TEST_DATABASE_URL" \
--         -f sql/seed_snap_s1a.sql
--
-- Not registered in scripts/apply_migrations.py — this is a one-off data seed,
-- not a schema migration (same pattern as register_gold_standard_filings.sql).

-- 1. Relabel the existing row for CIK 0001644378 (was "Snap", actually RMR Group Inc.)
UPDATE companies
SET company_name = 'RMR Group Inc.'
WHERE cik = '0001644378'
  AND company_name = 'Snap';

-- 2. Register Snap Inc. (CIK 0001564408, S-1/A filed 2017-02-27)
INSERT INTO companies (cik, company_name)
VALUES ('0001564408', 'Snap Inc.')
ON CONFLICT (cik) DO NOTHING;

-- 3. Register the Snap S-1/A filing (primary doc confirmed 200 via SEC on 2026-04-21)
INSERT INTO filings (
    company_id, cik, accession_number, form_type, filing_date,
    period_end_date, sec_html_url, is_in_scope_phase1, processing_status
)
SELECT
    company_id,
    '0001564408',
    '0001193125-17-056992',
    'S-1/A',
    '2017-02-27',
    NULL,  -- not re-deriving fiscal year-end from the cover page in this seed
    'https://www.sec.gov/Archives/edgar/data/1564408/000119312517056992/d270216ds1a.htm',
    true,
    'pending'
FROM companies
WHERE cik = '0001564408'
ON CONFLICT (company_id, accession_number) DO NOTHING;

-- Verification
SELECT f.filing_id, c.company_name, f.cik, f.accession_number,
       f.form_type, f.filing_date, f.processing_status
FROM filings f
JOIN companies c ON f.company_id = c.company_id
WHERE f.cik IN ('0001644378', '0001564408')
ORDER BY f.filing_id;
