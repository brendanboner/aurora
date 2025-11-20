#!/usr/bin/env python3
"""
Script to reprocess a specific document from the knowledge graph.
Fetches the document URL and resends it through the digester pipeline.
"""

import os
import sys
import json
import requests

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'neo4j-client'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rabbitmq-client'))

from neo4j_client.client import Neo4jClient
from rabbitmq_client.producer import RabbitMQProducer


def fetch_webpage_content(url):
    """Fetch text content from a webpage using retriever API."""
    try:
        # Try to use the retriever API if available
        retriever_url = os.getenv('RETRIEVER_URL', 'http://localhost:8001')
        response = requests.post(
            f"{retriever_url}/scrape",
            json={"url": url},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get('content', '')
        else:
            print(f"Retriever API returned status {response.status_code}")
            print("Note: Content will need to be scraped. The document will be queued for processing.")
            return None
    except Exception as e:
        print(f"Error fetching content via retriever: {e}")
        print("Note: Content will need to be scraped. The document will be queued for processing.")
        return None


def reprocess_document(person_name=None, url=None):
    """
    Reprocess a document by fetching it from Neo4j and resending to RabbitMQ.
    
    Args:
        person_name: Name of person to find document for (e.g., "David Coleman")
        url: Direct URL of document to reprocess
    """
    # Connect to Neo4j
    neo4j_uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PASSWORD', 'password')
    
    client = Neo4jClient(uri=neo4j_uri, user=neo4j_user, password=neo4j_password, database='neo4j')
    client.connect()
    
    # Find document
    if person_name:
        query = '''
        MATCH (r:Resource)-[:MENTIONS]->(p:Person {name: $person_name})
        RETURN r.url as url, r.title as title, r.category as category, 
               r.publish_date as publish_date, r.datasource_id as datasource_id,
               r.scraped_at as scraped_at
        LIMIT 1
        '''
        results = client.execute_query(query, {'person_name': person_name})
    elif url:
        query = '''
        MATCH (r:Resource {url: $url})
        RETURN r.url as url, r.title as title, r.category as category,
               r.publish_date as publish_date, r.datasource_id as datasource_id,
               r.scraped_at as scraped_at
        '''
        results = client.execute_query(query, {'url': url})
    else:
        print("Error: Must provide either person_name or url")
        return
    
    if not results:
        print(f"No document found for {person_name or url}")
        return
    
    doc = results[0]
    print(f"Found document: {doc['title']}")
    print(f"URL: {doc['url']}")
    
    # Fetch fresh content from the URL
    print("\nFetching fresh content from URL...")
    content = fetch_webpage_content(doc['url'])
    
    if not content:
        print("\nWARNING: Could not fetch fresh content from URL.")
        print("Using placeholder content. You may need to manually provide the content")
        print("or ensure the retriever service is running and accessible.")
        content = f"[Content to be rescraped for: {doc['title']}]"
    else:
        print(f"Fetched {len(content)} characters of content")
    
    # Create message for digester
    message = {
        "title": doc['title'],
        "url": doc['url'],
        "category": doc['category'],
        "content": content,
        "publish_date": doc['publish_date'],
        "datasource_id": doc['datasource_id'],
        "scraped_at": doc['scraped_at']
    }
    
    # Delete existing resource and relationships to allow fresh ingestion
    print("\nDeleting existing resource and relationships...")
    delete_query = '''
    MATCH (r:Resource {url: $url})
    DETACH DELETE r
    '''
    client.execute_write(delete_query, {'url': doc['url']})
    print("✓ Deleted existing resource")
    
    # Send to RabbitMQ
    print("\nSending document to RabbitMQ for reprocessing...")
    
    rabbitmq_host = os.getenv('RABBITMQ_HOST', 'localhost')
    rabbitmq_port = int(os.getenv('RABBITMQ_PORT', 5672))
    rabbitmq_user = os.getenv('RABBITMQ_USER', 'guest')
    rabbitmq_password = os.getenv('RABBITMQ_PASSWORD', 'guest')
    queue_name = os.getenv('RABBITMQ_QUEUE', 'documents')
    
    producer = RabbitMQProducer(
        host=rabbitmq_host,
        port=rabbitmq_port,
        user=rabbitmq_user,
        password=rabbitmq_password,
        queue=queue_name
    )
    
    producer.connect()
    producer.publish_message(message)
    producer.close()
    
    print("✓ Document sent to digester queue")
    print("\nReprocessing initiated! The digester will extract metadata and rebuild relationships.")
    print(f"Monitor the digester logs: docker-compose logs -f digester")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Reprocess a document through the digester pipeline')
    parser.add_argument('--person', help='Name of person to find document for (e.g., "David Coleman")')
    parser.add_argument('--url', help='Direct URL of document to reprocess')
    
    args = parser.parse_args()
    
    if not args.person and not args.url:
        print("Error: Must provide either --person or --url")
        parser.print_help()
        sys.exit(1)
    
    reprocess_document(person_name=args.person, url=args.url)
