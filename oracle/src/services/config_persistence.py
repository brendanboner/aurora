"""Database persistence service for Oracle configuration.

This service handles storing and retrieving Oracle configuration settings
from PostgreSQL, allowing admin settings to persist across service restarts.
"""
from __future__ import annotations

import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

import psycopg2
import psycopg2.extras

from ..settings import settings

logger = logging.getLogger(__name__)

# PostgreSQL connection
_pg_conn = None


def _get_pg_conn():
    """Get PostgreSQL connection (singleton)."""
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        try:
            _pg_conn = psycopg2.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
            )
            logger.info("Connected to PostgreSQL for config persistence")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise
    return _pg_conn


def load_config(config_key: str) -> Optional[Dict[str, Any]]:
    """Load configuration from database.
    
    Args:
        config_key: Configuration key (e.g., 'query_settings')
        
    Returns:
        Configuration dictionary or None if not found
    """
    try:
        conn = _get_pg_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT config_value FROM oracle_config WHERE config_key = %s",
                (config_key,)
            )
            row = cur.fetchone()
            if row:
                return row['config_value']
            return None
    except Exception as e:
        logger.error(f"Error loading config '{config_key}': {e}")
        return None


def save_config(config_key: str, config_value: Dict[str, Any], updated_by: Optional[str] = None) -> bool:
    """Save configuration to database.
    
    Args:
        config_key: Configuration key (e.g., 'query_settings')
        config_value: Configuration dictionary
        updated_by: User ID who is updating the config (optional)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oracle_config (config_key, config_value, updated_by, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (config_key) 
                DO UPDATE SET 
                    config_value = EXCLUDED.config_value,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = EXCLUDED.updated_at
                """,
                (config_key, json.dumps(config_value), updated_by, datetime.utcnow())
            )
            conn.commit()
            logger.info(f"Saved config '{config_key}' to database")
            return True
    except Exception as e:
        logger.error(f"Error saving config '{config_key}': {e}")
        if conn:
            conn.rollback()
        return False


def initialize_config_from_db():
    """Initialize Oracle settings from database on startup.
    
    This loads persisted configuration from PostgreSQL and updates
    the in-memory settings object. Should be called during service startup.
    """
    try:
        # Load query settings
        query_settings = load_config('query_settings')
        if query_settings:
            logger.info("Loading persisted query settings from database")
            
            # Update settings object with persisted values
            if 'fast_pipeline_enabled' in query_settings:
                settings.fast_pipeline_enabled = query_settings['fast_pipeline_enabled']
            if 'fast_pipeline_rollout_percentage' in query_settings:
                settings.fast_pipeline_rollout_percentage = query_settings['fast_pipeline_rollout_percentage']
            if 'fast_pipeline_shadow_mode' in query_settings:
                settings.fast_pipeline_shadow_mode = query_settings['fast_pipeline_shadow_mode']
            if 'fast_confidence_threshold' in query_settings:
                settings.fast_confidence_threshold = query_settings['fast_confidence_threshold']
            if 'fast_cache_plan_ttl_hours' in query_settings:
                settings.fast_cache_plan_ttl = query_settings['fast_cache_plan_ttl_hours'] * 3600
            if 'fast_cache_result_ttl_minutes' in query_settings:
                settings.fast_cache_result_ttl = query_settings['fast_cache_result_ttl_minutes'] * 60
            if 'fast_cache_answer_ttl_minutes' in query_settings:
                settings.fast_cache_answer_ttl = query_settings['fast_cache_answer_ttl_minutes'] * 60
            if 'fast_deep_dive_enabled' in query_settings:
                settings.fast_deep_dive_enabled = query_settings['fast_deep_dive_enabled']
                
            logger.info(
                f"Loaded settings: fast_pipeline_enabled={settings.fast_pipeline_enabled}, "
                f"rollout={settings.fast_pipeline_rollout_percentage}%, "
                f"shadow_mode={settings.fast_pipeline_shadow_mode}"
            )
        else:
            logger.info("No persisted query settings found, using environment defaults")
    except Exception as e:
        logger.error(f"Error initializing config from database: {e}")
        logger.warning("Continuing with environment variable defaults")
