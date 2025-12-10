"""Extract metadata from document content using Azure OpenAI."""

import json
import hashlib
from typing import Dict, Any, List
from settings import settings
from utils.logger import setup_logger
from utils.llm_helpers import call_llm_with_retry, parse_json_from_llm_response
from utils.prompts import METADATA_EXTRACTION_PROMPT, METADATA_MERGE_PROMPT
from utils.validator import validate_metadata

logger = setup_logger(__name__, settings.log_level)


class MetadataExtractor:
    """Extract metadata from document content using Azure OpenAI."""
    
    def __init__(self):
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature
        self.max_chunk_size = settings.max_chunk_size
        self.chunk_overlap = settings.chunk_overlap
        
        logger.info(f"Initialized MetadataExtractor with Azure OpenAI deployment: {settings.azure_openai_deployment}")
    
    def chunk_content(self, content: str) -> List[str]:
        """Split content into overlapping chunks."""
        if len(content) <= self.max_chunk_size:
            return [content]
        
        chunks = []
        start = 0
        
        while start < len(content):
            end = start + self.max_chunk_size
            chunk = content[start:end]
            chunks.append(chunk)
            start = end - self.chunk_overlap
        
        logger.info(f"Split content into {len(chunks)} chunks")
        return chunks
    
    def call_llm(self, prompt: str, system_message: str = "You are a metadata extraction expert. Always respond with valid JSON.") -> str:
        """
        Call Azure OpenAI with the given prompt.
        
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
        return call_llm_with_retry(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_retries=settings.llm_rate_limit_retries,
            check_truncation=True
        )
    
    def extract_from_chunk(self, resource_data: Dict[str, Any], content_chunk: str) -> Dict[str, Any]:
        """Extract metadata from a single content chunk."""
        prompt = METADATA_EXTRACTION_PROMPT.format(
            title=resource_data.get("title", "Unknown"),
            url=resource_data.get("url", ""),
            category=resource_data.get("category", ""),
            publish_date=resource_data.get("publish_date", ""),
            content=content_chunk,
            max_tokens=self.max_tokens
        )
        
        response = self.call_llm(prompt)
        
        # Parse JSON response
        try:
            json_str = parse_json_from_llm_response(response)
            metadata = json.loads(json_str)
            return metadata
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response was: {response}")
            
            # Check if this might be due to truncation (unclosed JSON)
            if response and not response.rstrip().endswith('}'):
                error_msg = f"LLM response appears truncated (does not end with closing brace). Likely hit token limit."
                logger.error(error_msg)
                raise ValueError(error_msg) from e
            
            raise
    
    def merge_metadata(self, title: str, chunks_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge metadata from multiple chunks."""
        if len(chunks_metadata) == 1:
            return chunks_metadata[0]
        
        # Format chunks metadata for prompt
        chunks_str = json.dumps(chunks_metadata, indent=2)
        
        prompt = METADATA_MERGE_PROMPT.format(
            title=title,
            chunks_metadata=chunks_str,
            max_tokens=self.max_tokens
        )
        
        response = self.call_llm(prompt)
        
        # Parse JSON response
        try:
            json_str = parse_json_from_llm_response(response)
            metadata = json.loads(json_str)
            return metadata
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse merged metadata as JSON: {e}")
            logger.error(f"Response was: {response}")
            
            # Check if this might be due to truncation (unclosed JSON)
            if response and not response.rstrip().endswith('}'):
                error_msg = f"Merged metadata response appears truncated (does not end with closing brace). Likely hit token limit."
                logger.error(error_msg)
                raise ValueError(error_msg) from e
            
            raise
    
    def extract_metadata(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from a message.
        
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

        
        # Chunk content
        chunks = self.chunk_content(content)
        logger.info(f"Processing {len(chunks)} chunks for: {resource_data.get('title', 'Unknown')}")
        
        # Extract metadata from each chunk
        chunks_metadata = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Extracting metadata from chunk {i+1}/{len(chunks)}")
            chunk_metadata = self.extract_from_chunk(resource_data, chunk)
            chunks_metadata.append(chunk_metadata)
        
        # Merge metadata from all chunks
        logger.info("Merging metadata from all chunks")
        final_metadata = self.merge_metadata(resource_data.get("title", "Unknown"), chunks_metadata)

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
