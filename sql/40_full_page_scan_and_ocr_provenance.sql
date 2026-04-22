-- Migration 40: Full-page-scan classification + OCR-segment provenance
--
-- Extends two schemas to support OCR'd image-page content flowing through
-- the normal text-extraction pipeline:
--
--   1. v2_image_assets.classification CHECK: adds 'full_page_scan' so images
--      from issuers that file 8-Ks as page-image decks (e.g. PayPal) can be
--      classified distinctly from table/chart/logo/signature.
--
--   2. v2_segments gains two columns (source_type, source_img_id) so a segment
--      synthesized from image OCR can be traced back to its source image.
--      Facts derived from these segments still use v2_metric_facts.source_type
--      = 'text' (unchanged); OCR provenance is captured on the segment only.

BEGIN;

-- 1. Extend v2_image_assets.classification CHECK
ALTER TABLE v2_image_assets
    DROP CONSTRAINT IF EXISTS v2_image_assets_classification_check;

ALTER TABLE v2_image_assets
    ADD CONSTRAINT v2_image_assets_classification_check
    CHECK (classification IN (
        'chart', 'table_image', 'decorative', 'logo', 'signature', 'unknown',
        'full_page_scan'
    ));

-- 2. Add OCR provenance columns to v2_segments
ALTER TABLE v2_segments
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'text'
        CHECK (source_type IN ('text', 'image_ocr'));

ALTER TABLE v2_segments
    ADD COLUMN IF NOT EXISTS source_img_id UUID
        REFERENCES v2_image_assets(img_id) ON DELETE SET NULL;

-- Index for lookups / rollback queries targeting image_ocr segments
CREATE INDEX IF NOT EXISTS idx_v2_segments_source_type
    ON v2_segments(source_type)
    WHERE source_type = 'image_ocr';

COMMIT;
