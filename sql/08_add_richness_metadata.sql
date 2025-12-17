-- ============================================================================
-- Migration: Add Richness Metadata to source_segments
-- Purpose: Enable goldmine section identification
-- Date: 2025-12-17
-- Prerequisite: G1 complete (SourceSegment dataclass has richness fields)
-- ============================================================================

-- === FORWARD MIGRATION ===
BEGIN;

-- ============================================================================
-- 1. Add richness metadata columns
-- ============================================================================
-- These columns enable goldmine detection by storing computed richness metrics
-- for each segment. Fields match SourceSegment dataclass (src/extraction/models.py).

ALTER TABLE source_segments
ADD COLUMN IF NOT EXISTS metric_density NUMERIC,
ADD COLUMN IF NOT EXISTS distinct_metric_count INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS contains_temporal_trend BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS contains_cohort_breakdown BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS image_count INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS richness_score NUMERIC;

-- ============================================================================
-- 2. Create indexes for goldmine queries
-- ============================================================================

-- Index for finding top goldmine segments per filing (ordered by richness score)
-- Partial index: only index segments that have been scored
CREATE INDEX IF NOT EXISTS idx_source_segments_richness
ON source_segments (filing_id, richness_score DESC NULLS LAST)
WHERE richness_score IS NOT NULL;

-- Index for finding segments with temporal trends or cohort breakdowns
-- Partial index: only index segments with these high-value flags
CREATE INDEX IF NOT EXISTS idx_source_segments_temporal_cohort
ON source_segments (filing_id)
WHERE contains_temporal_trend = TRUE OR contains_cohort_breakdown = TRUE;

-- ============================================================================
-- 3. Add column comments
-- ============================================================================

COMMENT ON COLUMN source_segments.metric_density IS 'Metrics per 100 characters of text - measures concentration of metric disclosures';
COMMENT ON COLUMN source_segments.distinct_metric_count IS 'Count of unique metric IDs detected in this segment';
COMMENT ON COLUMN source_segments.contains_temporal_trend IS 'True if segment discusses multiple time periods (indicates trend disclosure)';
COMMENT ON COLUMN source_segments.contains_cohort_breakdown IS 'True if segment contains cohort analysis patterns (high-value for retention analysis)';
COMMENT ON COLUMN source_segments.image_count IS 'Count of meaningful images/charts in segment (excludes decorative images)';
COMMENT ON COLUMN source_segments.richness_score IS 'Composite goldmine score 0-10 computed from density, trends, cohorts, and images';

COMMIT;

-- ============================================================================
-- === ROLLBACK (run separately if needed) ===
-- ============================================================================
-- Uncomment and run this section to revert the migration.
--
-- BEGIN;
--
-- -- Drop indexes first
-- DROP INDEX IF EXISTS idx_source_segments_richness;
-- DROP INDEX IF EXISTS idx_source_segments_temporal_cohort;
--
-- -- Drop columns
-- ALTER TABLE source_segments
-- DROP COLUMN IF EXISTS metric_density,
-- DROP COLUMN IF EXISTS distinct_metric_count,
-- DROP COLUMN IF EXISTS contains_temporal_trend,
-- DROP COLUMN IF EXISTS contains_cohort_breakdown,
-- DROP COLUMN IF EXISTS image_count,
-- DROP COLUMN IF EXISTS richness_score;
--
-- COMMIT;
-- ============================================================================

-- ============================================================================
-- NOTES:
--
-- For large tables in production, consider running index creation with CONCURRENTLY:
--   CREATE INDEX CONCURRENTLY idx_source_segments_richness ...
--
-- This allows concurrent reads/writes but requires running outside a transaction.
-- ============================================================================
