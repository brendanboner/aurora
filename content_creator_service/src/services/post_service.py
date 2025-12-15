"""Post persistence helpers."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import HTTPException

from .. import db
from ..models.post import FeedPost, PostRecord, PostSource


class PostService:
    def create_post(
        self,
        *,
        agent_id: int,
        title: str,
        body: str,
        summary: str | None,
        tags: List[str],
        visibility: str,
        importance: str,
        content_length: str,
        sources: List[PostSource],
    ) -> int:
        row = db.fetch_one(
            """
            INSERT INTO post (
                agent_id, title, body, summary, tags, visibility, importance, content_length
            ) VALUES (
                %(agent_id)s, %(title)s, %(body)s, %(summary)s, %(tags)s, %(visibility)s, %(importance)s, %(content_length)s
            )
            RETURNING id
            """,
            {
                "agent_id": agent_id,
                "title": title,
                "body": body,
                "summary": summary,
                "tags": tags,
                "visibility": visibility,
                "importance": importance,
                "content_length": content_length,
            },
        )
        if not row:
            raise HTTPException(status_code=500, detail="Failed to insert post")
        post_row = dict(row)
        post_id = post_row["id"]
        self._store_sources(post_id, sources)
        return post_id

    def fetch_posts(self, user_id: str, limit: int, offset: int, *, query: str | None = None) -> List[FeedPost]:  # Cognito UUID
        where_clause = ""
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
        if query:
            where_clause = (
                "WHERE ("
                "p.title ILIKE %(like_q)s OR "
                "p.body ILIKE %(like_q)s OR "
                "EXISTS (SELECT 1 FROM unnest(p.tags) t WHERE t ILIKE %(like_q)s) OR "
                "REPLACE(LOWER(p.title), '-', '') LIKE REPLACE(LOWER(%(like_q)s), '-', '') OR "
                "REPLACE(LOWER(p.body), '-', '') LIKE REPLACE(LOWER(%(like_q)s), '-', '')"
                ")"
            )
            params["like_q"] = f"%{query}%"

        rows = db.fetch_all(
            f"""
            WITH follows AS (
                SELECT agent_id FROM user_agent_follow WHERE user_id = %(user_id)s
            ), reactions AS (
                SELECT post_id, reaction_type FROM user_post_reaction WHERE user_id = %(user_id)s
            )
            SELECT p.id,
                   p.agent_id,
                   ca.name AS agent_name,
                   p.title,
                   p.body,
                   p.summary,
                   p.tags,
                   p.visibility,
                   p.importance,
                   p.content_length,
                   p.created_at,
                   0.0 AS score,
                   (f.agent_id IS NOT NULL) AS is_following_agent,
                   r.reaction_type AS user_reaction
            FROM post p
            JOIN creator_agent ca ON ca.id = p.agent_id
            LEFT JOIN follows f ON f.agent_id = p.agent_id
            LEFT JOIN reactions r ON r.post_id = p.id
            {where_clause}
            ORDER BY p.created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        posts: List[FeedPost] = []
        for row in rows:
            data = dict(row)
            data["is_following_agent"] = bool(data.get("is_following_agent"))
            data["sources"] = self._load_sources(data["id"])
            posts.append(FeedPost(**data))
        return posts

    def _load_sources(self, post_id: int) -> List[PostSource]:
        rows = db.fetch_all(
            "SELECT source_kind, source_identifier, url, confidence FROM post_source WHERE post_id = %s",
            (post_id,),
        )
        return [PostSource(**dict(row)) for row in rows]

    def _store_sources(self, post_id: int, sources: List[PostSource]) -> None:
        if not sources:
            return
        for source in sources:
            payload = source.model_dump()
            db.execute(
                """
                INSERT INTO post_source (post_id, source_kind, source_identifier, url, confidence)
                VALUES (%(post_id)s, %(source_kind)s, %(source_identifier)s, %(url)s, %(confidence)s)
                """,
                {
                    "post_id": post_id,
                    **payload,
                },
            )

    def store_reaction(self, user_id: str, post_id: int, reaction: str) -> None:
        if reaction not in {"like", "dislike"}:
            raise HTTPException(status_code=400, detail="Invalid reaction")
        db.execute(
            """
            INSERT INTO user_post_reaction (user_id, post_id, reaction_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, post_id)
            DO UPDATE SET reaction_type = EXCLUDED.reaction_type, created_at = NOW()
            """,
            (user_id, post_id, reaction),
        )

    def remove_reaction(self, user_id: str, post_id: int) -> None:
        db.execute(
            "DELETE FROM user_post_reaction WHERE user_id = %s AND post_id = %s",
            (user_id, post_id),
        )

    def get_post(self, post_id: int) -> PostRecord:
        row = db.fetch_one(
            """
            SELECT p.id,
                   p.agent_id,
                   ca.name AS agent_name,
                   p.title,
                   p.body,
                   p.summary,
                   p.tags,
                   p.visibility,
                   p.importance,
                     p.content_length,
                   p.created_at,
                   0.0 AS score
            FROM post p
            JOIN creator_agent ca ON ca.id = p.agent_id
            WHERE p.id = %s
            """,
            (post_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        data = dict(row)
        data["sources"] = self._load_sources(post_id)
        return PostRecord(**data)
