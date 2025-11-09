"""Neo4j client for knowledge graph operations."""

from neo4j import GraphDatabase
from typing import Dict, Any, List, Optional
import logging


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
    
    def create_constraints(self):
        """Create unique constraints for all node types."""
        constraints = [
            "CREATE CONSTRAINT resource_url IF NOT EXISTS FOR (r:Resource) REQUIRE r.url IS UNIQUE",
            "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT standard_name IF NOT EXISTS FOR (s:Standard) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT standard_edition_name IF NOT EXISTS FOR (se:StandardEdition) REQUIRE se.name IS UNIQUE",
            "CREATE CONSTRAINT organization_name IF NOT EXISTS FOR (o:Organization) REQUIRE o.name IS UNIQUE",
            "CREATE CONSTRAINT datasource_name IF NOT EXISTS FOR (ds:DataSource) REQUIRE ds.name IS UNIQUE",
            "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT team_name IF NOT EXISTS FOR (t:Team) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT project_name IF NOT EXISTS FOR (p:Project) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT skill_name IF NOT EXISTS FOR (s:Skill) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE",
        ]
        
        for constraint in constraints:
            try:
                self.execute_write(constraint)
                constraint_desc = constraint.split('FOR')[1].split('REQUIRE')[0].strip()
                self.logger.info(f"Created constraint: {constraint_desc}")
            except Exception as e:
                # Constraint might already exist
                self.logger.debug(f"Constraint creation skipped: {e}")
        
        self.logger.info("Constraints setup complete")
    
    def initialize_base_data(self, organizations: Optional[List[Dict[str, str]]] = None, 
                            data_sources: Optional[List[Dict[str, str]]] = None):
        """
        Initialize base organizations and data sources.
        
        Args:
            organizations: List of organization dicts with 'name' and 'description'
            data_sources: List of data source dicts with 'name', 'url', and 'source_type'
        """
        # Default organizations if none provided
        if organizations is None:
            organizations = [
                {"name": "Wi-Fi Alliance", "description": "Global network of companies that brings Wi-Fi technology to users"},
                {"name": "IEEE", "description": "Institute of Electrical and Electronics Engineers"},
                {"name": "IETF", "description": "Internet Engineering Task Force"},
                {"name": "3GPP", "description": "3rd Generation Partnership Project"},
            ]
        
        # Default data sources if none provided
        if data_sources is None:
            data_sources = [
                {"name": "wi-fi-alliance", "url": "https://www.wi-fi.org", "source_type": "organization_website"},
                {"name": "ieee-standards", "url": "https://standards.ieee.org", "source_type": "standards_body"},
                {"name": "ietf-rfcs", "url": "https://www.ietf.org/rfc", "source_type": "standards_body"},
            ]
        
        # Create organizations
        for org in organizations:
            query = """
            MERGE (o:Organization {name: $name})
            ON CREATE SET 
                o.description = $description,
                o.created_at = datetime()
            RETURN o
            """
            self.execute_write(query, org)
            self.logger.info(f"Created/updated organization: {org['name']}")
        
        # Create data sources
        for ds in data_sources:
            query = """
            MERGE (ds:DataSource {name: $name})
            ON CREATE SET 
                ds.url = $url,
                ds.source_type = $source_type,
                ds.created_at = datetime()
            RETURN ds
            """
            self.execute_write(query, ds)
            self.logger.info(f"Created/updated data source: {ds['name']}")
        
        self.logger.info("Base data initialization complete")
    
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
