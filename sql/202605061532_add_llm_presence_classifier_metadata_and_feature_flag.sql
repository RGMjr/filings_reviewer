-- Migration 202605061532: add llm presence classifier metadata and feature flag
--
-- Adds the column the LLM presence-classifier stage will write to and seeds
-- the rollback feature flag. The column is JSONB with no schema enforcement
-- so prompt-version / score / model-fallback metadata can evolve without
-- further migrations. Default off; flip via UPDATE feature_flags once
-- shadow-mode validation passes.

BEGIN;

-- ==========================================================================
-- v2_text_metric_presence.classifier_metadata
-- ==========================================================================
-- Shape (advisory; not enforced):
--   { "prompt_version": "<semver>",
--     "llm_score": <0..1>,
--     "model": "claude-haiku-4-5" | "claude-sonnet-4-6",
--     "sonnet_fallback": <bool>,
--     "candidate_source": "keyword" | "paraphrase_recall" | "both" }
-- NULL on rows produced by non-classifier stages.

ALTER TABLE v2_text_metric_presence
    ADD COLUMN IF NOT EXISTS classifier_metadata JSONB;

-- ==========================================================================
-- presence_classifier_enabled feature flag
-- ==========================================================================
-- Default 'off' so the classifier ships in shadow mode (writes only when
-- keyword path also fires; never overrides). Operators flip to 'shadow'
-- (logs disagreements) or 'on' (authoritative) per the rollout sequence in
-- docs/operations/text-pipeline-presence-pivot-plan.md.

INSERT INTO feature_flags (key, value)
VALUES ('presence_classifier_enabled', 'off')
ON CONFLICT (key) DO NOTHING;

COMMIT;
