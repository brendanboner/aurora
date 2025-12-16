-- ============================================================================
-- Aurora Database Seed Data
-- ============================================================================
-- This file contains default data that should be inserted when the database
-- is first initialized. It's run after db_schema.sql creates the tables.
-- ============================================================================

-- Note: Datasource configuration has been migrated to Neo4j DataSource nodes.
-- All scraper settings, schedules, and weights are now stored in the
-- knowledge graph at neo4j-client/neo4j_client/initial_data.json

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
