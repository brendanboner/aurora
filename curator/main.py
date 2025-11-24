"""
Knowledge Graph Curator Service

This service organizes the knowledge graph by creating hierarchical relationships
between topics based on semantic similarity and LLM analysis.
"""

import sys
from typing import List, Dict, Any

from settings import settings
from utils.logger import setup_logger
from clustering import TopicClusterer
from llm.hierarchy_analyzer import HierarchyAnalyzer
from neo4j_client import Neo4jClient, GraphRepository
from neo4j_client.deduplicator import NodeDeduplicator
from neo4j_client.models import (
    Topic,
    TopicEncompasses,
    TopicSubtopicOf
)


logger = setup_logger(__name__, settings.log_level)


class CuratorService:
    """
    Main orchestrator for knowledge graph curation.
    
    Currently implements topic hierarchy organization through:
    1. Clustering topics by semantic similarity
    2. LLM analysis to identify broader/narrower relationships
    3. Inserting relationships into the knowledge graph
    """
    
    def __init__(self):
        """Initialize the curator service with all required components."""
        logger.info("Initializing Knowledge Graph Curator Service...")
        
        # Initialize Neo4j client
        self.neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            logger_instance=logger
        )
        
        self.graph_repository = None
        
        # Initialize topic clusterer
        self.clusterer = TopicClusterer(
            min_cluster_size=settings.cluster_min_size,
            max_cluster_size=settings.cluster_max_size,
            distance_threshold=settings.cluster_distance_threshold,
            overlap_neighbors=settings.cluster_overlap_neighbors,
            logger_instance=logger
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
            logger_instance=logger
        )
        
        logger.info("Curator Service initialized successfully")
    
    def connect_to_graph(self):
        """Connect to the Neo4j knowledge graph."""
        logger.info("Connecting to Neo4j knowledge graph...")
        self.neo4j_client.connect()
        self.graph_repository = GraphRepository(
            self.neo4j_client,
            logger_instance=logger
        )
        self.deduplicator = NodeDeduplicator(
            self.neo4j_client,
            logger_instance=logger
        )
        logger.info("Connected to knowledge graph")
    
    def organize_topic_hierarchy(self):
        """
        Organize topics into a hierarchy.
        
        Process:
        1. Retrieve all topics from the knowledge graph
        2. Cluster topics by semantic similarity
        3. Analyze each cluster with LLM to identify hierarchical relationships
        4. Insert relationships into the knowledge graph
        
        Note:
            Always processes ALL topics to ensure a unified hierarchy.
            Neo4j MERGE handles duplicate relationships gracefully, so re-processing
            existing topics is safe and ensures new topics integrate properly.
        """
        logger.info("="*80)
        logger.info("Starting topic hierarchy organization")
        logger.info("="*80)
        
        # Step 1: Retrieve all topics
        logger.info("Step 1: Retrieving all topics from knowledge graph...")
        topics = self.graph_repository.get_all_nodes(Topic)
        logger.info(f"Retrieved {len(topics)} topics")
        
        if not topics:
            logger.warning("No topics found to organize")
            return
        
        # Log some sample topics
        logger.info(f"Sample topics: {[t.get('name') for t in topics[:5]]}")
        
        # Step 2: Cluster topics
        logger.info("\nStep 2: Clustering topics by semantic similarity...")
        clusters = self.clusterer.cluster_topics(topics)
        
        if not clusters:
            logger.warning("No clusters created")
            return
        
        logger.info(f"Created {len(clusters)} clusters")
        for i, cluster in enumerate(clusters):
            logger.info(
                f"  Cluster {i+1}: {len(cluster)} topics - "
                f"{[t.get('name') for t in cluster[:3]]}..."
            )
        
        # Step 3: Process each cluster - propose topics, dedupe, create, analyze, insert relationships
        logger.info("\nStep 3: Processing clusters with LLM...")
        
        all_new_topics = []  # Track all new topics created across clusters
        all_relationships = []  # Accumulate all relationships
        
        # Aggregate statistics across all clusters
        total_stats = {
            "encompasses": 0,
            "subtopic_of": 0,
            "cycles_prevented": 0,
            "redundant_skipped": 0,
            "errors": 0
        }
        
        for i, cluster in enumerate(clusters):
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing Cluster {i+1}/{len(clusters)}")
            logger.info(f"{'='*60}")
            logger.info(f"Cluster topics: {[t.get('name') for t in cluster]}")
            
            # Step 3a: Suggest general topics for this cluster
            logger.info(f"\nStep 3a: Checking if cluster needs general topics...")
            suggested_topics = self.hierarchy_analyzer.suggest_general_topics(cluster)
            
            cluster_new_topics = []
            if suggested_topics:
                logger.info(f"  LLM suggested {len(suggested_topics)} general topic(s)")
                
                # Step 3b: Deduplicate using NodeDeduplicator (vector similarity + optional LLM)
                logger.info(f"\nStep 3b: Deduplicating suggested topics...")
                for proposed_topic in suggested_topics:
                    # Use the existing NodeDeduplicator from neo4j-client
                    duplicate_result = self.deduplicator.check_topic_duplicate(
                        proposed_topic,
                        k_neighbors=5,
                        similarity_threshold=0.85,  # High threshold for auto-merge
                        llm_review_threshold=0.6    # LLM reviews borderline cases
                    )
                    
                    if duplicate_result and duplicate_result.get("is_duplicate"):
                        # Duplicate found - use existing topic instead
                        existing_id = duplicate_result.get("existing_id")
                        existing_node = duplicate_result.get("existing_node")
                        similarity = duplicate_result.get("similarity_score", 0.0)
                        action = duplicate_result.get("action", "unknown")
                        logger.info(
                            f"  DUPLICATE: '{proposed_topic.name}' matches existing '{existing_id}' "
                            f"(similarity: {similarity:.2f}, action: {action})"
                        )
                        
                        # Add existing topic to cluster so LLM can create relationships to it
                        if existing_node:
                            # Check if it's already in the cluster
                            if not any(t.get("topic_id") == existing_id for t in cluster):
                                logger.info(f"    Adding existing topic '{existing_id}' to cluster")
                                cluster.append(existing_node)
                            else:
                                logger.debug(f"    Topic '{existing_id}' already in cluster")
                    else:
                        # Unique topic - insert it
                        logger.info(f"  UNIQUE: '{proposed_topic.name}' - creating in graph")
                        
                        # Step 3c: Create the new topic in Neo4j
                        try:
                            # create_node returns the created node with all properties including embedding
                            created_topic = self.graph_repository.create_node(proposed_topic)
                            
                            # DEBUG: Log what create_node returns
                            logger.debug(f"Created_topic type: {type(created_topic)}")
                            if created_topic:
                                logger.debug(f"Created_topic main fields: topic_id={created_topic.get('topic_id')}, name={created_topic.get('name')}, has_embedding={bool(created_topic.get('embedding'))}")

                            
                            if created_topic:
                                logger.info(f"    ✓ Created topic '{proposed_topic.name}' (ID: {proposed_topic.topic_id})")
                                # Add the complete topic (with embedding) to cluster
                                cluster.append(created_topic)
                                cluster_new_topics.append(proposed_topic)
                            else:
                                logger.warning(f"    ✗ Failed to create topic '{proposed_topic.name}' - no result returned")
                            
                        except Exception as e:
                            logger.error(f"    ✗ Failed to create topic '{proposed_topic.name}': {e}")
            else:
                logger.info(f"  No general topics suggested for cluster {i+1}")
            
            # Track new topics created in this cluster
            all_new_topics.extend(cluster_new_topics)
            
            # Step 3d: Analyze cluster for hierarchical relationships
            # Now the cluster includes any newly created general topics!
            logger.info(f"\nStep 3d: Analyzing relationships in augmented cluster...")
            logger.info(f"  Cluster size: {len(cluster)} topics (including {len(cluster_new_topics)} new)")
            
            cluster_relationships = self.hierarchy_analyzer.analyze_cluster(cluster)
            logger.info(f"  Found {len(cluster_relationships)} relationships")
            
            # Step 3e: Validate relationships for this cluster
            # Validation checks that all referenced topics exist in Neo4j (they do - we just created them!)
            logger.info(f"\nStep 3e: Validating relationships...")
            
            # Get current topics from Neo4j (includes newly created ones)
            current_topics = self.graph_repository.get_all_nodes(Topic)
            validated_relationships = self.hierarchy_analyzer.validate_relationships(
                cluster_relationships,
                current_topics
            )
            logger.info(f"  Validated {len(validated_relationships)}/{len(cluster_relationships)} relationships")
            
            # Step 3f: Insert relationships for this cluster
            if validated_relationships:
                logger.info(f"\nStep 3f: Inserting {len(validated_relationships)} relationships...")
                cluster_stats = self._insert_relationships(validated_relationships)
                logger.info(
                    f"  Inserted: {cluster_stats['encompasses']} ENCOMPASSES, "
                    f"{cluster_stats['subtopic_of']} SUBTOPIC_OF"
                )
                if cluster_stats['cycles_prevented'] > 0:
                    logger.info(f"  Cycles prevented: {cluster_stats['cycles_prevented']}")
                if cluster_stats['redundant_skipped'] > 0:
                    logger.info(f"  Redundant skipped: {cluster_stats['redundant_skipped']}")
                if cluster_stats['errors'] > 0:
                    logger.warning(f"  Errors: {cluster_stats['errors']}")
                
                # Aggregate stats
                for key in total_stats:
                    total_stats[key] += cluster_stats[key]
            
            # Accumulate relationships for final stats
            all_relationships.extend(validated_relationships)
            
            logger.info(f"\nCluster {i+1} processing complete")
        
        logger.info(f"\nAll intra-cluster processing complete")
        logger.info(f"  Total new topics created: {len(all_new_topics)}")
        logger.info(f"  Total relationships inserted: {len(all_relationships)}")
        
        # Step 3.5: Cross-cluster analysis (identify high-level relationships)
        logger.info(f"\n{'='*60}")
        logger.info("Step 3.5: Cross-Cluster Analysis")
        logger.info(f"{'='*60}")
        
        cross_cluster_relationships = []
        representatives = []
        
        if settings.enable_cross_cluster_analysis and len(clusters) > 1:
            logger.info("Analyzing cluster representatives for cross-cluster relationships...")
            
            # Extract representative topic from each cluster (most central)
            for i, cluster in enumerate(clusters):
                rep = self.clusterer.find_most_central_topic(cluster)
                
                # DEBUG: Log what find_most_central_topic returns
                logger.debug(f"  DEBUG Cluster {i+1}: rep type: {type(rep)}")
                if rep:
                    logger.debug(f"Cluster {i+1} representative: topic_id={rep.get('topic_id')}, name={rep.get('name')}, has_embedding={bool(rep.get('embedding'))}")
                    representatives.append(rep)
                    logger.info(f"  Cluster {i+1} representative: {rep.get('name')}")
            
            logger.info(f"\nTotal representatives: {len(representatives)}")
            
            # If we have many representatives, batch or cluster them to avoid overwhelming the LLM
            if len(representatives) <= settings.cluster_max_size:
                # Few enough representatives - analyze them all together
                logger.info(f"Analyzing all {len(representatives)} representatives in one batch")
                cross_cluster_rels = self.hierarchy_analyzer.analyze_cluster_representatives(
                    representatives
                )
                
                # Validate against current graph state
                current_topics = self.graph_repository.get_all_nodes(Topic)
                validated_cross_rels = self.hierarchy_analyzer.validate_relationships(
                    cross_cluster_rels,
                    current_topics
                )
                
                # Insert cross-cluster relationships
                if validated_cross_rels:
                    logger.info(f"Inserting {len(validated_cross_rels)} cross-cluster relationships...")
                    cross_stats = self._insert_relationships(validated_cross_rels)
                    logger.info(
                        f"  Inserted: {cross_stats['encompasses']} ENCOMPASSES, "
                        f"{cross_stats['subtopic_of']} SUBTOPIC_OF"
                    )
                    
                    # Aggregate cross-cluster stats
                    for key in total_stats:
                        total_stats[key] += cross_stats[key]
                
                cross_cluster_relationships.extend(validated_cross_rels)
                
            else:
                # Too many representatives - cluster them first, then analyze each meta-cluster
                logger.info(
                    f"Too many representatives ({len(representatives)}) for single analysis. "
                    f"Clustering representatives into meta-clusters..."
                )
                
                # Cluster the representatives themselves
                meta_clusters = self.clusterer.cluster_topics(representatives)
                logger.info(f"Created {len(meta_clusters)} meta-clusters from representatives")
                
                # Analyze each meta-cluster
                for i, meta_cluster in enumerate(meta_clusters):
                    logger.info(
                        f"  Meta-cluster {i+1}: {len(meta_cluster)} representatives - "
                        f"{[r.get('name') for r in meta_cluster[:3]]}..."
                    )
                    
                    meta_relationships = self.hierarchy_analyzer.analyze_cluster_representatives(
                        meta_cluster
                    )
                    
                    # Validate and insert
                    current_topics = self.graph_repository.get_all_nodes(Topic)
                    validated_meta = self.hierarchy_analyzer.validate_relationships(
                        meta_relationships,
                        current_topics
                    )
                    
                    if validated_meta:
                        meta_stats = self._insert_relationships(validated_meta)
                        logger.info(
                            f"    Inserted: {meta_stats['encompasses']} ENCOMPASSES, "
                            f"{meta_stats['subtopic_of']} SUBTOPIC_OF"
                        )
                        
                        # Aggregate meta-cluster stats
                        for key in total_stats:
                            total_stats[key] += meta_stats[key]
                    
                    cross_cluster_relationships.extend(validated_meta)
                
                logger.info(
                    f"Cross-cluster analysis complete: {len(cross_cluster_relationships)} "
                    f"relationships across {len(meta_clusters)} meta-clusters"
                )
        else:
            if not settings.enable_cross_cluster_analysis:
                logger.info("Cross-cluster analysis disabled in settings")
            else:
                logger.info("Only one cluster, skipping cross-cluster analysis")
        
        # Final Summary
        logger.info("\n" + "="*80)
        logger.info("TOPIC HIERARCHY ORGANIZATION COMPLETE")
        logger.info("="*80)
        logger.info(f"  Original topics from database: {len(topics)}")
        logger.info(f"  New general topics created: {len(all_new_topics)}")
        if all_new_topics:
            logger.info(f"    New topics: {[t.name for t in all_new_topics]}")
        logger.info(f"  Total topics now: {len(topics) + len(all_new_topics)}")
        logger.info(f"")
        logger.info(f"  Clusters created: {len(clusters)}")
        logger.info(f"  Cluster representatives analyzed: {len(representatives)}")
        logger.info(f"")
        logger.info(f"  Intra-cluster relationships: {len(all_relationships)}")
        logger.info(f"  Cross-cluster relationships: {len(cross_cluster_relationships)}")
        logger.info(f"  Total relationships: {len(all_relationships) + len(cross_cluster_relationships)}")
        logger.info(f"")
        logger.info(f"  ENCOMPASSES created: {total_stats['encompasses']}")
        logger.info(f"  SUBTOPIC_OF created: {total_stats['subtopic_of']}")
        if total_stats['cycles_prevented'] > 0:
            logger.info(f"  Cycles prevented: {total_stats['cycles_prevented']}")
        if total_stats['redundant_skipped'] > 0:
            logger.info(f"  Redundant relationships skipped: {total_stats['redundant_skipped']}")
        if total_stats['errors'] > 0:
            logger.warning(f"  Errors encountered: {total_stats['errors']}")
        logger.info("="*80)
    
    def _insert_relationships(
        self,
        relationships: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Insert hierarchical relationships into the knowledge graph.
        
        For each ENCOMPASSES relationship, automatically creates the reciprocal SUBTOPIC_OF.
        Validates that relationships don't create cycles before insertion.
        
        Args:
            relationships: List of relationship dictionaries from LLM analysis
            
        Returns:
            Statistics dictionary with counts of inserted relationships
        """
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
                
                # Handle new ENCOMPASSES relationship (creates reciprocal SUBTOPIC_OF)
                if rel_type == "ENCOMPASSES":
                    # Check for cycles before inserting
                    if self.graph_repository.would_create_cycle(source_id, target_id):
                        logger.warning(
                            f"Skipping ENCOMPASSES relationship that would create cycle: "
                            f"{source_id} -> {target_id}"
                        )
                        stats["cycles_prevented"] += 1
                        continue
                    
                    # Check for redundant relationships (transitive reduction)
                    redundancy_check = self.graph_repository.check_relationship_redundancy(source_id, target_id)
                    
                    if redundancy_check["is_redundant"]:
                        # Case 1: Simple transitivity - just skip
                        if redundancy_check["case_type"] == "transitive":
                            logger.info(
                                f"Skipping transitive redundancy: "
                                f"{source_id} -> {target_id} ({redundancy_check['conflict_description']})"
                            )
                            stats["redundant_skipped"] += 1
                            continue
                        
                        # Cases 2 & 3: Need LLM resolution for common parent/child conflicts
                        if redundancy_check["needs_llm_resolution"]:
                            logger.info(
                                f"Potential conflict detected: {redundancy_check['conflict_description']}"
                            )
                            logger.info("Requesting LLM resolution...")
                            
                            # Fetch only the 3 topics involved in the conflict
                            topic_ids = redundancy_check["topics_for_resolution"]
                            conflict_topics = []
                            for topic_id in topic_ids:
                                # Use general get_node method with Topic model
                                topic_node = Topic(topic_id=topic_id, name="", classification="")
                                topic = self.graph_repository.get_node(topic_node)
                                if topic:
                                    conflict_topics.append(topic)
                                else:
                                    logger.warning(f"Topic {topic_id} not found in database")
                                    # Create minimal topic dict as fallback
                                    conflict_topics.append({
                                        "topic_id": topic_id,
                                        "name": topic_id,
                                        "classification": ""
                                    })
                            
                            # Ask LLM to resolve the conflict
                            resolution = self.hierarchy_analyzer.resolve_hierarchical_conflict(
                                redundancy_check,
                                conflict_topics
                            )
                            
                            # Apply the LLM's decision
                            applied = self._apply_conflict_resolution(
                                resolution,
                                source_id,
                                target_id,
                                confidence,
                                reasoning
                            )
                            
                            if applied:
                                stats["encompasses"] += len(resolution.get("relationships_to_add", []))
                                stats["subtopic_of"] += len(resolution.get("relationships_to_add", []))
                                stats["redundant_skipped"] += 1
                                logger.info(f"Applied LLM resolution: {resolution['decision']}")
                            else:
                                stats["redundant_skipped"] += 1
                                logger.info(f"Kept existing structure per LLM decision")
                            
                            continue
                        
                        # Fallback: skip if redundant but no LLM resolution needed
                        logger.info(
                            f"Skipping redundant relationship: "
                            f"{source_id} -> {target_id} ({redundancy_check['conflict_description']})"
                        )
                        stats["redundant_skipped"] += 1
                        continue
                    
                    # Create ENCOMPASSES relationship (broader -> narrower)
                    encompasses_rel = TopicEncompasses(
                        source_id=source_id,
                        target_id=target_id,
                        reasoning=reasoning,
                        confidence=confidence
                    )
                    self.graph_repository.create_relationship(encompasses_rel)
                    stats["encompasses"] += 1
                    
                    logger.info(
                        f"Created ENCOMPASSES: {source_id} -> {target_id} "
                        f"(confidence: {confidence:.2f})"
                    )
                    if reasoning:
                        logger.debug(f"  Reasoning: {reasoning}")
                    
                    # Automatically create reciprocal SUBTOPIC_OF relationship (narrower -> broader)
                    subtopic_rel = TopicSubtopicOf(
                        source_id=target_id,  # Reversed
                        target_id=source_id,  # Reversed
                        confidence=confidence
                    )
                    self.graph_repository.create_relationship(subtopic_rel)
                    stats["subtopic_of"] += 1
                    
                    logger.info(
                        f"  └─ Auto-created SUBTOPIC_OF: {target_id} -> {source_id}"
                    )
                
                else:
                    logger.warning(f"Unknown relationship type: {rel_type}")
                    stats["errors"] += 1
                    continue
                
            except Exception as e:
                logger.error(f"Error inserting relationship {rel}: {e}")
                stats["errors"] += 1
        
        return stats
    
    def _apply_conflict_resolution(
        self,
        resolution: Dict[str, Any],
        proposed_source: str,
        proposed_target: str,
        confidence: float,
        reasoning: str
    ) -> bool:
        """
        Apply the LLM's conflict resolution decision to the graph.
        
        Args:
            resolution: LLM resolution dict with decision, relationships to add/remove
            proposed_source: Source topic ID of originally proposed relationship
            proposed_target: Target topic ID of originally proposed relationship
            confidence: Confidence of the originally proposed relationship
            reasoning: Reasoning for the originally proposed relationship
            
        Returns:
            True if changes were applied, False if existing structure was kept
        """
        decision = resolution.get("decision")
        llm_confidence = resolution.get("confidence", 0.0)
        
        # Only apply if LLM is confident (above our threshold)
        if llm_confidence < self.hierarchy_analyzer.confidence_threshold:
            logger.warning(
                f"LLM confidence ({llm_confidence:.2f}) below threshold "
                f"({self.hierarchy_analyzer.confidence_threshold}), keeping existing structure"
            )
            return False
        
        if decision == "keep_existing":
            # LLM says topics are siblings - don't add the proposed relationship
            logger.info(f"LLM decision: Topics are siblings, keeping existing structure")
            return False
        
        elif decision == "remodel" or decision == "accept_proposed":
            # Delete relationships that need to be removed
            for rel_to_remove in resolution.get("relationships_to_remove", []):
                parent_id = rel_to_remove["parent"]
                child_id = rel_to_remove["child"]
                
                # Delete both ENCOMPASSES and reciprocal SUBTOPIC_OF
                encompasses_rel = TopicEncompasses(
                    source_id=parent_id,
                    target_id=child_id,
                    reasoning="",
                    confidence=0.0
                )
                self.graph_repository.delete_relationship(encompasses_rel)
                
                subtopic_rel = TopicSubtopicOf(
                    source_id=child_id,
                    target_id=parent_id,
                    confidence=0.0
                )
                self.graph_repository.delete_relationship(subtopic_rel)
                
                logger.info(f"Removed relationship: {parent_id} -> {child_id}")
            
            # Add relationships that need to be created
            for rel_to_add in resolution.get("relationships_to_add", []):
                parent_id = rel_to_add["parent"]
                child_id = rel_to_add["child"]
                
                # Create ENCOMPASSES
                encompasses_rel = TopicEncompasses(
                    source_id=parent_id,
                    target_id=child_id,
                    reasoning=f"LLM remodeling: {resolution.get('reasoning', '')}",
                    confidence=llm_confidence
                )
                self.graph_repository.create_relationship(encompasses_rel)
                
                # Create reciprocal SUBTOPIC_OF
                subtopic_rel = TopicSubtopicOf(
                    source_id=child_id,
                    target_id=parent_id,
                    confidence=llm_confidence
                )
                self.graph_repository.create_relationship(subtopic_rel)
                
                logger.info(
                    f"Created relationship: {parent_id} -> {child_id} "
                    f"(confidence: {llm_confidence:.2f})"
                )
            
            return True
        
        else:
            logger.warning(f"Unknown LLM decision: {decision}, keeping existing structure")
            return False
    
    def run(self):
        """
        Main entry point for the curator service.
        
        This method orchestrates the entire curation workflow:
        1. Connect to the knowledge graph
        2. Organize topic hierarchy
        3. Close connections
        """
        try:
            # Connect to Neo4j
            self.connect_to_graph()
            
            # Run topic hierarchy organization (always processes all topics)
            self.organize_topic_hierarchy()
            
            logger.info("Curator service completed successfully")
            
        except KeyboardInterrupt:
            logger.info("Curator service interrupted by user")
            sys.exit(0)
            
        except Exception as e:
            logger.error(f"Fatal error in curator service: {e}", exc_info=True)
            sys.exit(1)
            
        finally:
            # Close Neo4j connection
            if self.neo4j_client:
                self.neo4j_client.close()
                logger.info("Neo4j connection closed")


def main():
    """Main entry point for the curator service."""
    logger.info("Starting Knowledge Graph Curator Service")
    logger.info(f"Configuration: {settings.model_dump()}")
    
    curator = CuratorService()
    curator.run()


if __name__ == "__main__":
    main()
