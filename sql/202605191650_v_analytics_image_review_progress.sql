-- Migration 202605191650: v_analytics_image_review_progress
--
-- Exposes the per-image review state aggregated from v2_image_assets +
-- v2_image_metric_confirmations. Mirrors DatabaseAdapter._derive_image_review_state
-- (src/infra/db.py) so the /v2/review/stats Image Confirmations box can
-- count images by what reviewers actually did via the per-metric flow,
-- not just by the legacy v2_image_assets.review_status column (which is
-- only flipped to 'reviewed' when mark_complete=true is passed).
--
-- Per CLAUDE.md: analytics surface lives in v_analytics_* views, not in
-- Python aggregation code.
--
-- Idempotency: CREATE OR REPLACE VIEW is re-run safe.

BEGIN;

CREATE OR REPLACE VIEW v_analytics_image_review_progress AS
WITH rollup AS (
    SELECT
        v.img_id,
        v.filing_id,
        v.review_status,
        v.classification,
        v.filename,
        v.detected_metrics,
        COALESCE(jsonb_array_length(v.detected_metrics), 0) AS detected_count,
        COUNT(c.*) AS total_confirmation_count,
        COUNT(DISTINCT c.confirmed_metric_id) FILTER (
            WHERE c.decision IN ('accept', 'correct', 'add')
              AND c.confirmed_metric_id IS NOT NULL
        ) AS positive_count,
        COUNT(DISTINCT c.detected_metric_id) FILTER (
            WHERE c.detected_metric_id IS NOT NULL
              AND c.decision IN ('accept', 'reject', 'correct')
        ) AS detected_decided_count,
        BOOL_OR(
            c.decision = 'reject'
            AND c.rejection_reason = 'no_relevant_metrics'
            AND c.detected_metric_id IS NULL
        ) AS has_no_relevant_sentinel
    FROM v2_image_assets v
    LEFT JOIN v2_image_metric_confirmations c ON c.img_id = v.img_id
    WHERE v.classification NOT IN ('decorative', 'logo', 'signature')
      AND v.filename IS NOT NULL
      AND v.filename <> ''
    GROUP BY v.img_id
)
SELECT
    r.img_id,
    r.filing_id,
    r.review_status,
    r.classification,
    r.detected_count,
    r.total_confirmation_count,
    r.positive_count,
    r.detected_decided_count,
    COALESCE(r.has_no_relevant_sentinel, FALSE) AS has_no_relevant_sentinel,
    CASE
        WHEN r.review_status IN ('skipped', 'auto_rejected') THEN 'no_relevant'
        -- Legacy V1 reviewers (and explicit mark_complete=true callers) flipped
        -- review_status='reviewed' directly. Treat that as a positive marker so
        -- the analytics count is a superset of the legacy reviewed set, not a
        -- replacement. Diverges intentionally from _derive_image_review_state,
        -- which is queue-thumbnail-only and doesn't see legacy V1 reviews.
        WHEN r.review_status = 'reviewed' THEN 'relevant'
        WHEN r.detected_count = 0 AND r.total_confirmation_count = 0 THEN 'pending'
        WHEN r.detected_decided_count >= r.detected_count
             AND r.positive_count > 0 THEN 'relevant'
        WHEN r.detected_decided_count >= r.detected_count
             AND r.positive_count = 0 THEN 'no_relevant'
        ELSE 'pending'
    END AS image_review_state
FROM rollup r;

COMMIT;
