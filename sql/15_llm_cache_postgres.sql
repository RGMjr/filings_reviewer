-- Migration: LLM response cache in PostgreSQL
-- Replaces local SQLite cache for cloud deployments

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    cache_version TEXT NOT NULL,
    model TEXT NOT NULL,
    response_content TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_cache_version ON llm_cache(cache_version);
CREATE INDEX IF NOT EXISTS idx_llm_cache_created ON llm_cache(created_at);
