"""Validate extracted metadata."""

from typing import Dict, Any, Optional
from datetime import datetime
from dateutil import parser
from utils.logger import setup_logger
from settings import settings


logger = setup_logger(__name__, settings.log_level)


def validate_metadata(metadata: Dict[str, Any]) -> bool:
    """
    Validate the new structured metadata format with nodes and relationships.
    
    Args:
        metadata: Dictionary containing 'nodes' and 'relationships' keys
        
    Returns:
        True if validation passes
        
    Raises:
        ValueError: If any required field is missing
    """
    # Check top-level keys
    if "nodes" not in metadata or "relationships" not in metadata:
        raise ValueError("Missing 'nodes' or 'relationships' in metadata")

    # Validate resource node
    resource = metadata["nodes"].get("resource")
    required_resource_fields = ["summary", "importance", "importance_explanation"]
    for field in required_resource_fields:
        if field not in resource:
            raise ValueError(f"Missing required field in resource: {field} in metadata")

    # Validate topics
    for topic in metadata["nodes"].get("topics", []):
        for field in ["name", "classification"]:
            if field not in topic:
                raise ValueError(f"Missing required field in topic: {field} in metadata")

    # Validate people
    for person in metadata["nodes"].get("people", []):
        if "name" not in person:
            raise ValueError("Missing required field in person: name in metadata")

    # Validate organizations
    for org in metadata["nodes"].get("organizations", []):
        for field in ["name", "org_type"]:
            if field not in org:
                raise ValueError(f"Missing required field in organization: {field} in metadata")

    # Validate relationships
    required_rel_fields = ["relationship_type", "source_identifier", "target_identifier", "confidence", "evidence"]
    for rel in metadata.get("relationships", []):
        for field in required_rel_fields:
            if field not in rel:
                raise ValueError(f"Missing required field in relationship: {field} in metadata")

    logger.info("Structured metadata validation passed")
    return True


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse a date string into a datetime object.
    
    Args:
        date_str: Date string to parse
        
    Returns:
        Parsed datetime object, or None if parsing fails
    """
    if not date_str:
        return None
    try:
        return parser.parse(date_str)
    except Exception as e:
        logger.error(f"Failed to parse date: {date_str}, error: {e}")
        return None
