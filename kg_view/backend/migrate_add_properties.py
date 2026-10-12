"""
Neo4j Migration Script: Add importance and tier properties to nodes

This script adds importance scores and tier levels to all nodes in the knowledge graph.
Importance is calculated based on:
- Number of incoming relationships (higher = more important)
- Node type (some types are inherently more important)
- Explicit curation (for Topics)

Tier is assigned based on topic hierarchy:
- Tier 0: Root/top-level topics (Wi-Fi Alliance, core standards)
- Tier 1: Major topics (Wi-Fi 7, 802.11be, etc.)
- Tier 2: Detailed topics (all other topics)
"""

import os
import sys
from typing import Dict, Any

# Add neo4j-client to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'neo4j-client'))

from neo4j_client import Neo4jClient


def migrate_add_importance_and_tier():
    """Add importance and tier properties to all nodes"""
    
    uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    user = os.getenv('NEO4J_USER', 'neo4j')
    password = os.getenv('NEO4J_PASSWORD', 'password')
    database = os.getenv('NEO4J_DATABASE', 'neo4j')
    
    client = Neo4jClient(uri=uri, user=user, password=password, database=database)
    client.connect()
    
    print("Starting migration: Adding importance and tier properties...")
    
    try:
        # Step 1: Calculate importance scores for all nodes
        # Based on incoming relationship count and node type
        importance_query = """
        MATCH (n)
        WHERE NOT EXISTS(n.importance)
        WITH n, 
             size((n)<--()) as inboundCount,
             CASE labels(n)[0]
                 WHEN 'Topic' THEN 0.3
                 WHEN 'Organization' THEN 0.2
                 WHEN 'Resource' THEN 0.1
                 WHEN 'Person' THEN 0.15
                 WHEN 'Event' THEN 0.05
                 ELSE 0.01
             END as typeBase
        SET n.importance = CASE 
            WHEN inboundCount = 0 THEN typeBase
            WHEN inboundCount < 5 THEN typeBase + (inboundCount * 0.05)
            WHEN inboundCount < 20 THEN typeBase + 0.25 + ((inboundCount - 5) * 0.02)
            ELSE typeBase + 0.55 + ((inboundCount - 20) * 0.01)
        END
        RETURN count(n) as nodesUpdated
        """
        
        result = client.execute_query(importance_query)
        if result:
            print(f"✓ Set importance scores for {result[0].get('nodesUpdated', 0)} nodes")
        
        # Step 2: Set initial tier levels based on topic hierarchy
        # Root topics: explicitly curated top-level topics (tier 0)
        tier_0_query = """
        MATCH (t:Topic)
        WHERE toLower(t.name) IN ['wi-fi alliance', 'wi-fi standards', 'ieee 802.11', '802.11', 'wi-fi'] 
           OR toLower(t.identifier) IN ['wifi-alliance', 'ieee802.11', 'wi-fi']
        SET t.tier = 0
        RETURN count(t) as rootTopicsSet
        """
        
        result = client.execute_query(tier_0_query)
        if result:
            print(f"✓ Set tier 0 (root) for {result[0].get('rootTopicsSet', 0)} topics")
        
        # Step 2b: Major topics that are directly related to tier-0 topics (tier 1)
        tier_1_query = """
        MATCH (root:Topic {tier: 0})-[rel:ENCOMPASSES|RELATED_TO]->(t:Topic)
        WHERE NOT EXISTS(t.tier)
        SET t.tier = 1
        RETURN count(DISTINCT t) as majorTopicsSet
        """
        
        result = client.execute_query(tier_1_query)
        if result:
            print(f"✓ Set tier 1 (major) for {result[0].get('majorTopicsSet', 0)} topics")
        
        # Step 2c: All other topics get tier 2 (leaf/detailed topics)
        tier_2_query = """
        MATCH (t:Topic)
        WHERE NOT EXISTS(t.tier)
        SET t.tier = 2
        RETURN count(t) as leafTopicsSet
        """
        
        result = client.execute_query(tier_2_query)
        if result:
            print(f"✓ Set tier 2 (leaf) for {result[0].get('leafTopicsSet', 0)} topics")
        
        # Step 3: Set tier for non-topic nodes
        non_topic_tier_query = """
        MATCH (n)
        WHERE NOT labels(n)[0] = 'Topic' AND NOT EXISTS(n.tier)
        SET n.tier = 2
        RETURN count(n) as nonTopicsSet
        """
        
        result = client.execute_query(non_topic_tier_query)
        if result:
            print(f"✓ Set tier 2 for {result[0].get('nonTopicsSet', 0)} non-topic nodes")
        
        # Step 4: Verify the migration
        verify_query = """
        MATCH (n)
        WHERE EXISTS(n.importance) AND EXISTS(n.tier)
        RETURN 
            count(*) as totalNodesWithProperties,
            count(CASE WHEN n.tier = 0 THEN 1 END) as tier0Nodes,
            count(CASE WHEN n.tier = 1 THEN 1 END) as tier1Nodes,
            count(CASE WHEN n.tier = 2 THEN 1 END) as tier2Nodes,
            min(n.importance) as minImportance,
            max(n.importance) as maxImportance,
            avg(n.importance) as avgImportance
        """
        
        result = client.execute_query(verify_query)
        if result:
            stats = result[0]
            print("\n✓ Migration completed successfully!")
            print(f"  • Total nodes updated: {stats['totalNodesWithProperties']}")
            print(f"  • Tier 0 (root) nodes: {stats['tier0Nodes']}")
            print(f"  • Tier 1 (major) nodes: {stats['tier1Nodes']}")
            print(f"  • Tier 2 (leaf) nodes: {stats['tier2Nodes']}")
            print(f"  • Importance range: {stats['minImportance']:.3f} - {stats['maxImportance']:.3f}")
            print(f"  • Average importance: {stats['avgImportance']:.3f}")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        client.close()
        return False


if __name__ == "__main__":
    success = migrate_add_importance_and_tier()
    sys.exit(0 if success else 1)
