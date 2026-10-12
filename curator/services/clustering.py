"""
Topic Clustering Module

This module provides clustering functionality for organizing topics into groups
based on their embedding vectors using Agglomerative Clustering.
"""

from typing import List, Dict, Any, Tuple
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_distances
import logging


logger = logging.getLogger(__name__)


class TopicClusterer:
    """
    Clusters topics based on their embeddings using Agglomerative Clustering.
    
    Agglomerative clustering is a hierarchical clustering method that builds
    nested clusters by progressively merging similar topics. This is ideal for
    creating topic hierarchies.
    """
    
    def __init__(
        self,
        min_cluster_size: int = 3,
        max_cluster_size: int = 10,
        distance_threshold: float = 0.5,
        overlap_neighbors: int = 3,
        logger_instance: logging.Logger = None
    ):
        """
        Initialize the topic clusterer.
        
        Args:
            min_cluster_size: Minimum number of topics in a cluster
            max_cluster_size: Maximum number of topics in a cluster
            distance_threshold: Distance threshold for agglomerative clustering
            overlap_neighbors: Number of nearest external topics to add to each cluster (0 = no overlap)
            logger_instance: Optional logger instance
        """
        self.min_cluster_size = min_cluster_size
        self.max_cluster_size = max_cluster_size
        self.distance_threshold = distance_threshold
        self.overlap_neighbors = overlap_neighbors
        self.logger = logger_instance or logger
    
    def cluster_topics(
        self,
        topics: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Cluster topics based on their embedding vectors.
        
        Process:
        1. Extract embeddings and convert to numpy array
        2. Compute cosine distance matrix
        3. Perform agglomerative clustering
        4. Refine cluster sizes to meet min/max constraints
        5. Return clustered topics
        
        Args:
            topics: List of topic dictionaries with 'embedding' field
            
        Returns:
            List of clusters, where each cluster is a list of topic dictionaries
        """
        if not topics:
            self.logger.warning("No topics provided for clustering")
            return []
        
        # Normalize topics to ensure they're all flat dicts (unwrap any Cypher wrappers)
        topics = self._normalize_topics(topics)
        
        if len(topics) < self.min_cluster_size:
            self.logger.warning(
                f"Only {len(topics)} topics available, less than minimum cluster size "
                f"of {self.min_cluster_size}. Returning all topics as single cluster."
            )
            return [topics]
        
        self.logger.info(f"Clustering {len(topics)} topics...")
        
        # Step 1: Extract embeddings and filter topics without embeddings
        embeddings = self._extract_embeddings(topics)
        
        if embeddings is None:
            self.logger.error("Failed to extract embeddings from topics")
            return [topics]  # Return all as one cluster if extraction fails
        
        # Filter topics to only include those with valid embeddings
        # This ensures the topic list matches the embeddings array
        topics_with_embeddings = [
            topic for topic in topics 
            if topic.get('embedding') is not None 
            and isinstance(topic.get('embedding'), (list, np.ndarray))
        ]
        
        if len(topics_with_embeddings) != len(topics):
            self.logger.info(
                f"Using {len(topics_with_embeddings)}/{len(topics)} topics with valid embeddings for clustering"
            )
        
        if len(topics_with_embeddings) < self.min_cluster_size:
            self.logger.warning(
                f"Only {len(topics_with_embeddings)} topics with embeddings, less than minimum cluster size "
                f"of {self.min_cluster_size}. Returning as single cluster."
            )
            return [topics_with_embeddings] if topics_with_embeddings else []
        
        # Update topics reference to filtered list
        topics = topics_with_embeddings
        
        # Step 2: Compute distance matrix
        distance_matrix = cosine_distances(embeddings)
        
        # Step 3: Perform agglomerative clustering
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=self.distance_threshold,
            linkage='average',
            metric='precomputed'
        )
        
        cluster_labels = clustering.fit_predict(distance_matrix)
        
        # Step 4: Group topics by cluster label
        clusters_dict: Dict[int, List[Dict[str, Any]]] = {}
        for topic, label in zip(topics, cluster_labels):
            if label not in clusters_dict:
                clusters_dict[label] = []
            clusters_dict[label].append(topic)
        
        raw_clusters = list(clusters_dict.values())
        
        self.logger.info(
            f"Initial clustering produced {len(raw_clusters)} clusters "
            f"(sizes: {[len(c) for c in raw_clusters]})"
        )
        
        # Step 5: Refine cluster sizes
        refined_clusters = self._refine_cluster_sizes(raw_clusters, embeddings, topics)
        
        self.logger.info(
            f"Final clustering: {len(refined_clusters)} clusters "
            f"(sizes: {[len(c) for c in refined_clusters]})"
        )
        
        # Step 6: Add overlapping topics (if enabled)
        if self.overlap_neighbors > 0 and len(refined_clusters) > 1:
            overlapping_clusters = self._add_cluster_overlaps(
                refined_clusters, 
                embeddings, 
                topics
            )
            return overlapping_clusters
        
        return refined_clusters
    
    def _normalize_topics(
        self,
        topics: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize topics to ensure they're all flat dictionaries.
        
        Some topics may come wrapped in Cypher result format like {"n": {...}}.
        This method unwraps them to ensure consistent structure.
        
        Args:
            topics: List of topic dictionaries (may be wrapped)
            
        Returns:
            List of normalized (unwrapped) topic dictionaries
        """
        normalized = []
        for topic in topics:
            # If topic has only one key 'n', it's a Cypher wrapper - extract it
            if isinstance(topic, dict) and len(topic) == 1 and 'n' in topic:
                normalized.append(topic['n'])
            else:
                normalized.append(topic)
        return normalized
    
    def _extract_embeddings(
        self,
        topics: List[Dict[str, Any]]
    ) -> np.ndarray | None:
        """
        Extract embeddings from topics and convert to numpy array.
        
        Args:
            topics: List of topic dictionaries
            
        Returns:
            Numpy array of embeddings or None if extraction fails
        """
        try:
            embeddings = []
            topics_without_embeddings = []
            
            for topic in topics:
                embedding = topic.get('embedding')
                if embedding is None or not isinstance(embedding, (list, np.ndarray)):
                    topics_without_embeddings.append(topic.get('name', 'unknown'))
                    continue
                embeddings.append(embedding)
            
            # Log warning if any topics are missing embeddings
            if topics_without_embeddings:
                self.logger.warning(
                    f"{len(topics_without_embeddings)} topic(s) missing embeddings and will be excluded from clustering: "
                    f"{', '.join(topics_without_embeddings[:5])}"
                    f"{' and more...' if len(topics_without_embeddings) > 5 else ''}"
                )
            
            if not embeddings:
                self.logger.error("No topics have valid embeddings")
                return None
            
            return np.array(embeddings)
        
        except Exception as e:
            self.logger.error(f"Error extracting embeddings: {e}")
            return None
    
    def _refine_cluster_sizes(
        self,
        clusters: List[List[Dict[str, Any]]],
        embeddings: np.ndarray,
        all_topics: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Refine cluster sizes to meet min/max constraints.
        
        Strategy:
        - Clusters that are too small (< min_size): Merge with nearest cluster
        - Clusters that are too large (> max_size): Split into smaller clusters
        - Singleton clusters: Merge with nearest cluster
        
        Args:
            clusters: Initial clusters from agglomerative clustering
            embeddings: Embedding vectors for all topics
            all_topics: All topic dictionaries for reference
            
        Returns:
            Refined clusters meeting size constraints
        """
        refined = []
        
        for cluster in clusters:
            cluster_size = len(cluster)
            
            # Handle clusters that are too large
            if cluster_size > self.max_cluster_size:
                self.logger.debug(
                    f"Splitting large cluster of size {cluster_size} into smaller chunks"
                )
                # Split into chunks of max_cluster_size
                for i in range(0, cluster_size, self.max_cluster_size):
                    chunk = cluster[i:i + self.max_cluster_size]
                    if len(chunk) >= self.min_cluster_size:
                        refined.append(chunk)
                    else:
                        # If the last chunk is too small, merge it with the previous one
                        if refined and len(refined[-1]) + len(chunk) <= self.max_cluster_size:
                            refined[-1].extend(chunk)
                        else:
                            refined.append(chunk)
            
            # Handle clusters that are too small
            elif cluster_size < self.min_cluster_size:
                self.logger.debug(
                    f"Cluster of size {cluster_size} is below minimum, will attempt merge"
                )
                # Try to merge with an existing refined cluster
                merged = False
                for refined_cluster in refined:
                    if len(refined_cluster) + cluster_size <= self.max_cluster_size:
                        refined_cluster.extend(cluster)
                        merged = True
                        self.logger.debug(
                            f"Merged small cluster into existing cluster "
                            f"(new size: {len(refined_cluster)})"
                        )
                        break
                
                # If couldn't merge, keep it anyway (better than losing topics)
                if not merged:
                    self.logger.debug(
                        f"Could not merge small cluster of size {cluster_size}, keeping as-is"
                    )
                    refined.append(cluster)
            
            # Cluster is just right
            else:
                refined.append(cluster)
        
        return refined
    
    def compute_cluster_centroid(
        self,
        cluster: List[Dict[str, Any]]
    ) -> np.ndarray:
        """
        Compute the centroid (mean embedding) of a cluster.
        Useful for finding representative topics or cluster centers.
        
        Args:
            cluster: List of topics in the cluster
            
        Returns:
            Centroid embedding as numpy array
        """
        embeddings = self._extract_embeddings(cluster)
        if embeddings is None or len(embeddings) == 0:
            return np.array([])
        
        return np.mean(embeddings, axis=0)
    
    def find_most_central_topic(
        self,
        cluster: List[Dict[str, Any]]
    ) -> Dict[str, Any] | None:
        """
        Find the most central topic in a cluster (closest to centroid).
        This can be used to identify potential broader topics.
        
        Args:
            cluster: List of topics in the cluster
            
        Returns:
            The most central topic dictionary, or None if cluster is empty
        """
        if not cluster:
            return None
        
        embeddings = self._extract_embeddings(cluster)
        if embeddings is None:
            return cluster[0]  # Fallback to first topic
        
        centroid = np.mean(embeddings, axis=0)
        distances = np.linalg.norm(embeddings - centroid, axis=1)
        
        most_central_idx = np.argmin(distances)
        return cluster[most_central_idx]
    
    def _add_cluster_overlaps(
        self,
        clusters: List[List[Dict[str, Any]]],
        embeddings: np.ndarray,
        all_topics: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Add overlapping topics to clusters by finding nearest external neighbors.
        
        This creates overlapping clusters where some topics appear in multiple clusters,
        allowing cross-cluster relationships to be identified more effectively.
        
        Args:
            clusters: List of clusters (each is a list of topics)
            embeddings: Embedding vectors for all topics
            all_topics: All topic dictionaries for reference
            
        Returns:
            List of overlapping clusters
        """
        self.logger.info(
            f"Adding {self.overlap_neighbors} nearest external neighbors to each cluster "
            "for cross-cluster relationship discovery..."
        )
        
        # Create topic ID to index mapping
        topic_id_to_idx = {
            topic['topic_id']: idx 
            for idx, topic in enumerate(all_topics)
        }
        
        overlapping_clusters = []
        
        for i, cluster in enumerate(clusters):
            # Get indices of topics in this cluster
            cluster_indices = [
                topic_id_to_idx[topic['topic_id']] 
                for topic in cluster
            ]
            
            # Compute cluster centroid
            cluster_embeddings = embeddings[cluster_indices]
            centroid = np.mean(cluster_embeddings, axis=0)
            
            # Find topics NOT in this cluster
            external_indices = [
                idx for idx in range(len(all_topics))
                if idx not in cluster_indices
            ]
            
            if not external_indices:
                # No external topics (single cluster case)
                overlapping_clusters.append(cluster)
                continue
            
            # Compute distances from centroid to all external topics
            external_embeddings = embeddings[external_indices]
            distances = np.linalg.norm(external_embeddings - centroid, axis=1)
            
            # Find k nearest external topics
            k = min(self.overlap_neighbors, len(external_indices))
            nearest_indices = np.argsort(distances)[:k]
            nearest_external_indices = [external_indices[idx] for idx in nearest_indices]
            nearest_topics = [all_topics[idx] for idx in nearest_external_indices]
            
            # Create overlapping cluster (original + nearest neighbors)
            overlapping_cluster = cluster + nearest_topics
            overlapping_clusters.append(overlapping_cluster)
            
            self.logger.debug(
                f"  Cluster {i+1}: Added {len(nearest_topics)} overlap topics "
                f"({len(cluster)} → {len(overlapping_cluster)} total) - "
                f"Overlaps: {[t.get('name') for t in nearest_topics]}..."
            )
        
        return overlapping_clusters

    def build_clusters_around_seeds(
        self,
        seed_topics: List[Dict[str, Any]],
        all_topics: List[Dict[str, Any]],
        context_neighbors: int = 5
    ) -> List[List[Dict[str, Any]]]:
        """
        Build clusters around seed topics by finding their nearest neighbors from all topics.
        
        This is used for incremental curation: seed_topics are the unorganized topics
        that need to be integrated into the hierarchy, and we build context clusters
        around them using nearby topics (which may already be organized).
        
        Each seed topic gets its own cluster containing:
        - The seed topic itself
        - Its N nearest neighbors from all_topics (may include organized topics)
        
        Similar seeds may end up in overlapping clusters, which is intentional -
        it allows the LLM to see the relationships between related new topics.
        
        Args:
            seed_topics: Topics to build clusters around (e.g., unorganized topics)
            all_topics: All topics to draw neighbors from (includes organized topics)
            context_neighbors: Number of nearest neighbors to include per seed
            
        Returns:
            List of clusters, each centered on one or more seed topics with context
        """
        if not seed_topics:
            self.logger.warning("No seed topics provided for clustering")
            return []
        
        if not all_topics:
            self.logger.warning("No topics available for context")
            return [seed_topics]  # Return seeds as single cluster
        
        # Normalize both lists
        seed_topics = self._normalize_topics(seed_topics)
        all_topics = self._normalize_topics(all_topics)
        
        self.logger.info(
            f"Building clusters around {len(seed_topics)} seed topics "
            f"using {len(all_topics)} total topics for context..."
        )
        
        # Extract embeddings from all topics
        all_embeddings = self._extract_embeddings(all_topics)
        if all_embeddings is None:
            self.logger.error("Failed to extract embeddings from all topics")
            return [seed_topics]
        
        # Create topic ID to index mapping for all topics
        topic_id_to_idx = {
            topic['topic_id']: idx 
            for idx, topic in enumerate(all_topics)
        }
        
        # Create set of seed topic IDs for quick lookup
        seed_ids = {topic['topic_id'] for topic in seed_topics}
        
        # Build a cluster for each seed topic
        seed_clusters: List[List[Dict[str, Any]]] = []
        
        for seed in seed_topics:
            seed_id = seed.get('topic_id')
            seed_embedding = seed.get('embedding')
            
            if seed_embedding is None:
                self.logger.warning(f"Seed topic '{seed.get('name')}' has no embedding, skipping")
                continue
            
            seed_embedding = np.array(seed_embedding)
            
            # Compute distances from seed to all topics
            distances = np.linalg.norm(all_embeddings - seed_embedding, axis=1)
            
            # Find k+1 nearest neighbors (includes self if seed is in all_topics)
            k = min(context_neighbors + 1, len(all_topics))
            nearest_indices = np.argsort(distances)[:k]
            
            # Build cluster: seed + nearest neighbors (excluding self)
            cluster = [seed]
            for idx in nearest_indices:
                neighbor = all_topics[idx]
                if neighbor['topic_id'] != seed_id:
                    cluster.append(neighbor)
                    if len(cluster) >= context_neighbors + 1:
                        break
            
            seed_clusters.append(cluster)
            
            self.logger.debug(
                f"  Seed '{seed.get('name')}': cluster of {len(cluster)} topics - "
                f"{[t.get('name') for t in cluster[:4]]}..."
            )
        
        # Merge similar seed clusters to reduce redundancy
        merged_clusters = self._merge_similar_seed_clusters(
            seed_clusters, 
            seed_ids,
            all_topics,
            all_embeddings
        )
        
        self.logger.info(
            f"Created {len(merged_clusters)} clusters from {len(seed_topics)} seeds "
            f"(avg size: {sum(len(c) for c in merged_clusters) / len(merged_clusters):.1f})"
        )
        
        return merged_clusters
    
    def _merge_similar_seed_clusters(
        self,
        seed_clusters: List[List[Dict[str, Any]]],
        seed_ids: set,
        all_topics: List[Dict[str, Any]],
        all_embeddings: np.ndarray
    ) -> List[List[Dict[str, Any]]]:
        """
        Merge seed clusters that have significant overlap or similar centroids.
        
        This reduces the number of LLM calls by combining clusters that would
        analyze the same topics anyway.
        
        Args:
            seed_clusters: List of clusters, each centered on a seed topic
            seed_ids: Set of seed topic IDs
            all_topics: All topics for reference
            all_embeddings: Embeddings for all topics
            
        Returns:
            Merged clusters
        """
        if len(seed_clusters) <= 1:
            return seed_clusters
        
        # Calculate centroids for each cluster
        cluster_centroids = []
        for cluster in seed_clusters:
            embeddings = self._extract_embeddings(cluster)
            if embeddings is not None and len(embeddings) > 0:
                cluster_centroids.append(np.mean(embeddings, axis=0))
            else:
                cluster_centroids.append(None)
        
        # Find clusters to merge based on centroid similarity
        merged = []
        used = set()
        
        for i, cluster in enumerate(seed_clusters):
            if i in used:
                continue
            
            # Start with this cluster
            merged_cluster = list(cluster)
            merged_cluster_ids = {t['topic_id'] for t in merged_cluster}
            used.add(i)
            
            if cluster_centroids[i] is None:
                merged.append(merged_cluster)
                continue
            
            # Find similar clusters to merge
            for j, other_cluster in enumerate(seed_clusters):
                if j in used or cluster_centroids[j] is None:
                    continue
                
                # Check centroid similarity
                distance = np.linalg.norm(cluster_centroids[i] - cluster_centroids[j])
                
                # Merge if centroids are close (distance threshold)
                if distance < self.distance_threshold:
                    # Add topics from other cluster that aren't already in merged
                    for topic in other_cluster:
                        if topic['topic_id'] not in merged_cluster_ids:
                            # Only add if we won't exceed max size
                            if len(merged_cluster) < self.max_cluster_size:
                                merged_cluster.append(topic)
                                merged_cluster_ids.add(topic['topic_id'])
                    used.add(j)
            
            # If cluster is too large, split it but ensure seeds are distributed
            if len(merged_cluster) > self.max_cluster_size:
                # Split into chunks, ensuring each chunk has at least one seed
                seeds_in_cluster = [t for t in merged_cluster if t['topic_id'] in seed_ids]
                context_in_cluster = [t for t in merged_cluster if t['topic_id'] not in seed_ids]
                
                # Distribute seeds across chunks
                chunk_size = self.max_cluster_size
                num_chunks = (len(merged_cluster) + chunk_size - 1) // chunk_size
                
                for chunk_idx in range(num_chunks):
                    chunk = []
                    # Add seed(s) to this chunk
                    seed_start = chunk_idx * len(seeds_in_cluster) // num_chunks
                    seed_end = (chunk_idx + 1) * len(seeds_in_cluster) // num_chunks
                    chunk.extend(seeds_in_cluster[seed_start:seed_end])
                    
                    # Fill with context topics
                    context_start = chunk_idx * len(context_in_cluster) // num_chunks
                    context_end = (chunk_idx + 1) * len(context_in_cluster) // num_chunks
                    chunk.extend(context_in_cluster[context_start:context_end])
                    
                    if chunk:
                        merged.append(chunk)
            else:
                merged.append(merged_cluster)
        
        return merged
