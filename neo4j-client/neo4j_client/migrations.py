"""Neo4j database migrations for knowledge graph schema enhancements."""

import logging
from typing import Dict, Any, Optional
from neo4j import Session

logger = logging.getLogger(__name__)


class Migrations:
    """Handle Neo4j schema migrations."""

    @staticmethod
    def run_all(session: Session, database: str = "neo4j") -> bool:
        """
        Run all pending migrations.
        
        Args:
            session: Neo4j session
            database: Database name
            
        Returns:
            True if all migrations succeeded, False otherwise
        """
        migrations = [
            Migrations.add_tier_to_topics,
            Migrations.add_importance_to_nodes,
        ]
        
        for migration_func in migrations:
            try:
                if not migration_func(session):
                    logger.error(f"Migration {migration_func.__name__} failed")
                    return False
            except Exception as e:
                logger.error(f"Error running migration {migration_func.__name__}: {e}")
                return False
        
        return True

    @staticmethod
    def add_tier_to_topics(session: Session) -> bool:
        """
        Add tier property to Topic nodes (0 = root, 1 = major, 2 = leaf).
        
        Idempotent - only updates topics WHERE tier IS NULL.
        """
        try:
            # Tier 0: Topics with no parent
            query_tier_0 = """
            MATCH (t:Topic)
            WHERE t.tier IS NULL
                AND NOT EXISTS ((t)<-[:ENCOMPASSES]-(:Topic))
            SET t.tier = 0
            RETURN COUNT(t) as updated
            """
            result = session.run(query_tier_0)
            record = result.single()
            count_0 = record["updated"] if record else 0
            logger.info(f"Set tier=0 for {count_0} root topics")
            
            # Tier 1: Topics with parent but no grandparent
            query_tier_1 = """
            MATCH (t:Topic)<-[:ENCOMPASSES]-(parent:Topic)
            WHERE t.tier IS NULL
                AND NOT EXISTS ((parent)<-[:ENCOMPASSES]-(:Topic))
            SET t.tier = 1
            RETURN COUNT(t) as updated
            """
            result = session.run(query_tier_1)
            record = result.single()
            count_1 = record["updated"] if record else 0
            logger.info(f"Set tier=1 for {count_1} major topics")
            
            # Tier 2: All remaining topics (leaf/nested)
            query_tier_2 = """
            MATCH (t:Topic)
            WHERE t.tier IS NULL
            SET t.tier = 2
            RETURN COUNT(t) as updated
            """
            result = session.run(query_tier_2)
            record = result.single()
            count_2 = record["updated"] if record else 0
            logger.info(f"Set tier=2 for {count_2} leaf topics")
            
            # Verify
            query_verify = """
            MATCH (t:Topic)
            WHERE t.tier IS NOT NULL
            RETURN COUNT(t) as total
            """
            result = session.run(query_verify)
            record = result.single()
            total = record["total"] if record else 0
            logger.info(f"Total topics with tier property: {total}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding tier to topics: {e}")
            return False

    @staticmethod
    def add_importance_to_nodes(session: Session) -> bool:
        """
        Add importance property to nodes based on inbound relationship count.
        
        Importance = COUNT(inbound_rels) / 100 (clamped 0-1)
        Idempotent - only updates nodes WHERE importance IS NULL.
        """
        try:
            # Add importance to Topics (based on resources that discuss them)
            query_topics = """
            MATCH (t:Topic)
            WHERE t.importance IS NULL
            WITH t, SIZE([(r:Resource)-[:DISCUSSES]->(t) | r]) as rel_count
            WITH t, rel_count,
                 CASE 
                     WHEN rel_count = 0 THEN 0.0
                     WHEN rel_count > 100 THEN 1.0
                     ELSE ROUND(rel_count / 100.0, 2)
                 END as importance_value
            SET t.importance = importance_value
            RETURN COUNT(t) as updated, ROUND(AVG(importance_value), 2) as avg_importance
            """
            result = session.run(query_topics)
            record = result.single()
            if record:
                logger.info(f"Added importance to {record['updated']} topics, avg={record['avg_importance']}")
            
            # Add importance to Organizations
            query_orgs = """
            MATCH (o:Organization)
            WHERE o.importance IS NULL
            WITH o, SIZE([(r:Resource)-[:PUBLISHED_BY]->(o) | r]) as rel_count
            WITH o, rel_count,
                 CASE 
                     WHEN rel_count = 0 THEN 0.0
                     WHEN rel_count > 100 THEN 1.0
                     ELSE ROUND(rel_count / 100.0, 2)
                 END as importance_value
            SET o.importance = importance_value
            RETURN COUNT(o) as updated
            """
            result = session.run(query_orgs)
            record = result.single()
            if record:
                logger.info(f"Added importance to {record['updated']} organizations")
            
            # Add importance to Persons
            query_persons = """
            MATCH (p:Person)
            WHERE p.importance IS NULL
            WITH p, SIZE([(r:Resource)-[:AUTHORED_BY]->(p) | r]) as rel_count
            WITH p, rel_count,
                 CASE 
                     WHEN rel_count = 0 THEN 0.0
                     WHEN rel_count > 100 THEN 1.0
                     ELSE ROUND(rel_count / 100.0, 2)
                 END as importance_value
            SET p.importance = importance_value
            RETURN COUNT(p) as updated
            """
            result = session.run(query_persons)
            record = result.single()
            if record:
                logger.info(f"Added importance to {record['updated']} persons")
            
            # Verify
            query_verify = """
            MATCH (n)
            WHERE n.importance IS NOT NULL
            RETURN COUNT(n) as total, 
                   ROUND(AVG(n.importance), 2) as avg_importance,
                   MIN(n.importance) as min_importance,
                   MAX(n.importance) as max_importance
            """
            result = session.run(query_verify)
            record = result.single()
            if record:
                logger.info(f"Importance stats: {record['total']} nodes, avg={record['avg_importance']}, "
                           f"min={record['min_importance']}, max={record['max_importance']}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding importance to nodes: {e}")
            return False

    @staticmethod
    def verify_migrations(session: Session) -> Dict[str, Any]:
        """
        Verify migration status and return statistics.
        
        Returns:
            Dictionary with migration status and counts
        """
        stats = {}
        
        try:
            # Check tier distribution on Topics
            query = """
            MATCH (t:Topic)
            RETURN t.tier as tier, COUNT(t) as count
            ORDER BY tier
            """
            result = session.run(query)
            tier_dist = {}
            for record in result:
                tier = record['tier'] if record['tier'] is not None else 'NULL'
                tier_dist[tier] = record['count']
            stats['tier_distribution'] = tier_dist
            
            # Check importance distribution
            query = """
            MATCH (n)
            WHERE n.importance IS NOT NULL
            RETURN 
                COUNT(n) as total,
                ROUND(AVG(n.importance), 2) as avg,
                MIN(n.importance) as min,
                MAX(n.importance) as max
            """
            result = session.run(query)
            record = result.single()
            if record:
                stats['importance'] = {
                    'total_nodes': record['total'],
                    'avg': record['avg'],
                    'min': record['min'],
                    'max': record['max'],
                }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error verifying migrations: {e}")
            return {'error': str(e)}
