-- ============================================================================
-- Migration: Create Image Review Schema
-- Purpose: Create tables for human-in-the-loop image classification in filings
-- Date: 2026-01-13
-- Task: IMG-1-1
-- Based on: /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
-- ============================================================================

-- Drop tables if they exist (for development)
DROP TABLE IF EXISTS image_review_decisions CASCADE;
DROP TABLE IF EXISTS image_review_candidates CASCADE;

-- ============================================================================
-- TABLE: image_review_candidates
-- ============================================================================
-- Grain: One row per chart image candidate awaiting human review
-- Purpose: Store potential chart images with context for human classification

CREATE TABLE image_review_candidates (
    -- Primary key
    image_candidate_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    source_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,

    -- Image identification
    image_src TEXT NOT NULL,  -- Image filename (e.g., 'mdaa2.jpg')
    image_url TEXT NOT NULL,  -- Full SEC URL to image

    -- Image metadata
    image_width INT,  -- Width in pixels (NULL if unknown)
    image_height INT,  -- Height in pixels (NULL if unknown)
    image_alt TEXT,  -- Alt text from HTML

    -- Context for classification
    preceding_text TEXT,  -- Text immediately before image in filing
    detected_keywords TEXT[],  -- Keywords found near image (e.g., {'cohort', 'retention'})

    -- Discovery metadata (from cohort chart detection)
    cohort_keyword_nearby BOOLEAN,  -- True if 'cohort' keyword found within 1500 chars
    image_index INT,  -- Position of image in filing (1-indexed)

    -- Scoring and classification
    cohort_confidence NUMERIC(3,2),  -- 0.00-1.00 confidence score
    is_decorative BOOLEAN,  -- True if likely decorative (logo, icon, bullet)

    -- Pattern learning
    detection_tier TEXT,  -- How this candidate was discovered

    -- Status
    review_status TEXT NOT NULL DEFAULT 'pending',

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_detection_tier CHECK (
        detection_tier IS NULL OR
        detection_tier IN ('tier_1_cohort', 'tier_2_large', 'tier_3_all', 'seed_list')
    ),
    CONSTRAINT check_review_status CHECK (
        review_status IN ('pending', 'reviewed', 'skipped')
    ),
    CONSTRAINT check_cohort_confidence CHECK (
        cohort_confidence IS NULL OR (cohort_confidence >= 0 AND cohort_confidence <= 1)
    ),
    -- Unique constraint: One image per filing (identified by src path)
    CONSTRAINT uq_image_review_candidates_filing_src UNIQUE (filing_id, image_src)
);

-- Indices
CREATE INDEX idx_image_candidates_filing ON image_review_candidates(filing_id);
CREATE INDEX idx_image_candidates_company ON image_review_candidates(company_id);
CREATE INDEX idx_image_candidates_segment ON image_review_candidates(source_segment_id) WHERE source_segment_id IS NOT NULL;
CREATE INDEX idx_image_candidates_status ON image_review_candidates(review_status);
CREATE INDEX idx_image_candidates_tier ON image_review_candidates(detection_tier) WHERE detection_tier IS NOT NULL;
CREATE INDEX idx_image_candidates_pending ON image_review_candidates(filing_id, review_status) WHERE review_status = 'pending';
CREATE INDEX idx_image_candidates_cohort ON image_review_candidates(cohort_keyword_nearby) WHERE cohort_keyword_nearby = true;

-- Comments
COMMENT ON TABLE image_review_candidates IS 'Chart image candidates in SEC filings awaiting human classification (cohort charts, revenue visualizations)';
COMMENT ON COLUMN image_review_candidates.image_src IS 'Image filename as found in HTML (e.g., ''mdaa2.jpg'')';
COMMENT ON COLUMN image_review_candidates.image_url IS 'Full SEC EDGAR URL to the image file';
COMMENT ON COLUMN image_review_candidates.preceding_text IS 'Text immediately before the image for context (typically 50-100 chars)';
COMMENT ON COLUMN image_review_candidates.detected_keywords IS 'Array of keywords found near image (e.g., cohort, retention, revenue)';
COMMENT ON COLUMN image_review_candidates.cohort_keyword_nearby IS 'True if ''cohort'' keyword detected within 1500 characters of image';
COMMENT ON COLUMN image_review_candidates.image_index IS 'Position of this image within the filing (1 = first image)';
COMMENT ON COLUMN image_review_candidates.cohort_confidence IS 'Confidence score (0-1) that image is a relevant chart based on heuristics';
COMMENT ON COLUMN image_review_candidates.is_decorative IS 'True if image is likely decorative (logo, icon, bullet) based on size/naming';
COMMENT ON COLUMN image_review_candidates.detection_tier IS 'Discovery method: tier_1_cohort (high confidence), tier_2_large (size-based), tier_3_all (all images), seed_list (manual)';
COMMENT ON COLUMN image_review_candidates.review_status IS 'Review status: pending (awaiting review), reviewed (decision made), skipped (intentionally skipped)';

-- ============================================================================
-- TABLE: image_review_decisions
-- ============================================================================
-- Grain: One row per human review decision on an image candidate
-- Purpose: Record human judgments on chart image classification

CREATE TABLE image_review_decisions (
    -- Primary key
    image_decision_id BIGSERIAL PRIMARY KEY,

    -- Foreign key (one decision per candidate)
    image_candidate_id BIGINT NOT NULL UNIQUE REFERENCES image_review_candidates(image_candidate_id) ON DELETE CASCADE,

    -- Decision
    decision TEXT NOT NULL,  -- 'relevant' or 'not_relevant'

    -- Chart type (required if decision = 'relevant')
    chart_type TEXT,

    -- Rejection reason (required if decision = 'not_relevant')
    rejection_reason TEXT,

    -- Review metadata
    reviewer_id TEXT,  -- Identifier for the reviewer
    reviewer_notes TEXT,  -- Optional notes from reviewer
    review_time_seconds INT,  -- Time spent on this decision

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_decision CHECK (
        decision IN ('relevant', 'not_relevant')
    ),
    CONSTRAINT check_chart_type CHECK (
        chart_type IS NULL OR
        chart_type IN ('cohort_table', 'cohort_heatmap', 'line_chart', 'bar_chart', 'stacked_bar', 'other_chart', 'mixed')
    ),
    CONSTRAINT check_rejection_reason CHECK (
        rejection_reason IS NULL OR
        rejection_reason IN ('decorative', 'not_a_chart', 'wrong_subject', 'duplicate', 'unreadable', 'other')
    ),
    -- If relevant, chart_type is required
    CONSTRAINT check_relevant_has_chart_type CHECK (
        decision != 'relevant' OR chart_type IS NOT NULL
    ),
    -- If not_relevant, rejection_reason is required
    CONSTRAINT check_not_relevant_has_reason CHECK (
        decision != 'not_relevant' OR rejection_reason IS NOT NULL
    )
);

-- Indices
-- Note: No index needed on image_candidate_id - UNIQUE constraint creates one automatically
CREATE INDEX idx_image_decisions_decision ON image_review_decisions(decision);
CREATE INDEX idx_image_decisions_chart_type ON image_review_decisions(chart_type) WHERE chart_type IS NOT NULL;
CREATE INDEX idx_image_decisions_rejection ON image_review_decisions(rejection_reason) WHERE rejection_reason IS NOT NULL;
CREATE INDEX idx_image_decisions_created ON image_review_decisions(created_at);
CREATE INDEX idx_image_decisions_reviewer ON image_review_decisions(reviewer_id) WHERE reviewer_id IS NOT NULL;

-- Comments
COMMENT ON TABLE image_review_decisions IS 'Human classification decisions on chart image candidates for pattern learning';
COMMENT ON COLUMN image_review_decisions.decision IS 'Classification decision: relevant (chart with useful data) or not_relevant (skip)';
COMMENT ON COLUMN image_review_decisions.chart_type IS 'Type of chart if relevant: cohort_table, cohort_heatmap, line_chart, bar_chart, stacked_bar, other_chart, mixed';
COMMENT ON COLUMN image_review_decisions.rejection_reason IS 'Reason for not_relevant: decorative, not_a_chart, wrong_subject, duplicate, unreadable, other';
COMMENT ON COLUMN image_review_decisions.reviewer_id IS 'Identifier for who made this decision (username, email) for multi-user tracking';
COMMENT ON COLUMN image_review_decisions.review_time_seconds IS 'Time spent reviewing this image (for workload analysis)';

-- ============================================================================
-- VIEWS for analysis
-- ============================================================================

-- View: Image review progress by filing
CREATE OR REPLACE VIEW v_image_review_progress_by_filing AS
SELECT
    irc.filing_id,
    f.accession_number,
    c.company_name,
    COUNT(*) AS total_images,
    COUNT(*) FILTER (WHERE irc.review_status = 'reviewed') AS reviewed_count,
    COUNT(*) FILTER (WHERE irc.review_status = 'pending') AS pending_count,
    COUNT(*) FILTER (WHERE irc.review_status = 'skipped') AS skipped_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE irc.review_status = 'reviewed') / NULLIF(COUNT(*), 0), 1) AS review_pct
FROM image_review_candidates irc
JOIN filings f ON irc.filing_id = f.filing_id
JOIN companies c ON irc.company_id = c.company_id
GROUP BY irc.filing_id, f.accession_number, c.company_name
ORDER BY pending_count DESC;

COMMENT ON VIEW v_image_review_progress_by_filing IS 'Image review progress summary by filing';

-- View: Decision statistics by detection tier (for pattern learning)
CREATE OR REPLACE VIEW v_image_decision_stats_by_tier AS
SELECT
    COALESCE(irc.detection_tier, 'unknown') AS detection_tier,
    ird.decision,
    COUNT(*) AS decision_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY COALESCE(irc.detection_tier, 'unknown')), 1) AS pct_of_tier
FROM image_review_decisions ird
JOIN image_review_candidates irc ON ird.image_candidate_id = irc.image_candidate_id
GROUP BY COALESCE(irc.detection_tier, 'unknown'), ird.decision
ORDER BY detection_tier, decision;

COMMENT ON VIEW v_image_decision_stats_by_tier IS 'Decision distribution by detection tier (for evaluating tier effectiveness)';

-- View: Chart type distribution for relevant images
CREATE OR REPLACE VIEW v_image_chart_type_distribution AS
SELECT
    ird.chart_type,
    COUNT(*) AS chart_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_relevant
FROM image_review_decisions ird
WHERE ird.decision = 'relevant' AND ird.chart_type IS NOT NULL
GROUP BY ird.chart_type
ORDER BY chart_count DESC;

COMMENT ON VIEW v_image_chart_type_distribution IS 'Distribution of chart types among relevant images';

-- View: Rejection reason summary
CREATE OR REPLACE VIEW v_image_rejection_reasons AS
SELECT
    COALESCE(irc.detection_tier, 'unknown') AS detection_tier,
    ird.rejection_reason,
    COUNT(*) AS rejection_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY COALESCE(irc.detection_tier, 'unknown')), 1) AS pct_of_tier_rejections
FROM image_review_decisions ird
JOIN image_review_candidates irc ON ird.image_candidate_id = irc.image_candidate_id
WHERE ird.decision = 'not_relevant'
GROUP BY COALESCE(irc.detection_tier, 'unknown'), ird.rejection_reason
ORDER BY detection_tier, rejection_count DESC;

COMMENT ON VIEW v_image_rejection_reasons IS 'Rejection patterns by tier for identifying systematic false positives';

-- ============================================================================
-- TRIGGERS for updated_at
-- ============================================================================

-- Reuse existing update_updated_at_column() function if it exists
-- Function definition (only create if not exists)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for image_review_candidates
DROP TRIGGER IF EXISTS trigger_image_review_candidates_updated_at ON image_review_candidates;
CREATE TRIGGER trigger_image_review_candidates_updated_at
    BEFORE UPDATE ON image_review_candidates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- End of migration
-- ============================================================================
