import json
from typing import Dict, Any, List
from settings import settings
from utils.logger import setup_logger
from .prompts import METADATA_EXTRACTION_PROMPT, METADATA_MERGE_PROMPT


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
            return response.choices[0].message.content
        
        except Exception as e:
            logger.error(f"Azure OpenAI call failed: {e}", exc_info=True)
            raise
    
    def extract_from_chunk(self, message: Dict[str, Any], content_chunk: str) -> Dict[str, Any]:
        """Extract metadata from a single content chunk."""
        prompt = METADATA_EXTRACTION_PROMPT.format(
            title=message.get("title", "Unknown"),
            url=message.get("url", ""),
            resource_type=message.get("resource_type", ""),
            source=message.get("source", ""),
            publish_date=message.get("publish_date", ""),
            content=content_chunk
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
            raise
    
    def merge_metadata(self, title: str, chunks_metadata: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge metadata from multiple chunks."""
        if len(chunks_metadata) == 1:
            return chunks_metadata[0]
        
        # Format chunks metadata for prompt
        chunks_str = json.dumps(chunks_metadata, indent=2)
        
        prompt = METADATA_MERGE_PROMPT.format(
            title=title,
            chunks_metadata=chunks_str
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
            raise
    
    def extract_metadata(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metadata from a message.
        
        Args:
            message: The document message from RabbitMQ
            
        Returns:
            Extracted metadata dictionary
        """
        content = message.get("content", "")
        
        if not content:
            logger.warning("No content in message, returning empty metadata")
            return {
                "summary": "",
                "topics": [],
                "standards": [],
                "standard_editions": [],
                "key_technologies": [],
                "industry_sectors": [],
                "use_cases": []
            }
        
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
            except Exception as e:
                logger.error(f"Failed to extract metadata from chunk {i+1}: {e}")
                continue
        
        if not chunks_metadata:
            raise Exception("Failed to extract metadata from any chunk")
        
        # Merge metadata from all chunks
        logger.info("Merging metadata from all chunks")
        final_metadata = self.merge_metadata(message.get("title", "Unknown"), chunks_metadata)
        
        # Add original message fields
        final_metadata.update({
            "title": message.get("title"),
            "url": message.get("url"),
            "resource_type": message.get("resource_type"),
            "source": message.get("source"),
            "publish_date": message.get("publish_date"),
            "timestamp": message.get("timestamp")
        })
        
        logger.info(f"Metadata extraction complete for: {message.get('title', 'Unknown')}")
        return final_metadata
