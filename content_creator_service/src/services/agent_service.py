"""Agent persistence helpers."""
from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException

from .. import db
from ..models.agent import CreatorAgent, CreatorAgentCreate, CreatorAgentUpdate


class AgentService:
    """CRUD helpers for CreatorAgents."""

    def list_agents(self, include_disabled: bool = True) -> List[CreatorAgent]:
        where_clause = "" if include_disabled else "WHERE enabled = TRUE"
        rows = db.fetch_all(
            f"SELECT * FROM creator_agent {{where}} ORDER BY name".replace("{where}", where_clause)
        )
        return [CreatorAgent(**row) for row in rows]

    def list_enabled_agents(self) -> List[CreatorAgent]:
        return self.list_agents(include_disabled=False)

    def get_agent(self, agent_id: int) -> CreatorAgent:
        row = db.fetch_one("SELECT * FROM creator_agent WHERE id = %s", (agent_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Agent not found")
        return CreatorAgent(**row)

    def create_agent(self, payload: CreatorAgentCreate) -> CreatorAgent:
        row = db.fetch_one(
            """
            INSERT INTO creator_agent (
                name, description, persona, expertise_topics, expertise_organisations,
                expertise_standards, tone_style, posting_cadence, content_length_preference,
                importance_threshold, enabled
            ) VALUES (
                %(name)s, %(description)s, %(persona)s, %(expertise_topics)s, %(expertise_organisations)s,
                %(expertise_standards)s, %(tone_style)s, %(posting_cadence)s, %(content_length_preference)s,
                %(importance_threshold)s, %(enabled)s
            ) RETURNING *
            """,
            payload.model_dump(),
        )
        return CreatorAgent(**row)

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
        return CreatorAgent(**row)

    def delete_agent(self, agent_id: int) -> None:
        deleted = db.execute("DELETE FROM creator_agent WHERE id = %s", (agent_id,))
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Agent not found")

    def follow_agent(self, user_id: int, agent_id: int) -> None:
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

    def unfollow_agent(self, user_id: int, agent_id: int) -> None:
        db.execute(
            "DELETE FROM user_agent_follow WHERE user_id = %s AND agent_id = %s",
            (user_id, agent_id),
        )
    
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
