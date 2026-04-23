ALTER TABLE v2_image_assets
  ADD COLUMN IF NOT EXISTS detected_metrics JSONB DEFAULT '[]'::jsonb;
