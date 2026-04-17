-- Migration 24: add 'part_of_date' rejection category to CHECK constraints
-- Covers existing DBs (ALTER below) and fresh-install DBs (via companion edits to
-- 07_create_review_schema.sql:109 and 09_v2_schema.sql:290).
--
-- EXISTING-DB OPERATOR NOTE: editing 07 and 09 changed their file checksums.
-- On next apply_migrations.py run you will get a RuntimeError checksum mismatch
-- for those two files. Fix by updating their ledger rows to the new checksums:
--   UPDATE schema_migrations
--      SET checksum = encode(sha256(pg_read_binary_file('sql/07_create_review_schema.sql')), 'hex')
--    WHERE id = '07_create_review_schema.sql';
--   UPDATE schema_migrations
--      SET checksum = encode(sha256(pg_read_binary_file('sql/09_v2_schema.sql')), 'hex')
--    WHERE id = '09_v2_schema.sql';
-- (Do NOT re-apply 07 — its CREATE INDEX statements lack IF NOT EXISTS and will error
--  on an existing DB. 09 is safe to re-apply but the checksum bump is simpler.)

-- V2 review decisions (auto-named inline CHECK)
ALTER TABLE v2_review_decisions
  DROP CONSTRAINT IF EXISTS v2_review_decisions_rejection_category_check;
ALTER TABLE v2_review_decisions
  ADD CONSTRAINT v2_review_decisions_rejection_category_check
    CHECK (rejection_category IN (
      'wrong_metric', 'not_a_metric', 'wrong_value', 'wrong_period',
      'part_of_date', 'duplicate', 'other'
    ));

-- V1 review decisions (named constraint check_rejection_category)
ALTER TABLE review_decisions
  DROP CONSTRAINT IF EXISTS check_rejection_category;
ALTER TABLE review_decisions
  ADD CONSTRAINT check_rejection_category
    CHECK (
      rejection_category IS NULL OR
      rejection_category IN (
        'wrong_metric', 'not_a_metric', 'wrong_value', 'wrong_period',
        'part_of_date', 'duplicate', 'other'
      )
    );
