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
-- Users are created automatically via Cognito authentication
-- ----------------------------------------------------------------------------
-- No seed users needed. Users will be created when they first log in through
-- the auth service, which creates app_users records with Cognito UUIDs.
-- ----------------------------------------------------------------------------
