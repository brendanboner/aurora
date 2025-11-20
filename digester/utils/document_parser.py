"""
Document Parser Utility

Extracts text content from binary files (PDF, DOCX, PPTX) using cached content.
"""

import base64
import io
import logging
from typing import Optional


logger = logging.getLogger(__name__)


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
    
    def parse_pdf(self, binary_data: bytes) -> str:
        """Extract text from PDF."""
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
            
            return "\n\n".join(text_parts) if text_parts else "[No text extracted from PDF]"
        except Exception as e:
            logger.error(f"PDF parsing failed: {e}")
            return f"[PDF parsing error: {str(e)}]"
    
    def parse_docx(self, binary_data: bytes) -> str:
        """Extract text from DOCX."""
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
            
            return "\n\n".join(text_parts) if text_parts else "[No text extracted from DOCX]"
        except Exception as e:
            logger.error(f"DOCX parsing failed: {e}")
            return f"[DOCX parsing error: {str(e)}]"
    
    def parse_pptx(self, binary_data: bytes) -> str:
        """Extract text from PPTX."""
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
            
            return "\n\n".join(text_parts) if text_parts else "[No text extracted from PPTX]"
        except Exception as e:
            logger.error(f"PPTX parsing failed: {e}")
            return f"[PPTX parsing error: {str(e)}]"
    
    def parse_from_base64(self, base64_content: str, file_extension: str) -> str:
        """
        Parse document from base64-encoded content.
        
        Args:
            base64_content: Base64-encoded binary content
            file_extension: File extension (pdf, docx, pptx, etc.)
            
        Returns:
            Extracted text content
        """
        try:
            # Decode base64
            binary_data = base64.b64decode(base64_content)
            
            # Route to appropriate parser
            ext = file_extension.lower().lstrip('.')
            
            if ext == 'pdf':
                return self.parse_pdf(binary_data)
            elif ext in ['docx', 'doc']:
                return self.parse_docx(binary_data)
            elif ext in ['pptx', 'ppt']:
                return self.parse_pptx(binary_data)
            else:
                return f"[Unsupported file type: {ext}]"
        
        except Exception as e:
            logger.error(f"Document parsing failed: {e}")
            return f"[Parsing error: {str(e)}]"
    
    def retrieve_and_parse(self, redis_client, url: str, file_extension: str) -> Optional[str]:
        """
        Retrieve cached binary content from Redis and parse it.
        
        Args:
            redis_client: Redis client instance
            url: Document URL (used as cache key)
            file_extension: File extension
            
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
            return self.parse_from_base64(cached, file_extension)
        
        except Exception as e:
            logger.error(f"Failed to retrieve/parse cached content: {e}")
            return None
