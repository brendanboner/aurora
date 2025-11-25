-- =============================================================================
-- Migration 002: Add Temporal Extraction Threshold
-- =============================================================================
-- This migration adds the temporal_extraction_days column to system_configuration
-- to control how far back in time we should extract events from documents.
--
-- This allows configuration of event extraction threshold per datasource:
-- - Documents older than this threshold won't have events extracted
-- - Helps focus on recent/relevant events
-- - Default: 90 days
-- =============================================================================

-- Add temporal_extraction_days column to system_configuration
ALTER TABLE system_configuration 
ADD COLUMN IF NOT EXISTS temporal_extraction_days INTEGER NOT NULL DEFAULT 90;

-- Add index for querying by temporal extraction threshold
CREATE INDEX IF NOT EXISTS idx_system_config_temporal_threshold 
ON system_configuration(temporal_extraction_days);

-- Update existing rows to have the default value
UPDATE system_configuration 
SET temporal_extraction_days = 90 
WHERE temporal_extraction_days IS NULL;

-- =============================================================================
-- Comments for Documentation
-- =============================================================================
COMMENT ON COLUMN system_configuration.temporal_extraction_days IS 
    'Days threshold for extracting events from documents. Documents older than this threshold (based on publish_date) will not have events extracted. Default: 90 days.';

