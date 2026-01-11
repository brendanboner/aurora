"""LLM Client - Azure OpenAI integration for Oracle Service."""

from dataclasses import dataclass
from typing import Optional
import logging
import os

try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None  # type: ignore

from src.settings import settings

logger = logging.getLogger(__name__)

# Embedding configuration
EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small dimensions

# Global client cache
_client: Optional[AzureOpenAI] = None


@dataclass
class LLMResponse:
    """Response from LLM call."""
    content: str
    tokens_used: int
    finish_reason: str


def get_llm_client() -> Optional[AzureOpenAI]:
    """
    Get a cached Azure OpenAI client.
    
    Returns None if:
    - The openai library is not installed
    - Required environment variables are missing
    - Client initialization fails
    """
    global _client
    
    if _client is not None:
        return _client
    
    if AzureOpenAI is None:
        logger.warning("AzureOpenAI library not available")
        return None
    
    # Check required configuration
    if not settings.azure_openai_api_key:
        logger.warning("AZURE_OPENAI_API_KEY not configured")
        return None
    
    if not settings.azure_openai_endpoint:
        logger.warning("AZURE_OPENAI_ENDPOINT not configured")
        return None
    
    if not settings.azure_openai_deployment:
        logger.warning("AZURE_OPENAI_DEPLOYMENT not configured")
        return None
    
    try:
        client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        # Store deployment name for later use
        client._deployment_name = settings.azure_openai_deployment  # type: ignore
        _client = client
        logger.info("Azure OpenAI client initialized successfully")
        return client
        
    except Exception as e:
        logger.error(f"Failed to initialize Azure OpenAI client: {e}")
        return None


async def call_llm(
    client: AzureOpenAI,
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.1,
    timeout: Optional[float] = None
) -> LLMResponse:
    """
    Make a call to the Azure OpenAI API.
    
    Args:
        client: Azure OpenAI client
        messages: List of message dicts with 'role' and 'content'
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature (0-1)
        timeout: Request timeout in seconds
        
    Returns:
        LLMResponse with content and token usage
    """
    deployment = getattr(client, '_deployment_name', settings.azure_openai_deployment)
    timeout = timeout or settings.llm_timeout
    
    try:
        # Note: Using synchronous call wrapped in async for simplicity
        # In production, consider using httpx async client directly
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        
        content = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0
        finish_reason = response.choices[0].finish_reason or "unknown"
        
        return LLMResponse(
            content=content,
            tokens_used=tokens_used,
            finish_reason=finish_reason
        )
        
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise


def reset_client():
    """Reset the cached client (useful for testing)."""
    global _client
    _client = None


async def generate_embedding(
    text: str,
    client: Optional[AzureOpenAI] = None,
) -> list[float]:
    """
    Generate an embedding vector for the given text using Azure OpenAI.
    
    Args:
        text: Text to embed
        client: Optional Azure OpenAI client (uses default if not provided)
        
    Returns:
        List of floats representing the embedding vector (1536 dimensions)
        
    Raises:
        ValueError: If client is not available or text is empty
        Exception: If embedding generation fails
    """
    if not text or not text.strip():
        raise ValueError("Cannot generate embedding for empty text")
    
    if client is None:
        client = get_llm_client()
    
    if client is None:
        raise ValueError("Azure OpenAI client not available for embedding generation")
    
    try:
        # Use the embedding deployment from settings
        deployment = settings.azure_openai_embedding_deployment
        
        response = client.embeddings.create(
            input=text,
            model=deployment,
        )
        
        embedding = response.data[0].embedding
        logger.debug(f"Generated embedding with {len(embedding)} dimensions for text: {text[:50]}...")
        
        return embedding
        
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        raise


async def generate_embeddings_batch(
    texts: list[str],
    client: Optional[AzureOpenAI] = None,
    batch_size: int = 100,
) -> list[list[float]]:
    """
    Generate embedding vectors for multiple texts using Azure OpenAI.
    
    Processes texts in batches to respect API limits.
    
    Args:
        texts: List of texts to embed
        client: Optional Azure OpenAI client (uses default if not provided)
        batch_size: Maximum texts per API call (default: 100)
        
    Returns:
        List of embedding vectors (one per input text)
        
    Raises:
        ValueError: If client is not available or texts is empty
        Exception: If embedding generation fails
    """
    if not texts:
        return []
    
    if client is None:
        client = get_llm_client()
    
    if client is None:
        raise ValueError("Azure OpenAI client not available for embedding generation")
    
    deployment = settings.azure_openai_embedding_deployment
    all_embeddings = []
    
    try:
        # Process in batches
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            # Filter out empty texts
            valid_texts = [t for t in batch if t and t.strip()]
            if not valid_texts:
                # Return zero vectors for empty texts
                all_embeddings.extend([[0.0] * EMBEDDING_DIMENSIONS for _ in batch])
                continue
            
            response = client.embeddings.create(
                input=valid_texts,
                model=deployment,
            )
            
            # Map embeddings back to original positions
            valid_idx = 0
            for text in batch:
                if text and text.strip():
                    all_embeddings.append(response.data[valid_idx].embedding)
                    valid_idx += 1
                else:
                    # Zero vector for empty text
                    all_embeddings.append([0.0] * EMBEDDING_DIMENSIONS)
            
        logger.debug(f"Generated embeddings for batch {i // batch_size + 1}, {len(valid_texts)} texts")
        
        return all_embeddings
        
    except Exception as e:
        logger.error(f"Batch embedding generation failed: {e}")
        raise


async def batch_generate_embeddings(
    texts: list[str],
    batch_size: int = 100,
) -> list[Optional[list[float]]]:
    """
    Generate embedding vectors for multiple texts.
    
    A convenience wrapper around generate_embeddings_batch that handles
    errors more gracefully for individual texts.
    
    Args:
        texts: List of texts to embed
        batch_size: Maximum texts per API call
        
    Returns:
        List of embedding vectors (None for failed texts)
    """
    try:
        return await generate_embeddings_batch(texts, batch_size=batch_size)
    except Exception as e:
        logger.error(f"Batch embedding generation failed: {e}")
        # Return None for all texts on failure
        return [None] * len(texts)
