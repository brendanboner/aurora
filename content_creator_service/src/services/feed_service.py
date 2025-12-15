"""Feed ranking service."""
from __future__ import annotations

from datetime import datetime, timezone

from ..models.feed import FeedResponse
from ..models.post import FeedPost, FeedPostPublic
from ..models.preferences import UserPreferenceProfile
from .post_service import PostService
from .preference_service import PreferenceService


class FeedService:
    def __init__(self) -> None:
        self._post_service = PostService()
        self._preference_service = PreferenceService()

    def fetch_feed(
        self,
        user_id: str,  # Cognito UUID
        limit: int,
        offset: int = 0,
        *,
        sort: str = "relevance",
        query: str | None = None,
    ) -> FeedResponse:
        profile = self._preference_service.get_profile(user_id)
        posts = self._post_service.fetch_posts(user_id, limit, offset, query=query)
        # Always compute scores for display; order by requested sort
        scored_posts = [self._apply_score(post, profile) for post in posts]
        # Normalise to 0..1 where max theoretical score is 3.5
        max_score = 3.5
        for p in scored_posts:
            try:
                p.normalized_score = max(0.0, min(1.0, (p.score or 0.0) / max_score))
            except Exception:
                p.normalized_score = None
        if sort == "date":
            ordered = sorted(scored_posts, key=lambda p: p.created_at, reverse=True)
        else:
            ordered = sorted(scored_posts, key=lambda p: p.score, reverse=True)
        next_offset = offset + len(ordered) if len(ordered) == limit else None
        # Map to public model without raw score
        public_posts = [
            FeedPostPublic(
                id=p.id,
                agent_id=p.agent_id,
                agent_name=p.agent_name,
                title=p.title,
                body=p.body,
                summary=p.summary,
                tags=p.tags,
                visibility=p.visibility,
                importance=p.importance,
                content_length=p.content_length,
                created_at=p.created_at,
                sources=p.sources,
                is_following_agent=p.is_following_agent,
                user_reaction=p.user_reaction,
                normalized_score=p.normalized_score,
            )
            for p in ordered
        ]
        return FeedResponse(user_id=user_id, posts=public_posts, next_offset=next_offset)

    def _apply_score(self, post: FeedPost, profile: UserPreferenceProfile) -> FeedPost:
        topic_score = self._topic_score(post, profile)
        affinity_score = profile.agent_affinity.get(str(post.agent_id), 0.5)
        recency_score = self._recency_score(post)
        length_bonus = 0.2 if profile.preferred_length == post.content_length else 0
        follow_bonus = 0.3 if post.is_following_agent else 0
        post.score = topic_score + affinity_score + recency_score + length_bonus + follow_bonus
        return post

    def _topic_score(self, post: FeedPost, profile: UserPreferenceProfile) -> float:
        if not post.tags:
            return 0.3
        weights = profile.topic_weights
        total = 0.0
        for tag in post.tags:
            total += weights.get(tag, 0.5)
        return total / max(len(post.tags), 1)

    def _recency_score(self, post: FeedPost) -> float:
        now = datetime.now(timezone.utc)
        delta_hours = (now - post.created_at).total_seconds() / 3600
        if delta_hours <= 24:
            return 1.0
        if delta_hours <= 72:
            return 0.7
        if delta_hours <= 168:
            return 0.4
        return 0.2
