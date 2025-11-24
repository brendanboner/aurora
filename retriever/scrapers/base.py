import abc
import aiohttp
import json
import time
import logging
import hashlib
from typing import Any, Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime
import redis

from rabbitmq_client.producer import RabbitMQProducer
from neo4j_client.client import Neo4jClient
from settings import settings

@dataclass
class Resource:
    """Base resource data structure that all scrapers should use"""
    title: str
    url: str
    category: str
    content: Optional[str] = None
    publish_date: Optional[str] = None
    datasource_id: Optional[str] = None  # Which scraper/site this came from

class BaseScraper:
    """Base class for all scrapers with common RabbitMQ publishing functionality"""
    
    # Subclasses can override this to set their scraper name for file naming
    scraper_name: str = "default"
    
    def __init__(self):
        # Suppress verbose pika logging - only show errors
        logging.getLogger('pika').setLevel(logging.ERROR)
        
        # Initialize RabbitMQ producer using settings
        self.rabbitmq_producer = RabbitMQProducer(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            user=settings.rabbitmq_user,
            password=settings.rabbitmq_password,
            queue=settings.rabbitmq_queue
        )
        self.session = None
        
        # Resolve JSON output file with scraper name placeholder
        self.json_file = settings.json_output_file.replace('{scraper}', self.scraper_name)
        
        # Initialize Neo4j client for URL checking
        try:
            self.neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database
            )
            self.neo4j_client.connect()
            logging.info("Neo4j connection established for URL deduplication")
        except Exception as e:
            logging.warning(f"Failed to connect to Neo4j: {e}. URL deduplication will be disabled.")
            self.neo4j_client = None
        
        # Initialize Redis for monitoring
        try:
            self.redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
                socket_connect_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            logging.info("Redis connection established for monitoring")
        except Exception as e:
            logging.warning(f"Failed to connect to Redis: {e}. Monitoring will be disabled.")
            self.redis_client = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
        if self.neo4j_client:
            self.neo4j_client.close()
    
    def update_heartbeat(self):
        """Update retriever heartbeat timestamp in Redis."""
        if self.redis_client:
            try:
                self.redis_client.set("retriever:heartbeat", datetime.now().timestamp(), ex=300)
            except Exception as e:
                logging.warning(f"Failed to update heartbeat: {e}")
    
    def update_current_processing(self, resource: Resource, stage: str):
        """Update current processing status in Redis."""
        if self.redis_client:
            try:
                processing_data = {
                    "title": resource.title,
                    "url": resource.url,
                    "category": resource.category,
                    "status": "retrieving",
                    "stage": stage,
                    "started_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                self.redis_client.set("retriever:current", json.dumps(processing_data), ex=300)
            except Exception as e:
                logging.warning(f"Failed to update current processing: {e}")
    
    def clear_current_processing(self):
        """Clear current processing status in Redis."""
        if self.redis_client:
            try:
                self.redis_client.delete("retriever:current")
            except Exception as e:
                logging.warning(f"Failed to clear current processing: {e}")
    
    def _compute_url_hash(self, url: str) -> str:
        """
        Compute SHA256 hash of a URL.
        
        Args:
            url: URL to hash
            
        Returns:
            SHA256 hash of the URL as a hex string
        """
        return hashlib.sha256(url.encode('utf-8')).hexdigest()
    
    def url_exists_in_db(self, url: str) -> bool:
        """
        Check if a URL already exists in the Neo4j database.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL exists in database, False otherwise
        """
        if not self.neo4j_client:
            # If Neo4j is not available, assume URL doesn't exist (fail open)
            logging.warning("Neo4j client not available, cannot check for duplicate URLs")
            return False
        
        try:
            url_hash = self._compute_url_hash(url)
            query = """
            MATCH (r:Resource {url_hash: $url_hash})
            RETURN r.url_hash as url_hash
            LIMIT 1
            """
            result = self.neo4j_client.execute_query(query, {"url_hash": url_hash})
            return len(result) > 0
        except Exception as e:
            logging.error(f"Error checking URL existence in Neo4j: {e}")
            # Fail open - if we can't check, assume it doesn't exist
            return False
    
    def filter_new_urls(self, resources: List[Resource]) -> List[Resource]:
        """
        Filter out resources whose URLs already exist in the database.
        
        Args:
            resources: List of Resource objects to filter
            
        Returns:
            List of Resource objects with only new URLs (not in database)
        """
        if not self.neo4j_client:
            logging.warning("Neo4j client not available, skipping URL deduplication")
            return resources
        
        new_resources = []
        duplicate_count = 0
        
        for resource in resources:
            if not self.url_exists_in_db(resource.url):
                new_resources.append(resource)
            else:
                duplicate_count += 1
                logging.debug(f"Skipping duplicate URL: {resource.url}")
        
        if duplicate_count > 0:
            logging.info(f"Filtered out {duplicate_count} duplicate URLs, {len(new_resources)} new URLs remain")
        
        return new_resources
    
    def _format_resource_for_logging(self, resource: Resource, content_limit: int = 50) -> Dict[str, Any]:
        """Helper method to format a resource for JSON logging"""
        return {
            "title": resource.title,
            "url": resource.url,
            "category": resource.category,
            "content": (resource.content[:content_limit] + "...") if resource.content and len(resource.content) > content_limit else resource.content,
            "publish_date": resource.publish_date,
            "datasource_id": resource.datasource_id
        }
    
    def publish_to_json(self, resource: Resource, additional_fields: Optional[Dict[str, Any]] = None):
        """
        Write scraped content to a JSON file (one message per line - JSONL format)
        
        Args:
            resource: The Resource object to publish
            additional_fields: Optional dict of additional fields to include in the message
        """
        # Base message structure
        message = {
            'title': resource.title,
            'url': resource.url,
            'category': resource.category,
            'content': resource.content,
            'publish_date': resource.publish_date,
            'datasource_id': resource.datasource_id,
            'scraped_at': time.time()
        }
        
        # Add any additional fields provided by the specific scraper
        if additional_fields:
            message.update(additional_fields)
        
        try:
            with open(self.json_file, 'a', encoding='utf-8') as f:
                json.dump(message, f, ensure_ascii=False)
                f.write('\n')
            logging.debug(f"Message written to {self.json_file}")
        except Exception as e:
            logging.error(f"Error writing to JSON file '{self.json_file}': {e}")
            raise
    
    def publish_message(self, resource: Resource, additional_fields: Optional[Dict[str, Any]] = None):
        """
        General publish function that routes to JSON file or RabbitMQ based on settings.
        
        Args:
            resource: The Resource object to publish
            additional_fields: Optional dict of additional fields to include in the message
        """
        if settings.output_mode == "json":
            self.publish_to_json(resource, additional_fields)
        else:
            self.publish_to_rabbitmq(resource, additional_fields)
    
    def publish_to_rabbitmq(self, resource: Resource, additional_fields: Optional[Dict[str, Any]] = None):
        """
        Publish scraped content to RabbitMQ queue
        
        Args:
            resource: The Resource object to publish
            additional_fields: Optional dict of additional fields to include in the message
        """
        # Base message structure
        message = {
            'title': resource.title,
            'url': resource.url,
            'category': resource.category,
            'content': resource.content,
            'publish_date': resource.publish_date,
            'datasource_id': resource.datasource_id,
            'scraped_at': time.time()
        }
        
        # Add any additional fields provided by the specific scraper
        if additional_fields:
            message.update(additional_fields)
            
        try:
            # Use the RabbitMQProducer client
            self.rabbitmq_producer.publish(message)
            
        except Exception as e:
            logging.error(f"Error publishing to RabbitMQ queue '{settings.rabbitmq_queue}': {e}")
            raise  # Re-raise so calling code can handle if needed
    
    @abc.abstractmethod
    async def run_scraper(self):
        """Abstract method that each scraper must implement for scraping execution"""
        pass
    
    @abc.abstractmethod
    async def scrape_resource(self, resource: Resource) -> Resource:
        """Abstract method that each scraper must implement to scrape individual resources"""
        pass