"""Extract metadata from document content using Azure OpenAI (ASYNC VERSION)."""

import json
import hashlib
import asyncio
from typing import Dict, Any, List
from settings import settings
from utils.logger import setup_logger
from utils.llm_helpers import call_llm_with_retry, parse_json_from_llm_response
from utils.prompts import METADATA_EXTRACTION_PROMPT, METADATA_MERGE_PROMPT
from utils.validator import validate_metadata

logger = setup_logger(__name__, settings.log_level)


class MetadataExtractor:
    """Extract metadata from document content using Azure OpenAI (ASYNC VERSION)."""
    
    def __init__(self):
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature
        self.max_chunk_size = settings.max_chunk_size
        self.chunk_overlap = settings.chunk_overlap
        
        logger.info(f"Initialized MetadataExtractor (async) with Azure OpenAI deployment: {settings.azure_openai_deployment}")
    
    def chunk_content(self, content: str) -> List[str]:
        """
        Split content into overlapping chunks, respecting sentence and paragraph boundaries.
        
        This prevents splitting mid-sentence which can break context for the LLM.
        Falls back to character-based splitting if no suitable boundaries are found.
        """
        if len(content) <= self.max_chunk_size:
            return [content]
        
        chunks = []
        start = 0
        
        while start < len(content):
            end = min(start + self.max_chunk_size, len(content))
            
            # If this is the last chunk, take everything
            if end >= len(content):
                chunks.append(content[start:])
                break
            
            # Try to find a good breaking point near the target end position
            # Priority: paragraph > sentence > word boundary > character split
            chunk_end = end
            
            # Look for paragraph break (double newline) in the last 20% of chunk
            search_start = end - int(self.max_chunk_size * 0.2)
            paragraph_break = content.rfind('\n\n', search_start, end)
            if paragraph_break > search_start:
                chunk_end = paragraph_break + 2  # Include the paragraph break
            else:
                # Look for sentence ending in the last 20% of chunk
                for punct in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
                    sentence_end = content.rfind(punct, search_start, end)
                    if sentence_end > search_start:
                        chunk_end = sentence_end + len(punct)
                        break
                else:
                    # Look for word boundary (space) in the last 10% of chunk
                    search_start = end - int(self.max_chunk_size * 0.1)
                    word_boundary = content.rfind(' ', search_start, end)
                    if word_boundary > search_start:
                        chunk_end = word_boundary + 1
                    # Otherwise use character split (chunk_end already = end)
            
            chunks.append(content[start:chunk_end])
            start = chunk_end - self.chunk_overlap
        
        logger.info(f"Split content into {len(chunks)} chunks with smart boundaries")
        return chunks
    
    async def call_llm(self, prompt: str, system_message: str = "You are a metadata extraction expert. Always respond with valid JSON.") -> str:
        """
        Call Azure OpenAI with the given prompt (ASYNC VERSION).
        
        Implements retry logic for rate limit (429) errors, waiting the 
        suggested time before retrying.
        
        Args:
            prompt: The prompt to send to the LLM
            system_message: The system message for the LLM
            
        Returns:
            The LLM response content
            
        Raises:
            ValueError: If response is truncated due to token limits
            Exception: If rate limit retries are exhausted or other API errors
        """
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ]
        return await call_llm_with_retry(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_retries=settings.llm_rate_limit_retries,
            check_truncation=True
        )
    
    async def extract_from_chunk(self, resource_data: Dict[str, Any], content_chunk: str) -> Dict[str, Any]:
        """Extract metadata from a single content chunk (ASYNC VERSION)."""
        prompt = METADATA_EXTRACTION_PROMPT.format(
            title=resource_data.get("title", "Unknown"),
            url=resource_data.get("url", ""),
            category=resource_data.get("category", ""),
            publish_date=resource_data.get("publish_date", ""),
            content=content_chunk,
            max_tokens=self.max_tokens
        )
        
        response = await self.call_llm(prompt)
        
        # Parse JSON response
        try:
            json_str = parse_json_from_llm_response(response)
            metadata = json.loads(json_str)
            return metadata
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}", exc_info=True)
            logger.error(f"Response was: {response}")
            
            # Check if this might be due to truncation (unclosed JSON)
            if response and not response.rstrip().endswith('}'):
                error_msg = f"LLM response appears truncated (does not end with closing brace). Likely hit token limit."
                logger.error(error_msg)
                raise ValueError(error_msg) from e
            
            raise
    
    async def merge_metadata(self, title: str, chunks_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge metadata from multiple chunks (ASYNC VERSION)."""
        if len(chunks_metadata) == 1:
            return chunks_metadata[0]
        
        # Format chunks metadata for prompt
        chunks_str = json.dumps(chunks_metadata, indent=2)
        
        prompt = METADATA_MERGE_PROMPT.format(
            title=title,
            chunks_metadata=chunks_str,
            max_tokens=self.max_tokens
        )
        
        response = await self.call_llm(prompt)
        
        # Parse JSON response
        try:
            json_str = parse_json_from_llm_response(response)
            metadata = json.loads(json_str)
            return metadata
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse merged metadata as JSON: {e}", exc_info=True)
            logger.error(f"Response was: {response}")
            
            # Check if this might be due to truncation (unclosed JSON)
            if response and not response.rstrip().endswith('}'):
                error_msg = f"Merged metadata response appears truncated (does not end with closing brace). Likely hit token limit."
                logger.error(error_msg)
                raise ValueError(error_msg) from e
            
            raise
    
    async def extract_metadata(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from a message (ASYNC VERSION).
        
        Args:
            message: The document message from RabbitMQ with resource_data nested 
                     and top-level datasource_id, scraped_at
            
        Returns:
            Extracted metadata dictionary
            
        Raises:
            ValueError: If message has no content
        """
        resource_data = message.get("resource_data", {})
        content = resource_data.get("content")
        
        # Compute SHA-256 hash of the full content for deduplication/identity
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        
        # Check if this is a parent video (has segments)
        metadata = resource_data.get("metadata", {})
        is_parent_video = metadata.get("has_segments", False)
        
        # For parent videos, use much larger chunks to reduce LLM calls
        # (parent metadata is mostly for overview, segments have the details)
        original_chunk_size = self.max_chunk_size
        if is_parent_video:
            self.max_chunk_size = 32000  # 4x larger for parent videos
            logger.info(f"Using larger chunks for parent video (32K chars)")
        
        # Chunk content
        chunks = self.chunk_content(content)
        logger.info(f"Processing {len(chunks)} chunks for: {resource_data.get('title', 'Unknown')}")
        
        # Extract metadata from each chunk sequentially to avoid rate limits
        # (Previously used asyncio.gather which fired all requests at once)
        logger.info(f"Extracting metadata from {len(chunks)} chunk(s) sequentially...")
        chunks_metadata = []
        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"Processing chunk {i}/{len(chunks)}")
            chunk_meta = await self.extract_from_chunk(resource_data, chunk)
            chunks_metadata.append(chunk_meta)
            # Small delay between chunks to respect rate limits
            if i < len(chunks):
                await asyncio.sleep(0.5)  # 500ms between requests = max 2 req/s
        
        # Restore original chunk size
        self.max_chunk_size = original_chunk_size
        
        # Merge metadata from all chunks
        logger.info("Merging metadata from all chunks")
        final_metadata = await self.merge_metadata(resource_data.get("title", "Unknown"), chunks_metadata)

        logger.info(f"Validating LLM metadata structure...")
        validate_metadata(final_metadata)
        
        # Add original message fields
        final_metadata["nodes"]["resource"].update({
            "title": resource_data.get("title"),
            "url": resource_data.get("url"),
            "category": resource_data.get("category"),
            "datasource_id": message.get("datasource_id"),
            "batch_id": message.get("batch_id"),
            "publish_date": resource_data.get("publish_date"),
            "scraped_at": message.get("scraped_at"),
            "content_hash": content_hash,
        })
        
        logger.debug(f"Extracted metadata: \n%s", json.dumps(final_metadata, indent=2))
        
        logger.info(f"Metadata extraction complete for: {resource_data.get('title', 'Unknown')}")
        return final_metadata
