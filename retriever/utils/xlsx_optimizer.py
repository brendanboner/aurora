"""
XLSX Optimizer - Intelligent Excel file processing with deduplication and delta detection.

This module provides smart extraction for Excel files, particularly optimized for 
attendance sheets that have repetitive structure across meetings.

Key features:
1. Skip instruction/template sheets
2. Extract only meaningful data rows
3. Generate compact summaries for attendance-style documents
4. Detect deltas between similar documents (same structure, different data)
5. Cache document fingerprints for comparison
"""

import io
import logging
import hashlib
import json
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)


class XLSXOptimizer:
    """
    Optimizes XLSX file processing by:
    - Skipping instruction/template sheets
    - Extracting structured summaries for attendance documents
    - Detecting changes between similar documents
    """
    
    # Sheet names that typically contain instructions/templates (case-insensitive)
    SKIP_SHEET_PATTERNS = {
        'instructions', 'instruction', 'template', 'readme', 'read me',
        'how to', 'howto', 'guide', 'help', 'example', 'sample'
    }
    
    # Keywords indicating attendance-style documents
    ATTENDANCE_KEYWORDS = {
        'attendance', 'attendee', 'participant', 'member', 'company',
        'organization', 'affiliation', 'present', 'name', 'email'
    }
    
    def __init__(self, enable_delta_detection: bool = True):
        """
        Initialize XLSX optimizer.
        
        Args:
            enable_delta_detection: If True, compare with previous versions
        """
        self.enable_delta_detection = enable_delta_detection
        self._document_cache: Dict[str, Dict] = {}  # fingerprint -> metadata
    
    def parse_smart(self, content: bytes, filename: str, 
                   url: Optional[str] = None) -> Dict[str, any]:
        """
        Parse XLSX with intelligent optimization.
        
        Args:
            content: Raw XLSX bytes
            filename: Original filename
            url: Optional source URL for caching/comparison
            
        Returns:
            Dict with:
                - text: Extracted text (optimized)
                - metadata: Document metadata
                - is_attendance: Whether this looks like attendance
                - delta: Changes from previous version (if applicable)
                - summary: Compact summary for LLM context
        """
        try:
            xlsx_file = io.BytesIO(content)
            wb = load_workbook(xlsx_file, read_only=True, data_only=True)
            
            # Analyze document structure
            doc_type = self._detect_document_type(wb, filename)
            
            if doc_type == 'attendance':
                result = self._parse_attendance_sheet(wb, filename, url)
            else:
                result = self._parse_standard_sheet(wb, filename)
            
            wb.close()
            
            # Generate fingerprint for delta detection
            if url and self.enable_delta_detection:
                fingerprint = self._generate_fingerprint(result)
                delta = self._detect_delta(url, fingerprint, result)
                result['delta'] = delta
            
            return result
            
        except Exception as e:
            logger.error(f"Error optimizing XLSX {filename}: {e}")
            raise
    
    def _detect_document_type(self, wb, filename: str) -> str:
        """
        Detect document type based on content and filename.
        
        Returns:
            'attendance', 'data', or 'general'
        """
        filename_lower = filename.lower()
        
        # Check filename
        if any(kw in filename_lower for kw in self.ATTENDANCE_KEYWORDS):
            return 'attendance'
        
        # Check sheet headers
        for sheet_name in wb.sheetnames[:3]:  # Check first 3 sheets
            if self._should_skip_sheet(sheet_name):
                continue
            
            sheet = wb[sheet_name]
            headers = self._extract_headers(sheet)
            
            # Count attendance-related headers
            attendance_score = sum(
                1 for h in headers 
                if any(kw in h.lower() for kw in self.ATTENDANCE_KEYWORDS)
            )
            
            if attendance_score >= 2:  # At least 2 attendance-related columns
                return 'attendance'
        
        return 'general'
    
    def _should_skip_sheet(self, sheet_name: str) -> bool:
        """Check if sheet should be skipped based on name."""
        name_lower = sheet_name.lower().strip()
        return any(pattern in name_lower for pattern in self.SKIP_SHEET_PATTERNS)
    
    def _extract_headers(self, sheet: Worksheet, max_rows: int = 5) -> List[str]:
        """
        Extract column headers from first few rows.
        
        Args:
            sheet: Worksheet to analyze
            max_rows: How many rows to check for headers
            
        Returns:
            List of detected header strings
        """
        headers = []
        
        # Try first few rows to find headers
        for row_idx, row in enumerate(sheet.iter_rows(values_only=True, max_row=max_rows)):
            if row_idx > max_rows:
                break
            
            # Skip empty rows
            if not any(cell for cell in row):
                continue
            
            # Check if this looks like a header row
            # (non-empty cells, mostly text, not all numbers)
            non_empty = [str(cell) for cell in row if cell is not None]
            if len(non_empty) >= 2:  # At least 2 columns
                # If mostly text and not numbers, likely headers
                numeric_count = sum(1 for val in non_empty if val.replace('.', '').isdigit())
                if numeric_count < len(non_empty) * 0.5:  # Less than 50% numbers
                    headers = non_empty
                    break
        
        return headers
    
    def _parse_attendance_sheet(self, wb, filename: str, 
                                url: Optional[str] = None) -> Dict:
        """
        Parse attendance-style Excel with compact summary.
        
        Generates:
        - List of unique companies/organizations
        - Attendee count
        - Meeting metadata
        - Minimal text representation
        """
        companies = set()
        attendees = []
        meeting_date = None
        meeting_group = None
        
        for sheet_name in wb.sheetnames:
            if self._should_skip_sheet(sheet_name):
                logger.info(f"Skipping instruction sheet: {sheet_name}")
                continue
            
            sheet = wb[sheet_name]
            headers = self._extract_headers(sheet)
            
            if not headers:
                continue
            
            # Find company/organization column
            company_col_idx = self._find_column_index(headers, 
                ['company', 'organization', 'affiliation', 'employer'])
            name_col_idx = self._find_column_index(headers,
                ['name', 'attendee', 'participant', 'member'])
            
            # Extract data rows (skip header rows)
            header_row_count = 1
            for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
                # Skip first few rows (headers/title)
                if row_idx < header_row_count:
                    continue
                
                # Skip empty rows
                if not any(cell for cell in row):
                    continue
                
                # Extract company if available
                if company_col_idx is not None and company_col_idx < len(row):
                    company = str(row[company_col_idx]).strip()
                    if company and company.lower() not in ('none', 'n/a', ''):
                        companies.add(company)
                
                # Extract name if available
                if name_col_idx is not None and name_col_idx < len(row):
                    name = str(row[name_col_idx]).strip()
                    if name and name.lower() not in ('none', 'n/a', ''):
                        attendees.append(name)
        
        # Try to extract meeting date from filename
        meeting_date = self._extract_date_from_filename(filename)
        
        # Try to extract working group from filename or URL
        if url:
            meeting_group = self._extract_group_from_url(url)
        
        # Generate compact summary
        summary = self._generate_attendance_summary(
            companies=companies,
            attendee_count=len(attendees),
            meeting_date=meeting_date,
            meeting_group=meeting_group,
            filename=filename
        )
        
        # Generate minimal full text (just companies list, no repetitive rows)
        full_text = self._generate_attendance_text(companies, len(attendees), summary)
        
        return {
            'text': full_text,
            'summary': summary,
            'is_attendance': True,
            'metadata': {
                'filename': filename,
                'companies': sorted(list(companies)),
                'attendee_count': len(attendees),
                'meeting_date': meeting_date,
                'meeting_group': meeting_group,
                'document_type': 'attendance'
            }
        }
    
    def _parse_standard_sheet(self, wb, filename: str) -> Dict:
        """
        Parse general Excel file (non-attendance).
        
        Uses standard extraction but skips instruction sheets.
        """
        text_parts = []
        
        for sheet_name in wb.sheetnames:
            if self._should_skip_sheet(sheet_name):
                logger.info(f"Skipping instruction sheet: {sheet_name}")
                continue
            
            sheet = wb[sheet_name]
            sheet_texts = [f"--- Sheet: {sheet_name} ---"]
            
            for row in sheet.iter_rows(values_only=True):
                row_values = [str(cell) if cell is not None else '' for cell in row]
                row_text = ' | '.join(v for v in row_values if v)
                if row_text:
                    sheet_texts.append(row_text)
            
            if len(sheet_texts) > 1:
                text_parts.append('\n'.join(sheet_texts))
        
        return {
            'text': '\n\n'.join(text_parts),
            'summary': f"Excel file: {filename} ({len(wb.sheetnames)} sheets)",
            'is_attendance': False,
            'metadata': {
                'filename': filename,
                'sheet_count': len(wb.sheetnames),
                'document_type': 'general'
            }
        }
    
    def _find_column_index(self, headers: List[str], 
                          keywords: List[str]) -> Optional[int]:
        """Find column index that matches any of the keywords."""
        for idx, header in enumerate(headers):
            header_lower = header.lower()
            if any(kw in header_lower for kw in keywords):
                return idx
        return None
    
    def _extract_date_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract date from filename.
        
        Patterns: Attendance_YYYYMMDD, 20260212_attendance, etc.
        """
        import re
        
        # Pattern: YYYY-MM-DD or YYYYMMDD
        patterns = [
            r'(\d{4})[_-]?(\d{2})[_-]?(\d{2})',  # 20260212, 2026-02-12, 2026_02_12
            r'(\d{2})[_-](\d{2})[_-](\d{4})',    # 02-12-2026, 02_12_2026
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                groups = match.groups()
                if len(groups[0]) == 4:  # YYYY-MM-DD
                    return f"{groups[0]}-{groups[1]}-{groups[2]}"
                else:  # MM-DD-YYYY
                    return f"{groups[2]}-{groups[0]}-{groups[1]}"
        
        return None
    
    def _extract_group_from_url(self, url: str) -> Optional[str]:
        """Extract working group name from URL."""
        import re
        
        # Pattern for Wi-Fi Alliance URLs
        # Example: https://groups.wi-fi.org/wg/Regulatory/...
        match = re.search(r'/wg/([^/]+)', url)
        if match:
            return match.group(1)
        
        return None
    
    def _generate_attendance_summary(self, companies: Set[str], 
                                    attendee_count: int,
                                    meeting_date: Optional[str],
                                    meeting_group: Optional[str],
                                    filename: str) -> str:
        """Generate compact summary for LLM context."""
        parts = []
        
        if meeting_group:
            parts.append(f"{meeting_group} Working Group")
        
        if meeting_date:
            parts.append(f"meeting on {meeting_date}")
        else:
            parts.append("meeting")
        
        parts.append(f"had {attendee_count} attendees")
        parts.append(f"from {len(companies)} companies")
        
        if companies:
            company_list = ', '.join(sorted(list(companies))[:10])  # First 10
            if len(companies) > 10:
                company_list += f", and {len(companies) - 10} others"
            parts.append(f": {company_list}")
        
        return ' '.join(parts) + '.'
    
    def _generate_attendance_text(self, companies: Set[str], 
                                 attendee_count: int,
                                 summary: str) -> str:
        """Generate minimal text representation."""
        text_parts = [
            "=== ATTENDANCE SUMMARY ===",
            summary,
            "",
            f"Total Attendees: {attendee_count}",
            f"Total Companies: {len(companies)}",
            "",
            "Companies in Attendance:",
        ]
        
        text_parts.extend(f"- {company}" for company in sorted(companies))
        
        return '\n'.join(text_parts)
    
    def _generate_fingerprint(self, result: Dict) -> str:
        """
        Generate fingerprint for delta detection.
        
        For attendance: fingerprint based on companies set
        For general: fingerprint based on full content hash
        """
        if result.get('is_attendance'):
            companies = result['metadata'].get('companies', [])
            data = json.dumps(sorted(companies), sort_keys=True)
        else:
            data = result['text']
        
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _detect_delta(self, url: str, fingerprint: str, 
                     result: Dict) -> Optional[Dict]:
        """
        Detect changes from previous version of this document.
        
        Returns:
            Dict with added/removed items, or None if no previous version
        """
        cache_key = self._normalize_url(url)
        
        if cache_key not in self._document_cache:
            # First time seeing this document
            self._document_cache[cache_key] = {
                'fingerprint': fingerprint,
                'metadata': result['metadata'],
                'timestamp': datetime.now().isoformat()
            }
            return None
        
        previous = self._document_cache[cache_key]
        
        if previous['fingerprint'] == fingerprint:
            # No changes
            return {'changed': False}
        
        # Detect specific changes
        if result.get('is_attendance'):
            delta = self._detect_attendance_delta(
                previous['metadata'],
                result['metadata']
            )
        else:
            delta = {'changed': True, 'type': 'content_modified'}
        
        # Update cache
        self._document_cache[cache_key] = {
            'fingerprint': fingerprint,
            'metadata': result['metadata'],
            'timestamp': datetime.now().isoformat(),
            'previous': previous
        }
        
        return delta
    
    def _detect_attendance_delta(self, old_meta: Dict, new_meta: Dict) -> Dict:
        """Detect specific changes in attendance documents."""
        old_companies = set(old_meta.get('companies', []))
        new_companies = set(new_meta.get('companies', []))
        
        added = new_companies - old_companies
        removed = old_companies - new_companies
        
        old_count = old_meta.get('attendee_count', 0)
        new_count = new_meta.get('attendee_count', 0)
        
        return {
            'changed': True,
            'type': 'attendance_modified',
            'companies_added': sorted(list(added)),
            'companies_removed': sorted(list(removed)),
            'attendee_count_delta': new_count - old_count,
            'previous_count': old_count,
            'new_count': new_count
        }
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for caching (remove query params, fragments)."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    def get_delta_summary(self, delta: Optional[Dict]) -> str:
        """
        Generate human-readable delta summary.
        
        Args:
            delta: Delta dict from _detect_delta
            
        Returns:
            Summary string for LLM context
        """
        if not delta or not delta.get('changed'):
            return "No changes from previous version."
        
        if delta.get('type') == 'attendance_modified':
            parts = []
            
            if delta.get('attendee_count_delta', 0) != 0:
                parts.append(
                    f"Attendance changed: {delta['previous_count']} → {delta['new_count']} "
                    f"({delta['attendee_count_delta']:+d})"
                )
            
            if delta.get('companies_added'):
                parts.append(f"New companies: {', '.join(delta['companies_added'])}")
            
            if delta.get('companies_removed'):
                parts.append(f"Removed: {', '.join(delta['companies_removed'])}")
            
            return ' | '.join(parts) if parts else "Minor attendance changes."
        
        return "Document content has been modified."
