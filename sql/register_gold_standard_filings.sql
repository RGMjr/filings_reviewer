-- Register Farfetch and Snowflake in the DB for V2 batch extraction.
-- The batch script falls back to data/gold_standard/<company_slug>/filing.html
-- when html_storage_path is NULL, using company_name.replace(" ", "_") as the slug.
-- Company names below are chosen so the slug matches the existing directory names:
--   Farfetch Limited  -> Farfetch_Limited  -> data/gold_standard/Farfetch_Limited/filing.html
--   Snowflake Inc     -> Snowflake_Inc     -> data/gold_standard/Snowflake_Inc/filing.html

-- Farfetch Limited (F-1, filed 2018; foreign private issuer)
INSERT INTO companies (cik, company_name)
VALUES ('0001740915', 'Farfetch Limited')
ON CONFLICT (cik) DO NOTHING;

INSERT INTO filings (
    company_id, cik, accession_number, form_type, filing_date,
    period_end_date, sec_html_url, is_in_scope_phase1, processing_status
)
SELECT
    company_id,
    '0001740915',
    '0001193125-18-267302',
    'F-1',
    '2018-09-21',
    '2017-12-31',
    'https://www.sec.gov/Archives/edgar/data/1740915/000119312518267302/filing-main.htm',
    true,
    'pending'
FROM companies WHERE cik = '0001740915'
ON CONFLICT (company_id, accession_number) DO NOTHING;

-- Snowflake Inc (S-1/A, filed 2020)
INSERT INTO companies (cik, company_name)
VALUES ('0001640147', 'Snowflake Inc')
ON CONFLICT (cik) DO NOTHING;

INSERT INTO filings (
    company_id, cik, accession_number, form_type, filing_date,
    period_end_date, sec_html_url, is_in_scope_phase1, processing_status
)
SELECT
    company_id,
    '0001640147',
    '0001628280-20-013518',
    'S-1',
    '2020-09-16',
    '2020-01-31',
    'https://www.sec.gov/Archives/edgar/data/1640147/000162828020013518/snowflakes-1a2.htm',
    true,
    'pending'
FROM companies WHERE cik = '0001640147'
ON CONFLICT (company_id, accession_number) DO NOTHING;

-- Verify
SELECT f.filing_id, c.company_name, f.form_type, f.filing_date, f.html_storage_path
FROM filings f
JOIN companies c ON f.company_id = c.company_id
ORDER BY f.filing_id;
