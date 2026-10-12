"""
Event Association Service for the digester.

This service handles automatic association of documents with events based on
dates found in document titles. It supports:
- Date extraction from titles
- Single event auto-linking
- LLM disambiguation for multiple events on the same date

Returns relationship models to be added to the normal pipeline flow,
rather than inserting directly into the graph.
"""

import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import date

from settings import settings
from utils.logger import setup_logger
from utils.llm_helpers import call_llm_with_retry, parse_json_from_llm_response
from utils.date_helpers import extract_date_from_title
from utils.prompts import EVENT_DISAMBIGUATION_PROMPT, MAX_REASONING_LENGTH, MAX_EVIDENCE_LENGTH
from neo4j_client import GraphRepository
from neo4j_client.models import ResourceRelatesToEvent

logger = setup_logger(__name__, settings.log_level)


# Auto-link confidence for single event matches
SINGLE_EVENT_CONFIDENCE = 0.95

# Maximum error message length for evidence field
MAX_ERROR_MESSAGE_LENGTH = 50


class EventAssociator:
    """
    Associate documents with events based on dates in document titles.
    
    Returns relationship models that can be added to the models dict
    and flow through the normal deduplication/insertion pipeline.
    """
    
    def __init__(self, graph_repository: GraphRepository):
        """
        Initialize the EventAssociator.
        
        Args:
            graph_repository: GraphRepository instance for querying events
        """
        self.graph_repository = graph_repository
        
        logger.info("Initialized EventAssociator")
    
    async def _call_llm(self, prompt: str) -> str:
        """Call Azure OpenAI with retry logic for rate limits."""
        messages = [
            {"role": "system", "content": "You are an expert at matching documents to events. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ]
        return await call_llm_with_retry(
            messages=messages,
            temperature=0.1,
            max_tokens=200
        )
    
    def _format_events_list(self, events: List[Dict[str, Any]]) -> str:
        """Format events list for the LLM prompt."""
        lines = []
        for i, event in enumerate(events, 1):
            name = event.get("name", "Unknown Event")
            event_type = event.get("event_type", "unknown")
            description = event.get("description", "")[:150]
            if len(event.get("description", "")) > 150:
                description += "..."
            
            lines.append(f"{i}. {name}")
            lines.append(f"   Type: {event_type}")
            if description:
                lines.append(f"   Description: {description}")
            lines.append("")
        
        return "\n".join(lines)
    
    async def _disambiguate_events(
        self,
        title: str,
        summary: str,
        extracted_date: date,
        events: List[Dict[str, Any]]
    ) -> Tuple[Optional[Dict[str, Any]], float, str]:
        """Use LLM to disambiguate between multiple events."""
        events_list = self._format_events_list(events)
        
        prompt = EVENT_DISAMBIGUATION_PROMPT.format(
            title=title,
            summary=summary or "(No summary available)",
            extracted_date=extracted_date.isoformat(),
            events_list=events_list
        )
        
        try:
            response = await self._call_llm(prompt)
            
            # Parse JSON response
            json_str = parse_json_from_llm_response(response)
            result = json.loads(json_str)
            
            event_index = result.get("event_index", 0)
            confidence = float(result.get("confidence", 0.0))
            reasoning = result.get("reasoning", "")[:MAX_REASONING_LENGTH]
            
            # Valid range: 0 (no match) or 1 to len(events) (1-based indexing)
            if event_index < 0 or event_index > len(events):
                logger.warning(f"LLM returned invalid event_index {event_index} (valid: 0 or 1-{len(events)}), treating as no match")
                return None, 0.0, "Invalid event index returned"
            
            if event_index == 0:
                return None, confidence, reasoning
            
            return events[event_index - 1], confidence, reasoning
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM disambiguation response: {e}", exc_info=True)
            return None, 0.0, "Failed to parse LLM response"
        except Exception as e:
            logger.error(f"Error during event disambiguation: {e}", exc_info=True)
            return None, 0.0, f"Error: {str(e)[:MAX_ERROR_MESSAGE_LENGTH]}"
    
    async def get_event_relationship(
        self,
        resource_url_hash: str,
        resource_title: str,
        resource_summary: str,
        datasource_id: str
    ) -> Optional[ResourceRelatesToEvent]:
        """
        Get an event relationship for a resource based on its title date.
        
        This method returns a relationship model that can be added to the
        models dict and flow through the normal pipeline (deduplication, insertion).
        
        Args:
            resource_url_hash: The url_hash of the resource node
            resource_title: The title of the resource (for date extraction)
            resource_summary: The summary of the resource (for disambiguation)
            datasource_id: The datasource_id to filter events by
            
        Returns:
            ResourceRelatesToEvent model if a match is found, None otherwise
        """
        # Step 1: Extract date from title
        extracted_date = extract_date_from_title(resource_title)
        
        if not extracted_date:
            logger.debug(f"No date found in title: '{resource_title}'")
            return None
        
        logger.info(f"Extracted date {extracted_date} from title: '{resource_title}'")
        
        # Step 2: Query for matching events
        events = self.graph_repository.get_events_by_datasource_and_date(
            datasource_id=datasource_id,
            target_date=extracted_date.isoformat()
        )
        
        if not events:
            logger.debug(f"No events found for datasource '{datasource_id}' on {extracted_date}")
            return None
        
        logger.info(f"Found {len(events)} event(s) for datasource '{datasource_id}' on {extracted_date}")
        
        # Step 3: Determine association
        selected_event = None
        confidence = 0.0
        evidence = ""
        
        if len(events) == 1:
            # Single event - auto-link
            selected_event = events[0]
            confidence = SINGLE_EVENT_CONFIDENCE
            evidence = f"Document date {extracted_date} matches single event"
            logger.info(f"Auto-linking to single event: {selected_event.get('name')}")
            
        else:
            # Multiple events - LLM disambiguation
            logger.info(f"Multiple events ({len(events)}) on {extracted_date} - using LLM disambiguation")
            selected_event, confidence, reasoning = await self._disambiguate_events(
                title=resource_title,
                summary=resource_summary,
                extracted_date=extracted_date,
                events=events
            )
            
            if selected_event and confidence >= settings.event_disambiguation_confidence_threshold:
                evidence = f"LLM matched (conf={confidence:.2f}): {reasoning}"
                logger.info(f"LLM selected event '{selected_event.get('name')}' with confidence {confidence:.2f}")
            elif selected_event:
                logger.info(f"LLM confidence {confidence:.2f} below threshold - skipping")
                return None
            else:
                logger.info(f"LLM could not determine matching event: {reasoning}")
                return None
        
        # Step 4: Build and return the relationship model
        if selected_event:
            event_url_hash = selected_event.get("url_hash")
            
            if not event_url_hash:
                logger.error(f"Event missing url_hash: {selected_event}")
                return None
            
            relationship = ResourceRelatesToEvent(
                source_id=resource_url_hash,
                target_id=event_url_hash,
                confidence=confidence,
                evidence=evidence[:MAX_EVIDENCE_LENGTH],
                context_type="material"
            )
            
            logger.info(f"Created event relationship: Resource -> Event '{selected_event.get('name')}'")
            return relationship
        
        return None
