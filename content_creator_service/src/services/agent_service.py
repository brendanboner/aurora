"""Agent persistence helpers."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .. import db
from ..models.agent import CreatorAgent, CreatorAgentCreate, CreatorAgentUpdate
from ..llm_client import get_llm_client
from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class AgentService:
    """CRUD helpers for CreatorAgents."""

    def list_agents(self, include_disabled: bool = True) -> List[CreatorAgent]:
        where_clause = "" if include_disabled else "WHERE enabled = TRUE"
        rows = db.fetch_all(
            f"SELECT * FROM creator_agent {{where}} ORDER BY name".replace("{where}", where_clause)
        )
        return [CreatorAgent(**dict(row)) for row in rows]

    def list_enabled_agents(self) -> List[CreatorAgent]:
        return self.list_agents(include_disabled=False)

    def get_agent(self, agent_id: int) -> CreatorAgent:
        row = db.fetch_one("SELECT * FROM creator_agent WHERE id = %s", (agent_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        return CreatorAgent(**dict(row))

    def get_agent_by_name(self, name: str) -> CreatorAgent:
        row = db.fetch_one(
            "SELECT * FROM creator_agent WHERE LOWER(name) = LOWER(%s)",
            (name,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        return CreatorAgent(**dict(row))

    def create_agent(self, payload: CreatorAgentCreate) -> CreatorAgent:
        row = db.fetch_one(
            """
            INSERT INTO creator_agent (
                name, description, persona, expertise_topics, expertise_organisations,
                expertise_standards, tone_style, posting_cadence, content_length_preference,
                importance_threshold, discovery_tolerance, cadence_window_days, enabled
            ) VALUES (
                %(name)s, %(description)s, %(persona)s, %(expertise_topics)s, %(expertise_organisations)s,
                %(expertise_standards)s, %(tone_style)s, %(posting_cadence)s, %(content_length_preference)s,
                %(importance_threshold)s, %(discovery_tolerance)s, %(cadence_window_days)s, %(enabled)s
            ) RETURNING *
            """,
            payload.model_dump(),
        )
        return CreatorAgent(**dict(row))

    def update_agent(self, agent_id: int, payload: CreatorAgentUpdate) -> CreatorAgent:
        data = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
        if not data:
            return self.get_agent(agent_id)

        assignments = ", ".join(f"{key} = %({key})s" for key in data.keys())
        data["id"] = agent_id
        row = db.fetch_one(
            f"""
            UPDATE creator_agent
            SET {assignments}
            WHERE id = %(id)s
            RETURNING *
            """,
            data,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        return CreatorAgent(**dict(row))

    def delete_agent(self, agent_id: int) -> None:
        deleted = db.execute("DELETE FROM creator_agent WHERE id = %s", (agent_id,))
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Agent not found")

    def follow_agent(self, user_id: str, agent_id: int) -> None:
        try:
            db.execute(
                """
                INSERT INTO user_agent_follow (user_id, agent_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, agent_id) DO UPDATE SET followed_at = NOW()
                """,
                (user_id, agent_id),
            )
        except Exception as exc:  # pragma: no cover - surfacing constraint errors
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def unfollow_agent(self, user_id: str, agent_id: int) -> None:
        db.execute(
            "DELETE FROM user_agent_follow WHERE user_id = %s AND agent_id = %s",
            (user_id, agent_id),
        )
    
    def get_followed_agents(self, user_id: str) -> List[dict]:
        """Get all agents followed by a user with their basic info."""
        rows = db.fetch_all(
            """
            SELECT ca.id, ca.name, ca.description, ca.persona, 
                   ca.posting_cadence, ca.content_length_preference,
                   ca.enabled, uaf.followed_at
            FROM creator_agent ca
            INNER JOIN user_agent_follow uaf ON ca.id = uaf.agent_id
            WHERE uaf.user_id = %s
            ORDER BY ca.name
            """,
            (user_id,),
        )
        return [dict(row) for row in rows]
    
    def mark_agent_run(self, agent_id: int, *, event_cursor: Optional[str], generated: bool) -> None:
        db.execute(
            """
            UPDATE creator_agent
            SET last_run_at = NOW(),
                last_event_cursor = CASE
                    WHEN %(cursor)s IS NULL THEN last_event_cursor
                    ELSE %(cursor)s
                END,
                last_generated_at = CASE
                    WHEN %(generated)s THEN NOW()
                    ELSE last_generated_at
                END
            WHERE id = %(agent_id)s
            """,
            {
                "cursor": event_cursor,
                "generated": generated,
                "agent_id": agent_id,
            },
        )

    def parse_linkedin_profile(self, linkedin_text: str) -> Dict[str, Any]:
        """
        Parse LinkedIn profile paste using LLM to extract agent configuration.
        
        Args:
            linkedin_text: Raw paste of LinkedIn profile page
            
        Returns:
            Dict with CreatorAgentBase fields ready for form population
            
        Raises:
            HTTPException: If LLM fails or returns invalid JSON
        """
        # Basic text cleanup - remove excessive whitespace
        cleaned_text = re.sub(r'\n{3,}', '\n\n', linkedin_text)
        cleaned_text = re.sub(r' {2,}', ' ', cleaned_text)
        cleaned_text = cleaned_text.strip()
        
        # Build prompts
        prompt_builder = PromptBuilder()
        system_prompt, user_prompt = prompt_builder.build_linkedin_parsing_prompt(cleaned_text)
        
        # Call LLM
        try:
            llm_client = get_llm_client()
            result = llm_client.generate(system_prompt, user_prompt)
            
            # Validate required fields are present
            required_fields = {'name', 'enabled'}
            missing = required_fields - set(result.keys())
            if missing:
                logger.error(f"LLM response missing required fields: {missing}")
                raise ValueError(f"Missing required fields: {missing}")
            
            # Ensure lists for array fields
            for field in ['expertise_topics', 'expertise_organisations', 'expertise_standards']:
                if field not in result:
                    result[field] = []
                elif not isinstance(result[field], list):
                    result[field] = []
            
            # Ensure numeric types
            if 'discovery_tolerance' in result:
                try:
                    result['discovery_tolerance'] = float(result['discovery_tolerance'])
                except (ValueError, TypeError):
                    result['discovery_tolerance'] = 0.5
            else:
                result['discovery_tolerance'] = 0.5
                
            if 'cadence_window_days' in result:
                try:
                    result['cadence_window_days'] = int(result['cadence_window_days'])
                except (ValueError, TypeError):
                    result['cadence_window_days'] = 7
            else:
                result['cadence_window_days'] = 7
            
            logger.info(f"Successfully parsed LinkedIn profile, generated agent: {result.get('name')}")
            return result
            
        except json.JSONDecodeError as exc:
            logger.error(f"LLM returned invalid JSON: {exc}")
            raise HTTPException(
                status_code=500,
                detail="Failed to parse LLM response. Please try again."
            ) from exc
        except Exception as exc:
            logger.error(f"LinkedIn profile parsing failed: {exc}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse LinkedIn profile: {str(exc)}"
            ) from exc
