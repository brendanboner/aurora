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
    resource_type: str
    content: Optional[str] = None
    publish_date: Optional[str] = None
    source: Optional[str] = None  # Which scraper/site this came from

class BaseScraper:
    """Base class for all scrapers with common RabbitMQ publishing functionality"""
    
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
            "resource_type": resource.resource_type,
            "content": (resource.content[:content_limit] + "...") if resource.content and len(resource.content) > content_limit else resource.content,
            "publish_date": resource.publish_date,
            "source": resource.source
        }
    
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
            'resource_type': resource.resource_type,
            'content': resource.content,
            'publish_date': resource.publish_date,
            'source': resource.source,
            'timestamp': time.time()
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