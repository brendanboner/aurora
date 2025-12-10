"""
Hierarchy Analyzer Module

This module uses LLM to analyze topic clusters and identify broader-than and
narrower-than relationships between topics.
"""

import json
import logging
import time
from typing import List, Dict, Any, Optional
from openai import AzureOpenAI, RateLimitError, APIError

from .prompts import (
    HIERARCHY_ANALYSIS_SYSTEM_PROMPT,
    HIERARCHY_ANALYSIS_USER_PROMPT,
    CONFLICT_RESOLUTION_SYSTEM_PROMPT,
    CONFLICT_RESOLUTION_USER_PROMPT,
    GENERAL_TOPIC_SUGGESTION_SYSTEM_PROMPT,
    GENERAL_TOPIC_SUGGESTION_USER_PROMPT,
    format_topics_for_prompt
)
from neo4j_client.models import Topic


logger = logging.getLogger(__name__)


class HierarchyAnalyzer:
    """
    Uses Azure OpenAI to analyze topic clusters and identify hierarchical relationships.
    """
    
    def __init__(
        self,
        api_key: str,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-08-01-preview",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        confidence_threshold: float = 0.7,
        logger_instance: Optional[logging.Logger] = None
    ):
        """
        Initialize the hierarchy analyzer.
        
        Args:
            api_key: Azure OpenAI API key
            endpoint: Azure OpenAI endpoint URL
            deployment: Azure OpenAI deployment name
            api_version: Azure OpenAI API version
            max_tokens: Maximum tokens for LLM response
            temperature: LLM temperature (lower = more deterministic)
            confidence_threshold: Minimum confidence to accept relationships
            logger_instance: Optional logger instance
        """
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint
        )
        self.deployment = deployment
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.confidence_threshold = confidence_threshold
        self.logger = logger_instance or logger
        
        # Retry configuration for rate limits
        self.max_retries = 5
        self.initial_retry_delay = 10  # seconds
        self.max_retry_delay = 120  # seconds
        
        self.logger.info(
            f"Initialized HierarchyAnalyzer with deployment: {deployment}, "
            f"confidence threshold: {confidence_threshold}"
        )
    
    def _call_llm_with_retry(
        self,
        messages: List[Dict[str, str]],
        operation_name: str = "LLM call"
    ) -> Optional[str]:
        """
        Make an LLM API call with automatic retry on rate limit errors.
        
        Uses exponential backoff when rate limited, waiting progressively longer
        between retries up to max_retry_delay.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            operation_name: Name of the operation for logging
            
        Returns:
            The response content string, or None if all retries failed
            
        Raises:
            Exception: If a non-rate-limit error occurs
        """
        retry_delay = self.initial_retry_delay
        
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"}
                )
                return response.choices[0].message.content.strip()
                
            except RateLimitError as e:
                # Extract retry-after if provided in the error
                retry_after = getattr(e, 'retry_after', None)
                if retry_after:
                    wait_time = int(retry_after)
                else:
                    wait_time = min(retry_delay, self.max_retry_delay)
                
                if attempt < self.max_retries - 1:
                    self.logger.warning(
                        f"Rate limited during {operation_name} (attempt {attempt + 1}/{self.max_retries}). "
                        f"Waiting {wait_time} seconds before retry..."
                    )
                    time.sleep(wait_time)
                    # Exponential backoff for next attempt
                    retry_delay = min(retry_delay * 2, self.max_retry_delay)
                else:
                    self.logger.error(
                        f"Rate limit exceeded after {self.max_retries} attempts for {operation_name}"
                    )
                    raise
                    
            except APIError as e:
                # Handle other API errors (server errors, etc.)
                if e.status_code and e.status_code >= 500:
                    # Server error - retry
                    if attempt < self.max_retries - 1:
                        wait_time = min(retry_delay, self.max_retry_delay)
                        self.logger.warning(
                            f"Server error during {operation_name} (attempt {attempt + 1}/{self.max_retries}): {e}. "
                            f"Waiting {wait_time} seconds before retry..."
                        )
                        time.sleep(wait_time)
                        retry_delay = min(retry_delay * 2, self.max_retry_delay)
                    else:
                        self.logger.error(
                            f"Server error persisted after {self.max_retries} attempts for {operation_name}"
                        )
                        raise
                else:
                    # Client error - don't retry
                    raise
        
        return None
    
    def analyze_cluster(
        self,
        cluster: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze a cluster of topics to identify hierarchical relationships.
        
        Args:
            cluster: List of topic dictionaries in the cluster
            
        Returns:
            List of relationship dictionaries with fields:
                - source_topic_id: Source topic ID
                - target_topic_id: Target topic ID
                - relationship_type: "BROADER_THAN" or "NARROWER_THAN"
                - confidence: Confidence score (0.0-1.0)
                - reasoning: Explanation of the relationship
        """
        if not cluster or len(cluster) < 2:
            self.logger.warning(
                f"Cluster has fewer than 2 topics ({len(cluster)}), skipping analysis"
            )
            return []
        
        self.logger.info(
            f"Analyzing cluster with {len(cluster)} topics: "
            f"{[t.get('name', 'unknown') for t in cluster]}"
        )
        
        # Format topics for the prompt
        topics_json = format_topics_for_prompt(cluster)
        
        # Build the prompt
        user_prompt = HIERARCHY_ANALYSIS_USER_PROMPT.format(
            topics_json=topics_json
        )
        
        try:
            # Call Azure OpenAI with retry logic
            messages = [
                {"role": "system", "content": HIERARCHY_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            
            response_text = self._call_llm_with_retry(
                messages, 
                operation_name="cluster analysis"
            )
            
            if response_text is None:
                self.logger.error("LLM call returned no response after retries")
                return []
            
            self.logger.debug(f"LLM response: {response_text}")
            
            result = json.loads(response_text)
            relationships = result.get("relationships", [])
            
            # Filter by confidence threshold
            filtered_relationships = [
                rel for rel in relationships
                if rel.get("confidence", 0) >= self.confidence_threshold
            ]
            
            self.logger.info(
                f"Found {len(relationships)} relationships "
                f"({len(filtered_relationships)} above confidence threshold of {self.confidence_threshold})"
            )
            
            # Log the relationships
            for rel in filtered_relationships:
                self.logger.info(
                    f"  {rel['source_topic_id']} --{rel['relationship_type']}--> "
                    f"{rel['target_topic_id']} "
                    f"(confidence: {rel['confidence']:.2f})"
                )
            
            return filtered_relationships
        
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse LLM response as JSON: {e}")
            self.logger.error(f"Response text: {response_text if 'response_text' in locals() else 'N/A'}")
            return []
        
        except Exception as e:
            self.logger.error(f"Error analyzing cluster: {e}", exc_info=True)
            return []
    
    def analyze_multiple_clusters(
        self,
        clusters: List[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze multiple clusters and return all hierarchical relationships.
        
        Args:
            clusters: List of clusters, where each cluster is a list of topics
            
        Returns:
            Combined list of all relationships across all clusters
        """
        all_relationships = []
        
        for i, cluster in enumerate(clusters):
            self.logger.info(f"Analyzing cluster {i+1}/{len(clusters)}")
            
            cluster_relationships = self.analyze_cluster(cluster)
            all_relationships.extend(cluster_relationships)
        
        self.logger.info(
            f"Analyzed {len(clusters)} clusters, found {len(all_relationships)} "
            f"total relationships"
        )
        
        return all_relationships
    
    def analyze_cluster_representatives(
        self,
        representatives: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze representative topics from different clusters to identify
        high-level cross-cluster hierarchical relationships.
        
        This second-pass analysis ensures that broader topics from one cluster
        (e.g., "Wireless Standards") can be connected to more specific topics
        from another cluster (e.g., "Wi-Fi").
        
        Args:
            representatives: List of representative topics (one per cluster)
            
        Returns:
            List of cross-cluster relationship dictionaries
        """
        if not representatives or len(representatives) < 2:
            self.logger.info(
                f"Only {len(representatives)} cluster representatives, "
                "skipping cross-cluster analysis"
            )
            return []
        
        self.logger.info(
            f"Analyzing {len(representatives)} cluster representatives for "
            "cross-cluster relationships"
        )
        self.logger.info(
            f"Representatives: {[r.get('name', 'unknown') for r in representatives]}"
        )
        
        # Use the same analysis method as regular clusters
        # This ensures consistency in how relationships are identified
        cross_cluster_relationships = self.analyze_cluster(representatives)
        
        self.logger.info(
            f"Found {len(cross_cluster_relationships)} cross-cluster relationships"
        )
        
        return cross_cluster_relationships
    
    def validate_relationships(
        self,
        relationships: List[Dict[str, Any]],
        all_topics: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Validate that all relationships reference existing topics.
        
        Args:
            relationships: List of relationship dictionaries
            all_topics: List of all topic dictionaries
            
        Returns:
            Filtered list of valid relationships
        """
        topic_ids = {topic["topic_id"] for topic in all_topics}
        valid_relationships = []
        
        for rel in relationships:
            source_id = rel.get("source_topic_id")
            target_id = rel.get("target_topic_id")
            
            if source_id not in topic_ids:
                self.logger.warning(
                    f"Relationship references unknown source topic: {source_id}"
                )
                continue
            
            if target_id not in topic_ids:
                self.logger.warning(
                    f"Relationship references unknown target topic: {target_id}"
                )
                continue
            
            if source_id == target_id:
                self.logger.warning(
                    f"Relationship has same source and target: {source_id}"
                )
                continue
            
            valid_relationships.append(rel)
        
        self.logger.info(
            f"Validated {len(valid_relationships)}/{len(relationships)} relationships"
        )
        
        return valid_relationships

    def resolve_hierarchical_conflict(
        self,
        conflict_data: Dict[str, Any],
        conflict_topics: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use LLM to resolve a hierarchical conflict between three topics.
        
        This is called when redundancy detection finds a potential conflict:
        - Case 2: Common parent (A→B, A→C exist, trying B→C)
        - Case 3: Common child (A→C, B→C exist, trying A→B)
        
        Args:
            conflict_data: Dict from check_relationship_redundancy with keys:
                - case_type: 'common_parent' or 'common_child'
                - topics_for_resolution: [topic_id_1, topic_id_2, topic_id_3]
                - existing_relationships: List of {parent, child} dicts
                - proposed_relationship: {parent, child} dict
                - conflict_description: Human-readable description
                - common_node_id: ID of common parent or child
            conflict_topics: List of exactly 3 topic dictionaries involved in the conflict
            
        Returns:
            Dict with resolution decision:
                - decision: 'remodel' | 'keep_existing' | 'accept_proposed'
                - reasoning: Explanation from LLM
                - final_structure: List of {parent, child} relationships
                - relationships_to_remove: List of {parent, child} to delete
                - relationships_to_add: List of {parent, child} to create
                - confidence: Confidence score
        """
        topic_ids = conflict_data["topics_for_resolution"]
        
        self.logger.info(
            f"Resolving {conflict_data['case_type']} conflict for topics: {topic_ids}"
        )
        
        # Format topics for prompt
        topics_json = format_topics_for_prompt(conflict_topics)
        
        # Format relationships for display
        existing_rels_str = json.dumps(conflict_data["existing_relationships"], indent=2)
        proposed_rel_str = json.dumps(conflict_data["proposed_relationship"], indent=2)
        
        # Build the prompt
        user_prompt = CONFLICT_RESOLUTION_USER_PROMPT.format(
            conflict_type=conflict_data["case_type"],
            topics_json=topics_json,
            existing_relationships=existing_rels_str,
            proposed_relationship=proposed_rel_str,
            conflict_description=conflict_data["conflict_description"]
        )
        
        try:
            # Call Azure OpenAI with retry logic
            messages = [
                {"role": "system", "content": CONFLICT_RESOLUTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            
            response_text = self._call_llm_with_retry(
                messages,
                operation_name="conflict resolution"
            )
            
            if response_text is None:
                self.logger.error("LLM call returned no response after retries")
                return {
                    "decision": "keep_existing",
                    "reasoning": "LLM call failed after retries",
                    "final_structure": conflict_data["existing_relationships"],
                    "relationships_to_remove": [],
                    "relationships_to_add": [],
                    "confidence": 0.0
                }
            
            self.logger.debug(f"LLM conflict resolution response: {response_text}")
            
            resolution = json.loads(response_text)
            
            # Log the decision
            self.logger.info(
                f"LLM decision: {resolution.get('decision')} "
                f"(confidence: {resolution.get('confidence', 0):.2f})"
            )
            self.logger.info(f"Reasoning: {resolution.get('reasoning', 'N/A')}")
            
            # Log structural changes
            if resolution.get("relationships_to_remove"):
                self.logger.info(f"  To remove: {resolution['relationships_to_remove']}")
            if resolution.get("relationships_to_add"):
                self.logger.info(f"  To add: {resolution['relationships_to_add']}")
            
            return resolution
        
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse LLM conflict resolution response as JSON: {e}")
            self.logger.error(f"Response text: {response_text if 'response_text' in locals() else 'N/A'}")
            # Return a conservative default: keep existing structure
            return {
                "decision": "keep_existing",
                "reasoning": f"JSON parse error: {str(e)}",
                "final_structure": conflict_data["existing_relationships"],
                "relationships_to_remove": [],
                "relationships_to_add": [],
                "confidence": 0.0
            }
        
        except Exception as e:
            self.logger.error(f"Error resolving conflict: {e}", exc_info=True)
            # Return a conservative default: keep existing structure
            return {
                "decision": "keep_existing",
                "reasoning": f"Error during LLM call: {str(e)}",
                "final_structure": conflict_data["existing_relationships"],
                "relationships_to_remove": [],
                "relationships_to_add": [],
                "confidence": 0.0
            }


    def suggest_general_topics(
        self,
        cluster: List[Dict[str, Any]]
    ) -> List[Topic]:
        """
        Analyze a cluster and suggest 0-N general/umbrella topics to organize it.
        
        This method identifies when a cluster would benefit from one or more broader
        topics that don't currently exist. For example, a cluster with "Wi-Fi 6",
        "Wi-Fi 6E", "Wi-Fi 7" might benefit from a "Wi-Fi Standards" umbrella topic.
        
        Args:
            cluster: List of topic dictionaries in the cluster
            
        Returns:
            List of Topic model instances for suggested general topics
        """
        if not cluster or len(cluster) < 2:
            self.logger.info(
                f"Cluster has fewer than 2 topics ({len(cluster)}), "
                "skipping general topic suggestion"
            )
            return []
        
        self.logger.info(
            f"Analyzing cluster for general topic suggestions: "
            f"{[t.get('name', 'unknown') for t in cluster]}"
        )
        
        # Format topics for the prompt
        topics_json = format_topics_for_prompt(cluster)
        
        # Build the prompt
        user_prompt = GENERAL_TOPIC_SUGGESTION_USER_PROMPT.format(
            topics_json=topics_json
        )
        
        try:
            # Call Azure OpenAI with retry logic
            messages = [
                {"role": "system", "content": GENERAL_TOPIC_SUGGESTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            
            response_text = self._call_llm_with_retry(
                messages,
                operation_name="general topic suggestion"
            )
            
            if response_text is None:
                self.logger.error("LLM call returned no response after retries")
                return []
            
            self.logger.debug(f"LLM general topic suggestion response: {response_text}")
            
            result = json.loads(response_text)
            suggested_topics_raw = result.get("suggested_topics", [])
            
            # Convert to Topic model instances
            suggested_topics = []
            for topic_data in suggested_topics_raw:
                try:
                    # Create Topic model (topic_id will be auto-generated from name)
                    topic = Topic(
                        name=topic_data["name"],
                        classification=topic_data["classification"],
                        identifier=topic_data.get("identifier"),
                        issuer=topic_data.get("issuer"),
                        aliases=topic_data.get("aliases", []),
                        created_by="curator"
                    )
                    
                    # Log the suggestion
                    self.logger.info(
                        f"  Suggested: '{topic.name}' ({topic.classification}) "
                        f"→ encompasses {len(topic_data.get('would_encompass', []))} topics"
                    )
                    self.logger.debug(f"    Reasoning: {topic_data.get('reasoning', 'N/A')}")
                    
                    suggested_topics.append(topic)
                    
                except Exception as e:
                    self.logger.error(
                        f"Failed to create Topic model from suggestion: {topic_data}. Error: {e}"
                    )
                    continue
            
            self.logger.info(
                f"Suggested {len(suggested_topics)} general topic(s) for cluster"
            )
            
            return suggested_topics
        
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse LLM response as JSON: {e}")
            self.logger.error(f"Response text: {response_text if 'response_text' in locals() else 'N/A'}")
            return []
        
        except Exception as e:
            self.logger.error(f"Error suggesting general topics: {e}", exc_info=True)
            return []

