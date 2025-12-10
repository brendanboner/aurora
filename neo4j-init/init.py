"""
Neo4j Initialization Service

One-time initialization container that:
1. Waits for Neo4j to be ready
2. Creates schema (constraints and indexes)
3. Loads base data (organizations and data sources)

This ensures the database is ready before other services start.
"""

import os
import sys
import time
import logging

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("neo4j-init")

# Suppress noisy debug logs from dependencies
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("neo4j.io").setLevel(logging.WARNING)
logging.getLogger("neo4j.pool").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("neo4j_client.models").setLevel(logging.INFO)


def wait_for_neo4j(client, max_retries: int = 30, retry_interval: int = 2) -> bool:
    """
    Wait for Neo4j to be ready to accept connections.
    
    Args:
        client: Neo4jClient instance
        max_retries: Maximum number of connection attempts
        retry_interval: Seconds between retries
        
    Returns:
        True if connected successfully, False otherwise
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempting to connect to Neo4j (attempt {attempt}/{max_retries})...")
            client.connect()
            logger.info("Successfully connected to Neo4j")
            return True
        except Exception as e:
            logger.warning(f"Connection failed: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
            else:
                logger.error("Max retries reached. Could not connect to Neo4j.")
                return False
    return False


def check_schema_exists(client) -> bool:
    """
    Check if schema has already been initialized.
    
    Looks for the presence of key constraints as an indicator.
    
    Args:
        client: Neo4jClient instance
        
    Returns:
        True if schema appears to be initialized
    """
    try:
        result = client.execute_query(
            "SHOW CONSTRAINTS WHERE name = 'resource_url_hash'"
        )
        return len(result) > 0
    except Exception as e:
        logger.warning(f"Could not check schema status: {e}")
        return False


def check_base_data_exists(client) -> bool:
    """
    Check if base data has already been loaded.
    
    Looks for the presence of Organization nodes as an indicator.
    
    Args:
        client: Neo4jClient instance
        
    Returns:
        True if base data appears to be loaded
    """
    try:
        result = client.execute_query(
            "MATCH (o:Organization) RETURN count(o) as count"
        )
        count = result[0]["count"] if result else 0
        return count > 0
    except Exception as e:
        logger.warning(f"Could not check base data status: {e}")
        return False


def main():
    """Main initialization routine."""
    logger.info("=" * 60)
    logger.info("Neo4j Initialization Service Starting")
    logger.info("=" * 60)
    
    # Import here to avoid issues if neo4j_client not installed
    try:
        from neo4j_client import Neo4jClient, GraphRepository
    except ImportError as e:
        logger.error(f"Failed to import neo4j_client: {e}")
        sys.exit(1)
    
    # Get configuration from environment
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "neo4j")
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")
    
    logger.info(f"Neo4j URI: {neo4j_uri}")
    logger.info(f"Neo4j Database: {neo4j_database}")
    
    # Create client
    client = Neo4jClient(
        uri=neo4j_uri,
        user=neo4j_user,
        password=neo4j_password,
        database=neo4j_database,
        logger_instance=logger
    )
    
    # Wait for Neo4j to be ready
    if not wait_for_neo4j(client):
        logger.error("Failed to connect to Neo4j. Exiting.")
        sys.exit(1)
    
    try:
        # Check and create schema
        schema_exists = check_schema_exists(client)
        if schema_exists:
            logger.info("Schema already exists, skipping schema creation")
        else:
            logger.info("Creating schema (constraints and indexes)...")
            client.setup_schema()
            logger.info("Schema created successfully")
        
        # Check and load base data
        repo = GraphRepository(client, logger_instance=logger)
        base_data_exists = check_base_data_exists(client)
        if base_data_exists:
            logger.info("Base data already exists, skipping base data initialization")
        else:
            logger.info("Loading base data (organizations and data sources)...")
            repo.initialize_base_data()
            logger.info("Base data loaded successfully")
        
        logger.info("=" * 60)
        logger.info("Neo4j Initialization Complete")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        client.close()
    
    sys.exit(0)


if __name__ == "__main__":
    main()
