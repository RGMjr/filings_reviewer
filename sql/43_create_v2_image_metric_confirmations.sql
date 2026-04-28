-- Migration 43: Create v2_image_metric_confirmations table
--
-- Stores per-reviewer adjudication decisions for metric-presence signals on chart images.
-- Four decision types:
--   accept  : detected_metric_id = confirmed_metric_id (both non-null)
--   reject  : detected_metric_id non-null, confirmed_metric_id null, rejection_reason required.
--             Sentinel exception: when rejection_reason='no_relevant_metrics'
--             ("Reject all" on an image with zero keyword-detected metrics)
--             BOTH IDs may be NULL. The unique-index COALESCE(.., '') admits
--             one such sentinel row per (img_id, reviewer_id).
--   correct : both IDs non-null and different, rejection_reason optional
--   add     : detected_metric_id null, confirmed_metric_id non-null (reviewer adds missed metric)

CREATE TABLE v2_image_metric_confirmations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  img_id UUID NOT NULL REFERENCES v2_image_assets(img_id) ON DELETE CASCADE,
  detected_metric_id TEXT NULL,         -- what the classifier said (NULL when decision='add')
  confirmed_metric_id TEXT NULL,        -- what the reviewer says is there (NULL when decision='reject')
  decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject', 'correct', 'add')),
  rejection_reason TEXT NULL,           -- required when decision='reject'; optional for 'correct'
  reviewer_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_v2_image_metric_confirmations_img_id
  ON v2_image_metric_confirmations(img_id);

-- One decision per reviewer per detected metric on a given image.
-- COALESCE lets 'add' rows (detected_metric_id IS NULL) coexist uniquely
-- by their confirmed_metric_id.
CREATE UNIQUE INDEX idx_v2_image_metric_confirmations_unique
  ON v2_image_metric_confirmations(
    img_id,
    reviewer_id,
    COALESCE(detected_metric_id, confirmed_metric_id, '')
  );
