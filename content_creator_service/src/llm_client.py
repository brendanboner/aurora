"""Thin wrapper around Azure OpenAI completions used by CreatorAgents."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from openai import AzureOpenAI

from .settings import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Simple Azure OpenAI helper that enforces deterministic outputs."""

    def __init__(self):
        settings = get_settings()
        if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
            raise RuntimeError("Azure OpenAI credentials are not configured")

        self._client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key,
        )
        self._deployment = settings.azure_openai_deployment
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Invoke the chat completion API and return the parsed JSON payload."""
        if not self._deployment:
            raise RuntimeError("Azure OpenAI deployment is not configured")

        logger.debug("Invoking LLM deployment %s", self._deployment)
        response = self._client.chat.completions.create(
            model=self._deployment,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned empty content")

        import json

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("LLM response failed JSON parsing: %s", content)
            raise RuntimeError("LLM returned invalid JSON") from exc


_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return a cached LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
