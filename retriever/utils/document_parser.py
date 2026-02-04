"""Document parser for extracting text from various file formats."""

import logging
import io
from typing import Optional

logger = logging.getLogger(__name__)


class DocumentParser:
    """
    Parser for extracting text content from uploaded documents.
    
    Supported formats:
    - PDF (.pdf)
    - Word Documents (.docx)
    - PowerPoint (.pptx)
    - Excel (.xlsx)
    - Plain Text (.txt)
    - Markdown (.md)
    """
    
    def parse(self, content: bytes, filename: str) -> str:
        """
        Extract text content from a document.
        
        Args:
            content: Raw file bytes
            filename: Original filename (used to determine format)
            
        Returns:
            Extracted text content
        """
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        
        try:
            if ext == 'pdf':
                return self._parse_pdf(content)
            elif ext == 'docx':
                return self._parse_docx(content)
            elif ext == 'pptx':
                return self._parse_pptx(content)
            elif ext == 'xlsx':
                return self._parse_xlsx(content)
            elif ext in ('txt', 'md'):
                return self._parse_text(content)
            else:
                logger.warning(f"Unknown file extension: {ext}, treating as text")
                return self._parse_text(content)
        except Exception as e:
            logger.error(f"Error parsing {filename}: {e}")
            raise ValueError(f"Failed to parse document: {e}")
    
    def _parse_pdf(self, content: bytes) -> str:
        """Extract text from PDF."""
        try:
            from pypdf import PdfReader
            
            pdf_file = io.BytesIO(content)
            reader = PdfReader(pdf_file)
            
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            
            return '\n\n'.join(text_parts)
        except ImportError:
            logger.error("pypdf not installed. Install with: pip install pypdf")
            raise
    
    def _parse_docx(self, content: bytes) -> str:
        """Extract text from Word document."""
        try:
            from docx import Document
            
            doc_file = io.BytesIO(content)
            doc = Document(doc_file)
            
            text_parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            # Also extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = ' | '.join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        text_parts.append(row_text)
            
            return '\n\n'.join(text_parts)
        except ImportError:
            logger.error("python-docx not installed. Install with: pip install python-docx")
            raise
    
    def _parse_pptx(self, content: bytes) -> str:
        """Extract text from PowerPoint presentation."""
        try:
            from pptx import Presentation
            
            pptx_file = io.BytesIO(content)
            prs = Presentation(pptx_file)
            
            text_parts = []
            for slide_num, slide in enumerate(prs.slides, 1):
                slide_texts = [f"--- Slide {slide_num} ---"]
                
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_texts.append(shape.text)
                
                if len(slide_texts) > 1:  # More than just the slide header
                    text_parts.append('\n'.join(slide_texts))
            
            return '\n\n'.join(text_parts)
        except ImportError:
            logger.error("python-pptx not installed. Install with: pip install python-pptx")
            raise
    
    def _parse_xlsx(self, content: bytes) -> str:
        """Extract text from Excel spreadsheet."""
        try:
            from openpyxl import load_workbook
            
            xlsx_file = io.BytesIO(content)
            wb = load_workbook(xlsx_file, read_only=True, data_only=True)
            
            text_parts = []
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                sheet_texts = [f"--- Sheet: {sheet_name} ---"]
                
                for row in sheet.iter_rows(values_only=True):
                    row_values = [str(cell) if cell is not None else '' for cell in row]
                    row_text = ' | '.join(v for v in row_values if v)
                    if row_text:
                        sheet_texts.append(row_text)
                
                if len(sheet_texts) > 1:
                    text_parts.append('\n'.join(sheet_texts))
            
            wb.close()
            return '\n\n'.join(text_parts)
        except ImportError:
            logger.error("openpyxl not installed. Install with: pip install openpyxl")
            raise
    
    def _parse_text(self, content: bytes) -> str:
        """Parse plain text or markdown files."""
        # Try common encodings
        encodings = ['utf-8', 'utf-16', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        # Fallback: decode with replacement
        return content.decode('utf-8', errors='replace')
