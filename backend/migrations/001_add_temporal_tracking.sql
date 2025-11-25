-- =============================================================================
-- Migration 001: Add Temporal Tracking and System Configuration
-- =============================================================================
-- This migration adds tables for tracking document changes over time and
-- configuring datasource scraping behavior.
--
-- Tables added:
-- 1. system_configuration: Global config for datasources and relevance weights
-- 2. document_change_log: Audit log of document changes (uncompressed)
-- 3. document_change_log_compressed: Compressed yearly summaries for old changes
--
-- =============================================================================

-- =============================================================================
-- System Configuration Table
-- =============================================================================
-- Stores configuration for datasources and temporal relevance scoring weights
CREATE TABLE IF NOT EXISTS system_configuration (
    datasource_id               TEXT PRIMARY KEY,
    name                        TEXT NOT NULL,
    scrape_frequency            TEXT NOT NULL DEFAULT 'daily',  -- hourly, daily, weekly, manual
    check_content_hash          BOOLEAN NOT NULL DEFAULT TRUE,
    last_scraped_at             TIMESTAMPTZ,
    publish_weight              REAL NOT NULL DEFAULT 1.0,      -- Weight for newly published docs
    update_weight               REAL NOT NULL DEFAULT 0.8,      -- Weight for updated docs
    event_weight                REAL NOT NULL DEFAULT 0.9,      -- Weight for events
    temporal_extraction_days    INTEGER NOT NULL DEFAULT 90,    -- Days threshold for extracting events from documents
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for querying by scrape frequency
CREATE INDEX IF NOT EXISTS idx_system_config_scrape_freq 
ON system_configuration(scrape_frequency);

-- Index for querying by temporal extraction threshold
CREATE INDEX IF NOT EXISTS idx_system_config_temporal_threshold 
ON system_configuration(temporal_extraction_days);

-- =============================================================================
-- Document Change Log Table
-- =============================================================================
-- Tracks all changes to documents (content, metadata, etc.)
-- Uncompressed for recent changes (< 1 year old)
CREATE TABLE IF NOT EXISTS document_change_log (
    id                  SERIAL PRIMARY KEY,
    url_hash            TEXT NOT NULL,
    old_content_hash    TEXT,
    new_content_hash    TEXT NOT NULL,
    old_publish_date    TIMESTAMPTZ,
    new_publish_date    TIMESTAMPTZ,
    old_title           TEXT,
    new_title           TEXT,
    changed_fields      JSONB NOT NULL,  -- Array of field names that changed
    changed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for querying change history
CREATE INDEX IF NOT EXISTS idx_doc_change_log_url_hash 
ON document_change_log(url_hash);

CREATE INDEX IF NOT EXISTS idx_doc_change_log_changed_at 
ON document_change_log(changed_at DESC);

-- =============================================================================
-- Document Change Log Compressed Table
-- =============================================================================
-- Compressed summaries of document changes older than 1 year
-- Aggregated by document and year to reduce storage
CREATE TABLE IF NOT EXISTS document_change_log_compressed (
    id                  SERIAL PRIMARY KEY,
    url_hash            TEXT NOT NULL,
    year                INTEGER NOT NULL,
    change_count        INTEGER NOT NULL DEFAULT 0,
    first_change        TIMESTAMPTZ NOT NULL,
    last_change         TIMESTAMPTZ NOT NULL,
    changes_summary     JSONB NOT NULL,  -- {field_name: change_count}
    compressed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(url_hash, year)
);

-- Index for querying compressed history
CREATE INDEX IF NOT EXISTS idx_doc_change_compressed_url 
ON document_change_log_compressed(url_hash, year DESC);

-- =============================================================================
-- Stored Procedure: Compress Old Change Logs
-- =============================================================================
-- Compresses document_change_log entries older than 365 days into yearly summaries
CREATE OR REPLACE FUNCTION compress_old_change_logs()
RETURNS INTEGER AS $$
DECLARE
    compressed_count INTEGER := 0;
BEGIN
    -- Insert compressed summaries for logs older than 1 year
    WITH field_changes AS (
        SELECT 
            url_hash,
            EXTRACT(YEAR FROM changed_at)::INTEGER as year,
            changed_at,
            jsonb_array_elements_text(changed_fields) as field_name
        FROM document_change_log
        WHERE changed_at < NOW() - INTERVAL '365 days'
    ),
    field_counts AS (
        SELECT 
            url_hash,
            year,
            field_name,
            COUNT(*) as field_count
        FROM field_changes
        GROUP BY url_hash, year, field_name
    ),
    aggregated AS (
        SELECT 
            url_hash,
            year,
            jsonb_object_agg(field_name, field_count) as changes_summary
        FROM field_counts
        GROUP BY url_hash, year
    )
    INSERT INTO document_change_log_compressed (
        url_hash, 
        year, 
        change_count, 
        first_change, 
        last_change, 
        changes_summary
    )
    SELECT 
        dcl.url_hash,
        EXTRACT(YEAR FROM dcl.changed_at)::INTEGER as year,
        COUNT(*) as change_count,
        MIN(dcl.changed_at) as first_change,
        MAX(dcl.changed_at) as last_change,
        COALESCE(agg.changes_summary, '{}'::jsonb) as changes_summary
    FROM document_change_log dcl
    LEFT JOIN aggregated agg ON dcl.url_hash = agg.url_hash 
        AND EXTRACT(YEAR FROM dcl.changed_at)::INTEGER = agg.year
    WHERE dcl.changed_at < NOW() - INTERVAL '365 days'
    GROUP BY dcl.url_hash, EXTRACT(YEAR FROM dcl.changed_at)::INTEGER, agg.changes_summary
    ON CONFLICT (url_hash, year) 
    DO UPDATE SET
        change_count = document_change_log_compressed.change_count + EXCLUDED.change_count,
        last_change = GREATEST(document_change_log_compressed.last_change, EXCLUDED.last_change),
        changes_summary = document_change_log_compressed.changes_summary || EXCLUDED.changes_summary,
        compressed_at = NOW();
    
    GET DIAGNOSTICS compressed_count = ROW_COUNT;
    
    -- Delete compressed logs
    DELETE FROM document_change_log
    WHERE changed_at < NOW() - INTERVAL '365 days';
    
    RETURN compressed_count;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Insert Default System Configuration
-- =============================================================================
-- Add default configuration for known datasources
INSERT INTO system_configuration (datasource_id, name, scrape_frequency, check_content_hash)
VALUES 
    ('wfa_resource_page', 'Wi-Fi Alliance Resource Center', 'daily', TRUE),
    ('manual_upload', 'Manual Document Upload', 'manual', TRUE)
ON CONFLICT (datasource_id) DO NOTHING;

-- =============================================================================
-- Comments for Documentation
-- =============================================================================
COMMENT ON TABLE system_configuration IS 'Configuration for datasource scraping and relevance scoring weights';
COMMENT ON TABLE document_change_log IS 'Audit log of document changes (uncompressed, < 1 year old)';
COMMENT ON TABLE document_change_log_compressed IS 'Compressed yearly summaries of document changes (> 1 year old)';
COMMENT ON FUNCTION compress_old_change_logs() IS 'Compresses document change logs older than 365 days into yearly summaries';
