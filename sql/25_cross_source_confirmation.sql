-- Migration 25: cross-source confirmation columns for v2_metric_facts
ALTER TABLE v2_metric_facts
  ADD COLUMN cross_source_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN confirming_source_types TEXT[] NOT NULL DEFAULT '{}';
