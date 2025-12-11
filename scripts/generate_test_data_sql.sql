-- Generate synthetic test data for D3 manual testing
-- Run with: PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -f scripts/generate_test_data_sql.sql

-- Clear existing data
DELETE FROM review_decisions;
DELETE FROM review_candidates;
DELETE FROM source_segments;
DELETE FROM metric_values;
DELETE FROM filings;
DELETE FROM companies;

-- Insert test companies
INSERT INTO companies (cik, company_name, ticker, industry_code, created_at)
VALUES
    ('0001234567', 'CloudTech Solutions, Inc.', 'CLDT', '7372', NOW()),
    ('0001234568', 'DataFlow Analytics, Inc.', 'DFLW', '7373', NOW()),
    ('0001234569', 'NetworkHub Technologies, Inc.', 'NTWK', '7374', NOW()),
    ('0001234570', 'FinTech Innovations Corp.', 'FINT', '6211', NOW()),
    ('0001234571', 'E-Commerce Platform Inc.', 'ECPL', '5961', NOW());

-- Insert test filings (2 per company = 10 total)
INSERT INTO filings (
    company_id, cik, accession_number, form_type, filing_date,
    sec_html_url, is_in_scope_phase1, is_first_time_issuer, is_spac, created_at
)
SELECT
    c.company_id,
    c.cik,
    '0001193125-23-' || LPAD((ROW_NUMBER() OVER ())::TEXT, 6, '0'),
    'S-1',
    ('2023-03-15'::DATE + ((ROW_NUMBER() OVER () - 1) * 30 || ' days')::INTERVAL),
    'https://www.sec.gov/Archives/edgar/data/' || c.cik || '/test.html',
    TRUE,
    TRUE,
    FALSE,
    NOW()
FROM companies c
CROSS JOIN generate_series(1, 2) AS filing_num;

-- Insert test source segments
-- Segment 1: Active Customers (good example)
INSERT INTO source_segments (
    filing_id, segment_type, section_path, section_heading, sequence_index,
    raw_text, char_start_offset, char_end_offset, created_at
)
SELECT
    filing_id,
    'paragraph',
    'Item 1. Business > Overview',
    'Business Overview',
    1,
    'As of December 31, 2023, we had approximately 125,000 active customers. We define an active customer as any customer who has made a transaction with us in the trailing 12-month period. Our active customer base has grown by 45% year-over-year, driven primarily by improvements in our go-to-market strategy.',
    1000,
    1350,
    NOW()
FROM filings;

-- Segment 2: ARR (good example)
INSERT INTO source_segments (
    filing_id, segment_type, section_path, section_heading, sequence_index,
    raw_text, char_start_offset, char_end_offset, created_at
)
SELECT
    filing_id,
    'paragraph',
    'Item 1. Business > Metrics',
    'Business Metrics',
    2,
    'Annual Recurring Revenue (ARR) was $493 million as of December 31, 2023, up from $312 million in the prior year. We calculate ARR as the annualized value of all active subscription contracts at the end of the period, excluding one-time fees and professional services revenue.',
    2000,
    2320,
    NOW()
FROM filings;

-- Segment 3: NRR (good example)
INSERT INTO source_segments (
    filing_id, segment_type, section_path, section_heading, sequence_index,
    raw_text, char_start_offset, char_end_offset, created_at
)
SELECT
    filing_id,
    'paragraph',
    'Item 7. Management Discussion > KPIs',
    'Key Performance Indicators',
    3,
    'Our net revenue retention rate was 118% for the year ended December 31, 2023. We define net revenue retention as the percentage change in revenue from our existing customer base, including expansion, contraction, and churn.',
    3000,
    3240,
    NOW()
FROM filings;

-- Segment 4: CAC (table format)
INSERT INTO source_segments (
    filing_id, segment_type, section_path, section_heading, sequence_index,
    raw_text, char_start_offset, char_end_offset, created_at
)
SELECT
    filing_id,
    'table',
    'Item 7. Management Discussion > Metrics',
    'Operating Metrics',
    4,
    E'Customer Acquisition Cost\t$1,250\t$1,450\nAverage Contract Value\t$15,000\t$12,000\nPayback Period (months)\t10\t14',
    4000,
    4150,
    NOW()
FROM filings;

-- Segment 5: Gross Margin
INSERT INTO source_segments (
    filing_id, segment_type, section_path, section_heading, sequence_index,
    raw_text, char_start_offset, char_end_offset, created_at
)
SELECT
    filing_id,
    'paragraph',
    'Item 7. Management Discussion > Results',
    'Results of Operations',
    5,
    'Our gross margin was 72% for the year ended December 31, 2023, compared to 68% in the prior year. The improvement was primarily due to economies of scale in our infrastructure and improved pricing.',
    5000,
    5230,
    NOW()
FROM filings WHERE filing_id % 2 = 0; -- Only even filings

-- Insert test review candidates
-- Candidate 1: Active Customers
INSERT INTO review_candidates (
    filing_id, company_id, source_segment_id, char_position, context_text,
    raw_number_text, parsed_value, parsed_unit, triggering_keyword,
    keyword_distance, keyword_position, suggested_metric_id,
    suggestion_confidence, features, review_status, created_at
)
SELECT
    s.filing_id,
    f.company_id,
    s.source_segment_id,
    50,
    'As of December 31, 2023, we had approximately 125,000 active customers. We define an active customer as any customer who has made',
    '125,000',
    125000,
    'count',
    'active customers',
    15,
    'after',
    'active_customers',
    0.85,
    '{"keyword_distance": 15, "is_in_table": false, "contains_definition": true, "section_heading": "Business Overview"}'::jsonb,
    'pending',
    NOW()
FROM source_segments s
JOIN filings f ON s.filing_id = f.filing_id
WHERE s.section_heading = 'Business Overview';

-- Candidate 2: ARR
INSERT INTO review_candidates (
    filing_id, company_id, source_segment_id, char_position, context_text,
    raw_number_text, parsed_value, parsed_unit, triggering_keyword,
    keyword_distance, keyword_position, suggested_metric_id,
    suggestion_confidence, features, review_status, created_at
)
SELECT
    s.filing_id,
    f.company_id,
    s.source_segment_id,
    40,
    'Annual Recurring Revenue (ARR) was $493 million as of December 31, 2023, up from $312 million in the prior year. We calculate ARR as',
    '$493 million',
    493000000,
    'currency',
    'ARR',
    10,
    'after',
    'arr',
    0.90,
    '{"keyword_distance": 10, "is_in_table": false, "contains_definition": true, "section_heading": "Business Metrics"}'::jsonb,
    'pending',
    NOW()
FROM source_segments s
JOIN filings f ON s.filing_id = f.filing_id
WHERE s.section_heading = 'Business Metrics';

-- Candidate 3: NRR
INSERT INTO review_candidates (
    filing_id, company_id, source_segment_id, char_position, context_text,
    raw_number_text, parsed_value, parsed_unit, triggering_keyword,
    keyword_distance, keyword_position, suggested_metric_id,
    suggestion_confidence, features, review_status, created_at
)
SELECT
    s.filing_id,
    f.company_id,
    s.source_segment_id,
    30,
    'Our net revenue retention rate was 118% for the year ended December 31, 2023. We define net revenue retention as the percentage change',
    '118%',
    118,
    'percentage',
    'retention rate',
    10,
    'after',
    'nrr',
    0.88,
    '{"keyword_distance": 10, "is_in_table": false, "contains_definition": true, "section_heading": "Key Performance Indicators"}'::jsonb,
    'pending',
    NOW()
FROM source_segments s
JOIN filings f ON s.filing_id = f.filing_id
WHERE s.section_heading = 'Key Performance Indicators';

-- Candidate 4: CAC (from table)
INSERT INTO review_candidates (
    filing_id, company_id, source_segment_id, char_position, context_text,
    raw_number_text, parsed_value, parsed_unit, triggering_keyword,
    keyword_distance, keyword_position, suggested_metric_id,
    suggestion_confidence, features, review_status, created_at
)
SELECT
    s.filing_id,
    f.company_id,
    s.source_segment_id,
    25,
    'Customer Acquisition Cost $1,250 $1,450 Average Contract Value $15,000 $12,000 Payback Period (months) 10 14',
    '$1,250',
    1250,
    'currency',
    'Customer Acquisition Cost',
    5,
    'after',
    'cac',
    0.92,
    '{"keyword_distance": 5, "is_in_table": true, "contains_definition": false, "section_heading": "Operating Metrics"}'::jsonb,
    'pending',
    NOW()
FROM source_segments s
JOIN filings f ON s.filing_id = f.filing_id
WHERE s.section_heading = 'Operating Metrics';

-- Candidate 5: Gross Margin
INSERT INTO review_candidates (
    filing_id, company_id, source_segment_id, char_position, context_text,
    raw_number_text, parsed_value, parsed_unit, triggering_keyword,
    keyword_distance, keyword_position, suggested_metric_id,
    suggestion_confidence, features, review_status, created_at
)
SELECT
    s.filing_id,
    f.company_id,
    s.source_segment_id,
    20,
    'Our gross margin was 72% for the year ended December 31, 2023, compared to 68% in the prior year. The improvement was primarily due',
    '72%',
    72,
    'percentage',
    'gross margin',
    8,
    'after',
    'gross_margin',
    0.80,
    '{"keyword_distance": 8, "is_in_table": false, "contains_definition": false, "section_heading": "Results of Operations"}'::jsonb,
    'pending',
    NOW()
FROM source_segments s
JOIN filings f ON s.filing_id = f.filing_id
WHERE s.section_heading = 'Results of Operations';

-- Add some reviewed candidates to test filtering
-- Mark some candidates as reviewed in the first 2 filings
INSERT INTO review_decisions (candidate_id, decision, assigned_metric_id, review_time_seconds, created_at)
SELECT
    candidate_id,
    'accept',
    suggested_metric_id,
    FLOOR(RANDOM() * 60 + 30)::INT, -- Random review time 30-90 seconds
    NOW()
FROM review_candidates
WHERE filing_id IN (SELECT filing_id FROM filings ORDER BY filing_id LIMIT 2)
  AND candidate_id % 2 = 0; -- Accept half of them

-- Update candidate status to 'reviewed' for those with decisions
UPDATE review_candidates rc
SET review_status = 'reviewed'
WHERE EXISTS (
    SELECT 1 FROM review_decisions rd WHERE rd.candidate_id = rc.candidate_id
);

-- Display summary
SELECT
    'Companies' AS entity,
    COUNT(*)::TEXT AS count
FROM companies
UNION ALL
SELECT
    'Filings',
    COUNT(*)::TEXT
FROM filings
UNION ALL
SELECT
    'Source Segments',
    COUNT(*)::TEXT
FROM source_segments
UNION ALL
SELECT
    'Review Candidates (Total)',
    COUNT(*)::TEXT
FROM review_candidates
UNION ALL
SELECT
    'Review Candidates (Pending)',
    COUNT(*)::TEXT
FROM review_candidates
WHERE review_status = 'pending'
UNION ALL
SELECT
    'Review Candidates (Reviewed)',
    COUNT(*)::TEXT
FROM review_candidates
WHERE review_status = 'reviewed'
UNION ALL
SELECT
    'Review Decisions',
    COUNT(*)::TEXT
FROM review_decisions;
