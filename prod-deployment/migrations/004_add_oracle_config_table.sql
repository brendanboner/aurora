-- Oracle Service Configuration
-- Stores runtime configuration for Oracle query settings
-- This table allows admin settings to persist across service restarts

CREATE TABLE IF NOT EXISTS oracle_config (
    id              SERIAL PRIMARY KEY,
    config_key      TEXT NOT NULL UNIQUE,
    config_value    JSONB NOT NULL,
    updated_by      TEXT,  -- User ID who last updated this setting
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_oracle_config_key ON oracle_config(config_key);

-- Insert default query settings
INSERT INTO oracle_config (config_key, config_value) VALUES (
    'query_settings',
    jsonb_build_object(
        'fast_pipeline_enabled', false,
        'fast_pipeline_rollout_percentage', 0,
        'fast_pipeline_shadow_mode', false,
        'fast_confidence_threshold', 0.6,
        'fast_cache_plan_ttl_hours', 24,
        'fast_cache_result_ttl_minutes', 60,
        'fast_cache_answer_ttl_minutes', 60,
        'fast_deep_dive_enabled', true
    )
) ON CONFLICT (config_key) DO NOTHING;
