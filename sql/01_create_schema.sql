-- Customer Metrics Filings Analysis - Database Schema
-- Version: 0.1
-- Date: 2025-11-15

-- Drop tables if they exist (for development)
DROP TABLE IF EXISTS filings CASCADE;
DROP TABLE IF EXISTS companies CASCADE;

-- ============================================================================
-- TABLE: companies
-- ============================================================================
-- Grain: One row per issuer (company)
-- Purpose: Central reference for issuer metadata; allows multiple filings per company

CREATE TABLE companies (
    -- Primary key
    company_id BIGSERIAL PRIMARY KEY,

    -- External identifiers
    cik TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    ticker TEXT,

    -- Classification
    country_of_domicile TEXT,
    industry_code TEXT,
    industry_classification_source TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indices for companies
CREATE INDEX idx_companies_cik ON companies(cik);
CREATE INDEX idx_companies_ticker ON companies(ticker) WHERE ticker IS NOT NULL;

-- ============================================================================
-- TABLE: filings
-- ============================================================================
-- Grain: One row per SEC filing document in scope
-- Purpose: Represent each S-1 (and later 10-K) with classification flags and links to companies

CREATE TABLE filings (
    -- Primary key
    filing_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    cik TEXT NOT NULL,

    -- Filing identifiers
    accession_number TEXT NOT NULL,
    form_type TEXT NOT NULL,
    filing_date DATE NOT NULL,
    period_end_date DATE,

    -- URLs
    sec_html_url TEXT NOT NULL,
    sec_txt_url TEXT,

    -- Classification flags (Phase 1)
    is_in_scope_phase1 BOOLEAN NOT NULL DEFAULT FALSE,
    is_first_time_issuer BOOLEAN,
    is_spac BOOLEAN,
    offering_type TEXT,  -- 'primary', 'secondary', 'mixed'
    classification_method TEXT,  -- 'heuristic', 'manual_review', 'uncertain'

    -- Processing metadata
    processing_status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'fetched', 'processed', 'failed', etc.
    processing_notes TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT unique_company_accession UNIQUE (company_id, accession_number),
    CONSTRAINT check_form_type CHECK (form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A', '10-K', '10-K/A')),
    CONSTRAINT check_offering_type CHECK (offering_type IS NULL OR offering_type IN ('primary', 'secondary', 'mixed')),
    CONSTRAINT check_classification_method CHECK (classification_method IS NULL OR classification_method IN ('heuristic', 'manual_review', 'uncertain'))
);

-- Indices for filings
CREATE INDEX idx_filings_company_id ON filings(company_id);
CREATE INDEX idx_filings_cik ON filings(cik);
CREATE INDEX idx_filings_accession ON filings(accession_number);
CREATE INDEX idx_filings_filing_date ON filings(filing_date);
CREATE INDEX idx_filings_form_type ON filings(form_type);
CREATE INDEX idx_filings_scope_phase1 ON filings(is_in_scope_phase1) WHERE is_in_scope_phase1 = TRUE;
CREATE INDEX idx_filings_processing_status ON filings(processing_status);
CREATE INDEX idx_filings_scope_status ON filings(is_in_scope_phase1, processing_status, filing_date) WHERE is_in_scope_phase1 = TRUE;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE companies IS 'Central registry of issuers (companies). One row per CIK.';
COMMENT ON COLUMN companies.cik IS 'SEC Central Index Key - primary external identifier';
COMMENT ON COLUMN companies.company_name IS 'Official issuer name as shown in SEC filings';

COMMENT ON TABLE filings IS 'Registry of SEC filing documents in scope for analysis';
COMMENT ON COLUMN filings.is_in_scope_phase1 IS 'True if filing is in Phase 1 universe (S-1/F-1 first-time issuers, non-SPAC, non-secondary-only)';
COMMENT ON COLUMN filings.is_first_time_issuer IS 'True if this filing corresponds to company''s first public equity issuance';
COMMENT ON COLUMN filings.is_spac IS 'True if issuer is a SPAC (excluded from Phase 1)';
COMMENT ON COLUMN filings.offering_type IS 'Classification of offering: primary, secondary, or mixed';
COMMENT ON COLUMN filings.classification_method IS 'How classification flags were determined: heuristic, manual_review, or uncertain';
COMMENT ON COLUMN filings.processing_status IS 'Current processing state in pipeline: pending, fetched, processed, failed, etc.';
