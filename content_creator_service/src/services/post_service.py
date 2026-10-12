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
        user_id: str | None = None,
        agent_type: str = "shared",
    ) -> int:
        row = db.fetch_one(
            """
            INSERT INTO post (
                agent_id, user_id, agent_type, title, body, summary, tags, visibility, importance, content_length
            ) VALUES (
                %(agent_id)s, %(user_id)s, %(agent_type)s, %(title)s, %(body)s, %(summary)s, %(tags)s, %(visibility)s, %(importance)s, %(content_length)s
            )
            RETURNING id
            """,
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "agent_type": agent_type,
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

    def fetch_posts(
        self,
        user_id: str,
        limit: int,
        offset: int,
        *,
        query: str | None = None,
        personal_agent_id: int | None = None,
    ) -> List[FeedPost]:  # Cognito UUID
        where_clause_and = ""
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}
        if query:
            where_clause_and = (
                "AND ("
                "p.title ILIKE %(like_q)s OR "
                "p.body ILIKE %(like_q)s OR "
                "EXISTS (SELECT 1 FROM unnest(p.tags) t WHERE t ILIKE %(like_q)s) OR "
                "REPLACE(LOWER(p.title), '-', '') LIKE REPLACE(LOWER(%(like_q)s), '-', '') OR "
                "REPLACE(LOWER(p.body), '-', '') LIKE REPLACE(LOWER(%(like_q)s), '-', '')"
                ")"
            )
            params["like_q"] = f"%{query}%"
        if personal_agent_id is not None:
            where_clause_and += " AND p.agent_type = 'personal' AND p.agent_id = %(personal_agent_id)s"
            params["personal_agent_id"] = personal_agent_id

        rows = db.fetch_all(
            f"""
            WITH follows AS (
                SELECT agent_id FROM user_agent_follow WHERE user_id = %(user_id)s
            ), reactions AS (
                SELECT post_id, reaction_type FROM user_post_reaction WHERE user_id = %(user_id)s
            )
            SELECT p.id,
                   p.agent_id,
                   COALESCE(ca.name, ua.name, 'Unknown') AS agent_name,
                   p.title,
                   p.body,
                   p.summary,
                   p.tags,
                   p.visibility,
                   p.importance,
                   p.content_length,
                   p.created_at,
                   0.0 AS score,
                   CASE
                       WHEN p.agent_type = 'personal' THEN COALESCE(ua.show_in_feed, FALSE)
                       ELSE COALESCE(f.agent_id IS NOT NULL, FALSE)
                   END AS is_following_agent,
                   r.reaction_type AS user_reaction,
                   p.agent_type,
                   p.user_id AS post_user_id
            FROM post p
            LEFT JOIN creator_agent ca ON ca.id = p.agent_id AND p.agent_type = 'shared'
            LEFT JOIN user_agent ua ON ua.id = p.agent_id AND p.agent_type = 'personal'
            LEFT JOIN follows f ON f.agent_id = p.agent_id AND p.agent_type = 'shared'
            LEFT JOIN reactions r ON r.post_id = p.id
            WHERE (
                -- Show shared/public posts
                (p.agent_type = 'shared' AND p.visibility = 'public')
                OR
                -- Show user's own personal agent posts (if enabled)
                (p.agent_type = 'personal' AND p.user_id = %(user_id)s AND ua.enabled = TRUE AND ua.show_in_feed = TRUE)
            )
            {where_clause_and}
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
            "SELECT source_kind, source_identifier, url, confidence, title FROM post_source WHERE post_id = %s",
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
                INSERT INTO post_source (post_id, source_kind, source_identifier, url, confidence, title)
                VALUES (%(post_id)s, %(source_kind)s, %(source_identifier)s, %(url)s, %(confidence)s, %(title)s)
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

    def add_comment(self, post_id: int, user_id: str, body: str, user_display_name: str | None = None) -> dict:
        """Add a comment to a post. Returns the created comment row."""
        # Verify post exists
        self.get_post(post_id)
        row = db.fetch_one(
            """
            INSERT INTO post_comment (post_id, user_id, user_display_name, body)
            VALUES (%s, %s, %s, %s)
            RETURNING id, post_id, user_id, user_display_name, body, created_at
            """,
            (post_id, user_id, user_display_name, body),
        )
        if not row:
            raise HTTPException(status_code=500, detail="Failed to create comment")
        return dict(row)

    def get_comments(self, post_id: int, limit: int = 50) -> list[dict]:
        """Return comments for a post, oldest first."""
        rows = db.fetch_all(
            """
            SELECT id, post_id, user_id, user_display_name, body, created_at
            FROM post_comment
            WHERE post_id = %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (post_id, limit),
        )
        return [dict(r) for r in (rows or [])]

    def purge_agent_posts(self, agent_id: int) -> int:
        row = db.fetch_one("SELECT COUNT(*) AS cnt FROM post WHERE agent_id = %s", (agent_id,))
        db.execute("DELETE FROM post WHERE agent_id = %s", (agent_id,))
        return int(row["cnt"]) if row else 0

    def purge_all_posts(self) -> int:
        """Delete all posts in the system. Returns count deleted."""
        row = db.fetch_one("SELECT COUNT(*) AS cnt FROM post", ())
        db.execute("DELETE FROM post", ())
        return int(row["cnt"]) if row else 0

    def get_post(self, post_id: int) -> PostRecord:
        row = db.fetch_one(
            """
            SELECT p.id,
                   p.agent_id,
                   COALESCE(ca.name, ua.name, 'Unknown') AS agent_name,
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
            LEFT JOIN creator_agent ca ON ca.id = p.agent_id AND p.agent_type = 'shared'
            LEFT JOIN user_agent ua ON ua.id = p.agent_id AND p.agent_type = 'personal'
            WHERE p.id = %s
            """,
            (post_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        data = dict(row)
        data["sources"] = self._load_sources(post_id)
        return PostRecord(**data)
