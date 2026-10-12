"""
Algorithmic Hierarchy Inference Module

Infers topic hierarchical relationships using algorithmic methods instead of LLM.
Uses name patterns, embedding analysis, classification rules, and graph structure.
"""

import re
import logging
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


class AlgorithmicHierarchyInference:
    """
    Infers hierarchical relationships between topics using algorithmic methods.
    
    Methods:
    1. Name pattern matching (version numbers, substrings, standards)
    2. Embedding centrality (central topics = parents)
    3. Classification hierarchy (domain > field > technology > protocol)
    4. Neighbor inference (similar to existing children = same parent)
    """
    
    # Classification hierarchy levels (lower number = more general)
    CLASSIFICATION_HIERARCHY = {
        'domain': 1,
        'field': 2,
        'technology': 3,
        'standard': 3,
        'framework': 4,
        'protocol': 5,
        'certification': 5,
        'implementation': 6,
        'product': 6
    }
    
    def __init__(self, logger_instance: Optional[logging.Logger] = None):
        """Initialize the algorithmic inference engine."""
        self.logger = logger_instance or logger
    
    def infer_all_relationships(
        self,
        topics: List[Dict[str, Any]],
        confidence_threshold: float = 0.75
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Infer all relationships using multiple algorithmic methods.
        
        Args:
            topics: List of topic dictionaries
            confidence_threshold: Minimum confidence for high-confidence relationships
            
        Returns:
            Tuple of (high_confidence_relationships, needs_review_relationships)
        """
        self.logger.info(f"Running algorithmic inference on {len(topics)} topics...")
        
        # Gather relationships from all methods
        name_rels = self.infer_from_names(topics)
        embedding_rels = self.infer_from_embeddings(topics)
        classification_rels = self.infer_from_classification(topics)
        
        self.logger.info(
            f"Inference results: {len(name_rels)} name-based, "
            f"{len(embedding_rels)} embedding-based, "
            f"{len(classification_rels)} classification-based"
        )
        
        # Merge and filter
        high_confidence, needs_review = self.merge_and_filter_relationships(
            name_rels,
            embedding_rels,
            classification_rels,
            [],  # neighbor_rels added separately for incremental
            confidence_threshold
        )
        
        self.logger.info(
            f"After merging: {len(high_confidence)} high-confidence, "
            f"{len(needs_review)} need review"
        )
        
        return high_confidence, needs_review
    
    def infer_from_names(self, topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Infer hierarchical relationships from name patterns.
        
        Patterns detected:
        - Substring: "Wi-Fi" ⊃ "Wi-Fi 6"
        - Version: "Python" ⊃ "Python 3.11"
        - Standard: "IEEE 802.11" ⊃ "IEEE 802.11ax"
        - Extension: "AI" ⊃ "AI Ethics"
        """
        relationships = []
        
        # Sort topics by name length (shorter names = more general)
        sorted_topics = sorted(topics, key=lambda t: len(t.get('name', '')))
        
        for i, specific_topic in enumerate(sorted_topics):
            specific_name = specific_topic.get('name', '')
            if not specific_name:
                continue
            
            for general_topic in sorted_topics[:i]:
                general_name = general_topic.get('name', '')
                if not general_name:
                    continue
                
                # Check if names suggest hierarchy
                is_hierarchical, confidence = self._check_name_hierarchy(
                    general_name, 
                    specific_name,
                    general_topic.get('classification'),
                    specific_topic.get('classification')
                )
                
                if is_hierarchical and confidence > 0.5:
                    relationships.append({
                        'source_topic_id': general_topic['topic_id'],
                        'target_topic_id': specific_topic['topic_id'],
                        'confidence': confidence,
                        'method': 'name_pattern',
                        'reasoning': f"Name pattern: '{general_name}' encompasses '{specific_name}'"
                    })
        
        return relationships
    
    def _check_name_hierarchy(
        self,
        general_name: str,
        specific_name: str,
        general_class: Optional[str] = None,
        specific_class: Optional[str] = None
    ) -> Tuple[bool, float]:
        """
        Check if specific_name is likely a child of general_name.
        
        Returns:
            (is_hierarchical, confidence_score)
        """
        general_lower = general_name.lower().strip()
        specific_lower = specific_name.lower().strip()
        
        # Avoid self-reference
        if general_lower == specific_lower:
            return False, 0.0
        
        # Pattern 1: Specific starts with general (substring)
        if specific_lower.startswith(general_lower):
            remainder = specific_lower[len(general_lower):].strip()
            
            # Check for version number pattern
            if re.match(r'^[\s\-:\.]*v?\d+[\.\d]*[a-z]?$', remainder):
                # "Python" → "Python 3.11"
                confidence = 0.95
                if general_class == specific_class:
                    confidence = 0.98
                return True, confidence
            
            # Check for extension/qualifier
            if len(remainder) > 0 and len(remainder) < len(general_lower) * 2:
                # "AI" → "AI Ethics"
                confidence = 0.80
                if general_class == specific_class:
                    confidence = 0.85
                return True, confidence
        
        # Pattern 2: Standard notation (e.g., IEEE 802.11 ⊃ IEEE 802.11ax)
        if re.match(r'^[a-z]+\s+\d+[\.\d]*', general_lower):
            if specific_lower.startswith(general_lower):
                return True, 0.90
        
        # Pattern 3: Acronym expansion
        if self._is_acronym_of(general_lower, specific_lower):
            return True, 0.70
        
        return False, 0.0
    
    def _is_acronym_of(self, short: str, long: str) -> bool:
        """Check if short is an acronym of long."""
        words = re.findall(r'\b\w+', long)
        if len(words) < 2:
            return False
        acronym = ''.join(w[0] for w in words).lower()
        return short == acronym
    
    def infer_from_embeddings(
        self,
        topics: List[Dict[str, Any]],
        max_parents_per_cluster: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Infer hierarchical relationships from embedding centrality.
        
        Algorithm:
        1. Compute cluster centroid
        2. Most central topics (closest to centroid) = likely parents
        3. Peripheral topics = likely children
        4. Connect if similarity is in sweet spot (0.60-0.85)
        """
        if len(topics) < 3:
            return []
        
        relationships = []
        
        # Extract embeddings
        topics_with_embeddings = [
            t for t in topics 
            if t.get('embedding') is not None and isinstance(t.get('embedding'), (list, np.ndarray))
        ]
        
        if len(topics_with_embeddings) < 3:
            return []
        
        try:
            embeddings = np.array([t['embedding'] for t in topics_with_embeddings])
            centroid = np.mean(embeddings, axis=0).reshape(1, -1)
            
            # Calculate distances from centroid
            distances = []
            for i, topic in enumerate(topics_with_embeddings):
                topic_emb = embeddings[i].reshape(1, -1)
                dist = np.linalg.norm(embeddings[i] - centroid)
                distances.append((topic, dist, i))
            
            # Sort by centrality (most central first)
            distances.sort(key=lambda x: x[1])
            
            # Top N are potential parents
            potential_parents = distances[:max_parents_per_cluster]
            potential_children = distances[max_parents_per_cluster:]
            
            for parent_topic, parent_dist, parent_idx in potential_parents:
                parent_emb = embeddings[parent_idx].reshape(1, -1)
                
                for child_topic, child_dist, child_idx in potential_children:
                    child_emb = embeddings[child_idx].reshape(1, -1)
                    
                    # Calculate similarity
                    similarity = cosine_similarity(parent_emb, child_emb)[0][0]
                    
                    # Sweet spot: related but hierarchical (not siblings)
                    if 0.60 < similarity < 0.85:
                        # Higher confidence if child is more peripheral
                        peripherality_factor = (child_dist - parent_dist) / (child_dist + parent_dist + 0.001)
                        confidence = 0.60 + (peripherality_factor * 0.15)
                        confidence = min(max(confidence, 0.50), 0.75)
                        
                        relationships.append({
                            'source_topic_id': parent_topic['topic_id'],
                            'target_topic_id': child_topic['topic_id'],
                            'confidence': confidence,
                            'method': 'embedding_centrality',
                            'reasoning': f"Embedding centrality: parent dist={parent_dist:.2f}, child dist={child_dist:.2f}, similarity={similarity:.2f}"
                        })
        
        except Exception as e:
            self.logger.warning(f"Error in embedding inference: {e}")
        
        return relationships
    
    def infer_from_classification(
        self,
        topics: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Infer hierarchical relationships from topic classifications.
        
        Uses classification hierarchy:
        domain (1) > field (2) > technology/standard (3) > framework/protocol (4-5) > implementation (6)
        """
        relationships = []
        
        for general_topic in topics:
            general_class = general_topic.get('classification', '').lower()
            general_level = self.CLASSIFICATION_HIERARCHY.get(general_class, 99)
            
            if general_level == 99:
                continue
            
            for specific_topic in topics:
                if general_topic['topic_id'] == specific_topic['topic_id']:
                    continue
                
                specific_class = specific_topic.get('classification', '').lower()
                specific_level = self.CLASSIFICATION_HIERARCHY.get(specific_class, 99)
                
                if specific_level == 99:
                    continue
                
                # General must be at higher level
                if general_level < specific_level:
                    # Check if they're semantically related via embeddings
                    try:
                        general_emb = general_topic.get('embedding')
                        specific_emb = specific_topic.get('embedding')
                        
                        if general_emb is not None and specific_emb is not None:
                            general_emb = np.array(general_emb).reshape(1, -1)
                            specific_emb = np.array(specific_emb).reshape(1, -1)
                            similarity = cosine_similarity(general_emb, specific_emb)[0][0]
                            
                            if similarity > 0.60:
                                confidence = 0.65 + (similarity - 0.60) * 0.2
                                confidence = min(confidence, 0.75)
                                
                                relationships.append({
                                    'source_topic_id': general_topic['topic_id'],
                                    'target_topic_id': specific_topic['topic_id'],
                                    'confidence': confidence,
                                    'method': 'classification_hierarchy',
                                    'reasoning': f"Classification: {general_class} ({general_level}) encompasses {specific_class} ({specific_level}), similarity={similarity:.2f}"
                                })
                    except Exception as e:
                        self.logger.debug(f"Error computing similarity for classification: {e}")
        
        return relationships
    
    def infer_from_neighbors(
        self,
        new_topics: List[Dict[str, Any]],
        existing_topics_with_parents: List[Tuple[Dict[str, Any], List[str]]]
    ) -> List[Dict[str, Any]]:
        """
        Infer relationships by analyzing existing graph structure.
        
        Logic: If new_topic is similar to existing topics with same parent,
        it likely has the same parent.
        
        Args:
            new_topics: New topics to organize
            existing_topics_with_parents: List of (topic, parent_ids) tuples
        """
        relationships = []
        
        if not existing_topics_with_parents:
            return []
        
        for new_topic in new_topics:
            new_emb = new_topic.get('embedding')
            if new_emb is None:
                continue
            
            new_emb_arr = np.array(new_emb).reshape(1, -1)
            
            # Find similar existing topics
            similarities = []
            for existing_topic, parent_ids in existing_topics_with_parents:
                existing_emb = existing_topic.get('embedding')
                if existing_emb is None or not parent_ids:
                    continue
                
                existing_emb_arr = np.array(existing_emb).reshape(1, -1)
                similarity = cosine_similarity(new_emb_arr, existing_emb_arr)[0][0]
                
                if similarity > 0.70:
                    similarities.append((existing_topic, parent_ids, similarity))
            
            # Sort by similarity
            similarities.sort(key=lambda x: x[2], reverse=True)
            
            # Consider top 3 most similar
            for existing_topic, parent_ids, similarity in similarities[:3]:
                for parent_id in parent_ids:
                    # Confidence based on similarity
                    confidence = 0.65 + (similarity - 0.70) * 0.3
                    confidence = min(confidence, 0.80)
                    
                    relationships.append({
                        'source_topic_id': parent_id,
                        'target_topic_id': new_topic['topic_id'],
                        'confidence': confidence,
                        'method': 'neighbor_inference',
                        'reasoning': f"Similar to '{existing_topic['name']}' (similarity={similarity:.2f}) which has this parent"
                    })
        
        return relationships
    
    def merge_and_filter_relationships(
        self,
        name_based: List[Dict[str, Any]],
        embedding_based: List[Dict[str, Any]],
        classification_based: List[Dict[str, Any]],
        neighbor_based: List[Dict[str, Any]],
        confidence_threshold: float = 0.75
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Merge relationships from all methods and split by confidence.
        
        When multiple methods suggest the same relationship:
        - Average their confidence scores
        - Add bonus for multiple methods agreeing
        
        Returns:
            (high_confidence_relationships, needs_review_relationships)
        """
        # Merge by (source, target) key
        merged = {}
        
        all_relationships = name_based + embedding_based + classification_based + neighbor_based
        
        for rel in all_relationships:
            key = (rel['source_topic_id'], rel['target_topic_id'])
            
            if key not in merged:
                merged[key] = {
                    'source_topic_id': rel['source_topic_id'],
                    'target_topic_id': rel['target_topic_id'],
                    'confidence_scores': [],
                    'methods': [],
                    'reasonings': []
                }
            
            merged[key]['confidence_scores'].append(rel['confidence'])
            merged[key]['methods'].append(rel['method'])
            merged[key]['reasonings'].append(rel['reasoning'])
        
        # Calculate final confidence and split
        high_confidence = []
        needs_review = []
        
        for key, data in merged.items():
            # Average confidence
            avg_confidence = sum(data['confidence_scores']) / len(data['confidence_scores'])
            
            # Bonus for multiple methods agreeing (max +0.15)
            method_bonus = min(0.05 * (len(data['methods']) - 1), 0.15)
            
            final_confidence = min(avg_confidence + method_bonus, 1.0)
            
            relationship = {
                'source_topic_id': data['source_topic_id'],
                'target_topic_id': data['target_topic_id'],
                'relationship_type': 'ENCOMPASSES',
                'confidence': final_confidence,
                'reasoning': f"Algorithmic inference ({', '.join(set(data['methods']))}): {data['reasonings'][0]}"
            }
            
            if final_confidence >= confidence_threshold:
                high_confidence.append(relationship)
            else:
                needs_review.append(relationship)
        
        return high_confidence, needs_review
