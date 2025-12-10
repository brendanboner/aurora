-- ============================================================================
-- Aurora Database Seed Data
-- ============================================================================
-- This file contains default data that should be inserted when the database
-- is first initialized. It's run after db_schema.sql creates the tables.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Default System Configuration (Scraper Sources)
-- ----------------------------------------------------------------------------
-- Cron schedule format: minute hour day month weekday
-- Examples:
--   '0 3 * * *'   = Daily at 3:00 AM UTC
--   '0 */6 * * *' = Every 6 hours
--   '0 9 * * 1-5' = Weekdays at 9:00 AM UTC
--   NULL          = Manual only (no auto-scraping)

INSERT INTO system_configuration (
    datasource_id, name, scraper_type, resource_url, scrape_schedule, run_on_startup,
    check_content_hash, scraper_delay, max_resources, max_redirects, folders,
    discovery_mode, consecutive_duplicates_limit, full_refresh_schedule
)
VALUES 
    -- WFA Public Resource Center (incremental mode - stops after 5 consecutive duplicates)
    -- Mon-Sat: incremental scrape | Sunday: full refresh to catch content updates
    ('wfa_resource_page', 'Wi-Fi Alliance Resource Center', 'wfa', '/resource-center', '0 3 * * 1-6', FALSE, TRUE, 0.5, 3, 10, NULL,
     'incremental', 5, '0 3 * * 0'),
    
    -- WFA Causeway Internal Portal Working Groups (date_based mode - uses folder/doc modification dates)
    -- Daily scrapes automatically pick up new AND revised documents based on mod dates
    ('wfa_causeway_broadcasttg', 'WFA Causeway - Broadcast TG', 'wfa_causeway', '/wg/BroadcastTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Agendas & Meeting Documents", "MRD", "Attendance & Minutes", "SOW", "Wi-Fi Alliance Staff Documents"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_passpointmtg', 'WFA Causeway - Passpoint MTG', 'wfa_causeway', '/wg/PasspointMTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Documents", "Meeting Minutes & Attendance", "Wi-Fi Alliance Staff Reports", "Agendas & Meeting Documents", "Tech Overview"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_securitymtg', 'WFA Causeway - Security MTG', 'wfa_causeway', '/wg/SecurityMTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Attendance & Minutes", "Agendas & Meeting Documents", "Contributions", "Statement of Work", "Wi-Fi Alliance Staff Documents", "Wi-Fi Alliance certification requirements"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_sensingtg', 'WFA Causeway - Sensing TG', 'wfa_causeway', '/wg/SensingTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["MRD", "Agendas & Meeting Documents", "Attendance & Minutes", "SOW", "Wi-Fi Alliance Staff documents"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_wifi7mtg', 'WFA Causeway - Wi-Fi 7 MTG', 'wfa_causeway', '/wg/WiFi7MTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Wi-Fi Alliance Staff Documents", "MRD", "Attendance & Minutes", "Agendas & Meeting Documents", "Tech Overview", "SOW"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_wifi8mtg', 'WFA Causeway - Wi-Fi 8 MTG', 'wfa_causeway', '/wg/WiFi8MTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Attendance & Minutes", "Agendas & Meeting Documents", "Contributions", "MRD", "SOW", "Wi-Fi Alliance Staff documents"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_wifihalowtg', 'WFA Causeway - Wi-Fi HaLow TG', 'wfa_causeway', '/wg/WiFiHaLowTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Agendas & Meeting Documents", "Minutes & Attendance", "Wi-Fi Alliance Staff", "MRD", "SOW", "Spectrum Documents"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_wifilocationtg', 'WFA Causeway - Wi-Fi Location TG', 'wfa_causeway', '/wg/WiFiLocationTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Meeting Documents", "Meeting Minutes", "MRD", "SOW", "Working Documents", "Review Documents", "Use Cases"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_xrmstg', 'WFA Causeway - XRMS TG', 'wfa_causeway', '/wg/XRMSTG/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, '["Wi-Fi Alliance Staff Documents", "MRD", "Minutes & Attendance", "Agenda", "Contributions"]'::jsonb,
     'date_based', 0, NULL),
    ('wfa_causeway_regulatorytg', 'WFA Causeway - Regulatory', 'wfa_causeway', '/wg/Regulatory/document', '0 3 * * *', FALSE, TRUE, 0.5, 3, 10, NULL,
     'date_based', 0, NULL),
    
    -- Manual upload placeholder (no scraper)
    ('manual_upload', 'Manual Document Upload', NULL, NULL, NULL, FALSE, TRUE, 0.5, 3, 10, NULL,
     'incremental', 0, NULL)
ON CONFLICT (datasource_id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- Sample Users (for development/testing)
-- ----------------------------------------------------------------------------

-- USER 1: Wi-Fi standards engineer
INSERT INTO app_users (email, display_name)
VALUES ('alice@example.com', 'Alice Standards')
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       ARRAY['Wi-Fi 6E', 'Wi-Fi 7', '802.11be', 'AFC Systems'],
       ARRAY['Wi-Fi Alliance', 'IEEE 802.11'],
       ARRAY['John Doe', 'Jane Smith']
FROM app_users WHERE email = 'alice@example.com'
ON CONFLICT (user_id) DO NOTHING;

-- USER 2: Security-focused researcher
INSERT INTO app_users (email, display_name)
VALUES ('bob@example.com', 'Bob Security')
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       ARRAY['WPA3', '802.11i', 'Zero Trust', 'Device Identity'],
       ARRAY['Wi-Fi Alliance', 'NIST'],
       ARRAY['Dr. Secure']
FROM app_users WHERE email = 'bob@example.com'
ON CONFLICT (user_id) DO NOTHING;

-- USER 3: Spectrum and regulatory analyst
INSERT INTO app_users (email, display_name)
VALUES ('carol@example.com', 'Carol Spectrum')
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       ARRAY['6 GHz', 'AFC regulation', 'FCC updates', 'ETSI activities'],
       ARRAY['FCC', 'ETSI', 'Wi-Fi Alliance'],
       ARRAY['Commissioner Smith']
FROM app_users WHERE email = 'carol@example.com'
ON CONFLICT (user_id) DO NOTHING;

-- USER 4: Corporate technology strategist
INSERT INTO app_users (email, display_name)
VALUES ('dave@example.com', 'Dave Strategist')
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       ARRAY['AI Networking', 'Edge Computing', 'Wi-Fi 7', 'Enterprise Security'],
       ARRAY['Wi-Fi Alliance', 'IEEE', 'Cisco'],
       ARRAY['CTO Johnson']
FROM app_users WHERE email = 'dave@example.com'
ON CONFLICT (user_id) DO NOTHING;
