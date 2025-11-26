import json
import hashlib
from typing import Dict, Any, List
from settings import settings
from utils.logger import setup_logger
from .prompts import METADATA_EXTRACTION_PROMPT, METADATA_MERGE_PROMPT
from normalization import MetadataValidator

logger = setup_logger(__name__, settings.log_level)

class MetadataExtractor:
    """Extract metadata from document content using Azure OpenAI."""
    
    def __init__(self):
        self.deployment = settings.azure_openai_deployment
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature
        self.max_chunk_size = settings.max_chunk_size
        self.chunk_overlap = settings.chunk_overlap
        
        # Initialize Azure OpenAI client
        from openai import AzureOpenAI
        self.client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint
        )
        
        logger.info(f"Initialized MetadataExtractor with Azure OpenAI deployment: {self.deployment}")
    
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
    
    def call_llm(self, prompt: str) -> str:
        """Call Azure OpenAI with the given prompt."""
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a metadata extraction expert. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            # Check if response was truncated due to token limit
            finish_reason = response.choices[0].finish_reason
            if finish_reason == "length":
                error_msg = f"LLM response truncated due to max_tokens limit ({self.max_tokens}). Content too large for current token limit."
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            return response.choices[0].message.content
        
        except ValueError:
            # Re-raise ValueError (token limit errors)
            raise
        except Exception as e:
            logger.error(f"Azure OpenAI call failed: {e}", exc_info=True)
            raise
    
    def extract_from_chunk(self, message: Dict[str, Any], content_chunk: str) -> Dict[str, Any]:
        """Extract metadata from a single content chunk."""
        prompt = METADATA_EXTRACTION_PROMPT.format(
            title=message.get("title", "Unknown"),
            url=message.get("url", ""),
            category=message.get("category", ""),
            datasource_id=message.get("datasource_id", ""),
            publish_date=message.get("publish_date", ""),
            content=content_chunk,
            max_tokens=self.max_tokens
        )
        
        response = self.call_llm(prompt)
        
        # Parse JSON response
        try:
            # Try to extract JSON from markdown code blocks if present
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
            
            metadata = json.loads(response)
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
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
            
            metadata = json.loads(response)
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
            message: The document message from RabbitMQ
            
        Returns:
            Extracted metadata dictionary
            
        Raises:
            ValueError: If message has no content
        """
        content = message.get("content")
        
        # Compute SHA-256 hash of the full content for deduplication/identity
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        
        # Chunk content
        chunks = self.chunk_content(content)
        logger.info(f"Processing {len(chunks)} chunks for: {message.get('title', 'Unknown')}")
        
        # Extract metadata from each chunk
        chunks_metadata = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Extracting metadata from chunk {i+1}/{len(chunks)}")
            try:
                chunk_metadata = self.extract_from_chunk(message, chunk)
                chunks_metadata.append(chunk_metadata)
            except ValueError:
                # Validation errors (token limits, malformed data) should fail immediately
                # Re-raise to send to DLQ without wasting more API calls
                raise
            except Exception as e:
                # Other errors (network issues, etc.) might be transient - log and try next chunk
                logger.error(f"Failed to extract metadata from chunk {i+1}: {e}")
                continue
        
        if not chunks_metadata:
            raise ValueError("Failed to extract metadata from any chunk")
        
        # Merge metadata from all chunks
        logger.info("Merging metadata from all chunks")
        final_metadata = self.merge_metadata(message.get("title", "Unknown"), chunks_metadata)

        logger.info(f"Validating LLM metadata structure...")
        MetadataValidator().validate_metadata(final_metadata)
        
        # Add original message fields
        final_metadata["nodes"]["resource"].update({
            "title": message.get("title"),
            "url": message.get("url"),
            "category": message.get("category"),
            "datasource_id": message.get("datasource_id"),  # source from retriever is the datasource_id
            "publish_date": message.get("publish_date"),
            "scraped_at": message.get("scraped_at"),
            "content_hash": content_hash,
        })
        
        logger.debug(f"Extracted metadata: \n%s", json.dumps(final_metadata, indent=2))
        
        logger.info(f"Metadata extraction complete for: {message.get('title', 'Unknown')}")
        return final_metadata
