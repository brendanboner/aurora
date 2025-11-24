"""Build Pydantic models from extracted metadata."""

from typing import Dict, Any, List
from utils.logger import setup_logger
from settings import settings
from neo4j_client.models import (
    Resource, Topic, Organization, Person,
    ResourceRelatesToTopic, ResourceMentionsPerson, ResourceMentionsOrganization,
    PersonAffiliatedWithOrganization, PersonConnectedToTopic, OrganizationAssociatedWithTopic
)

logger = setup_logger(__name__, settings.log_level)


# Map relationship type strings to model classes
RELATIONSHIP_MODELS = {
    "RESOURCE_RELATES_TO_TOPIC": ResourceRelatesToTopic,
    "RESOURCE_MENTIONS_PERSON": ResourceMentionsPerson,
    "RESOURCE_MENTIONS_ORGANIZATION": ResourceMentionsOrganization,
    "PERSON_AFFILIATED_WITH_ORGANIZATION": PersonAffiliatedWithOrganization,
    "PERSON_CONNECTED_TO_TOPIC": PersonConnectedToTopic,
    "ORGANIZATION_ASSOCIATED_WITH_TOPIC": OrganizationAssociatedWithTopic,
}


class MetadataModelBuilder:
    """Build validated Pydantic models from raw metadata."""
    
    @staticmethod
    def build_models(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build Pydantic models from metadata dictionary.
        
        Models handle their own normalization and validation through Pydantic validators.
        
        Args:
            metadata: Dictionary with 'nodes' and 'relationships' keys
            
        Returns:
            Dictionary with built model instances:
                {
                    "nodes": {
                        "resource": Resource,
                        "topics": List[Topic],
                        "people": List[Person],
                        "organizations": List[Organization]
                    },
                    "relationships": List[Relationship]
                }
        """
        # Validate structure
        if "nodes" not in metadata:
            raise ValueError("Missing 'nodes' key in metadata")
        if "relationships" not in metadata:
            raise ValueError("Missing 'relationships' key in metadata")
        
        nodes = metadata["nodes"]
        
        # Build node models
        resource = MetadataModelBuilder._build_resource(nodes.get("resource", {}))
        topics = MetadataModelBuilder._build_topics(nodes.get("topics", []))
        organizations = MetadataModelBuilder._build_organizations(nodes.get("organizations", []))
        people = MetadataModelBuilder._build_people(nodes.get("people", []))
        
        logger.info(
            f"Built node models: 1 resource, {len(topics)} topics, "
            f"{len(people)} people, {len(organizations)} organizations"
        )
        
        # Build relationship models
        relationships = MetadataModelBuilder._build_relationships(
            raw_relationships=metadata["relationships"],
            resource=resource,
            topics=topics,
            organizations=organizations,
            people=people
        )
        
        logger.info(f"Built {len(relationships)} relationship models")
        
        return {
            "nodes": {
                "resource": resource,
                "topics": topics,
                "people": people,
                "organizations": organizations
            },
            "relationships": relationships
        }
    
    @staticmethod
    def _build_resource(data: Dict[str, Any]) -> Resource:
        """Build Resource model."""
        try:
            return Resource(
                url=data.get("url"),
                title=data.get("title"),
                summary=data.get("summary"),
                content_hash=data.get("content_hash"),
                doc_type=data.get("doc_type", "unknown"),
                category=data.get("category", "unknown"),
                scraped_at=data.get("scraped_at", ""),
                importance=data.get("importance", 0.0),
                importance_explanation=data.get("importance_explanation", "unknown"),
                extreme_impact=data.get("extreme_impact"),
                publish_date=data.get("publish_date", "unknown"),
                access_notes=data.get("access_notes"),
                datasource_id=data.get("datasource_id")
            )
        except Exception as e:
            raise ValueError(f"Failed to create Resource model: {e}")
    
    @staticmethod
    def _build_topics(topics_data: List[Dict[str, Any]]) -> List[Topic]:
        """Build Topic models."""
        topics = []
        for topic_data in topics_data:
            try:
                topic = Topic(
                    name=topic_data.get("name"),
                    classification=topic_data.get("classification"),
                    identifier=topic_data.get("identifier"),
                    issuer=topic_data.get("issuer"),
                    aliases=topic_data.get("aliases", []),
                    created_by="digester"
                )
                topics.append(topic)
            except Exception as e:
                logger.warning(f"Failed to create Topic model for '{topic_data.get('name')}': {e}")
        return topics
    
    @staticmethod
    def _build_organizations(orgs_data: List[Dict[str, Any]]) -> List[Organization]:
        """Build Organization models."""
        organizations = []
        for org_data in orgs_data:
            try:
                org = Organization(
                    name=org_data.get("name"),
                    org_type=org_data.get("org_type"),
                    aliases=org_data.get("aliases", []),
                    homepage_url=org_data.get("homepage_url")
                )
                organizations.append(org)
            except Exception as e:
                logger.warning(f"Failed to create Organization model for '{org_data.get('name')}': {e}")
        return organizations
    
    @staticmethod
    def _build_people(people_data: List[Dict[str, Any]]) -> List[Person]:
        """Build Person models."""
        people = []
        for person_data in people_data:
            try:
                person = Person(
                    name=person_data.get("name"),
                    email=person_data.get("email")
                )
                people.append(person)
            except Exception as e:
                logger.warning(f"Failed to create Person model for '{person_data.get('name')}': {e}")
        return people
    
    @staticmethod
    def _build_relationships(
        raw_relationships: List[Dict[str, Any]],
        resource: Resource,
        topics: List[Topic],
        organizations: List[Organization],
        people: List[Person]
    ) -> List[Any]:
        """
        Build relationship models by mapping identifiers to node IDs.
        
        The LLM provides human-readable identifiers (names, titles) in relationships.
        We need to map these to the actual node IDs (topic_id, person_id, etc).
        """
        # Build lookup maps: normalized name -> node ID
        # (Node names are already normalized by the models themselves)
        topic_id_map = {topic.name: topic.topic_id for topic in topics}
        person_id_map = {person.name: person.person_id for person in people}
        org_id_map = {org.name: org.org_id for org in organizations}
        
        relationships = []
        
        for rel_data in raw_relationships:
            rel_type = rel_data.get("relationship_type")
            source_identifier = rel_data.get("source_identifier")
            target_identifier = rel_data.get("target_identifier")
            
            # Map identifiers to actual node IDs
            source_id = MetadataModelBuilder._resolve_node_id(
                rel_type=rel_type,
                identifier=source_identifier,
                is_source=True,
                resource=resource,
                topic_id_map=topic_id_map,
                person_id_map=person_id_map,
                org_id_map=org_id_map
            )
            
            target_id = MetadataModelBuilder._resolve_node_id(
                rel_type=rel_type,
                identifier=target_identifier,
                is_source=False,
                resource=resource,
                topic_id_map=topic_id_map,
                person_id_map=person_id_map,
                org_id_map=org_id_map
            )
            
            # Skip if we couldn't resolve both ends
            if not source_id or not target_id:
                logger.warning(
                    f"Skipping relationship {rel_type}: "
                    f"source '{source_identifier}' -> {source_id}, "
                    f"target '{target_identifier}' -> {target_id}"
                )
                continue
            
            # Build the relationship model
            try:
                rel_model_class = RELATIONSHIP_MODELS[rel_type]
                rel_model = rel_model_class(
                    source_id=source_id,
                    target_id=target_id,
                    **{k: v for k, v in rel_data.items() 
                       if k not in ["relationship_type", "source_identifier", "target_identifier"]}
                )
                relationships.append(rel_model)
            except Exception as e:
                logger.warning(f"Failed to create {rel_type} relationship: {e}")
        
        return relationships
    
    @staticmethod
    def _resolve_node_id(
        rel_type: str,
        identifier: str,
        is_source: bool,
        resource: Resource,
        topic_id_map: Dict[str, str],
        person_id_map: Dict[str, str],
        org_id_map: Dict[str, str]
    ) -> str:
        """
        Resolve a human-readable identifier to an actual node ID.
        
        The models normalize names during instantiation, so we need to normalize
        the identifier the same way to look it up in our maps.
        """
        from neo4j_client.models import normalize_string
        
        if not identifier:
            return None
        
        # Determine node type from relationship type
        if is_source:
            if rel_type.startswith("RESOURCE_"):
                return resource.url_hash
            elif rel_type.startswith("PERSON_"):
                node_type = "person"
            elif rel_type.startswith("ORGANIZATION_"):
                node_type = "organization"
            elif rel_type.startswith("TOPIC_"):
                node_type = "topic"
            else:
                logger.warning(f"Unknown source type for relationship: {rel_type}")
                return None
        else:
            if rel_type.endswith("_TO_TOPIC") or "TOPIC" in rel_type.split("_")[-1]:
                node_type = "topic"
            elif rel_type.endswith("_TO_PERSON") or "PERSON" in rel_type.split("_")[-1]:
                node_type = "person"
            elif rel_type.endswith("_TO_ORGANIZATION") or "ORGANIZATION" in rel_type.split("_")[-1]:
                node_type = "organization"
            elif rel_type.endswith("_TO_RESOURCE"):
                return resource.url_hash
            else:
                logger.warning(f"Unknown target type for relationship: {rel_type}")
                return None
        
        # Normalize the identifier to match how the models normalize their names
        if node_type == "topic":
            normalized = normalize_string(identifier, case="lower")
            node_id = topic_id_map.get(normalized)
            if not node_id:
                logger.debug(f"Topic not found: '{identifier}' (normalized: '{normalized}'). Available: {list(topic_id_map.keys())}")
        elif node_type == "person":
            normalized = normalize_string(identifier, case="title")
            node_id = person_id_map.get(normalized)
            if not node_id:
                logger.debug(f"Person not found: '{identifier}' (normalized: '{normalized}'). Available: {list(person_id_map.keys())}")
        elif node_type == "organization":
            normalized = normalize_string(identifier, case="title")
            node_id = org_id_map.get(normalized)
            if not node_id:
                logger.debug(f"Organization not found: '{identifier}' (normalized: '{normalized}'). Available: {list(org_id_map.keys())}")
        else:
            return None
        
        return node_id
