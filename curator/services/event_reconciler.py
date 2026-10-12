"""
Event Reconciliation Module

This module handles event reconciliation logic:
1. Detect events that have "disappeared" from the source (possibly cancelled or rescheduled)
2. Mark them as "unconfirmed" for review
3. Use embeddings to find if they were rescheduled/renamed to a new URL
4. Create SUPERSEDES relationships and migrate user attendance
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from neo4j_client import Neo4jClient, GraphRepository
from neo4j_client.models import Event, EventSupersedes, IngestionBatch
from settings import settings


class EventReconciler:
    """
    Handles event reconciliation after scraping completes.
    
    Responsibilities:
    1. Find completed ingestion batches that need event reconciliation
    2. Mark disappeared events as "unconfirmed"
    3. Find similar events using embeddings (possible rescheduling)
    4. Create SUPERSEDES relationships
    5. Migrate user attendance when events are superseded
    6. Auto-cancel events that remain unconfirmed for too long
    """
    
    # Similarity threshold for matching rescheduled events
    SIMILARITY_THRESHOLD = 0.85
    
    # Days after which unconfirmed events are auto-cancelled
    AUTO_CANCEL_DAYS = 7
    
    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        graph_repository: Optional[GraphRepository] = None,
        logger_instance: Optional[logging.Logger] = None
    ):
        """
        Initialize the EventReconciler.
        
        Args:
            neo4j_client: Neo4j client instance (created if not provided)
            graph_repository: Graph repository instance (created if not provided)
            logger_instance: Optional logger instance
        """
        self.logger = logger_instance or logging.getLogger(__name__)
        
        # Track if we own the connections (need to close them)
        self._owns_neo4j = neo4j_client is None
        
        # Initialize Neo4j connection if not provided
        if neo4j_client is None:
            self.logger.debug("Initializing Neo4j connection...")
            self._neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database,
                logger_instance=self.logger
            )
            self._neo4j_client.connect()
            self.neo4j_client = self._neo4j_client
            self.graph_repository = GraphRepository(
                self._neo4j_client,
                logger_instance=self.logger
            )
        else:
            self._neo4j_client = None
            self.neo4j_client = neo4j_client
            self.graph_repository = graph_repository
    
    def close(self):
        """Clean up resources."""
        if self._owns_neo4j and self._neo4j_client:
            self._neo4j_client.close()
            self._neo4j_client = None
    
    def has_pending_work(self) -> tuple[bool, int]:
        """
        Check if there are completed ingestion batches that need reconciliation.
        
        Queries Neo4j for batches where:
        - status = "completed" (digester finished)
        - reconciled_at IS NULL (not yet reconciled)
        - datasource has_events = true (contains events that need reconciliation)
        
        Returns:
            Tuple of (has_work, count) - whether there's work and how many batches
        """
        try:
            query = """
            MATCH (b:IngestionBatch)-[:BELONGS_TO]->(ds:DataSource)
            WHERE b.status = "completed" 
              AND b.reconciled_at IS NULL
              AND ds.has_events = true
            RETURN count(b) as pending_count
            """
            
            results = self.neo4j_client.execute_query(query, {})
            pending_count = results[0]["pending_count"] if results else 0
            
            if pending_count > 0:
                self.logger.debug(f"Found {pending_count} batch(es) pending reconciliation")
            
            return pending_count > 0, pending_count
            
        except Exception as e:
            self.logger.error(f"Error checking for pending work: {e}")
            return False, 0
    
    def get_batches_pending_reconciliation(self) -> List[Dict[str, Any]]:
        """
        Get completed ingestion batches that haven't been reconciled yet.
        
        Only returns batches where:
        - status = "completed" (digester finished)
        - reconciled_at IS NULL (not yet reconciled)
        - datasource has_events = true (contains events that need reconciliation)
        
        Returns:
            List of batch records to process
        """
        try:
            query = """
            MATCH (b:IngestionBatch)-[:BELONGS_TO]->(ds:DataSource)
            WHERE b.status = "completed" 
              AND b.reconciled_at IS NULL
              AND ds.has_events = true
            RETURN b.batch_id as batch_id,
                   b.datasource_id as datasource_id,
                   b.scrape_started_at as scrape_started_at,
                   b.scrape_completed_at as scrape_completed_at,
                   b.items_digested as items_digested,
                   b.events_count as events_count
            ORDER BY b.scrape_completed_at ASC
            """
            
            results = self.neo4j_client.execute_query(query, {})
            
            pending = []
            for row in results:
                # Convert Neo4j DateTime to ISO string if needed
                scrape_started = row.get("scrape_started_at")
                if hasattr(scrape_started, 'isoformat'):
                    scrape_started = scrape_started.isoformat()
                elif hasattr(scrape_started, 'to_native'):
                    scrape_started = scrape_started.to_native().isoformat()
                
                pending.append({
                    "batch_id": row["batch_id"],
                    "datasource_id": row["datasource_id"],
                    "scrape_started_at": scrape_started,
                    "items_digested": row.get("items_digested", 0),
                    "events_count": row.get("events_count", 0)
                })
            
            if pending:
                self.logger.info(f"Found {len(pending)} batch(es) pending reconciliation")
            
            return pending
            
        except Exception as e:
            self.logger.error(f"Error getting batches pending reconciliation: {e}")
            return []
    
    def mark_batch_reconciled(self, batch_id: str):
        """
        Mark an ingestion batch as reconciled.
        
        Args:
            batch_id: The batch ID to mark as reconciled
        """
        try:
            query = """
            MATCH (b:IngestionBatch {batch_id: $batch_id})
            SET b.reconciled_at = datetime()
            RETURN b.batch_id
            """
            self.neo4j_client.execute_write(query, {"batch_id": batch_id})
            self.logger.debug(f"Marked batch {batch_id} as reconciled")
        except Exception as e:
            self.logger.warning(f"Failed to mark batch {batch_id} as reconciled: {e}")
    
    def reconcile_datasource_events(self, datasource_id: str, scrape_started_at: str) -> Dict[str, int]:
        """
        Reconcile events for a datasource after scraping.
        
        Marks future events that weren't updated during the scrape as "unconfirmed".
        These events have disappeared from the source and are likely cancelled.
        
        Simple logic: if the same URL doesn't appear in the scrape, the event is gone.
        We don't try to match similar events as this can lead to incorrect data
        (e.g., matching recurring meeting instances as rescheduled versions).
        
        Args:
            datasource_id: ID of the datasource to reconcile
            scrape_started_at: ISO timestamp of when the scrape started
            
        Returns:
            Statistics dictionary with reconciliation results
        """
        self.logger.info(f"Starting reconciliation for datasource: {datasource_id}")
        self.logger.debug(f"Scrape started at: {scrape_started_at}")
        
        stats = {
            "events_checked": 0,
            "marked_unconfirmed": 0,
            "errors": 0
        }
        
        try:
            # Find future events from this datasource that weren't updated during this scrape
            # These are events that have "disappeared" from the source
            # Note: start_date is stored as ISO string, so we need to convert with datetime()
            query = """
            MATCH (e:Event)-[:INGESTED_FROM]->(ds:DataSource {datasource_id: $datasource_id})
            WHERE datetime(e.start_date) > datetime()
              AND e.status IN ['scheduled', 'unconfirmed']
              AND (e.last_updated IS NULL OR e.last_updated < datetime($scrape_started_at))
            RETURN e.url_hash as url_hash, e.name as name, e.status as status,
                   e.start_date as start_date, e.embedding as embedding,
                   e.last_updated as last_updated
            """
            
            self.logger.debug(f"Executing query with datasource_id={datasource_id}, scrape_started_at={scrape_started_at}")
            
            results = self.neo4j_client.execute_query(query, {
                "datasource_id": datasource_id,
                "scrape_started_at": scrape_started_at
            })
            
            stats["events_checked"] = len(results)
            self.logger.info(f"Found {len(results)} event(s) not updated since scrape for {datasource_id}")
            
            for event_data in results:
                url_hash = event_data["url_hash"]
                name = event_data.get("name", "Unknown")
                current_status = event_data.get("status")
                last_updated = event_data.get("last_updated")
                
                self.logger.debug(
                    f"Processing event: {name} (status={current_status}, "
                    f"last_updated={last_updated})"
                )
                
                # Mark as unconfirmed if it's currently scheduled
                # Simple logic: if the URL didn't appear in this scrape, it's gone from the source
                if current_status == "scheduled":
                    self._mark_event_unconfirmed(url_hash, name)
                    stats["marked_unconfirmed"] += 1
            
            self.logger.info(
                f"Reconciliation complete for {datasource_id}: "
                f"checked={stats['events_checked']}, unconfirmed={stats['marked_unconfirmed']}"
            )
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error reconciling events for {datasource_id}: {e}", exc_info=True)
            stats["errors"] += 1
            return stats
    
    def _mark_event_unconfirmed(self, url_hash: str, name: str):
        """Mark an event as unconfirmed (disappeared from source)."""
        try:
            query = """
            MATCH (e:Event {url_hash: $url_hash})
            SET e.status = 'unconfirmed',
                e.unconfirmed_at = datetime()
            RETURN e.url_hash
            """
            self.neo4j_client.execute_write(query, {"url_hash": url_hash})
            self.logger.debug(f"Marked event as unconfirmed: {name}")
        except Exception as e:
            self.logger.error(f"Failed to mark event {name} as unconfirmed: {e}")
    
    def _mark_event_rescheduled(self, url_hash: str, name: str):
        """Mark an event as rescheduled (replaced by another event)."""
        try:
            query = """
            MATCH (e:Event {url_hash: $url_hash})
            SET e.status = 'rescheduled',
                e.rescheduled_at = datetime()
            RETURN e.url_hash
            """
            self.neo4j_client.execute_write(query, {"url_hash": url_hash})
            self.logger.debug(f"Marked event as rescheduled: {name}")
        except Exception as e:
            self.logger.error(f"Failed to mark event {name} as rescheduled: {e}")
    
    def _find_similar_event(
        self, 
        old_url_hash: str, 
        embedding: List[float], 
        datasource_id: str,
        scrape_started_at: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find a similar event that may be a rescheduled version.
        
        Searches for events from the same datasource that:
        - Were updated during the recent scrape
        - Have high embedding similarity
        - Don't already have a SUPERSEDES relationship
        
        Args:
            old_url_hash: URL hash of the disappeared event
            embedding: Embedding vector of the disappeared event
            datasource_id: Datasource ID to search within
            scrape_started_at: ISO timestamp - only consider events updated after this
            
        Returns:
            Similar event data if found, None otherwise
        """
        try:
            # Use vector search to find similar events from the same datasource
            # that were updated during the scrape (i.e., currently exist in source)
            # Note: datasource_id is stored via INGESTED_FROM relationship, not on node
            query = """
            CALL db.index.vector.queryNodes('event_embedding_index', 10, $embedding)
            YIELD node, score
            WHERE node.url_hash <> $old_url_hash
              AND node.status = 'scheduled'
              AND node.last_updated >= datetime($scrape_started_at)
              AND score >= $threshold
              AND NOT EXISTS {
                  MATCH (node)-[:SUPERSEDES]->(:Event)
              }
              AND EXISTS {
                  MATCH (node)-[:INGESTED_FROM]->(:DataSource {datasource_id: $datasource_id})
              }
            RETURN node.url_hash as url_hash, node.name as name, score as similarity_score
            ORDER BY score DESC
            LIMIT 1
            """
            
            results = self.neo4j_client.execute_query(query, {
                "embedding": embedding,
                "old_url_hash": old_url_hash,
                "datasource_id": datasource_id,
                "scrape_started_at": scrape_started_at,
                "threshold": self.SIMILARITY_THRESHOLD
            })
            
            if results:
                similar = results[0]
                self.logger.debug(
                    f"Found similar event: '{similar['name']}' "
                    f"(similarity: {similar['similarity_score']:.3f})"
                )
                return similar
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding similar event: {e}")
            return None
    
    def _create_supersedes_relationship(
        self, 
        new_url_hash: str, 
        old_url_hash: str, 
        similarity_score: float
    ):
        """Create a SUPERSEDES relationship between events."""
        try:
            supersedes_rel = EventSupersedes(
                source_id=new_url_hash,
                target_id=old_url_hash,
                similarity_score=similarity_score,
                reason="Event rescheduled or URL changed"
            )
            self.graph_repository.create_relationship(supersedes_rel)
            self.logger.debug(f"Created SUPERSEDES relationship: {new_url_hash} -> {old_url_hash}")
        except Exception as e:
            self.logger.error(f"Failed to create SUPERSEDES relationship: {e}")
    
    def _migrate_user_attendance(self, old_url_hash: str, new_url_hash: str) -> int:
        """
        Migrate user attendance from old event to new event.
        
        When an event is superseded, users who were ATTENDING the old event
        should have their attendance migrated to the new event.
        
        Args:
            old_url_hash: URL hash of the old (superseded) event
            new_url_hash: URL hash of the new (superseding) event
            
        Returns:
            Number of attendance relationships migrated
        """
        try:
            # Find users attending the old event and create attendance for new event
            query = """
            MATCH (u:User)-[old_rel:ATTENDING]->(old_event:Event {url_hash: $old_url_hash})
            MATCH (new_event:Event {url_hash: $new_url_hash})
            
            // Create new ATTENDING relationship if it doesn't exist
            MERGE (u)-[new_rel:ATTENDING]->(new_event)
            ON CREATE SET new_rel.migrated_from = $old_url_hash,
                         new_rel.migrated_at = datetime(),
                         new_rel.created_at = old_rel.created_at
            
            // Mark old relationship as superseded (don't delete)
            SET old_rel.superseded_by = $new_url_hash,
                old_rel.superseded_at = datetime()
            
            RETURN count(new_rel) as migrated_count
            """
            
            results = self.neo4j_client.execute_write(query, {
                "old_url_hash": old_url_hash,
                "new_url_hash": new_url_hash
            })
            
            migrated_count = results[0]["migrated_count"] if results else 0
            
            if migrated_count > 0:
                self.logger.info(f"Migrated {migrated_count} user attendance(s) to new event")
            
            return migrated_count
            
        except Exception as e:
            self.logger.error(f"Failed to migrate user attendance: {e}")
            return 0
    
    def auto_cancel_stale_unconfirmed_events(self) -> int:
        """
        Auto-cancel events that have been unconfirmed for too long.
        
        Events marked as "unconfirmed" for more than AUTO_CANCEL_DAYS
        are assumed to be cancelled and updated accordingly.
        
        Returns:
            Number of events auto-cancelled
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=self.AUTO_CANCEL_DAYS)
            
            query = """
            MATCH (e:Event)
            WHERE e.status = 'unconfirmed'
              AND e.unconfirmed_at < datetime($cutoff_date)
            SET e.status = 'cancelled',
                e.auto_cancelled_at = datetime(),
                e.cancellation_reason = 'Auto-cancelled after ' + toString($days) + ' days unconfirmed'
            RETURN count(e) as cancelled_count
            """
            
            results = self.neo4j_client.execute_write(query, {
                "cutoff_date": cutoff_date.isoformat(),
                "days": self.AUTO_CANCEL_DAYS
            })
            
            cancelled_count = results[0]["cancelled_count"] if results else 0
            
            if cancelled_count > 0:
                self.logger.info(f"Auto-cancelled {cancelled_count} stale unconfirmed event(s)")
            
            return cancelled_count
            
        except Exception as e:
            self.logger.error(f"Failed to auto-cancel stale events: {e}")
            return 0
    
    def run(self) -> Dict[str, Any]:
        """
        Run the full event reconciliation process.
        
        1. Query Neo4j for completed batches that haven't been reconciled
        2. Process each batch's datasource events
        3. Mark batches as reconciled
        4. Auto-cancel stale unconfirmed events
        
        Returns:
            Aggregated statistics from all reconciliation operations
        """
        total_stats = {
            "batches_processed": 0,
            "events_checked": 0,
            "marked_unconfirmed": 0,
            "supersedes_created": 0,
            "attendance_migrated": 0,
            "auto_cancelled": 0,
            "errors": 0,
            "success": False
        }
        
        try:
            # Get batches pending reconciliation from Neo4j
            pending_batches = self.get_batches_pending_reconciliation()
            
            if not pending_batches:
                self.logger.debug("No batches pending reconciliation")
                # Still run auto-cancel even if no pending batches
                auto_cancelled = self.auto_cancel_stale_unconfirmed_events()
                total_stats["auto_cancelled"] = auto_cancelled
                total_stats["success"] = True
                return total_stats
            
            self.logger.info(f"Starting event reconciliation for {len(pending_batches)} batch(es)")
            
            for batch in pending_batches:
                batch_id = batch["batch_id"]
                datasource_id = batch["datasource_id"]
                scrape_started_at = batch["scrape_started_at"]
                
                self.logger.debug(f"Processing batch {batch_id} for datasource {datasource_id}")
                
                # Reconcile events for this datasource
                stats = self.reconcile_datasource_events(datasource_id, scrape_started_at)
                
                # Aggregate stats
                total_stats["batches_processed"] += 1
                for key in ["events_checked", "marked_unconfirmed", "supersedes_created", 
                           "attendance_migrated", "errors"]:
                    total_stats[key] += stats.get(key, 0)
                
                # Mark batch as reconciled in Neo4j
                self.mark_batch_reconciled(batch_id)
            
            # Auto-cancel stale unconfirmed events
            auto_cancelled = self.auto_cancel_stale_unconfirmed_events()
            total_stats["auto_cancelled"] = auto_cancelled
            
            total_stats["success"] = True
            
            # Log summary
            self.logger.info(
                f"Event reconciliation complete: "
                f"batches={total_stats['batches_processed']}, "
                f"checked={total_stats['events_checked']}, "
                f"unconfirmed={total_stats['marked_unconfirmed']}, "
                f"auto_cancelled={total_stats['auto_cancelled']}"
            )
            if total_stats["errors"] > 0:
                self.logger.warning(f"Reconciliation encountered {total_stats['errors']} error(s)")
                
        except Exception as e:
            self.logger.error(f"Error during event reconciliation: {e}", exc_info=True)
            total_stats["errors"] += 1
        
        return total_stats

