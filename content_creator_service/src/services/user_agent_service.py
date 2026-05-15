"""Service layer for managing personal user agents."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import db
from ..llm_client import get_llm_client
from ..models.user_agent import UserAgent, UserAgentCreate, UserAgentUpdate

logger = logging.getLogger(__name__)


class UserAgentService:
    """Service for CRUD operations and AI-powered agent creation."""
    
    def __init__(self):
        self.llm_client = get_llm_client()
    
    def _extract_agent_metadata_from_description(
        self, 
        project_description: str, 
        scope_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Use LLM to extract topics, organizations, persona, and tone from project description."""
        system_prompt = """You are an AI assistant that analyzes project descriptions and extracts structured metadata.

Given a project description and optional scope notes, extract:
1. expertise_topics: Array of relevant technical topics, technologies, or themes (5-15 items)
2. expertise_organisations: Array of organizations, companies, or vendors relevant to this project (0-10 items)
3. tone_style: The appropriate tone for content about this project (choose from: analytical, enthusiastic, critical, balanced, technical, executive)
4. persona: A 2-3 sentence description of the AI agent's role and perspective when monitoring this project

Return a JSON object with these exact keys: expertise_topics, expertise_organisations, tone_style, persona

Be specific and focused on what's actually mentioned or implied in the description."""

        user_prompt = f"""Project Description:
{project_description}

{f"Additional Scope Notes:\n{scope_notes}" if scope_notes else ""}

Extract the metadata as specified."""

        try:
            result = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature_override=0.3  # Lower temperature for more consistent extraction
            )
            
            # Validate required fields
            required_fields = ['expertise_topics', 'expertise_organisations', 'tone_style', 'persona']
            for field in required_fields:
                if field not in result:
                    logger.warning(f"LLM response missing field: {field}, setting default")
                    if field in ['expertise_topics', 'expertise_organisations']:
                        result[field] = []
                    elif field == 'tone_style':
                        result[field] = 'analytical'
                    else:
                        result[field] = ''
            
            logger.info(
                "Extracted metadata: %d topics, %d orgs, tone=%s",
                len(result.get('expertise_topics', [])),
                len(result.get('expertise_organisations', [])),
                result.get('tone_style')
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to extract metadata from description: {e}")
            # Return safe defaults
            return {
                'expertise_topics': [],
                'expertise_organisations': [],
                'tone_style': 'analytical',
                'persona': 'A focused AI agent monitoring relevant developments.'
            }
    
    def create_from_description(self, user_id: str, payload: UserAgentCreate) -> UserAgent:
        """Create a new user agent with AI-extracted metadata."""
        logger.info(f"Creating user agent '{payload.name}' for user {user_id}")
        
        # Extract AI metadata from description
        ai_metadata = self._extract_agent_metadata_from_description(
            payload.project_description,
            payload.scope_notes
        )
        
        row = db.fetch_one(
            """
            INSERT INTO user_agent (
                user_id, name, project_description, scope_notes, cadence,
                show_in_feed, enabled, expertise_topics, expertise_organisations,
                tone_style, persona, feedback_history
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                payload.name,
                payload.project_description,
                payload.scope_notes,
                payload.cadence,
                payload.show_in_feed,
                payload.enabled,
                ai_metadata.get('expertise_topics', []),
                ai_metadata.get('expertise_organisations', []),
                ai_metadata.get('tone_style', 'analytical'),
                ai_metadata.get('persona'),
                json.dumps([]),
            ),
        )
        if not row:
            raise RuntimeError("Failed to create user agent")
        return self._row_to_model(row)
    
    def get_user_agents(self, user_id: str) -> List[UserAgent]:
        """Get all agents for a specific user."""
        rows = db.fetch_all(
            """
            SELECT * FROM user_agent
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return [self._row_to_model(row) for row in rows]
    
    def get_user_agent(self, user_id: str, agent_id: int) -> Optional[UserAgent]:
        """Get a specific agent, verifying ownership."""
        row = db.fetch_one(
            """
            SELECT * FROM user_agent
            WHERE id = %s AND user_id = %s
            """,
            (agent_id, user_id),
        )
        return self._row_to_model(row) if row else None
    
    def update_user_agent(
        self, 
        user_id: str, 
        agent_id: int, 
        payload: UserAgentUpdate
    ) -> Optional[UserAgent]:
        """Update a user agent, re-running AI extraction if description changed."""
        # First verify ownership
        existing = self.get_user_agent(user_id, agent_id)
        if not existing:
            return None
        
        # If project_description or scope_notes changed, re-extract metadata
        reextract_metadata = (
            payload.project_description is not None or 
            payload.scope_notes is not None
        )
        
        ai_metadata = {}
        if reextract_metadata:
            new_description = payload.project_description or existing.project_description
            new_scope = payload.scope_notes if payload.scope_notes is not None else existing.scope_notes
            
            logger.info(f"Re-extracting metadata for agent {agent_id} due to description change")
            ai_metadata = self._extract_agent_metadata_from_description(
                new_description,
                new_scope
            )
        
        # Build update query dynamically
        updates = []
        params = []
        
        if payload.name is not None:
            updates.append("name = %s")
            params.append(payload.name)
        
        if payload.project_description is not None:
            updates.append("project_description = %s")
            params.append(payload.project_description)
        
        if payload.scope_notes is not None:
            updates.append("scope_notes = %s")
            params.append(payload.scope_notes)
        
        if payload.cadence is not None:
            updates.append("cadence = %s")
            params.append(payload.cadence)
        
        if payload.show_in_feed is not None:
            updates.append("show_in_feed = %s")
            params.append(payload.show_in_feed)
        
        if payload.enabled is not None:
            updates.append("enabled = %s")
            params.append(payload.enabled)
        
        # Add AI-extracted metadata if we re-extracted
        if ai_metadata:
            updates.append("expertise_topics = %s")
            params.append(ai_metadata.get('expertise_topics', []))
            
            updates.append("expertise_organisations = %s")
            params.append(ai_metadata.get('expertise_organisations', []))
            
            updates.append("tone_style = %s")
            params.append(ai_metadata.get('tone_style', 'analytical'))
            
            updates.append("persona = %s")
            params.append(ai_metadata.get('persona'))
        
        if not updates:
            return existing
        
        params.extend([agent_id, user_id])
        
        row = db.fetch_one(
            f"""
            UPDATE user_agent
            SET {", ".join(updates)}
            WHERE id = %s AND user_id = %s
            RETURNING *
            """,
            tuple(params),
        )
        return self._row_to_model(row) if row else None
    
    def delete_user_agent(self, user_id: str, agent_id: int) -> bool:
        """Delete a user agent (cascade deletes posts)."""
        deleted = db.execute(
            """
            DELETE FROM user_agent
            WHERE id = %s AND user_id = %s
            """,
            (agent_id, user_id),
        ) > 0

        if deleted:
            logger.info(f"Deleted user agent {agent_id} for user {user_id}")

        return deleted
    
    def process_feedback(
        self, 
        user_id: str, 
        agent_id: int, 
        feedback_text: str,
        post_id: Optional[int] = None
    ) -> Optional[UserAgent]:
        """Process user feedback and update agent using AI to infer improvements."""
        agent = self.get_user_agent(user_id, agent_id)
        if not agent:
            return None
        
        logger.info(f"Processing feedback for agent {agent_id}: {feedback_text[:100]}")
        
        # Use LLM to analyze feedback and suggest improvements
        system_prompt = """You are an AI assistant that helps improve content generation agents based on user feedback.

Given the current agent configuration and user feedback, determine what changes should be made to improve future content generation.

The agent can be adjusted by:
1. Updating scope_notes: Add constraints, exclusions, or preferences
2. Updating persona: Refine the agent's perspective or role
3. Updating tone_style: Change the tone if requested

Return a JSON object with:
- scope_notes_update: Additional text to append to scope_notes (or null if no change)
- persona_update: New persona text (or null if no change)
- tone_style_update: New tone style (or null if no change)
- summary: Brief explanation of what was changed

Be conservative - only suggest changes that are clearly indicated by the feedback."""

        user_prompt = f"""Current Agent Configuration:
Name: {agent.name}
Project: {agent.project_description}
Current Scope Notes: {agent.scope_notes or '(none)'}
Current Persona: {agent.persona or '(none)'}
Current Tone: {agent.tone_style}
Topics: {', '.join(agent.expertise_topics[:10])}
Organizations: {', '.join(agent.expertise_organisations[:5])}

User Feedback:
{feedback_text}

Determine what changes should be made to improve this agent."""

        try:
            result = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature_override=0.4
            )
            
            # Apply updates
            updates = []
            params = []
            
            if result.get('scope_notes_update'):
                new_scope = (agent.scope_notes or '') + '\n\n' + result['scope_notes_update']
                updates.append("scope_notes = %s")
                params.append(new_scope.strip())
            
            if result.get('persona_update'):
                updates.append("persona = %s")
                params.append(result['persona_update'])
            
            if result.get('tone_style_update'):
                updates.append("tone_style = %s")
                params.append(result['tone_style_update'])
            
            # Add feedback to history
            feedback_entry = {
                'timestamp': datetime.now().isoformat(),
                'feedback_text': feedback_text,
                'post_id': post_id,
                'applied_changes': result.get('summary', 'No changes applied')
            }
            
            # Append to feedback history (keep last 100 entries)
            current_history = agent.feedback_history or []
            current_history.append(feedback_entry)
            if len(current_history) > 100:
                current_history = current_history[-100:]
            
            updates.append("feedback_history = %s")
            params.append(json.dumps(current_history))
            
            if updates:
                params.extend([agent_id, user_id])
                
                row = db.fetch_one(
                    f"""
                    UPDATE user_agent
                    SET {", ".join(updates)}
                    WHERE id = %s AND user_id = %s
                    RETURNING *
                    """,
                    tuple(params),
                )

                logger.info(f"Applied feedback to agent {agent_id}: {result.get('summary')}")

                return self._row_to_model(row) if row else None
            
            return agent
            
        except Exception as e:
            logger.error(f"Failed to process feedback: {e}")
            # Still save feedback to history even if we couldn't process it
            feedback_entry = {
                'timestamp': datetime.now().isoformat(),
                'feedback_text': feedback_text,
                'post_id': post_id,
                'applied_changes': 'Failed to process automatically'
            }
            
            current_history = agent.feedback_history or []
            current_history.append(feedback_entry)
            if len(current_history) > 100:
                current_history = current_history[-100:]
            
            row = db.fetch_one(
                """
                UPDATE user_agent
                SET feedback_history = %s
                WHERE id = %s AND user_id = %s
                RETURNING *
                """,
                (json.dumps(current_history), agent_id, user_id),
            )
            return self._row_to_model(row) if row else None
    
    def get_all_enabled_agents(self) -> List[Dict[str, Any]]:
        """Get all enabled user agents for scheduler (across all users)."""
        rows = db.fetch_all(
            """
            SELECT * FROM user_agent
            WHERE enabled = TRUE
            ORDER BY user_id, id
            """
        )
        return [self._row_to_dict(row) for row in rows]

    def mark_run(self, agent_id: int) -> None:
        """Stamp last_run_at without touching last_generated_at (no content was produced)."""
        db.execute(
            "UPDATE user_agent SET last_run_at = NOW() WHERE id = %s",
            (agent_id,)
        )
    
    def _row_to_model(self, row) -> UserAgent:
        """Convert database row to UserAgent model."""
        row_dict = self._row_to_dict(row)
        return UserAgent(**row_dict)
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert database row to dictionary."""
        data = dict(row)
        
        # Parse JSONB feedback_history
        if 'feedback_history' in data and isinstance(data['feedback_history'], str):
            data['feedback_history'] = json.loads(data['feedback_history'])
        elif 'feedback_history' not in data:
            data['feedback_history'] = []
        
        return data
