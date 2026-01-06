-- ============================================================================
-- Migration: Add Suppressed Candidates Table and Unique Indexes
-- Purpose: Prevent duplicate review candidates and capture suppressed alternatives
-- Date: 2026-01-06
-- Task: DUP-1
-- ============================================================================

-- ============================================================================
-- UNIQUE INDEXES on review_candidates
-- ============================================================================
-- Prevent duplicate candidates for the same (filing, segment, position, metric)
-- PostgreSQL treats NULLs as distinct, so we need two partial indexes:
--   1. For candidates WITH source_segment_id (most common case)
--   2. For candidates WITHOUT source_segment_id (16 of 349 candidates)

-- Drop existing indexes if they exist (idempotent)
DROP INDEX IF EXISTS uq_review_candidates_with_segment;
DROP INDEX IF EXISTS uq_review_candidates_without_segment;

-- Index 1: Candidates with source_segment_id (non-NULL)
-- Key: (filing_id, source_segment_id, char_position, suggested_metric_id)
-- Note: triggering_keyword excluded - best candidate wins regardless of keyword
CREATE UNIQUE INDEX uq_review_candidates_with_segment
ON review_candidates (filing_id, source_segment_id, char_position, suggested_metric_id)
WHERE source_segment_id IS NOT NULL;

COMMENT ON INDEX uq_review_candidates_with_segment IS
    'Prevents duplicate candidates for same (filing, segment, position, metric) when segment is known';

-- Index 2: Candidates without source_segment_id (NULL)
-- Key: (filing_id, char_position, suggested_metric_id)
-- Uses document-level char_position as alternative to segment_id
CREATE UNIQUE INDEX uq_review_candidates_without_segment
ON review_candidates (filing_id, char_position, suggested_metric_id)
WHERE source_segment_id IS NULL;

COMMENT ON INDEX uq_review_candidates_without_segment IS
    'Prevents duplicate candidates for same (filing, position, metric) when segment is unknown';

-- ============================================================================
-- TABLE: suppressed_candidates
-- ============================================================================
-- Grain: One row per suppressed alternative candidate
-- Purpose: Capture alternatives that were not selected as the best candidate
--          for pattern learning when human reclassification reveals our
--          confidence scoring was wrong
--
-- Use cases:
--   1. When multiple candidates at same position, only highest confidence is kept
--   2. Cross-sentence matches suppressed in favor of same-sentence matches
--   3. Duplicate execution detection (running candidate gen twice)

DROP TABLE IF EXISTS suppressed_candidates CASCADE;

CREATE TABLE suppressed_candidates (
    -- Primary key
    suppressed_id BIGSERIAL PRIMARY KEY,

    -- =========================================================================
    -- COPIED FIELDS FROM review_candidates
    -- All fields from the suppressed candidate are preserved for learning
    -- =========================================================================

    -- Foreign keys (same as review_candidates)
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    source_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,

    -- Location and context (same as review_candidates)
    char_position INT NOT NULL,
    context_text TEXT NOT NULL,
    raw_number_text TEXT NOT NULL,
    parsed_value NUMERIC,
    parsed_unit TEXT,

    -- Keyword match info (same as review_candidates)
    triggering_keyword TEXT NOT NULL,
    keyword_distance INT NOT NULL,
    keyword_position TEXT NOT NULL,

    -- Classification (same as review_candidates)
    suggested_metric_id TEXT,
    suggestion_confidence NUMERIC,
    features JSONB,

    -- =========================================================================
    -- SUPPRESSION-SPECIFIC FIELDS
    -- =========================================================================

    -- Link to the winning candidate (nullable in case winner is deleted)
    winner_candidate_id BIGINT REFERENCES review_candidates(candidate_id) ON DELETE SET NULL,

    -- Why this candidate was suppressed
    suppression_reason TEXT NOT NULL,

    -- Winner's confidence at the time of suppression (for comparison)
    winner_confidence NUMERIC,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),

    -- =========================================================================
    -- CONSTRAINTS
    -- =========================================================================

    -- Validate keyword_position matches review_candidates constraint
    CONSTRAINT check_suppressed_keyword_position
        CHECK (keyword_position IN ('before', 'after')),

    -- Validate suppression_reason is one of known values
    CONSTRAINT check_suppression_reason
        CHECK (suppression_reason IN (
            'lower_confidence',    -- Lost confidence comparison at same position
            'cross_sentence',      -- Same-sentence match preferred over cross-sentence
            'duplicate_execution'  -- Candidate gen was run twice
        )),

    -- Validate confidence score range (same as review_candidates)
    CONSTRAINT check_suppressed_confidence
        CHECK (suggestion_confidence IS NULL OR
               (suggestion_confidence >= 0 AND suggestion_confidence <= 1)),

    -- Validate winner_confidence range
    CONSTRAINT check_winner_confidence
        CHECK (winner_confidence IS NULL OR
               (winner_confidence >= 0 AND winner_confidence <= 1))
);

-- ============================================================================
-- INDEXES for suppressed_candidates
-- ============================================================================

-- Index for finding suppressed alternatives for a winning candidate
CREATE INDEX idx_suppressed_by_winner
ON suppressed_candidates(winner_candidate_id)
WHERE winner_candidate_id IS NOT NULL;

-- Index for learning queries by filing
CREATE INDEX idx_suppressed_by_filing
ON suppressed_candidates(filing_id);

-- Index for learning queries by metric
CREATE INDEX idx_suppressed_by_metric
ON suppressed_candidates(suggested_metric_id)
WHERE suggested_metric_id IS NOT NULL;

-- Index for analyzing suppression patterns
CREATE INDEX idx_suppressed_by_reason
ON suppressed_candidates(suppression_reason);

-- Index for confidence comparison analysis
CREATE INDEX idx_suppressed_confidence_comparison
ON suppressed_candidates(suggestion_confidence, winner_confidence)
WHERE suggestion_confidence IS NOT NULL AND winner_confidence IS NOT NULL;

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE suppressed_candidates IS
    'Candidates that were not selected as best match, preserved for pattern learning';

COMMENT ON COLUMN suppressed_candidates.winner_candidate_id IS
    'The candidate that was selected over this one (NULL if winner deleted)';

COMMENT ON COLUMN suppressed_candidates.suppression_reason IS
    'Why suppressed: lower_confidence (lost comparison), cross_sentence (same-sentence preferred), duplicate_execution (script run twice)';

COMMENT ON COLUMN suppressed_candidates.winner_confidence IS
    'Winner confidence at suppression time (preserved even if winner later updated)';

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify unique indexes were created
DO $$
DECLARE
    idx_count INT;
BEGIN
    SELECT COUNT(*) INTO idx_count
    FROM pg_indexes
    WHERE tablename = 'review_candidates'
      AND indexname LIKE 'uq_review_candidates_%';

    IF idx_count != 2 THEN
        RAISE EXCEPTION 'Expected 2 unique indexes on review_candidates, found %', idx_count;
    END IF;

    RAISE NOTICE 'Verified: 2 unique indexes created on review_candidates';
END $$;

-- Verify suppressed_candidates table was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'suppressed_candidates'
    ) THEN
        RAISE EXCEPTION 'suppressed_candidates table was not created';
    END IF;

    RAISE NOTICE 'Verified: suppressed_candidates table created';
END $$;

-- Verify all expected columns exist
DO $$
DECLARE
    expected_cols TEXT[] := ARRAY[
        'suppressed_id', 'filing_id', 'company_id', 'source_segment_id',
        'char_position', 'context_text', 'raw_number_text', 'parsed_value',
        'parsed_unit', 'triggering_keyword', 'keyword_distance', 'keyword_position',
        'suggested_metric_id', 'suggestion_confidence', 'features',
        'winner_candidate_id', 'suppression_reason', 'winner_confidence', 'created_at'
    ];
    col TEXT;
    missing_cols TEXT[] := ARRAY[]::TEXT[];
BEGIN
    FOREACH col IN ARRAY expected_cols LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'suppressed_candidates' AND column_name = col
        ) THEN
            missing_cols := array_append(missing_cols, col);
        END IF;
    END LOOP;

    IF array_length(missing_cols, 1) > 0 THEN
        RAISE EXCEPTION 'Missing columns in suppressed_candidates: %', missing_cols;
    END IF;

    RAISE NOTICE 'Verified: All 19 expected columns present in suppressed_candidates';
END $$;

-- Print summary
DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Migration 08_add_suppressed_candidates.sql completed successfully';
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Created:';
    RAISE NOTICE '  - UNIQUE INDEX uq_review_candidates_with_segment';
    RAISE NOTICE '  - UNIQUE INDEX uq_review_candidates_without_segment';
    RAISE NOTICE '  - TABLE suppressed_candidates (19 columns, 5 indexes)';
    RAISE NOTICE '============================================================';
END $$;
