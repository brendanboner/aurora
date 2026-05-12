"""Redis-backed conversational context store.

Stores the last N query/answer turns per user session so the LLM can answer
follow-up questions without the user repeating context.

Keys:  conv:{user_id}   → JSON list of {role, content} pairs (oldest first)
TTL:   2 hours (reset on every write)
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Max turns stored per user (each turn = 1 user message + 1 assistant message = 2 items)
MAX_TURNS = 5
TTL_SECONDS = 7200  # 2 hours


class ConversationStore:
    """Lightweight Redis wrapper for per-user conversation history."""

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self.enabled = redis_client is not None

    @staticmethod
    def _key(user_id: str) -> str:
        return f"conv:{user_id}"

    async def get_context(self, user_id: Optional[str], max_turns: int = 2) -> list[dict]:
        """Return the last max_turns turns as a list of {role, content} dicts.

        Returns an empty list when the store is disabled or nothing is cached.
        max_turns is the number of *conversation turns* (each = user + assistant pair),
        so the returned list has up to max_turns * 2 items.
        """
        if not self.enabled or not user_id:
            return []
        try:
            raw = await self._redis.get(self._key(user_id))
            if not raw:
                return []
            history: list[dict] = json.loads(raw)
            # Each turn is a user+assistant pair; slice to last max_turns pairs
            keep = max_turns * 2
            return history[-keep:] if len(history) > keep else history
        except Exception as exc:
            logger.debug(f"ConversationStore.get_context failed for {user_id}: {exc}")
            return []

    async def append_turn(
        self,
        user_id: Optional[str],
        question: str,
        answer: str,
    ) -> None:
        """Append a user/assistant turn and persist, trimming to MAX_TURNS."""
        if not self.enabled or not user_id:
            return
        try:
            raw = await self._redis.get(self._key(user_id))
            history: list[dict] = json.loads(raw) if raw else []

            history.append({"role": "user", "content": question})
            # Store a condensed version of the answer — strip markdown citations
            # so the context is cleaner (the full citations are in the documents layer)
            compact = _condense_answer(answer)
            history.append({"role": "assistant", "content": compact})

            # Trim to MAX_TURNS conversation pairs
            max_items = MAX_TURNS * 2
            if len(history) > max_items:
                history = history[-max_items:]

            await self._redis.setex(
                self._key(user_id), TTL_SECONDS, json.dumps(history)
            )
        except Exception as exc:
            logger.debug(f"ConversationStore.append_turn failed for {user_id}: {exc}")

    async def clear(self, user_id: Optional[str]) -> None:
        """Erase conversation history for a user (e.g. on explicit clear)."""
        if not self.enabled or not user_id:
            return
        try:
            await self._redis.delete(self._key(user_id))
        except Exception as exc:
            logger.debug(f"ConversationStore.clear failed for {user_id}: {exc}")


def _condense_answer(answer: str, max_chars: int = 600) -> str:
    """Trim an answer to a compact form suitable for conversation context.

    Strips citation markers like [1], [2] since the prior answer's document
    list is not available in the new query context.
    """
    import re
    text = re.sub(r'\[\d+\]', '', answer)  # remove citation markers
    text = re.sub(r'\s{2,}', ' ', text).strip()
    if len(text) > max_chars:
        # Truncate at last sentence boundary within max_chars
        cut = text[:max_chars]
        last_period = cut.rfind('.')
        if last_period > max_chars // 2:
            cut = cut[:last_period + 1]
        return cut + '…'
    return text
