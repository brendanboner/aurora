#!/usr/bin/env python3
"""
Backfill embeddings for existing Resources in Neo4j.

This script generates embeddings for Resource nodes that don't have them,
enabling vector similarity search for historical documents.

Usage:
    python -m scripts.backfill_embeddings [options]

Options:
    --node-type     Node type to backfill (resource, topic, organization) [default: resource]
    --batch-size    Number of nodes per batch [default: 100]
    --max-nodes     Maximum nodes to process (0 = all) [default: 0]
    --dry-run       Preview without making changes [default: false]
    --force         Re-embed nodes that already have embeddings [default: false]

Environment Variables:
    NEO4J_URI                       Neo4j connection URI
    NEO4J_USERNAME                  Neo4j username
    NEO4J_PASSWORD                  Neo4j password
    AZURE_OPENAI_API_KEY           Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT          Azure OpenAI endpoint
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT  Embedding model deployment name
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Suppress verbose neo4j driver logs
logging.getLogger('neo4j').setLevel(logging.WARNING)


def get_neo4j_driver():
    """Create Neo4j driver from environment variables."""
    uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    username = os.getenv('NEO4J_USERNAME', 'neo4j')
    password = os.getenv('NEO4J_PASSWORD', 'password')
    
    logger.info(f"Connecting to Neo4j at {uri}...")
    return GraphDatabase.driver(uri, auth=(username, password))


def get_openai_client():
    """Create Azure OpenAI client for embeddings."""
    try:
        from openai import AzureOpenAI
    except ImportError:
        logger.error("openai package not installed. Run: pip install openai")
        sys.exit(1)
    
    api_key = os.getenv('AZURE_OPENAI_API_KEY')
    endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
    api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-08-01-preview')
    
    if not api_key or not endpoint:
        logger.error("AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT must be set")
        sys.exit(1)
    
    return AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )


def get_embedding_text_resource(props: dict) -> str:
    """Build embedding text for a Resource node."""
    parts = []
    
    if props.get("title"):
        parts.append(f"Title: {props['title']}")
    
    if props.get("summary"):
        parts.append(f"Summary: {props['summary']}")
    
    return "\n".join(parts) if parts else ""


def get_embedding_text_topic(props: dict) -> str:
    """Build embedding text for a Topic node."""
    parts = [f"Topic: {props.get('name', '')}"]
    
    if props.get("description"):
        parts.append(f"Description: {props['description']}")
    
    if props.get("aliases"):
        aliases = props["aliases"]
        if isinstance(aliases, list):
            parts.append(f"Also known as: {', '.join(aliases)}")
        else:
            parts.append(f"Also known as: {aliases}")
    
    return "\n".join(parts)


def get_embedding_text_organization(props: dict) -> str:
    """Build embedding text for an Organization node."""
    parts = [f"Organization: {props.get('name', '')}"]
    
    if props.get("description"):
        parts.append(f"Description: {props['description']}")
    
    if props.get("aliases"):
        aliases = props["aliases"]
        if isinstance(aliases, list):
            parts.append(f"Also known as: {', '.join(aliases)}")
        else:
            parts.append(f"Also known as: {aliases}")
    
    return "\n".join(parts)


def get_embedding_text(node_type: str, props: dict) -> str:
    """Get embedding text based on node type."""
    if node_type == "resource":
        return get_embedding_text_resource(props)
    elif node_type == "topic":
        return get_embedding_text_topic(props)
    elif node_type == "organization":
        return get_embedding_text_organization(props)
    else:
        raise ValueError(f"Unknown node type: {node_type}")


def get_id_field(node_type: str) -> str:
    """Get the ID field name for a node type."""
    return {
        "resource": "url_hash",
        "topic": "topic_id",
        "organization": "org_id",
    }.get(node_type, "id")


def count_nodes_needing_embeddings(session, node_type: str, force: bool) -> int:
    """Count nodes that need embeddings."""
    label = node_type.capitalize()
    
    if force:
        query = f"MATCH (n:{label}) RETURN count(n) AS count"
    else:
        query = f"MATCH (n:{label}) WHERE n.embedding IS NULL OR size(n.embedding) = 0 RETURN count(n) AS count"
    
    result = session.run(query)
    record = result.single()
    return record["count"] if record else 0


def fetch_nodes_batch(
    session,
    node_type: str,
    batch_size: int,
    skip: int,
    force: bool,
) -> list[dict]:
    """Fetch a batch of nodes that need embeddings."""
    label = node_type.capitalize()
    id_field = get_id_field(node_type)
    
    if force:
        query = f"""
        MATCH (n:{label})
        RETURN n, n.{id_field} AS id
        ORDER BY n.{id_field}
        SKIP $skip
        LIMIT $limit
        """
    else:
        query = f"""
        MATCH (n:{label})
        WHERE n.embedding IS NULL OR size(n.embedding) = 0
        RETURN n, n.{id_field} AS id
        ORDER BY n.{id_field}
        SKIP $skip
        LIMIT $limit
        """
    
    result = session.run(query, skip=skip, limit=batch_size)
    
    nodes = []
    for record in result:
        node = record["n"]
        props = dict(node)
        props["_id"] = record["id"]
        nodes.append(props)
    
    return nodes


def generate_embeddings_batch(
    client,
    texts: list[str],
    deployment: str,
) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    # Filter out empty texts
    valid_indices = [i for i, t in enumerate(texts) if t and t.strip()]
    valid_texts = [texts[i] for i in valid_indices]
    
    if not valid_texts:
        return [[0.0] * 1536 for _ in texts]
    
    response = client.embeddings.create(
        input=valid_texts,
        model=deployment,
    )
    
    # Map embeddings back to original positions
    embeddings = [[0.0] * 1536 for _ in texts]
    for idx, valid_idx in enumerate(valid_indices):
        embeddings[valid_idx] = response.data[idx].embedding
    
    return embeddings


def update_embeddings_batch(
    session,
    node_type: str,
    updates: list[dict],
) -> int:
    """Update embeddings for a batch of nodes."""
    label = node_type.capitalize()
    id_field = get_id_field(node_type)
    
    query = f"""
    UNWIND $updates AS update
    MATCH (n:{label} {{{id_field}: update.id}})
    SET n.embedding = update.embedding
    RETURN count(n) AS updated
    """
    
    result = session.run(query, updates=updates)
    record = result.single()
    return record["updated"] if record else 0


def backfill_embeddings(
    node_type: str,
    batch_size: int = 100,
    max_nodes: int = 0,
    dry_run: bool = False,
    force: bool = False,
):
    """Main backfill function."""
    driver = get_neo4j_driver()
    openai_client = get_openai_client()
    deployment = os.getenv('AZURE_OPENAI_EMBEDDING_DEPLOYMENT', 'text-embedding-3-small')
    
    logger.info(f"Using embedding model: {deployment}")
    
    try:
        with driver.session() as session:
            # Count nodes needing embeddings
            total_nodes = count_nodes_needing_embeddings(session, node_type, force)
            
            if max_nodes > 0:
                total_nodes = min(total_nodes, max_nodes)
            
            logger.info(f"Found {total_nodes} {node_type} nodes to process")
            
            if total_nodes == 0:
                logger.info("No nodes need embeddings. Done!")
                return
            
            if dry_run:
                logger.info("DRY RUN - no changes will be made")
            
            # Process in batches
            processed = 0
            updated = 0
            skipped = 0
            errors = 0
            start_time = time.time()
            
            while processed < total_nodes:
                batch_start = time.time()
                
                # Fetch batch
                nodes = fetch_nodes_batch(
                    session, node_type, batch_size, 0 if not force else processed, force
                )
                
                if not nodes:
                    break
                
                # Generate embedding texts
                texts = []
                valid_nodes = []
                
                for node in nodes:
                    text = get_embedding_text(node_type, node)
                    if text and text.strip():
                        texts.append(text)
                        valid_nodes.append(node)
                    else:
                        skipped += 1
                        logger.debug(f"Skipping node {node.get('_id')} - no embedding text")
                
                if not texts:
                    processed += len(nodes)
                    continue
                
                # Generate embeddings
                try:
                    embeddings = generate_embeddings_batch(openai_client, texts, deployment)
                except Exception as e:
                    logger.error(f"Embedding generation failed: {e}")
                    errors += len(texts)
                    processed += len(nodes)
                    continue
                
                # Update nodes (unless dry run)
                if not dry_run:
                    updates = [
                        {"id": node["_id"], "embedding": emb}
                        for node, emb in zip(valid_nodes, embeddings)
                        if emb and any(v != 0.0 for v in emb)
                    ]
                    
                    if updates:
                        batch_updated = update_embeddings_batch(session, node_type, updates)
                        updated += batch_updated
                
                processed += len(nodes)
                batch_time = time.time() - batch_start
                
                # Progress logging
                pct = (processed / total_nodes) * 100
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (total_nodes - processed) / rate if rate > 0 else 0
                
                logger.info(
                    f"Progress: {processed}/{total_nodes} ({pct:.1f}%) | "
                    f"Updated: {updated} | Skipped: {skipped} | Errors: {errors} | "
                    f"Batch: {batch_time:.1f}s | ETA: {eta:.0f}s"
                )
                
                # Rate limiting - be nice to Azure OpenAI
                if batch_time < 1.0:
                    time.sleep(1.0 - batch_time)
            
            # Final summary
            total_time = time.time() - start_time
            logger.info(f"\n{'='*60}")
            logger.info(f"Backfill {'(DRY RUN) ' if dry_run else ''}complete!")
            logger.info(f"  Node type: {node_type}")
            logger.info(f"  Processed: {processed}")
            logger.info(f"  Updated: {updated}")
            logger.info(f"  Skipped: {skipped}")
            logger.info(f"  Errors: {errors}")
            logger.info(f"  Total time: {total_time:.1f}s")
            logger.info(f"{'='*60}")
            
    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for Neo4j nodes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--node-type",
        choices=["resource", "topic", "organization"],
        default="resource",
        help="Node type to backfill (default: resource)",
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of nodes per batch (default: 100)",
    )
    
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=0,
        help="Maximum nodes to process, 0 = all (default: 0)",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without making changes",
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed nodes that already have embeddings",
    )
    
    args = parser.parse_args()
    
    backfill_embeddings(
        node_type=args.node_type,
        batch_size=args.batch_size,
        max_nodes=args.max_nodes,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    main()
