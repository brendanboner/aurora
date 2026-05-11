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
            Migrations.add_ietf_datasources,
            Migrations.add_wba_newsroom_datasource,
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
    def add_ietf_datasources(session: Session) -> bool:
        """
        Upsert IETF Blog and IETF Datatracker DataSource nodes.

        Idempotent — uses MERGE so it is safe to run on every startup.
        These nodes are defined in initial_data.json but are skipped when
        base data already exists (organisations present). This migration
        ensures they are always present regardless of when the service was
        first initialised.
        """
        try:
            datasources = [
                {
                    "datasource_id": "ietf_blog",
                    "name": "IETF Blog",
                    "display_name": "IETF",
                    "org_id": "ietf",
                    "source_type": "scraped_webpage",
                    "fetch_url": "https://www.ietf.org/blog/",
                    "has_events": False,
                    "scraper_type": "ietf_blog",
                    "resource_url": "/blog/",
                    "scrape_schedule": "0 6 * * *",
                    "run_on_startup": False,
                    "check_content_hash": True,
                    "publish_weight": 1.0,
                    "update_weight": 0.8,
                    "event_weight": 0.7,
                    "temporal_extraction_days": 90,
                    "scraper_delay": 1.0,
                    "max_resources": 100,
                    "max_redirects": 5,
                    "discovery_mode": "incremental",
                    "consecutive_duplicates_limit": 5,
                    "description": "IETF public blog — news, announcements and IETF meeting previews",
                },
                {
                    "datasource_id": "ietf_datatracker_api",
                    "name": "IETF Datatracker",
                    "display_name": "IETF Datatracker",
                    "org_id": "ietf",
                    "source_type": "scraped_webpage",
                    "fetch_url": "https://datatracker.ietf.org/",
                    "has_events": True,
                    "scraper_type": "ietf_datatracker",
                    "resource_url": "/",
                    "scrape_schedule": "0 4 * * *",
                    "run_on_startup": False,
                    "check_content_hash": True,
                    "publish_weight": 1.0,
                    "update_weight": 0.9,
                    "event_weight": 1.0,
                    "temporal_extraction_days": 180,
                    "scraper_delay": 1.0,
                    "max_resources": -1,
                    "max_redirects": 5,
                    "discovery_mode": "incremental",
                    "consecutive_duplicates_limit": 0,
                    "description": "IETF Datatracker — internet-drafts, RFCs and meeting sessions for selected areas and working groups",
                    "folders": ["area:wit", "area:int", "area:rtg", "area:sec"],
                },
            ]

            for ds in datasources:
                folders = ds.pop("folders", None)
                query = """
                MERGE (d:DataSource {datasource_id: $datasource_id})
                ON CREATE SET
                    d.name                        = $name,
                    d.display_name                = $display_name,
                    d.org_id                      = $org_id,
                    d.source_type                 = $source_type,
                    d.fetch_url                   = $fetch_url,
                    d.has_events                  = $has_events,
                    d.scraper_type                = $scraper_type,
                    d.resource_url                = $resource_url,
                    d.scrape_schedule             = $scrape_schedule,
                    d.run_on_startup              = $run_on_startup,
                    d.check_content_hash          = $check_content_hash,
                    d.publish_weight              = $publish_weight,
                    d.update_weight               = $update_weight,
                    d.event_weight                = $event_weight,
                    d.temporal_extraction_days    = $temporal_extraction_days,
                    d.scraper_delay               = $scraper_delay,
                    d.max_resources               = $max_resources,
                    d.max_redirects               = $max_redirects,
                    d.discovery_mode              = $discovery_mode,
                    d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
                    d.description                 = $description
                ON MATCH SET
                    d.display_name                = $display_name,
                    d.description                 = $description
                RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
                """
                result = session.run(query, **ds)
                record = result.single()
                if record:
                    action = "updated" if record["existed"] else "created"
                    logger.info(f"IETF datasource '{record['id']}' {action}")

                # Always ensure folders is set for ietf_datatracker_api
                if folders is not None:
                    session.run(
                        """
                        MATCH (d:DataSource {datasource_id: $datasource_id})
                        WHERE d.folders IS NULL OR size(d.folders) = 0
                        SET d.folders = $folders
                        """,
                        datasource_id=ds["datasource_id"],
                        folders=folders,
                    )
                    logger.info(f"Set folders on '{ds['datasource_id']}': {folders}")

            return True

        except Exception as e:
            logger.error(f"Error upserting IETF datasources: {e}")
            return False

    @staticmethod
    def add_wba_newsroom_datasource(session: Session) -> bool:
        """
        Upsert a WBA Newsroom DataSource node.

        The WBA newsroom (wballiance.com/newsroom/) is a WordPress blog
        containing press releases, partner spotlights, and trial reports.
        It is separate from the /resources/ section and was previously not
        scraped.  This migration ensures the datasource is present so the
        retriever will scrape it on its next scheduled run.

        Idempotent — uses MERGE on datasource_id.
        """
        try:
            ds = {
                "datasource_id": "wba_newsroom",
                "name": "WBA Newsroom",
                "display_name": "WBA Newsroom",
                "org_id": "wba",
                "source_type": "scraped_webpage",
                "fetch_url": "https://wballiance.com/newsroom/",
                "has_events": False,
                "scraper_type": "wba",
                "resource_url": "/newsroom/",
                "scrape_schedule": "0 7 * * *",
                "run_on_startup": False,
                "check_content_hash": True,
                "publish_weight": 1.0,
                "update_weight": 0.9,
                "event_weight": 0.7,
                "temporal_extraction_days": 90,
                "scraper_delay": 1.0,
                "max_resources": 200,
                "max_redirects": 5,
                "discovery_mode": "incremental",
                "consecutive_duplicates_limit": 5,
                "description": "WBA Newsroom — press releases, partner spotlights and field trial reports",
            }

            query = """
            MERGE (d:DataSource {datasource_id: $datasource_id})
            ON CREATE SET
                d.name                        = $name,
                d.display_name                = $display_name,
                d.org_id                      = $org_id,
                d.source_type                 = $source_type,
                d.fetch_url                   = $fetch_url,
                d.has_events                  = $has_events,
                d.scraper_type                = $scraper_type,
                d.resource_url                = $resource_url,
                d.scrape_schedule             = $scrape_schedule,
                d.run_on_startup              = $run_on_startup,
                d.check_content_hash          = $check_content_hash,
                d.publish_weight              = $publish_weight,
                d.update_weight               = $update_weight,
                d.event_weight                = $event_weight,
                d.temporal_extraction_days    = $temporal_extraction_days,
                d.scraper_delay               = $scraper_delay,
                d.max_resources               = $max_resources,
                d.max_redirects               = $max_redirects,
                d.discovery_mode              = $discovery_mode,
                d.consecutive_duplicates_limit= $consecutive_duplicates_limit,
                d.description                 = $description
            ON MATCH SET
                d.display_name                = $display_name,
                d.description                 = $description
            RETURN d.datasource_id as id, (d.name IS NOT NULL) as existed
            """
            result = session.run(query, **ds)
            record = result.single()
            if record:
                action = "updated" if record["existed"] else "created"
                logger.info(f"WBA Newsroom datasource '{record['id']}' {action}")

            return True

        except Exception as e:
            logger.error(f"Error upserting WBA Newsroom datasource: {e}")
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
