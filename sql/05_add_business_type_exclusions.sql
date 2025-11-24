-- Migration: Add business type exclusion fields
-- Date: 2025-11-20
-- Purpose: Add fields to track investment vehicles and resource extraction companies

-- Add is_investment_vehicle field
ALTER TABLE filings
ADD COLUMN IF NOT EXISTS is_investment_vehicle BOOLEAN NOT NULL DEFAULT FALSE;

-- Add is_resource_extraction field
ALTER TABLE filings
ADD COLUMN IF NOT EXISTS is_resource_extraction BOOLEAN NOT NULL DEFAULT FALSE;

-- Create indexes for exclusion queries
CREATE INDEX IF NOT EXISTS idx_filings_investment_vehicle
ON filings(is_investment_vehicle)
WHERE is_investment_vehicle = TRUE;

CREATE INDEX IF NOT EXISTS idx_filings_resource_extraction
ON filings(is_resource_extraction)
WHERE is_resource_extraction = TRUE;

-- Add comments
COMMENT ON COLUMN filings.is_investment_vehicle IS
'True if company is an investment vehicle (ETF, REIT, closed-end fund) that does not have traditional customer metrics.';

COMMENT ON COLUMN filings.is_resource_extraction IS
'True if company is in resource extraction (oil, gas, mining) - commodity-focused businesses that report on reserves/production rather than customer metrics.';
