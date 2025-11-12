import abc
import aiohttp
import json
import time
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass

from rabbitmq_client.producer import RabbitMQProducer
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
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
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
        """Abstract method that each scraper must implement for daily execution"""
        pass
    
    @abc.abstractmethod 
    async def run_full_scraper(self):
        """Abstract method that each scraper must implement for full database population"""
        pass
    
    @abc.abstractmethod
    async def scrape_resource(self, resource: Resource) -> Resource:
        """Abstract method that each scraper must implement to scrape individual resources"""
        pass