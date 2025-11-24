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
        
        # Step 1: Extract embeddings
        embeddings = self._extract_embeddings(topics)
        
        if embeddings is None:
            self.logger.error("Failed to extract embeddings from topics")
            return [topics]  # Return all as one cluster if extraction fails
        
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
            for topic in topics:
                embedding = topic.get('embedding')
                if embedding is None or not isinstance(embedding, (list, np.ndarray)):
                    self.logger.warning(
                        f"Topic '{topic.get('name', 'unknown')}' has no valid embedding"
                    )
                    # Use zero vector as fallback
                    embedding = [0.0] * 768  # Default embedding dimension
                embeddings.append(embedding)
            
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
                self.logger.info(
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
                self.logger.info(
                    f"Cluster of size {cluster_size} is below minimum, will attempt merge"
                )
                # Try to merge with an existing refined cluster
                merged = False
                for refined_cluster in refined:
                    if len(refined_cluster) + cluster_size <= self.max_cluster_size:
                        refined_cluster.extend(cluster)
                        merged = True
                        self.logger.info(
                            f"Merged small cluster into existing cluster "
                            f"(new size: {len(refined_cluster)})"
                        )
                        break
                
                # If couldn't merge, keep it anyway (better than losing topics)
                if not merged:
                    self.logger.warning(
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
            
            self.logger.info(
                f"  Cluster {i+1}: Added {len(nearest_topics)} overlap topics "
                f"({len(cluster)} → {len(overlapping_cluster)} total) - "
                f"Overlaps: {[t.get('name') for t in nearest_topics]}..."
            )
        
        return overlapping_clusters
