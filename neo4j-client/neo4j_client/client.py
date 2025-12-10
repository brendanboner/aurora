"""Neo4j client for knowledge graph operations."""

from neo4j import GraphDatabase
from typing import Dict, Any, List, Optional
import logging
import json
from pathlib import Path


logger = logging.getLogger(__name__)


class Neo4jClient:
    """Client for connecting to and interacting with Neo4j."""
    
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        logger_instance: Optional[logging.Logger] = None
    ):
        """
        Initialize Neo4j client.
        
        Args:
            uri: Neo4j connection URI (e.g., "bolt://localhost:7687")
            user: Neo4j username
            password: Neo4j password
            database: Database name (default: "neo4j")
            logger_instance: Optional logger instance. If not provided, uses module logger
        """
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.driver = None
        self.logger = logger_instance or logger
    
    def connect(self):
        """Establish connection to Neo4j."""
        self.logger.info(f"Connecting to Neo4j at {self.uri}")
        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password)
        )
        # Test connection
        self.driver.verify_connectivity()
        self.logger.info("Successfully connected to Neo4j")
    
    def close(self):
        """Close the connection."""
        if self.driver:
            self.driver.close()
            self.logger.info("Neo4j connection closed")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    def execute_query(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query (read operation).
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            List of result records as dictionaries
        """
        if not self.driver:
            self.connect()
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]
    
    def execute_write(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a write transaction.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            List of result records as dictionaries
        """
        if not self.driver:
            self.connect()
        
        def _transaction(tx):
            result = tx.run(query, parameters or {})
            return [record.data() for record in result]
        
        with self.driver.session(database=self.database) as session:
            return session.execute_write(_transaction)
    
    def setup_schema(self):
        """Create schema for the neo4j database including constraints and indexes."""
        self.logger.info("Setting up database schema (constraints and indexes)...")
        
        constraints = [
            # Resource: url_hash is unique
            "CREATE CONSTRAINT resource_url_hash IF NOT EXISTS FOR (r:Resource) REQUIRE r.url_hash IS UNIQUE",
            # Topic: topic_id is unique
            "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE",
            # Organization: org_id is unique
            "CREATE CONSTRAINT organization_org_id IF NOT EXISTS FOR (o:Organization) REQUIRE o.org_id IS UNIQUE",
            # DataSource: source_id is unique
            "CREATE CONSTRAINT datasource_source_id IF NOT EXISTS FOR (ds:DataSource) REQUIRE ds.source_id IS UNIQUE",
            # Person: person_id is unique
            "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.person_id IS UNIQUE",
            # Event: url_hash is unique (same pattern as Resource)
            "CREATE CONSTRAINT event_url_hash IF NOT EXISTS FOR (e:Event) REQUIRE e.url_hash IS UNIQUE",
            # IngestionBatch: batch_id is unique
            "CREATE CONSTRAINT ingestion_batch_id IF NOT EXISTS FOR (b:IngestionBatch) REQUIRE b.batch_id IS UNIQUE",
            # Team: name is unique
            "CREATE CONSTRAINT team_name IF NOT EXISTS FOR (t:Team) REQUIRE t.name IS UNIQUE",
            # Project: name is unique
            "CREATE CONSTRAINT project_name IF NOT EXISTS FOR (p:Project) REQUIRE p.name IS UNIQUE",
            # Skill: name is unique
            "CREATE CONSTRAINT skill_name IF NOT EXISTS FOR (s:Skill) REQUIRE s.name IS UNIQUE",
            # Tag: name is unique
            "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE",

            # Vector indexes for embeddings (using Neo4j vector search)
            # Resource embedding
            "CREATE VECTOR INDEX resource_embedding_index IF NOT EXISTS FOR (r:Resource) ON r.embedding OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            # Topic embedding
            "CREATE VECTOR INDEX topic_embedding_index IF NOT EXISTS FOR (t:Topic) ON t.embedding OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            # Organization embedding
            "CREATE VECTOR INDEX organization_embedding_index IF NOT EXISTS FOR (o:Organization) ON o.embedding OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            # DataSource embedding
            "CREATE VECTOR INDEX datasource_embedding_index IF NOT EXISTS FOR (ds:DataSource) ON ds.embedding OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            # Person embedding
            "CREATE VECTOR INDEX person_embedding_index IF NOT EXISTS FOR (p:Person) ON p.embedding OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            # Event embedding
            "CREATE VECTOR INDEX event_embedding_index IF NOT EXISTS FOR (e:Event) ON e.embedding OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            
            # Temporal indexes for date-based queries
            "CREATE INDEX event_start_date IF NOT EXISTS FOR (e:Event) ON (e.start_date)",
            "CREATE INDEX event_last_updated IF NOT EXISTS FOR (e:Event) ON (e.last_updated)",
            "CREATE INDEX event_status IF NOT EXISTS FOR (e:Event) ON (e.status)",
            "CREATE INDEX resource_publish_date IF NOT EXISTS FOR (r:Resource) ON (r.publish_date)",
            "CREATE INDEX resource_content_changed_at IF NOT EXISTS FOR (r:Resource) ON (r.content_changed_at)",
            "CREATE INDEX resource_created_at IF NOT EXISTS FOR (r:Resource) ON (r.created_at)",
            
            # IngestionBatch indexes for reconciliation queries
            "CREATE INDEX ingestion_batch_status IF NOT EXISTS FOR (b:IngestionBatch) ON (b.status)",
            "CREATE INDEX ingestion_batch_reconciled_at IF NOT EXISTS FOR (b:IngestionBatch) ON (b.reconciled_at)",
            
            # DataSource index for event reconciliation filtering
            "CREATE INDEX datasource_has_events IF NOT EXISTS FOR (ds:DataSource) ON (ds.has_events)",
            
            # Topic index for created_by (used by curator to find digester-created topics)
            "CREATE INDEX topic_created_by IF NOT EXISTS FOR (t:Topic) ON (t.created_by)",
        ]
        
        for constraint in constraints:
            try:
                self.execute_write(constraint)
                constraint_desc = constraint.split('FOR')[1].split('REQUIRE')[0].strip()
                self.logger.debug(f"Created constraint/index: {constraint_desc}")
            except Exception as e:
                # Constraint might already exist
                self.logger.debug(f"Constraint creation skipped: {e}")
        self.logger.info("Database schema setup complete")
    
    def clear_database(self, confirm: bool = False):
        """
        Clear all nodes and relationships from the database.
        
        Args:
            confirm: Must be True to actually clear the database (safety check)
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to clear database")
        
        self.logger.warning("Clearing entire database...")
        query = "MATCH (n) DETACH DELETE n"
        self.execute_write(query)
        self.logger.info("Database cleared")
