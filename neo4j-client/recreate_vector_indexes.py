#!/usr/bin/env python3
"""
Script to drop and recreate vector indexes with new dimensions.

Run this after changing embedding dimensions to recreate all vector indexes.
"""

import os
import sys
from neo4j import GraphDatabase

def recreate_vector_indexes():
    """Drop old vector indexes and create new ones with updated dimensions."""
    
    # Get Neo4j credentials from environment
    uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    username = os.getenv('NEO4J_USERNAME', 'neo4j')
    password = os.getenv('NEO4J_PASSWORD', 'password')
    
    print(f"Connecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(username, password))
    
    try:
        with driver.session() as session:
            # Drop existing indexes
            print("\nDropping existing vector indexes...")
            drop_commands = [
                "DROP INDEX resource_embedding_index IF EXISTS",
                "DROP INDEX topic_embedding_index IF EXISTS",
                "DROP INDEX organization_embedding_index IF EXISTS",
                "DROP INDEX datasource_embedding_index IF EXISTS",
                "DROP INDEX person_embedding_index IF EXISTS",
                "DROP INDEX event_embedding_index IF EXISTS",
            ]
            
            for cmd in drop_commands:
                print(f"  {cmd}")
                session.run(cmd)
            
            print("\nCreating new vector indexes with 1536 dimensions...")
            create_commands = [
                "CREATE VECTOR INDEX resource_embedding_index IF NOT EXISTS FOR (r:Resource) ON r.embedding OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
                "CREATE VECTOR INDEX topic_embedding_index IF NOT EXISTS FOR (t:Topic) ON t.embedding OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
                "CREATE VECTOR INDEX organization_embedding_index IF NOT EXISTS FOR (o:Organization) ON o.embedding OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
                "CREATE VECTOR INDEX datasource_embedding_index IF NOT EXISTS FOR (ds:DataSource) ON ds.embedding OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
                "CREATE VECTOR INDEX person_embedding_index IF NOT EXISTS FOR (p:Person) ON p.embedding OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
                "CREATE VECTOR INDEX event_embedding_index IF NOT EXISTS FOR (e:Event) ON e.embedding OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
            ]
            
            for cmd in create_commands:
                print(f"  Creating index...")
                session.run(cmd)
            
            print("\n✅ Vector indexes recreated successfully!")
            print("\nNote: Indexes may take a few moments to build if you have existing data.")
            print("Check index status with: SHOW INDEXES")
            
    finally:
        driver.close()

if __name__ == "__main__":
    try:
        recreate_vector_indexes()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
