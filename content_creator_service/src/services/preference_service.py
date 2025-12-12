"""Deterministic preference learning and persistence."""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from psycopg2.extras import Json

from .. import db
from ..models.preferences import UserPreferenceProfile

_DEFAULT_TOPIC_WEIGHT = 0.5


class PreferenceService:
    def get_profile(self, user_id: int) -> UserPreferenceProfile:
        row = db.fetch_one(
            "SELECT * FROM user_preference_profile WHERE user_id = %s",
            (user_id,),
        )
        if not row:
            self._create_default_profile(user_id)
            row = db.fetch_one(
                "SELECT * FROM user_preference_profile WHERE user_id = %s",
                (user_id,),
            )
        return UserPreferenceProfile(**row)

    def _create_default_profile(self, user_id: int) -> None:
        db.execute(
            """
            INSERT INTO user_preference_profile (user_id, topic_weights, agent_affinity)
            VALUES (%s, '{}'::jsonb, '{}'::jsonb)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )

    def apply_topic_feedback(self, user_id: int, topics: Iterable[str], delta: float) -> UserPreferenceProfile:
        profile = self.get_profile(user_id)
        weights = dict(profile.topic_weights)
        for topic in topics:
            if not topic:
                continue
            weights[topic] = max(0.0, min(1.0, weights.get(topic, _DEFAULT_TOPIC_WEIGHT) + delta))
        db.execute(
            """
            UPDATE user_preference_profile
            SET topic_weights = %s::jsonb, updated_at = NOW()
            WHERE user_id = %s
            """,
            (Json(weights), user_id),
        )
        profile.topic_weights = weights
        return profile

    def adjust_agent_affinity(self, user_id: int, agent_id: int, delta: float) -> UserPreferenceProfile:
        profile = self.get_profile(user_id)
        affinity = {k: float(v) for k, v in profile.agent_affinity.items()}
        key = str(agent_id)
        affinity[key] = max(0.0, min(1.0, affinity.get(key, _DEFAULT_TOPIC_WEIGHT) + delta))
        db.execute(
            """
            UPDATE user_preference_profile
            SET agent_affinity = %s::jsonb, updated_at = NOW()
            WHERE user_id = %s
            """,
            (Json(affinity), user_id),
        )
        profile.agent_affinity = affinity
        return profile

    def update_length_preference(self, user_id: int, length: str) -> None:
        db.execute(
            """
            UPDATE user_preference_profile
            SET preferred_length = %s, updated_at = NOW()
            WHERE user_id = %s
            """,
            (length, user_id),
        )

    def update_profile(
        self,
        user_id: int,
        *,
        preferred_length: Optional[str] = None,
        preferred_cadence: Optional[str] = None,
        topic_weights: Optional[Dict[str, float]] = None,
        agent_affinity: Optional[Dict[str, float]] = None,
    ) -> UserPreferenceProfile:
        updates = []
        params: Dict[str, object] = {"user_id": user_id}
        if preferred_length:
            updates.append("preferred_length = %(preferred_length)s")
            params["preferred_length"] = preferred_length
        if preferred_cadence:
            updates.append("preferred_cadence = %(preferred_cadence)s")
            params["preferred_cadence"] = preferred_cadence
        if topic_weights is not None:
            updates.append("topic_weights = %(topic_weights)s::jsonb")
            params["topic_weights"] = Json(topic_weights)
        if agent_affinity is not None:
            updates.append("agent_affinity = %(agent_affinity)s::jsonb")
            params["agent_affinity"] = Json(agent_affinity)

        if updates:
            updates.append("updated_at = NOW()")
            set_clause = ", ".join(updates)
            db.execute(
                f"""
                UPDATE user_preference_profile
                SET {set_clause}
                WHERE user_id = %(user_id)s
                """,
                params,
            )
        return self.get_profile(user_id)
