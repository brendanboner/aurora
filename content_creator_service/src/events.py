"""Domain events ingested from RabbitMQ or polling pipelines."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class KnowledgeEvent:
    """Represents a new or updated knowledge graph event that may trigger agents."""

    event_type: str
    external_id: str
    title: str
    summary: str
    topics: List[str]
    organisations: List[str]
    published_at: Optional[datetime] = None
    importance: str = "normal"

    def fingerprint(self) -> str:
        """Unique identifier used to avoid duplicate generations."""
        return self.external_id or self.title
