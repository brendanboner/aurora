"""
Document Parser Utility

Extracts text content from binary files (PDF, DOCX, PPTX) using cached content.
"""

import base64
import io
import logging
from typing import Optional, Tuple


logger = logging.getLogger(__name__)

# Token limit for LLM processing (conservative estimate)
# Limit content size to leave room for the large prompt (~5000 tokens) and response (up to 4096 tokens)
# Model context window is typically 128k tokens, so we limit content to avoid excessive costs
# Set to 3000 chars (~750 tokens) to ensure LLM response fits within 4096 token limit
DEFAULT_TOKEN_LIMIT = 3000  # chars ~750 tokens for content, leaves room for prompt + response
CHARS_PER_TOKEN = 4  # Rough approximation


class DocumentParser:
    """Parse binary documents to extract text content."""
    
    def __init__(self):
        """Initialize document parser with library imports."""
        self.pdf_available = False
        self.docx_available = False
        self.pptx_available = False
        
        try:
            import pypdf
            self.pypdf = pypdf
            self.pdf_available = True
        except ImportError:
            logger.warning("pypdf not available - PDF parsing disabled")
        
        try:
            import docx
            self.docx = docx
            self.docx_available = True
        except ImportError:
            logger.warning("python-docx not available - DOCX parsing disabled")
        
        try:
            import pptx
            self.pptx = pptx
            self.pptx_available = True
        except ImportError:
            logger.warning("python-pptx not available - PPTX parsing disabled")
    
    def parse_pdf(self, binary_data: bytes, simplify_large: bool = True) -> str:
        """
        Extract text from PDF.
        
        Args:
            binary_data: Binary PDF content
            simplify_large: If True, simplify content if it exceeds token limit
        """
        if not self.pdf_available:
            return "[PDF parsing not available]"
        
        try:
            pdf_file = io.BytesIO(binary_data)
            reader = self.pypdf.PdfReader(pdf_file)
            
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            
            if not text_parts:
                return "[No text extracted from PDF]"
            
            full_text = "\n\n".join(text_parts)
            
            # Simplify if content is too large for LLM
            if simplify_large and len(full_text) > DEFAULT_TOKEN_LIMIT:
                return self.simplify_document_content(full_text, "PDF")
            
            return full_text
            
        except Exception as e:
            logger.error(f"PDF parsing failed: {e}")
            return f"[PDF parsing error: {str(e)}]"
    
    def parse_docx(self, binary_data: bytes, simplify_large: bool = True) -> str:
        """
        Extract text from DOCX.
        
        Args:
            binary_data: Binary DOCX content
            simplify_large: If True, simplify content if it exceeds token limit
        """
        if not self.docx_available:
            return "[DOCX parsing not available]"
        
        try:
            docx_file = io.BytesIO(binary_data)
            doc = self.docx.Document(docx_file)
            
            text_parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            # Extract from tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            text_parts.append(cell.text)
            
            if not text_parts:
                return "[No text extracted from DOCX]"
            
            full_text = "\n\n".join(text_parts)
            
            # Simplify if content is too large for LLM
            if simplify_large and len(full_text) > DEFAULT_TOKEN_LIMIT:
                return self.simplify_document_content(full_text, "DOCX")
            
            return full_text
            
        except Exception as e:
            logger.error(f"DOCX parsing failed: {e}")
            return f"[DOCX parsing error: {str(e)}]"
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text (rough approximation)."""
        return len(text) // CHARS_PER_TOKEN
    
    def simplify_document_content(self, text: str, doc_type: str = "document", max_chars: int = DEFAULT_TOKEN_LIMIT) -> str:
        """
        Simplify document content if it's too large.
        Keeps only essential text and removes repetitive formatting.
        Works for PDF, DOCX, PPTX, and other text-based documents.
        
        Args:
            text: The full document text
            doc_type: Document type for logging (e.g., "PDF", "DOCX", "PPTX")
            max_chars: Maximum character limit
        """
        if len(text) <= max_chars:
            return text
        
        logger.warning(f"{doc_type} content too large ({len(text)} chars, ~{self.estimate_tokens(text)} tokens). Simplifying...")
        
        # Split by double newlines (paragraph boundaries)
        sections = text.split("\n\n")
        
        # Deduplicate and remove very short sections (< 10 chars)
        seen = set()
        unique_sections = []
        for section in sections:
            section = section.strip()
            if len(section) < 10:
                continue
            # Use first 50 chars as dedup key
            key = section[:50].lower()
            if key not in seen:
                seen.add(key)
                unique_sections.append(section)
        
        # Join and truncate if still too large
        simplified = "\n\n".join(unique_sections)
        
        if len(simplified) > max_chars:
            logger.warning(f"Still too large after dedup. Truncating to {max_chars} chars")
            simplified = simplified[:max_chars] + "\n\n[Content truncated due to size]"
        
        logger.info(f"Simplified {doc_type} from {len(text)} to {len(simplified)} chars (~{self.estimate_tokens(simplified)} tokens)")
        return simplified
    
    def simplify_pptx_content(self, text: str, max_chars: int = DEFAULT_TOKEN_LIMIT) -> str:
        """
        Simplify PowerPoint content if it's too large.
        Wrapper for backward compatibility.
        """
        return self.simplify_document_content(text, "PPTX", max_chars)
    
    def parse_pptx(self, binary_data: bytes, simplify_large: bool = True) -> str:
        """
        Extract text from PPTX.
        
        Args:
            binary_data: Binary PPTX content
            simplify_large: If True, simplify content if it exceeds token limit
        """
        if not self.pptx_available:
            return "[PPTX parsing not available]"
        
        try:
            pptx_file = io.BytesIO(binary_data)
            prs = self.pptx.Presentation(pptx_file)
            
            text_parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        text_parts.append(shape.text)
            
            if not text_parts:
                return "[No text extracted from PPTX]"
            
            full_text = "\n\n".join(text_parts)
            
            # Simplify if content is too large for LLM
            if simplify_large and len(full_text) > DEFAULT_TOKEN_LIMIT:
                return self.simplify_pptx_content(full_text)
            
            return full_text
            
        except Exception as e:
            logger.error(f"PPTX parsing failed: {e}")
            return f"[PPTX parsing error: {str(e)}]"
    
    def parse_from_base64(self, base64_content: str, file_extension: str, simplify_large: bool = True) -> str:
        """
        Parse document from base64-encoded content.
        
        Args:
            base64_content: Base64-encoded binary content
            file_extension: File extension (pdf, docx, pptx, etc.)
            simplify_large: If True, simplify large PowerPoint content
            
        Returns:
            Extracted text content
        """
        try:
            # Decode base64
            binary_data = base64.b64decode(base64_content)
            
            # Route to appropriate parser
            ext = file_extension.lower().lstrip('.')
            
            if ext == 'pdf':
                return self.parse_pdf(binary_data, simplify_large=simplify_large)
            elif ext in ['docx', 'doc']:
                return self.parse_docx(binary_data, simplify_large=simplify_large)
            elif ext in ['pptx', 'ppt']:
                result = self.parse_pptx(binary_data, simplify_large=simplify_large)
                # If PPTX parsing failed, try DOCX (some .pptx files are actually .docx)
                if result.startswith("[PPTX parsing error:"):
                    logger.warning(f"PPTX parsing failed, attempting DOCX fallback")
                    docx_result = self.parse_docx(binary_data, simplify_large=simplify_large)
                    if not docx_result.startswith("[DOCX parsing error:"):
                        logger.info("Successfully parsed as DOCX instead of PPTX")
                        return docx_result
                return result
            else:
                return f"[Unsupported file type: {ext}]"
        
        except Exception as e:
            logger.error(f"Document parsing failed: {e}")
            return f"[Parsing error: {str(e)}]"
    
    def retrieve_and_parse(self, redis_client, url: str, file_extension: str, simplify_large: bool = True) -> Optional[str]:
        """
        Retrieve cached binary content from Redis and parse it.
        
        Args:
            redis_client: Redis client instance
            url: Document URL (used as cache key)
            file_extension: File extension
            simplify_large: If True, simplify large PowerPoint content
            
        Returns:
            Extracted text content or None if not found
        """
        try:
            cache_key = f"binary_content:{url}"
            cached = redis_client.get(cache_key)
            
            if not cached:
                logger.warning(f"No cached content found for {url}")
                return None
            
            # Decode from bytes to string if needed
            if isinstance(cached, bytes):
                cached = cached.decode('ascii')
            
            logger.info(f"Retrieved cached content for {url}, parsing as {file_extension}")
            return self.parse_from_base64(cached, file_extension, simplify_large=simplify_large)
        
        except Exception as e:
            logger.error(f"Failed to retrieve/parse cached content: {e}")
            return None
