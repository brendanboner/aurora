from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
import ast
from utils.logger import setup_logger
from settings import settings
from neo4j_client.models import *


logger = setup_logger(__name__, settings.log_level)


class MetadataNormalizer:
    RELATIONSHIP_TYPE_MAP = {
        "RESOURCE_RELATES_TO_TOPIC": ResourceRelatesToTopic,
        "RESOURCE_MENTIONS_PERSON": ResourceMentionsPerson,
        "RESOURCE_MENTIONS_ORGANIZATION": ResourceMentionsOrganization,
        "RESOURCE_MENTIONS_EVENT": ResourceMentionsEvent,
        "PERSON_AFFILIATED_WITH_ORGANIZATION": PersonAffiliatedWithOrganization,
        "PERSON_CONNECTED_TO_TOPIC": PersonConnectedToTopic,
        "ORGANIZATION_ASSOCIATED_WITH_TOPIC": OrganizationAssociatedWithTopic,
    }

    # Define normalization cases for each relationship type
    RELATIONSHIP_CASE_MAP = {
        "RESOURCE_RELATES_TO_TOPIC": {"source": "title", "target": "lower"},
        "RESOURCE_MENTIONS_PERSON": {"source": "title", "target": "title"},
        "RESOURCE_MENTIONS_ORGANIZATION": {"source": "title", "target": "title"},
        "RESOURCE_MENTIONS_EVENT": {"source": "title", "target": "title"},
        "PERSON_AFFILIATED_WITH_ORGANIZATION": {"source": "title", "target": "title"},
        "PERSON_CONNECTED_TO_TOPIC": {"source": "title", "target": "lower"},
        "ORGANIZATION_ASSOCIATED_WITH_TOPIC": {"source": "title", "target": "lower"},
    }
    @staticmethod
    def normalize_string_field(value: Any, case: str = "lower"):
        """
        Normalize a string field or list of string fields from LLM output.
        - Handles both single strings and lists of strings
        - Converts to string if not already
        - Strips leading/trailing whitespace
        - Collapses multiple spaces
        - Normalizes case: 'upper', 'lower', 'title', 'sentence'
        - Returns empty string for None (or empty list for list input)
        - Filters out None/empty values from lists
        
        Args:
            value: The input value to normalize (str, List[str], or Any)
            case: Case normalization ('upper', 'lower', 'title', 'sentence')
            
        Returns:
            Normalized string, or list of normalized strings if input was a list
        """
        # Handle None
        if value is None:
            return ""
        
        # Handle list of strings
        if isinstance(value, list):
            normalized_list = []
            for item in value:
                if item is None:
                    continue
                if not isinstance(item, str):
                    item = str(item)
                item = item.strip()
                item = " ".join(item.split())
                
                # Apply case normalization
                if case == "upper":
                    item = item.upper()
                elif case == "lower":
                    item = item.lower()
                elif case == "title":
                    item = item.title()
                elif case == "sentence":
                    if item:
                        item = item[0].upper() + item[1:].lower()
                
                # Only add non-empty strings
                if item:
                    normalized_list.append(item)
            
            return normalized_list
        
        # Handle single string
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        value = " ".join(value.split())
        if case == "upper":
            value = value.upper()
        elif case == "lower":
            value = value.lower()
        elif case == "title":
            value = value.title()
        elif case == "sentence":
            if value:
                value = value[0].upper() + value[1:].lower()
        return value
    """Normalize extracted metadata."""
    
    @staticmethod
    def normalize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build and validate models from the new metadata structure.
        Models will normalize and validate fields on creation.
        
        Args:
            metadata: The metadata dictionary with 'nodes' and 'relationships' keys
            
        Returns:
            Dictionary with validated models
        """
        # Validate top-level structure
        if "nodes" not in metadata:
            raise ValueError("Missing 'nodes' key in metadata")
        
        if "relationships" not in metadata:
            raise ValueError("Missing 'relationships' key in metadata")
        
        nodes = metadata.get("nodes", {})

        # Build Resource models
        resource_data = nodes.get("resource", {})
        try:
            # Parse publish_date to datetime if available
            publish_date = None
            if resource_data.get("publish_date") and resource_data.get("publish_date") != "unknown":
                try:
                    from dateutil.parser import parse as date_parse
                    publish_date = date_parse(resource_data.get("publish_date"))
                except Exception as e:
                    logger.warning(f"Failed to parse publish_date '{resource_data.get('publish_date')}': {e}")
                    # Fall back to scraped_at if publish_date is unparseable
                    if resource_data.get("scraped_at"):
                        publish_date = resource_data.get("scraped_at")
            
            resource_model = Resource(
                url=resource_data.get("url"),
                title=MetadataNormalizer.normalize_string_field(resource_data.get("title"), case="title"),
                summary=MetadataNormalizer.normalize_string_field(resource_data.get("summary"), case="sentence"),
                content_hash=resource_data.get("content_hash"),
                doc_type=MetadataNormalizer.normalize_string_field(resource_data.get("doc_type", "unknown")),
                category=MetadataNormalizer.normalize_string_field(resource_data.get("category", "unknown")),
                scraped_at=resource_data.get("scraped_at", ""),
                importance=resource_data.get("importance", 0.0),
                importance_explanation=MetadataNormalizer.normalize_string_field(resource_data.get("importance_explanation", "unknown"), case="sentence"),
                extreme_impact=MetadataNormalizer.normalize_string_field(resource_data.get("extreme_impact", None), case="sentence"),
                publish_date=publish_date,
                access_notes=MetadataNormalizer.normalize_string_field(resource_data.get("access_notes", None), case="sentence"),
                datasource_id=resource_data.get("datasource_id")
            )
        except Exception as e:
            raise ValueError(f"Failed to create Resource model: {e}")
        
        # Build Topic models - models will handle validation and normalization
        topic_models = []
        for topic_data in nodes.get("topics", []):
            try:
                topic = Topic(
                    name=MetadataNormalizer.normalize_string_field(topic_data.get("name"), case="lower"),
                    classification=MetadataNormalizer.normalize_string_field(topic_data.get("classification")),
                    identifier=MetadataNormalizer.normalize_string_field(topic_data.get("identifier", None)),
                    issuer=MetadataNormalizer.normalize_string_field(topic_data.get("issuer", None)),
                    aliases=MetadataNormalizer.normalize_string_field(topic_data.get("aliases", []), case="title")
                )
                topic_models.append(topic)
            except Exception as e:
                logger.warning(f"Failed to create Topic model for {topic_data.get('name')}: {e}")
        
        # Build Organization models
        org_models = []
        for org_data in nodes.get("organizations", []):
            try:
                org = Organization(
                    name=MetadataNormalizer.normalize_string_field(org_data.get("name"), case="title"),
                    org_type=MetadataNormalizer.normalize_string_field(org_data.get("org_type")),
                    aliases=MetadataNormalizer.normalize_string_field(org_data.get("aliases", []), case="title"),
                    homepage_url=MetadataNormalizer.normalize_string_field(org_data.get("homepage_url", None))
                )
                org_models.append(org)
            except Exception as e:
                logger.warning(f"Failed to create Organization model for {org_data.get('name')}: {e}")

        # Build Person models
        person_models = []
        for person_data in nodes.get("people", []):
            try:
                person = Person(
                    name=MetadataNormalizer.normalize_string_field(person_data.get("name"), case="title"),
                    email=MetadataNormalizer.normalize_string_field(person_data.get("email", None))
                )
                person_models.append(person)
            except Exception as e:
                logger.warning(f"Failed to create Person model for {person_data.get('name')}: {e}")
        
        # Build Event models
        event_models = []
        for event_data in nodes.get("events", []):
            try:
                # Parse start_date and end_date to datetime objects
                start_date = None
                if event_data.get("start_date"):
                    try:
                        from dateutil.parser import parse as date_parse
                        start_date = date_parse(event_data.get("start_date"))
                    except Exception as e:
                        logger.warning(f"Failed to parse start_date for event {event_data.get('name')}: {e}")
                
                end_date = None
                if event_data.get("end_date"):
                    try:
                        from dateutil.parser import parse as date_parse
                        end_date = date_parse(event_data.get("end_date"))
                    except Exception as e:
                        logger.warning(f"Failed to parse end_date for event {event_data.get('name')}: {e}")
                
                event = Event(
                    name=MetadataNormalizer.normalize_string_field(event_data.get("name"), case="title"),
                    event_type=MetadataNormalizer.normalize_string_field(event_data.get("event_type")),
                    start_date=start_date,
                    end_date=end_date,
                    location=MetadataNormalizer.normalize_string_field(event_data.get("location", ""), case="title"),
                    timezone=MetadataNormalizer.normalize_string_field(event_data.get("timezone", None)),
                    description=MetadataNormalizer.normalize_string_field(event_data.get("description", ""), case="sentence"),
                    url=MetadataNormalizer.normalize_string_field(event_data.get("url", None))
                )
                event_models.append(event)
            except Exception as e:
                logger.warning(f"Failed to create Event model for {event_data.get('name')}: {e}")
        
        logger.info(f"Built models: 1 resource, {len(topic_models)} topics, {len(person_models)} people, {len(org_models)} organizations, {len(event_models)} events")
        
        # Normalize Relationships
        relationships = metadata.get("relationships", [])
        # Build lookup maps for node identifiers to unique id fields
        resource_url_hash = resource_model.url_hash if resource_model else None
        topic_id_map = {t.name: getattr(t, t.id_field) for t in topic_models}
        person_id_map = {p.name: getattr(p, p.id_field) for p in person_models}
        org_id_map = {o.name: getattr(o, o.id_field) for o in org_models}
        event_id_map = {e.name: getattr(e, e.id_field) for e in event_models}

        relationship_models = []
        for rel_data in relationships:
            rel_type = rel_data.get("relationship_type")
            source_identifier = rel_data.get("source_identifier")
            target_identifier = rel_data.get("target_identifier")

            # Normalize identifiers to match the normalized names in the lookup maps
            # BUT don't normalize URLs - keep them as-is
            def normalize_identifier(identifier, target_case="title"):
                """Normalize identifier only if it's not a URL."""
                if not identifier:
                    return None
                # Check if it's a URL (simple heuristic: starts with http:// or https://)
                if isinstance(identifier, str) and (identifier.startswith('http://') or identifier.startswith('https://')):
                    return identifier  # Don't normalize URLs
                return MetadataNormalizer.normalize_string_field(identifier, case=target_case)
            
            # Get normalization cases from RELATIONSHIP_CASE_MAP, fallback to defaults
            case_map = MetadataNormalizer.RELATIONSHIP_CASE_MAP.get(rel_type, {})
            source_case = case_map.get("source")
            target_case = case_map.get("target")
            
            normalized_source_identifier = normalize_identifier(source_identifier, source_case)
            normalized_target_identifier = normalize_identifier(target_identifier, target_case)

            # Map source_id
            if rel_type.startswith("RESOURCE_"):
                source_id = resource_url_hash
            elif rel_type.startswith("PERSON_"):
                source_id = person_id_map.get(normalized_source_identifier)
                if not source_id:
                    logger.warning(f"Person not found for source_identifier '{source_identifier}' (normalized: '{normalized_source_identifier}'). Available: {list(person_id_map.keys())}")
            elif rel_type.startswith("ORGANIZATION_"):
                source_id = org_id_map.get(normalized_source_identifier)
                if not source_id:
                    logger.warning(f"Organization not found for source_identifier '{source_identifier}' (normalized: '{normalized_source_identifier}'). Available: {list(org_id_map.keys())}")
            elif rel_type.startswith("TOPIC_"):
                source_id = topic_id_map.get(normalized_source_identifier)
                if not source_id:
                    logger.warning(f"Topic not found for source_identifier '{source_identifier}' (normalized: '{normalized_source_identifier}'). Available: {list(topic_id_map.keys())}")
            else:
                source_id = source_identifier

            # Map target_id
            if rel_type.endswith("_TO_TOPIC") or rel_type.endswith("_CONNECTED_TO_TOPIC") or rel_type.endswith("_ASSOCIATED_WITH_TOPIC") or rel_type == "RESOURCE_RELATES_TO_TOPIC":
                target_id = topic_id_map.get(normalized_target_identifier)
                if not target_id:
                    logger.warning(f"Topic not found for target_identifier '{target_identifier}' (normalized: '{normalized_target_identifier}'). Available: {list(topic_id_map.keys())}")
            elif rel_type.endswith("_TO_PERSON") or rel_type == "RESOURCE_MENTIONS_PERSON":
                target_id = person_id_map.get(normalized_target_identifier)
                if not target_id:
                    logger.warning(f"Person not found for target_identifier '{target_identifier}' (normalized: '{normalized_target_identifier}'). Available: {list(person_id_map.keys())}")
            elif rel_type.endswith("_TO_ORGANIZATION") or rel_type == "RESOURCE_MENTIONS_ORGANIZATION" or rel_type == "PERSON_AFFILIATED_WITH_ORGANIZATION":
                target_id = org_id_map.get(normalized_target_identifier)
                if not target_id:
                    logger.warning(f"Organization not found for target_identifier '{target_identifier}' (normalized: '{normalized_target_identifier}'). Available: {list(org_id_map.keys())}")
            elif rel_type == "RESOURCE_MENTIONS_EVENT":
                target_id = event_id_map.get(normalized_target_identifier)
                if not target_id:
                    logger.warning(f"Event not found for target_identifier '{target_identifier}' (normalized: '{normalized_target_identifier}'). Available: {list(event_id_map.keys())}")
            elif rel_type.endswith("_TO_RESOURCE"):
                target_id = resource_url_hash
            else:
                target_id = target_identifier

            # Skip relationship if source or target couldn't be mapped
            if not source_id or not target_id:
                logger.warning(f"Skipping relationship {rel_type} due to missing source_id ({source_id}) or target_id ({target_id})")
                continue

            # Remove keys not needed in the model right before instantiation
            rel_data.pop("relationship_type", None)
            rel_data.pop("source_identifier", None)
            rel_data.pop("target_identifier", None)
            rel_data["source_id"] = source_id
            rel_data["target_id"] = target_id
            
            relationship_models.append(MetadataNormalizer.RELATIONSHIP_TYPE_MAP[rel_type](**rel_data))

        logger.info(f"Built {len(relationship_models)} relationship models")

        # Return structure with models and original metadata
        return {
            "nodes": {
                "resource": resource_model,
                "topics": topic_models,
                "people": person_models,
                "organizations": org_models,
                "events": event_models
            },
            "relationships": relationship_models
        }
    
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
