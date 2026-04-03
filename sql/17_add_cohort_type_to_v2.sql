-- Migration 17: Add cohort_type column to v2_metric_facts
ALTER TABLE v2_metric_facts ADD COLUMN cohort_type TEXT;
ALTER TABLE v2_metric_facts ADD CONSTRAINT chk_cohort_type
  CHECK (cohort_type IN ('acquisition', 'tenure', 'other') OR cohort_type IS NULL);
