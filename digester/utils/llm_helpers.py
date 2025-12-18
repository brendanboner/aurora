"""
Shared LLM utility functions for Azure OpenAI calls.

This module provides common functionality for making Azure OpenAI API calls
with retry logic, rate limit handling, and response parsing.
"""

import re
import time
from typing import List, Dict, Optional

from openai import AzureOpenAI

from settings import settings
from utils.logger import setup_logger

try:
    from common.llm_instrumentation import create_llm_span_manually
except ImportError:
    # Fallback if common module unavailable
    from contextlib import contextmanager
    @contextmanager
    def create_llm_span_manually(*args, **kwargs):
        yield None


logger = setup_logger(__name__, settings.log_level)


# Singleton client instance
_llm_client: Optional[AzureOpenAI] = None


def get_llm_client() -> AzureOpenAI:
    """
    Get or create the Azure OpenAI client singleton.
    
    Returns:
        AzureOpenAI client instance
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint
        )
    return _llm_client


def parse_rate_limit_wait_time(error_message: str) -> float:
    """
    Extract wait time from rate limit error message.
    
    Args:
        error_message: The error message from Azure OpenAI
        
    Returns:
        Wait time in seconds, defaults to 5.0 if not parseable
    """
    # Look for patterns like "retry after 4815 milliseconds" or "retry after 5 seconds"
    ms_match = re.search(r'retry after (\d+)\s*milliseconds', error_message, re.IGNORECASE)
    if ms_match:
        return int(ms_match.group(1)) / 1000.0
    
    sec_match = re.search(r'retry after (\d+)\s*seconds', error_message, re.IGNORECASE)
    if sec_match:
        return float(sec_match.group(1))
    
    # Default wait time if we can't parse
    return 5.0


def call_llm_with_retry(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    max_retries: Optional[int] = None,
    check_truncation: bool = False
) -> str:
    """
    Call Azure OpenAI with retry logic for rate limits.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        deployment: Azure OpenAI deployment name (defaults to settings.azure_openai_deployment)
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
        max_retries: Max retry attempts for rate limits (defaults to settings.llm_rate_limit_retries)
        check_truncation: If True, raise ValueError when response is truncated due to token limit
        
    Returns:
        The LLM response content string
        
    Raises:
        ValueError: If check_truncation=True and response was truncated
        Exception: If rate limit retries are exhausted or other API errors
    """
    if max_retries is None:
        max_retries = settings.llm_rate_limit_retries
    
    if deployment is None:
        deployment = settings.azure_openai_deployment
    
    client = get_llm_client()
    last_exception: Optional[Exception] = None
    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            with create_llm_span_manually(
                prompt_type="extract",
                model_provider="azure_openai"
            ) as span:
                response = client.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                
                # Record token usage if span is available
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("llm.tokens.prompt", response.usage.prompt_tokens)
                    span.set_attribute("llm.tokens.completion", response.usage.completion_tokens)
                    span.set_attribute("llm.tokens.total", response.usage.total_tokens)
                    span.set_attribute("llm.model", deployment)
                
                # Check if response was truncated due to token limit
                if check_truncation:
                    finish_reason = response.choices[0].finish_reason
                    if finish_reason == "length":
                        error_msg = f"LLM response truncated due to max_tokens limit ({max_tokens}). Content too large for current token limit."
                        logger.error(error_msg)
                        raise ValueError(error_msg)
                
                return response.choices[0].message.content
        
        except ValueError:
            # Re-raise ValueError (token limit errors) - these won't be fixed by retrying
            raise
        except Exception as e:
            error_str = str(e)
            last_exception = e
            
            # Check for rate limit error (429)
            is_rate_limit = "429" in error_str or "RateLimitReached" in error_str
            
            if is_rate_limit and attempt < max_retries:
                wait_time = parse_rate_limit_wait_time(error_str) + 0.5
                logger.warning(
                    f"Rate limit hit (attempt {attempt + 1}/{max_retries + 1}). "
                    f"Waiting {wait_time:.1f}s before retry..."
                )
                time.sleep(wait_time)
                continue
            
            # Either not a rate limit error, or we've exhausted retries
            if is_rate_limit:
                logger.error(f"Rate limit retries exhausted ({max_retries} retries).")
            else:
                logger.error(f"Azure OpenAI call failed: {e}", exc_info=True)
            raise
    
    # Should not reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("LLM call failed with no exception captured")


def parse_json_from_llm_response(response: str) -> str:
    """
    Extract JSON from LLM response that may be wrapped in markdown code blocks.
    
    Args:
        response: Raw LLM response string
        
    Returns:
        Cleaned JSON string ready for parsing
    """
    if "```json" in response:
        return response.split("```json")[1].split("```")[0].strip()
    elif "```" in response:
        return response.split("```")[1].split("```")[0].strip()
    return response.strip()
