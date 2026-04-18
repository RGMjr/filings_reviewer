-- Add detected_keywords audit column to v2_image_assets.
--
-- Persists the sorted, unique set of metric-keyword strings matched at
-- extraction time against config/metric_keywords.yaml patterns. Time-stamped
-- implicitly via v2_image_assets.created_at. Supports:
--   (1) decision-time reproducibility for reviewer audits — the YAML drifts,
--       but the persisted list is what the reviewer saw at decision time
--   (2) model-iteration feature input — keyword presence per image without
--       having to re-run the matcher against current YAML.
--
-- NULL = not yet computed (pre-backfill rows); populated lazily by
-- scripts/backfill_image_keywords.py.

ALTER TABLE v2_image_assets
    ADD COLUMN IF NOT EXISTS detected_keywords TEXT[];

CREATE INDEX IF NOT EXISTS idx_v2_image_assets_detected_keywords
    ON v2_image_assets USING GIN (detected_keywords);

COMMENT ON COLUMN v2_image_assets.detected_keywords IS
    'Sorted unique keyword strings matched at extraction time against '
    'config/metric_keywords.yaml patterns. Time-stamped via created_at. '
    'NULL = not yet computed (pre-backfill rows).';
