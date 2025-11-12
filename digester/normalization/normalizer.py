from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
import json
import ast
from utils.logger import setup_logger
from settings import settings
from neo4j_client.models import (
    Resource, Topic, Standard, StandardEdition,
    ResourceRelatesToTopic, ResourceReferencesStandard, ResourceReferencesEdition
)


logger = setup_logger(__name__, settings.log_level)


class MetadataNormalizer:
    """Normalize extracted metadata."""
    
    @staticmethod
    def normalize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize metadata by cleaning and standardizing values.
        
        Args:
            metadata: The metadata dictionary to normalize
            
        Returns:
            Normalized metadata dictionary
        """
        normalized = metadata.copy()
        
        # Normalize string fields
        string_fields = ["title", "summary", "category", "datasource_id"]
        for field in string_fields:
            if field in normalized and normalized[field]:
                normalized[field] = normalized[field].strip()
        
        # Normalize list fields - remove duplicates and empty names
        list_fields = [
            "topics", "standards", "standard_editions"
        ]
        
        for field in list_fields:
            if field in normalized and normalized[field]:
                cleaned_items = []
                seen_names = set()
                
                for item in normalized[field]:
                    
                    # First, check if item is a string representation of a dict
                    if isinstance(item, str):
                        try:
                            # Try to parse as JSON first
                            item = json.loads(item)
                            logger.info(f"Converted JSON string to dict: {item}")
                        except (json.JSONDecodeError, ValueError):
                            try:
                                # Fallback to ast.literal_eval for Python dict strings
                                item = ast.literal_eval(item)
                                logger.info(f"Converted Python dict string to dict: {item}")
                            except (ValueError, SyntaxError):
                                # If parsing fails, raise exception to retry message
                                error_msg = f"Failed to parse item in field '{field}': {item}. Expected dict format."
                                logger.error(error_msg)
                                raise ValueError(error_msg)
                    
                    if isinstance(item, dict):
                        # Normalize the name field
                        name = item.get("name", "").strip()
                        
                        # Skip items with empty names or duplicate names
                        if name and name not in seen_names:
                            # Create normalized dict with cleaned name
                            normalized_item = {"name": name}
                            
                            # Preserve other fields (confidence, relevance, etc.)
                            for key, value in item.items():
                                if key != "name":
                                    normalized_item[key] = value
                            
                            cleaned_items.append(normalized_item)
                            seen_names.add(name)
                    else:
                        # Item is not a dict and couldn't be converted - raise exception
                        error_msg = f"Invalid item type in field '{field}': {type(item)}. Expected dict, got: {item}"
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                
                normalized[field] = cleaned_items
            else:
                normalized[field] = []
        
        # Normalize datasource_id name (lowercase, replace spaces with hyphens)
        if "datasource_id" in normalized:
            normalized["datasource_id"] = normalized["datasource_id"].lower().replace(" ", "-")
        
        # Normalize resource type
        if "category" in normalized:
            normalized["category"] = normalized["category"].lower().replace(" ", "-")
        
        logger.info("Metadata normalization complete")
        return normalized
    
    @staticmethod
    def extract_entities(metadata: Dict[str, Any]) -> Tuple[
        Resource, 
        List[Tuple[Topic, ResourceRelatesToTopic]], 
        List[Tuple[Standard, ResourceReferencesStandard]], 
        List[Tuple[StandardEdition, ResourceReferencesEdition]],
        Optional[str]
    ]:
        """
        Extract entities (Resources, Topics, Standards, Standard Editions) from metadata.
        
        Args:
            metadata: The normalized metadata with topics/standards as dicts containing scores
            
        Returns:
            Tuple of (resource, topics_with_rels, standards_with_rels, standard_editions_with_rels, datasource_name)
            where each list contains tuples of (model, relationship_model) and datasource_name is optional
        """

        # Convert scraped_at timestamp to datetime
        scraped_at = metadata.get("scraped_at")
        if scraped_at and isinstance(scraped_at, (int, float)):
            scraped_at_dt = datetime.fromtimestamp(scraped_at)
        else:
            scraped_at_dt = datetime.now()
        
        # Extract data source name
        datasource_id = metadata.get("datasource_id")
        
        # Create Resource entity
        resource = Resource(
            title=metadata.get("title", ""),
            url=metadata.get("url", ""),
            doc_type=metadata.get("category", "unknown"),  # Maps to doc_type
            category=metadata.get("category", "unknown"),   # Maps to category
            summary=metadata.get("summary", ""),
            content_hash=metadata.get("content_hash", ""),
            publish_date=metadata.get("publish_date", "unknown"),
            scraped_at=scraped_at_dt,
            language="en"  # Default, could be extracted from metadata if available
        )

        # Create Topic entities with relationship properties
        topics_with_rels = []
        for topic_dict in metadata.get("topics", []):
            topic = Topic(name=topic_dict.get("name", ""))
            rel = ResourceRelatesToTopic(
                confidence=topic_dict.get("confidence"),
                relevance_score=topic_dict.get("relevance")
            )
            topics_with_rels.append((topic, rel))


        # Create Standard entities with relationship properties
        standards_with_rels = []
        for standard_dict in metadata.get("standards", []):
            standard = Standard(
                identifier=standard_dict.get("name", ""),
                name=standard_dict.get("name", "")
            )
            rel = ResourceReferencesStandard(
                confidence=standard_dict.get("confidence")
            )
            standards_with_rels.append((standard, rel))

        # Create Standard Edition entities with relationship properties
        standard_editions_with_rels = []
        for edition_dict in metadata.get("standard_editions", []):
            logger.info(f"Processing Standard Edition: {edition_dict}")
            logger.info(f"Type of Standard Edition: {type(edition_dict)}")
            edition_name = edition_dict.get("name", "")
            edition = StandardEdition(
                name=edition_name,
                identifier=edition_name,
                version=MetadataNormalizer._extract_version(edition_name)
            )
            rel = ResourceReferencesEdition(
                confidence=edition_dict.get("confidence")
            )
            standard_editions_with_rels.append((edition, rel))
        
        logger.info(f"Extracted entities: {len(topics_with_rels)} topics, "
                   f"{len(standards_with_rels)} standards, "
                   f"{len(standard_editions_with_rels)} standard editions, "
                   f"datasource_id: {datasource_id}")
        
        return resource, topics_with_rels, standards_with_rels, standard_editions_with_rels, datasource_id
    
    @staticmethod
    def _extract_version(edition_name: str) -> str:
        """Extract version number from standard edition name."""
        import re
        # Look for patterns like "2021", "v3", "3.0", etc.
        version_pattern = r'(?:v?(\d+(?:\.\d+)*)|-(\d{4}))'
        match = re.search(version_pattern, edition_name)
        if match:
            return match.group(1) or match.group(2)
        return ""
