-- Create system_configuration table
CREATE TABLE IF NOT EXISTS system_configuration (
    datasource_id       TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    scrape_frequency    TEXT NOT NULL DEFAULT 'daily',
    check_content_hash  BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at     TIMESTAMPTZ,
    publish_weight      REAL NOT NULL DEFAULT 1.0,
    update_weight       REAL NOT NULL DEFAULT 0.8,
    event_weight        REAL NOT NULL DEFAULT 0.9,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_system_config_scrape_freq 
ON system_configuration(scrape_frequency);

-- Insert default configurations
INSERT INTO system_configuration (datasource_id, name, scrape_frequency, check_content_hash)
VALUES 
    ('default', 'Default Configuration', 'daily', TRUE),
    ('wfa_resource_page', 'Wi-Fi Alliance Resource Center', 'daily', TRUE),
    ('manual_upload', 'Manual Document Upload', 'manual', TRUE)
ON CONFLICT (datasource_id) DO NOTHING;

-- Verify
SELECT datasource_id, name, publish_weight, update_weight, event_weight FROM system_configuration;
