-- ============================================================================
-- Migration: Dedup v2_image_assets by (doc_id, filename) + add UNIQUE
-- Purpose:   Root-cause fix for the Maplebear S-1 "220 pending images" bug.
--            v2_image_assets accumulated duplicate rows per re-extraction because
--            ImageAsset.img_id is a random UUID per run and persistence did
--            `ON CONFLICT (img_id) DO UPDATE` — which never fired, inserting a
--            fresh row each time. Decisions stayed attached to the original
--            img_id; new rows defaulted to review_status='pending'.
--
--            This migration collapses duplicate (doc_id, filename) groups,
--            consolidating status / predicted_relevance / detected_keywords onto
--            the kept row, then adds UNIQUE (doc_id, filename) to prevent
--            recurrence. Paired with a change in
--            src/extraction_v2/persistence.py to upsert on (doc_id, filename).
--
-- Priority for selecting the keeper img_id within a (doc_id, filename) group:
--   1. Row with an entry in v2_image_review_decisions (at most one per group,
--      enforced by v2_image_review_decisions.img_id UNIQUE).
--   2. Oldest created_at (tie-break on img_id ASC).
--
-- Consolidated status priority: reviewed > skipped > auto_rejected > pending.
-- Consolidated predicted_relevance: MAX across group (NULL-tolerant).
-- Consolidated detected_keywords: union of distinct keywords across group.
-- ============================================================================

BEGIN;

-- 1. Build keyword union per (doc_id, filename).
CREATE TEMP TABLE _tmp_kw_union ON COMMIT DROP AS
SELECT
    doc_id,
    filename,
    array_agg(DISTINCT kw ORDER BY kw) AS keywords
FROM v2_image_assets,
     LATERAL unnest(COALESCE(detected_keywords, ARRAY[]::TEXT[])) AS kw
GROUP BY doc_id, filename;

-- 2. Compute consolidated status + predicted_relevance per group, joined with
--    the keyword union.
CREATE TEMP TABLE _tmp_group_stats ON COMMIT DROP AS
SELECT
    v.doc_id,
    v.filename,
    CASE
        WHEN BOOL_OR(v.review_status = 'reviewed')      THEN 'reviewed'
        WHEN BOOL_OR(v.review_status = 'skipped')       THEN 'skipped'
        WHEN BOOL_OR(v.review_status = 'auto_rejected') THEN 'auto_rejected'
        ELSE 'pending'
    END AS consolidated_status,
    MAX(v.predicted_relevance) AS consolidated_predicted_relevance,
    ku.keywords AS consolidated_detected_keywords
FROM v2_image_assets v
LEFT JOIN _tmp_kw_union ku USING (doc_id, filename)
GROUP BY v.doc_id, v.filename, ku.keywords;

-- 3. Pick one keeper img_id per (doc_id, filename) group.
CREATE TEMP TABLE _tmp_keepers ON COMMIT DROP AS
SELECT DISTINCT ON (doc_id, filename)
    img_id AS keeper_img_id,
    doc_id,
    filename
FROM v2_image_assets v
ORDER BY
    doc_id,
    filename,
    EXISTS (
        SELECT 1 FROM v2_image_review_decisions d WHERE d.img_id = v.img_id
    ) DESC,
    created_at ASC NULLS LAST,
    img_id ASC;

-- 4. Apply consolidated columns to the keeper row.
UPDATE v2_image_assets t
SET
    review_status       = gs.consolidated_status,
    predicted_relevance = COALESCE(gs.consolidated_predicted_relevance, t.predicted_relevance),
    detected_keywords   = COALESCE(gs.consolidated_detected_keywords, t.detected_keywords)
FROM _tmp_keepers k
JOIN _tmp_group_stats gs USING (doc_id, filename)
WHERE t.img_id = k.keeper_img_id;

-- 5. Delete non-keeper rows. Safe: by construction, any row carrying a
--    review decision is the keeper (decisions are UNIQUE on img_id, and the
--    keeper-selection ORDER BY prefers rows with decisions). Non-keeper
--    rows therefore have no decisions to cascade-destroy.
DELETE FROM v2_image_assets v
WHERE v.img_id NOT IN (SELECT keeper_img_id FROM _tmp_keepers);

-- 6. Sanity: abort if any duplicates remain (should never happen after step 5,
--    but guards against a logic mistake before we add the UNIQUE constraint).
DO $$
DECLARE
    dup_groups INT;
BEGIN
    SELECT COUNT(*) INTO dup_groups FROM (
        SELECT 1 FROM v2_image_assets
        GROUP BY doc_id, filename
        HAVING COUNT(*) > 1
    ) sub;
    IF dup_groups > 0 THEN
        RAISE EXCEPTION 'sql/34 dedup incomplete: % duplicate (doc_id, filename) groups remain', dup_groups;
    END IF;
END $$;

-- 7. Enforce uniqueness going forward. Paired with the upsert target change
--    in src/extraction_v2/persistence.py:_persist_images_in_tx.
ALTER TABLE v2_image_assets
    ADD CONSTRAINT v2_image_assets_doc_filename_uk UNIQUE (doc_id, filename);

COMMIT;
