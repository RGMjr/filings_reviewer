-- Migration 202604291500: add_decided_against_hash_to_image_decision_tables
--
-- Adds a nullable decided_against_hash TEXT column to both image-decision
-- tables so the review UI can show a "stale OCR/chart data" badge when
-- content has changed since a reviewer made their decision.
--
-- Hash recipe (computed by application, not DB):
--   sha256((ocr_text or "") + "\x1f" + (chart_data_json or ""))
--
-- NULL hash (pre-deploy rows) → stale=False by design (grandfather clause).
-- No backfill planned; if later requested, write a follow-up migration.
--
-- Idempotency: ALTER TABLE ... IF NOT EXISTS is safe to re-run.

BEGIN;

ALTER TABLE v2_image_review_decisions
    ADD COLUMN IF NOT EXISTS decided_against_hash TEXT NULL;

ALTER TABLE v2_image_metric_confirmations
    ADD COLUMN IF NOT EXISTS decided_against_hash TEXT NULL;

COMMIT;
