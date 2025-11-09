"""Node models for Neo4j knowledge graph."""

from typing import Dict, Any, List, Optional
from datetime import datetime


class Node:
    """Base class for graph nodes."""
    
    def __init__(self, **properties):
        self.properties = properties
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary."""
        return self.properties


class Resource(Node):
    """Resource node - represents a document/resource."""
    
    def __init__(
        self,
        title: str,
        url: str,
        resource_type: str,
        summary: str,
        source: str,
        publish_date: Optional[str] = None,
        timestamp: Optional[float] = None,
        key_technologies: Optional[List[str]] = None,
        industry_sectors: Optional[List[str]] = None,
        use_cases: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(
            title=title,
            url=url,
            resource_type=resource_type,
            summary=summary,
            source=source,
            publish_date=publish_date,
            timestamp=timestamp,
            key_technologies=key_technologies or [],
            industry_sectors=industry_sectors or [],
            use_cases=use_cases or [],
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Topic(Node):
    """Topic node - represents a subject or topic."""
    
    def __init__(self, name: str, **kwargs):
        super().__init__(
            name=name,
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Standard(Node):
    """Standard node - represents a technical standard."""
    
    def __init__(self, name: str, **kwargs):
        super().__init__(
            name=name,
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class StandardEdition(Node):
    """Standard Edition node - represents a specific version of a standard."""
    
    def __init__(self, name: str, version: Optional[str] = None, **kwargs):
        super().__init__(
            name=name,
            version=version or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Organization(Node):
    """Organization node - represents an organization."""
    
    def __init__(self, name: str, description: Optional[str] = None, **kwargs):
        super().__init__(
            name=name,
            description=description or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class DataSource(Node):
    """DataSource node - represents a data source."""
    
    def __init__(
        self,
        name: str,
        url: Optional[str] = None,
        source_type: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            url=url or "",
            source_type=source_type or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Person(Node):
    """Person node - represents an individual."""
    
    def __init__(
        self,
        name: str,
        email: Optional[str] = None,
        title: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            email=email or "",
            title=title or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Team(Node):
    """Team node - represents a team or group."""
    
    def __init__(self, name: str, description: Optional[str] = None, **kwargs):
        super().__init__(
            name=name,
            description=description or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Project(Node):
    """Project node - represents a project."""
    
    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        status: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            description=description or "",
            status=status or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Skill(Node):
    """Skill node - represents a skill or competency."""
    
    def __init__(self, name: str, category: Optional[str] = None, **kwargs):
        super().__init__(
            name=name,
            category=category or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Report(Node):
    """Report node - represents a report."""
    
    def __init__(
        self,
        title: str,
        report_type: str,
        summary: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            title=title,
            report_type=report_type,
            summary=summary or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Insight(Node):
    """Insight node - represents an insight or finding."""
    
    def __init__(
        self,
        content: str,
        source: Optional[str] = None,
        confidence: Optional[float] = None,
        **kwargs
    ):
        super().__init__(
            content=content,
            source=source or "",
            confidence=confidence,
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Digest(Node):
    """Digest node - represents a content digest."""
    
    def __init__(
        self,
        title: str,
        summary: str,
        period: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            title=title,
            summary=summary,
            period=period or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Tag(Node):
    """Tag node - represents a tag or label."""
    
    def __init__(self, name: str, category: Optional[str] = None, **kwargs):
        super().__init__(
            name=name,
            category=category or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class IngestionEvent(Node):
    """Ingestion Event node - represents a data ingestion event."""
    
    def __init__(
        self,
        event_type: str,
        status: str,
        timestamp: float,
        details: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            event_type=event_type,
            status=status,
            timestamp=timestamp,
            details=details or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )


class Event(Node):
    """Event node - represents a general event."""
    
    def __init__(
        self,
        name: str,
        event_type: str,
        date: Optional[str] = None,
        location: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            event_type=event_type,
            date=date or "",
            location=location or "",
            created_at=datetime.now().isoformat(),
            **kwargs
        )
