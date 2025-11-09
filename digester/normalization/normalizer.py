from typing import Dict, Any, List
from utils.logger import setup_logger
from settings import settings


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
        string_fields = ["title", "summary", "resource_type", "source"]
        for field in string_fields:
            if field in normalized and normalized[field]:
                normalized[field] = normalized[field].strip()
        
        # Normalize list fields - remove duplicates and empty strings
        list_fields = [
            "topics", "standards", "standard_editions",
            "key_technologies", "industry_sectors", "use_cases"
        ]
        
        for field in list_fields:
            if field in normalized and normalized[field]:
                # Clean and deduplicate
                items = [item.strip() for item in normalized[field] if item and str(item).strip()]
                normalized[field] = list(dict.fromkeys(items))  # Preserve order while removing duplicates
            else:
                normalized[field] = []
        
        # Normalize source name (lowercase, replace spaces with hyphens)
        if "source" in normalized:
            normalized["source_normalized"] = normalized["source"].lower().replace(" ", "-")
        
        # Normalize resource type
        if "resource_type" in normalized:
            normalized["resource_type_normalized"] = normalized["resource_type"].lower().replace(" ", "-")
        
        logger.info("Metadata normalization complete")
        return normalized
    
    @staticmethod
    def extract_entities(metadata: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract entities (Resources, Topics, Standards, Standard Editions) from metadata.
        
        Args:
            metadata: The normalized metadata
            
        Returns:
            Dictionary with entity types as keys and lists of entity data as values
        """
        entities = {
            "resource": None,
            "topics": [],
            "standards": [],
            "standard_editions": []
        }
        
        # Create Resource entity
        entities["resource"] = {
            "title": metadata.get("title"),
            "url": metadata.get("url"),
            "resource_type": metadata.get("resource_type"),
            "summary": metadata.get("summary"),
            "source": metadata.get("source"),
            "publish_date": metadata.get("publish_date"),
            "timestamp": metadata.get("timestamp"),
            "key_technologies": metadata.get("key_technologies", []),
            "industry_sectors": metadata.get("industry_sectors", []),
            "use_cases": metadata.get("use_cases", [])
        }
        
        # Create Topic entities
        for topic in metadata.get("topics", []):
            entities["topics"].append({
                "name": topic
            })
        
        # Create Standard entities
        for standard in metadata.get("standards", []):
            entities["standards"].append({
                "name": standard
            })
        
        # Create Standard Edition entities
        for edition in metadata.get("standard_editions", []):
            entities["standard_editions"].append({
                "name": edition,
                "version": MetadataNormalizer._extract_version(edition)
            })
        
        logger.info(f"Extracted entities: {len(entities['topics'])} topics, "
                   f"{len(entities['standards'])} standards, "
                   f"{len(entities['standard_editions'])} standard editions")
        
        return entities
    
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
