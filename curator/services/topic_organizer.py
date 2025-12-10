"""
Topic Hierarchy Organizer

Organizes topics into hierarchical relationships using clustering and LLM analysis.
"""

import logging
from typing import List, Dict, Any, Optional, Callable

from services.clustering import TopicClusterer
from services.hierarchy_analyzer import HierarchyAnalyzer
from neo4j_client import Neo4jClient, GraphRepository
from neo4j_client.deduplicator import NodeDeduplicator
from neo4j_client.models import (
    Topic,
    TopicEncompasses,
    TopicSubtopicOf
)
from settings import settings


class TopicOrganizer:
    """
    Organizes topics into a hierarchy through clustering and LLM analysis.
    
    Process:
    1. Retrieve all topics from the knowledge graph
    2. Cluster topics by semantic similarity
    3. Analyze each cluster with LLM to identify hierarchical relationships
    4. Insert relationships into the knowledge graph
    """
    
    def __init__(
        self,
        graph_repository: Optional[GraphRepository] = None,
        deduplicator: Optional[NodeDeduplicator] = None,
        logger_instance: Optional[logging.Logger] = None,
        heartbeat_callback: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the TopicOrganizer.
        
        Args:
            graph_repository: Graph repository for Neo4j operations (created if not provided)
            deduplicator: Node deduplicator for checking duplicates (created if not provided)
            logger_instance: Optional logger instance
            heartbeat_callback: Optional callback to extend lock during long operations
        """
        self.logger = logger_instance or logging.getLogger(__name__)
        self._heartbeat_callback = heartbeat_callback
        
        # Track if we own the connections (need to close them)
        self._owns_connections = graph_repository is None
        
        # Initialize Neo4j connection if not provided
        if graph_repository is None:
            self.logger.info("Initializing Neo4j connection...")
            self._neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database,
                logger_instance=self.logger
            )
            self._neo4j_client.connect()
            self.graph_repository = GraphRepository(
                self._neo4j_client,
                logger_instance=self.logger
            )
            self.deduplicator = NodeDeduplicator(
                self._neo4j_client,
                logger_instance=self.logger
            )
        else:
            self._neo4j_client = None
            self.graph_repository = graph_repository
            self.deduplicator = deduplicator
        
        # Initialize topic clusterer
        self.clusterer = TopicClusterer(
            min_cluster_size=settings.cluster_min_size,
            max_cluster_size=settings.cluster_max_size,
            distance_threshold=settings.cluster_distance_threshold,
            overlap_neighbors=settings.cluster_overlap_neighbors,
            logger_instance=self.logger
        )
        
        # Initialize hierarchy analyzer
        self.hierarchy_analyzer = HierarchyAnalyzer(
            api_key=settings.azure_openai_api_key,
            endpoint=settings.azure_openai_endpoint,
            deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            confidence_threshold=settings.hierarchy_confidence_threshold,
            logger_instance=self.logger
        )
    
    def _heartbeat(self):
        """Call heartbeat callback if set (extends Redis lock during long operations)."""
        if self._heartbeat_callback:
            try:
                self._heartbeat_callback()
            except Exception as e:
                self.logger.warning(f"Heartbeat callback failed: {e}")
    
    def close(self):
        """Clean up resources."""
        if self._owns_connections and self._neo4j_client:
            self._neo4j_client.close()
            self._neo4j_client = None
    
    def run(self) -> Dict[str, Any]:
        """
        Run topic hierarchy organization.
        
        Returns:
            Statistics dictionary with results
        """
        self.logger.info("="*80)
        self.logger.info("Starting topic hierarchy organization")
        self.logger.info("="*80)
        
        stats = {
            "topics_processed": 0,
            "new_topics_created": 0,
            "clusters_created": 0,
            "relationships_created": 0,
            "encompasses": 0,
            "subtopic_of": 0,
            "cycles_prevented": 0,
            "redundant_skipped": 0,
            "errors": 0,
            "success": False
        }
        
        try:
            # Step 1: Retrieve all topics
            self.logger.info("Step 1: Retrieving all topics from knowledge graph...")
            topics = self.graph_repository.get_all_nodes(Topic)
            stats["topics_processed"] = len(topics)
            self.logger.info(f"Retrieved {len(topics)} topics")
            
            if not topics:
                self.logger.warning("No topics found to organize")
                stats["success"] = True
                return stats
            
            # Log some sample topics
            self.logger.info(f"Sample topics: {[t.get('name') for t in topics[:5]]}")
            
            # Step 2: Cluster topics
            self.logger.info("\nStep 2: Clustering topics by semantic similarity...")
            clusters = self.clusterer.cluster_topics(topics)
            
            if not clusters:
                self.logger.warning("No clusters created")
                stats["success"] = True
                return stats
            
            stats["clusters_created"] = len(clusters)
            self.logger.info(f"Created {len(clusters)} clusters")
            for i, cluster in enumerate(clusters):
                self.logger.info(
                    f"  Cluster {i+1}: {len(cluster)} topics - "
                    f"{[t.get('name') for t in cluster[:3]]}..."
                )
            
            # Step 3: Process each cluster
            self.logger.info("\nStep 3: Processing clusters with LLM...")
            
            all_new_topics = []
            all_relationships = []
            
            for i, cluster in enumerate(clusters):
                # Heartbeat - extend lock for long-running operations
                self._heartbeat()
                
                self.logger.info(f"\n{'='*60}")
                self.logger.info(f"Processing Cluster {i+1}/{len(clusters)}")
                self.logger.info(f"{'='*60}")
                
                cluster_new_topics, cluster_relationships, cluster_stats = self._process_cluster(
                    cluster, i + 1
                )
                
                all_new_topics.extend(cluster_new_topics)
                all_relationships.extend(cluster_relationships)
                
                # Aggregate stats
                for key in ["encompasses", "subtopic_of", "cycles_prevented", "redundant_skipped", "errors"]:
                    stats[key] += cluster_stats.get(key, 0)
            
            stats["new_topics_created"] = len(all_new_topics)
            stats["relationships_created"] = len(all_relationships)
            
            # Step 4: Cross-cluster analysis
            if settings.enable_cross_cluster_analysis and len(clusters) > 1:
                cross_stats = self._process_cross_cluster(clusters)
                for key in ["encompasses", "subtopic_of", "cycles_prevented", "redundant_skipped", "errors"]:
                    stats[key] += cross_stats.get(key, 0)
                stats["relationships_created"] += cross_stats.get("relationships_created", 0)
            
            stats["success"] = True
            
            # Final Summary
            self._log_summary(stats, all_new_topics)
            
        except Exception as e:
            self.logger.error(f"Error during topic organization: {e}", exc_info=True)
            stats["errors"] += 1
        
        finally:
            # Clean up if we own the connections
            if self._owns_connections:
                self.close()
        
        return stats
    
    def _process_cluster(
        self, 
        cluster: List[Dict[str, Any]], 
        cluster_num: int
    ) -> tuple:
        """Process a single cluster of topics."""
        cluster_new_topics = []
        cluster_relationships = []
        cluster_stats = {
            "encompasses": 0,
            "subtopic_of": 0,
            "cycles_prevented": 0,
            "redundant_skipped": 0,
            "errors": 0
        }
        
        self.logger.info(f"Cluster topics: {[t.get('name') for t in cluster]}")
        
        # Step 3a: Suggest general topics for this cluster
        self.logger.info(f"\nStep 3a: Checking if cluster needs general topics...")
        suggested_topics = self.hierarchy_analyzer.suggest_general_topics(cluster)
        
        if suggested_topics:
            self.logger.info(f"  LLM suggested {len(suggested_topics)} general topic(s)")
            
            # Step 3b: Deduplicate using NodeDeduplicator
            self.logger.info(f"\nStep 3b: Deduplicating suggested topics...")
            for proposed_topic in suggested_topics:
                duplicate_result = self.deduplicator.check_topic_duplicate(
                    proposed_topic,
                    k_neighbors=5,
                    similarity_threshold=0.85,
                    llm_review_threshold=0.6
                )
                
                if duplicate_result and duplicate_result.get("is_duplicate"):
                    existing_id = duplicate_result.get("existing_id")
                    existing_node = duplicate_result.get("existing_node")
                    similarity = duplicate_result.get("similarity_score", 0.0)
                    action = duplicate_result.get("action", "unknown")
                    self.logger.info(
                        f"  DUPLICATE: '{proposed_topic.name}' matches existing '{existing_id}' "
                        f"(similarity: {similarity:.2f}, action: {action})"
                    )
                    
                    if existing_node and not any(t.get("topic_id") == existing_id for t in cluster):
                        self.logger.info(f"    Adding existing topic '{existing_id}' to cluster")
                        cluster.append(existing_node)
                else:
                    self.logger.info(f"  UNIQUE: '{proposed_topic.name}' - creating in graph")
                    
                    try:
                        created_topic = self.graph_repository.create_node(proposed_topic)
                        if created_topic:
                            self.logger.info(f"    ✓ Created topic '{proposed_topic.name}' (ID: {proposed_topic.topic_id})")
                            cluster.append(created_topic)
                            cluster_new_topics.append(proposed_topic)
                        else:
                            self.logger.warning(f"    ✗ Failed to create topic '{proposed_topic.name}'")
                    except Exception as e:
                        self.logger.error(f"    ✗ Failed to create topic '{proposed_topic.name}': {e}")
        else:
            self.logger.info(f"  No general topics suggested for cluster {cluster_num}")
        
        # Step 3d: Analyze cluster for hierarchical relationships
        self.logger.info(f"\nStep 3d: Analyzing relationships in augmented cluster...")
        self.logger.info(f"  Cluster size: {len(cluster)} topics (including {len(cluster_new_topics)} new)")
        
        relationships = self.hierarchy_analyzer.analyze_cluster(cluster)
        self.logger.info(f"  Found {len(relationships)} relationships")
        
        # Step 3e: Validate relationships
        self.logger.info(f"\nStep 3e: Validating relationships...")
        current_topics = self.graph_repository.get_all_nodes(Topic)
        validated_relationships = self.hierarchy_analyzer.validate_relationships(
            relationships, current_topics
        )
        self.logger.info(f"  Validated {len(validated_relationships)}/{len(relationships)} relationships")
        
        # Step 3f: Insert relationships
        if validated_relationships:
            self.logger.info(f"\nStep 3f: Inserting {len(validated_relationships)} relationships...")
            insert_stats = self._insert_relationships(validated_relationships)
            cluster_stats.update(insert_stats)
            cluster_relationships.extend(validated_relationships)
            
            self.logger.info(
                f"  Inserted: {insert_stats['encompasses']} ENCOMPASSES, "
                f"{insert_stats['subtopic_of']} SUBTOPIC_OF"
            )
        
        return cluster_new_topics, cluster_relationships, cluster_stats
    
    def _process_cross_cluster(self, clusters: List[List[Dict[str, Any]]]) -> Dict[str, int]:
        """Process cross-cluster relationships."""
        self.logger.info(f"\n{'='*60}")
        self.logger.info("Cross-Cluster Analysis")
        self.logger.info(f"{'='*60}")
        
        stats = {
            "encompasses": 0,
            "subtopic_of": 0,
            "cycles_prevented": 0,
            "redundant_skipped": 0,
            "errors": 0,
            "relationships_created": 0
        }
        
        self.logger.info("Analyzing cluster representatives for cross-cluster relationships...")
        
        representatives = []
        for i, cluster in enumerate(clusters):
            rep = self.clusterer.find_most_central_topic(cluster)
            if rep:
                representatives.append(rep)
                self.logger.info(f"  Cluster {i+1} representative: {rep.get('name')}")
        
        self.logger.info(f"\nTotal representatives: {len(representatives)}")
        
        if len(representatives) <= settings.cluster_max_size:
            cross_cluster_rels = self.hierarchy_analyzer.analyze_cluster_representatives(representatives)
            
            current_topics = self.graph_repository.get_all_nodes(Topic)
            validated_cross_rels = self.hierarchy_analyzer.validate_relationships(
                cross_cluster_rels, current_topics
            )
            
            if validated_cross_rels:
                self.logger.info(f"Inserting {len(validated_cross_rels)} cross-cluster relationships...")
                insert_stats = self._insert_relationships(validated_cross_rels)
                stats.update(insert_stats)
                stats["relationships_created"] = len(validated_cross_rels)
        else:
            self.logger.info(f"Too many representatives ({len(representatives)}), clustering them...")
            meta_clusters = self.clusterer.cluster_topics(representatives)
            
            for i, meta_cluster in enumerate(meta_clusters):
                meta_relationships = self.hierarchy_analyzer.analyze_cluster_representatives(meta_cluster)
                current_topics = self.graph_repository.get_all_nodes(Topic)
                validated_meta = self.hierarchy_analyzer.validate_relationships(
                    meta_relationships, current_topics
                )
                
                if validated_meta:
                    meta_stats = self._insert_relationships(validated_meta)
                    for key in ["encompasses", "subtopic_of", "cycles_prevented", "redundant_skipped", "errors"]:
                        stats[key] += meta_stats.get(key, 0)
                    stats["relationships_created"] += len(validated_meta)
        
        return stats
    
    def _insert_relationships(self, relationships: List[Dict[str, Any]]) -> Dict[str, int]:
        """Insert hierarchical relationships into the knowledge graph."""
        stats = {
            "encompasses": 0,
            "subtopic_of": 0,
            "cycles_prevented": 0,
            "redundant_skipped": 0,
            "errors": 0
        }
        
        for rel in relationships:
            try:
                source_id = rel["source_topic_id"]
                target_id = rel["target_topic_id"]
                rel_type = rel["relationship_type"]
                confidence = rel.get("confidence", 0.0)
                reasoning = rel.get("reasoning", "")
                
                if rel_type == "ENCOMPASSES":
                    # Check for cycles
                    if self.graph_repository.would_create_cycle(source_id, target_id):
                        self.logger.debug(f"Skipping cycle: {source_id} -> {target_id}")
                        stats["cycles_prevented"] += 1
                        continue
                    
                    # Check for redundancy
                    redundancy_check = self.graph_repository.check_relationship_redundancy(source_id, target_id)
                    
                    if redundancy_check["is_redundant"]:
                        if redundancy_check["case_type"] == "transitive":
                            stats["redundant_skipped"] += 1
                            continue
                        
                        if redundancy_check["needs_llm_resolution"]:
                            applied = self._resolve_conflict(redundancy_check, source_id, target_id, confidence, reasoning)
                            if applied:
                                stats["encompasses"] += 1
                                stats["subtopic_of"] += 1
                            stats["redundant_skipped"] += 1
                            continue
                        
                        stats["redundant_skipped"] += 1
                        continue
                    
                    # Create ENCOMPASSES relationship
                    encompasses_rel = TopicEncompasses(
                        source_id=source_id,
                        target_id=target_id,
                        reasoning=reasoning,
                        confidence=confidence
                    )
                    self.graph_repository.create_relationship(encompasses_rel)
                    stats["encompasses"] += 1
                    
                    self.logger.info(f"Created ENCOMPASSES: {source_id} -> {target_id} (confidence: {confidence:.2f})")
                    
                    # Create reciprocal SUBTOPIC_OF
                    subtopic_rel = TopicSubtopicOf(
                        source_id=target_id,
                        target_id=source_id,
                        confidence=confidence
                    )
                    self.graph_repository.create_relationship(subtopic_rel)
                    stats["subtopic_of"] += 1
                else:
                    self.logger.warning(f"Unknown relationship type: {rel_type}")
                    stats["errors"] += 1
                    
            except Exception as e:
                self.logger.error(f"Error inserting relationship {rel}: {e}")
                stats["errors"] += 1
        
        return stats
    
    def _resolve_conflict(
        self, 
        redundancy_check: Dict[str, Any],
        source_id: str,
        target_id: str,
        confidence: float,
        reasoning: str
    ) -> bool:
        """Resolve a hierarchical conflict using LLM."""
        topic_ids = redundancy_check["topics_for_resolution"]
        conflict_topics = []
        
        for topic_id in topic_ids:
            topic_node = Topic(topic_id=topic_id, name="", classification="")
            topic = self.graph_repository.get_node(topic_node)
            if topic:
                conflict_topics.append(topic)
            else:
                conflict_topics.append({"topic_id": topic_id, "name": topic_id, "classification": ""})
        
        resolution = self.hierarchy_analyzer.resolve_hierarchical_conflict(redundancy_check, conflict_topics)
        
        decision = resolution.get("decision")
        llm_confidence = resolution.get("confidence", 0.0)
        
        if llm_confidence < self.hierarchy_analyzer.confidence_threshold:
            return False
        
        if decision == "keep_existing":
            return False
        
        if decision in ["remodel", "accept_proposed"]:
            # Remove old relationships
            for rel_to_remove in resolution.get("relationships_to_remove", []):
                parent_id = rel_to_remove["parent"]
                child_id = rel_to_remove["child"]
                
                encompasses_rel = TopicEncompasses(source_id=parent_id, target_id=child_id, reasoning="", confidence=0.0)
                self.graph_repository.delete_relationship(encompasses_rel)
                
                subtopic_rel = TopicSubtopicOf(source_id=child_id, target_id=parent_id, confidence=0.0)
                self.graph_repository.delete_relationship(subtopic_rel)
            
            # Add new relationships
            for rel_to_add in resolution.get("relationships_to_add", []):
                parent_id = rel_to_add["parent"]
                child_id = rel_to_add["child"]
                
                encompasses_rel = TopicEncompasses(
                    source_id=parent_id,
                    target_id=child_id,
                    reasoning=f"LLM remodeling: {resolution.get('reasoning', '')}",
                    confidence=llm_confidence
                )
                self.graph_repository.create_relationship(encompasses_rel)
                
                subtopic_rel = TopicSubtopicOf(source_id=child_id, target_id=parent_id, confidence=llm_confidence)
                self.graph_repository.create_relationship(subtopic_rel)
            
            return True
        
        return False
    
    def _log_summary(self, stats: Dict[str, Any], new_topics: List[Any]):
        """Log the final summary."""
        self.logger.info("\n" + "="*80)
        self.logger.info("TOPIC HIERARCHY ORGANIZATION COMPLETE")
        self.logger.info("="*80)
        self.logger.info(f"  Topics processed: {stats['topics_processed']}")
        self.logger.info(f"  New topics created: {stats['new_topics_created']}")
        if new_topics:
            self.logger.info(f"    New topics: {[t.name for t in new_topics]}")
        self.logger.info(f"  Clusters processed: {stats['clusters_created']}")
        self.logger.info(f"  Relationships created: {stats['relationships_created']}")
        self.logger.info(f"  ENCOMPASSES: {stats['encompasses']}")
        self.logger.info(f"  SUBTOPIC_OF: {stats['subtopic_of']}")
        if stats['cycles_prevented'] > 0:
            self.logger.info(f"  Cycles prevented: {stats['cycles_prevented']}")
        if stats['redundant_skipped'] > 0:
            self.logger.info(f"  Redundant skipped: {stats['redundant_skipped']}")
        if stats['errors'] > 0:
            self.logger.warning(f"  Errors: {stats['errors']}")
        self.logger.info("="*80)
