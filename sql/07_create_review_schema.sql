-- ============================================================================
-- Migration: Create Human Review Schema
-- Purpose: Create tables for human-in-the-loop metric extraction review
-- Date: 2025-12-09
-- Based on: docs/HUMAN_REVIEW_SYSTEM_PLAN.md
-- ============================================================================

-- Drop tables if they exist (for development)
DROP TABLE IF EXISTS learned_patterns CASCADE;
DROP TABLE IF EXISTS review_decisions CASCADE;
DROP TABLE IF EXISTS review_candidates CASCADE;

-- ============================================================================
-- TABLE: review_candidates
-- ============================================================================
-- Grain: One row per candidate metric extraction awaiting human review
-- Purpose: Store potential metric extractions with context for human validation

CREATE TABLE review_candidates (
    -- Primary key
    candidate_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    source_segment_id BIGINT REFERENCES source_segments(source_segment_id) ON DELETE SET NULL,

    -- Location and context
    char_position INT NOT NULL,  -- Character position of number in segment
    context_text TEXT NOT NULL,  -- 30-50 words each direction from number
    raw_number_text TEXT NOT NULL,  -- The exact number string found
    parsed_value NUMERIC,  -- Parsed numeric value
    parsed_unit TEXT,  -- Detected unit (count, %, usd, etc.)

    -- Keyword match info
    triggering_keyword TEXT NOT NULL,  -- The keyword that triggered this candidate
    keyword_distance INT NOT NULL,  -- Characters from number to keyword
    keyword_position TEXT NOT NULL,  -- 'before' or 'after' the number

    -- Classification
    suggested_metric_id TEXT,  -- Initial suggested metric ID
    suggestion_confidence NUMERIC,  -- 0-1 confidence score
    features JSONB,  -- ML features for pattern learning

    -- Status
    review_status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'in_progress', 'reviewed', 'skipped'
    review_batch_id INT,  -- Groups candidates for batch review

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_keyword_position CHECK (keyword_position IN ('before', 'after')),
    CONSTRAINT check_review_status CHECK (review_status IN ('pending', 'in_progress', 'reviewed', 'skipped')),
    CONSTRAINT check_confidence CHECK (suggestion_confidence IS NULL OR (suggestion_confidence >= 0 AND suggestion_confidence <= 1))
);

-- Indices
CREATE INDEX idx_review_candidates_filing ON review_candidates(filing_id);
CREATE INDEX idx_review_candidates_company ON review_candidates(company_id);
CREATE INDEX idx_review_candidates_status ON review_candidates(review_status);
CREATE INDEX idx_review_candidates_batch ON review_candidates(review_batch_id) WHERE review_batch_id IS NOT NULL;
CREATE INDEX idx_review_candidates_pending ON review_candidates(filing_id, review_status) WHERE review_status = 'pending';
CREATE INDEX idx_review_candidates_metric ON review_candidates(suggested_metric_id) WHERE suggested_metric_id IS NOT NULL;

-- Comments
COMMENT ON TABLE review_candidates IS 'Candidate metric extractions awaiting human review (high-recall detection)';
COMMENT ON COLUMN review_candidates.context_text IS 'Surrounding text (30-50 words each direction) for human context';
COMMENT ON COLUMN review_candidates.raw_number_text IS 'Exact number string as found in source (e.g., "13,000", "$493M")';
COMMENT ON COLUMN review_candidates.triggering_keyword IS 'Metric keyword that triggered this candidate (e.g., "customers", "CAC")';
COMMENT ON COLUMN review_candidates.keyword_distance IS 'Character distance from number to triggering keyword';
COMMENT ON COLUMN review_candidates.features IS 'JSON object with ML features for pattern analysis';

-- ============================================================================
-- TABLE: review_decisions
-- ============================================================================
-- Grain: One row per human review decision on a candidate
-- Purpose: Record human judgments for pattern learning

CREATE TABLE review_decisions (
    -- Primary key
    decision_id BIGSERIAL PRIMARY KEY,

    -- Foreign key
    candidate_id BIGINT NOT NULL REFERENCES review_candidates(candidate_id) ON DELETE CASCADE,

    -- Decision
    decision TEXT NOT NULL,  -- 'accept', 'reject', 'reclassify'
    assigned_metric_id TEXT,  -- Final metric ID (may differ from suggested)

    -- Rejection details (when decision = 'reject')
    rejection_reason TEXT,  -- Free-text explanation
    rejection_category TEXT,  -- Categorized reason for pattern learning

    -- Review metadata
    reviewer_notes TEXT,  -- Optional notes from reviewer
    review_time_seconds INT,  -- Time spent on this decision

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_decision CHECK (decision IN ('accept', 'reject', 'reclassify')),
    CONSTRAINT check_rejection_category CHECK (
        rejection_category IS NULL OR
        rejection_category IN ('wrong_metric', 'not_a_metric', 'wrong_value', 'wrong_period', 'duplicate', 'other')
    ),
    CONSTRAINT check_accept_has_metric CHECK (
        decision != 'accept' OR assigned_metric_id IS NOT NULL
    ),
    CONSTRAINT check_reclassify_has_metric CHECK (
        decision != 'reclassify' OR assigned_metric_id IS NOT NULL
    )
);

-- Indices
CREATE INDEX idx_review_decisions_candidate ON review_decisions(candidate_id);
CREATE INDEX idx_review_decisions_decision ON review_decisions(decision);
CREATE INDEX idx_review_decisions_metric ON review_decisions(assigned_metric_id) WHERE assigned_metric_id IS NOT NULL;
CREATE INDEX idx_review_decisions_rejection ON review_decisions(rejection_category) WHERE rejection_category IS NOT NULL;

-- Comments
COMMENT ON TABLE review_decisions IS 'Human review decisions on candidate extractions for pattern learning';
COMMENT ON COLUMN review_decisions.decision IS 'Review decision: accept (correct metric), reject (not a valid extraction), reclassify (different metric)';
COMMENT ON COLUMN review_decisions.rejection_category IS 'Categorized rejection reason: wrong_metric, not_a_metric, wrong_value, wrong_period, duplicate, other';
COMMENT ON COLUMN review_decisions.review_time_seconds IS 'Time spent reviewing this candidate (for workload analysis)';

-- ============================================================================
-- TABLE: learned_patterns
-- ============================================================================
-- Grain: One row per discovered pattern from review analysis
-- Purpose: Store heuristics and statistical patterns for extraction improvement

CREATE TABLE learned_patterns (
    -- Primary key
    pattern_id BIGSERIAL PRIMARY KEY,

    -- Pattern type and scope
    pattern_type TEXT NOT NULL,  -- 'accept_rule', 'reject_rule', 'feature_weight'
    metric_id TEXT,  -- NULL for global patterns, specific ID for metric-specific

    -- Pattern definition
    pattern_name TEXT NOT NULL,  -- Human-readable name
    pattern_description TEXT,  -- Longer description of what pattern detects
    pattern_definition JSONB NOT NULL,  -- Machine-readable rule definition

    -- Performance metrics
    precision_score NUMERIC,  -- Precision on training data
    recall_score NUMERIC,  -- Recall on training data
    f1_score NUMERIC,  -- F1 score
    sample_count INT,  -- Number of samples pattern was evaluated on

    -- Status
    status TEXT NOT NULL DEFAULT 'candidate',  -- 'candidate', 'approved', 'rejected', 'deprecated'
    approved_at TIMESTAMPTZ,
    approved_by TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT check_pattern_type CHECK (pattern_type IN ('accept_rule', 'reject_rule', 'feature_weight')),
    CONSTRAINT check_pattern_status CHECK (status IN ('candidate', 'approved', 'rejected', 'deprecated')),
    CONSTRAINT check_scores CHECK (
        (precision_score IS NULL OR (precision_score >= 0 AND precision_score <= 1)) AND
        (recall_score IS NULL OR (recall_score >= 0 AND recall_score <= 1)) AND
        (f1_score IS NULL OR (f1_score >= 0 AND f1_score <= 1))
    )
);

-- Indices
CREATE INDEX idx_learned_patterns_type ON learned_patterns(pattern_type);
CREATE INDEX idx_learned_patterns_metric ON learned_patterns(metric_id) WHERE metric_id IS NOT NULL;
CREATE INDEX idx_learned_patterns_status ON learned_patterns(status);
CREATE INDEX idx_learned_patterns_approved ON learned_patterns(status, precision_score) WHERE status = 'approved';

-- Comments
COMMENT ON TABLE learned_patterns IS 'Patterns discovered from human review decisions for extraction improvement';
COMMENT ON COLUMN learned_patterns.pattern_type IS 'Type: accept_rule (high-precision accept), reject_rule (high-precision reject), feature_weight (statistical feature)';
COMMENT ON COLUMN learned_patterns.pattern_definition IS 'JSON definition of the pattern (rules, thresholds, feature weights)';
COMMENT ON COLUMN learned_patterns.status IS 'Lifecycle status: candidate (new), approved (in use), rejected (not useful), deprecated (superseded)';

-- ============================================================================
-- VIEWS for analysis
-- ============================================================================

-- View: Candidate review progress by filing
CREATE OR REPLACE VIEW v_review_progress_by_filing AS
SELECT
    rc.filing_id,
    f.accession_number,
    c.company_name,
    COUNT(*) AS total_candidates,
    COUNT(*) FILTER (WHERE rc.review_status = 'reviewed') AS reviewed_count,
    COUNT(*) FILTER (WHERE rc.review_status = 'pending') AS pending_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE rc.review_status = 'reviewed') / NULLIF(COUNT(*), 0), 1) AS review_pct
FROM review_candidates rc
JOIN filings f ON rc.filing_id = f.filing_id
JOIN companies c ON rc.company_id = c.company_id
GROUP BY rc.filing_id, f.accession_number, c.company_name
ORDER BY pending_count DESC;

COMMENT ON VIEW v_review_progress_by_filing IS 'Review progress summary by filing';

-- View: Decision statistics by metric
CREATE OR REPLACE VIEW v_decision_stats_by_metric AS
SELECT
    COALESCE(rc.suggested_metric_id, 'unknown') AS suggested_metric,
    rd.decision,
    COUNT(*) AS decision_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY COALESCE(rc.suggested_metric_id, 'unknown')), 1) AS pct_of_metric
FROM review_decisions rd
JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
GROUP BY COALESCE(rc.suggested_metric_id, 'unknown'), rd.decision
ORDER BY suggested_metric, decision;

COMMENT ON VIEW v_decision_stats_by_metric IS 'Decision distribution by suggested metric (for precision analysis)';

-- View: Rejection reasons summary
CREATE OR REPLACE VIEW v_rejection_reasons AS
SELECT
    COALESCE(rc.suggested_metric_id, 'unknown') AS suggested_metric,
    rd.rejection_category,
    COUNT(*) AS rejection_count,
    ROUND(AVG(rc.keyword_distance), 1) AS avg_keyword_distance,
    MODE() WITHIN GROUP (ORDER BY rc.keyword_position) AS common_keyword_position
FROM review_decisions rd
JOIN review_candidates rc ON rd.candidate_id = rc.candidate_id
WHERE rd.decision = 'reject'
GROUP BY COALESCE(rc.suggested_metric_id, 'unknown'), rd.rejection_category
ORDER BY suggested_metric, rejection_count DESC;

COMMENT ON VIEW v_rejection_reasons IS 'Rejection patterns for identifying systematic false positives';
