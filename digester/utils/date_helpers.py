"""Shared date parsing and extraction utilities."""

import re
from typing import Any, Optional, List, Tuple
from datetime import datetime, date
from dateutil import parser as date_parser
from utils.logger import setup_logger
from settings import settings


logger = setup_logger(__name__, settings.log_level)


# Date patterns to search for in document titles
# Order matters - more specific patterns should come first
TITLE_DATE_PATTERNS: List[Tuple[str, Optional[str]]] = [
    # ISO formats (most reliable)
    (r'(\d{4}-\d{2}-\d{2})', '%Y-%m-%d'),           # 2025-04-08
    (r'(\d{4}\.\d{2}\.\d{2})', '%Y.%m.%d'),         # 2025.10.09
    (r'(\d{4}/\d{2}/\d{2})', '%Y/%m/%d'),           # 2025/04/08
    
    # Compact ISO format (with word boundaries to avoid matching random numbers)
    (r'[_\-\s\.](\d{8})(?:[_\-\s\.]|$)', '%Y%m%d'),   # _20250408_ or -20250408. or 20250408
    (r'^(\d{8})(?:[_\-\s\.]|$)', '%Y%m%d'),           # 20250408 at start of title
    
    # US formats MM-DD-YYYY (4-digit year first for priority)
    (r'(\d{2}-\d{2}-\d{4})', '%m-%d-%Y'),           # 04-08-2025
    (r'(\d{2}/\d{2}/\d{4})', '%m/%d/%Y'),           # 04/08/2025
    (r'(\d{2}\.\d{2}\.\d{4})', '%m.%d.%Y'),         # 04.08.2025
    
    # US formats MM-DD-YY (2-digit year)
    (r'(\d{2}-\d{2}-\d{2})(?!\d)', '%m-%d-%y'),     # 04-08-25
    (r'(\d{2}/\d{2}/\d{2})(?!\d)', '%m/%d/%y'),     # 04/08/25
    (r'(\d{2}\.\d{2}\.\d{2})(?!\d)', '%m.%d.%y'),   # 04.08.25
    
    # Written formats (use dateutil parser)
    # Month name with day and year
    (r'(\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})', None),  # April 8, 2025
    (r'(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})', None),  # Apr 8, 2025
    
    # Day before month (European written style)
    (r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})', None),  # 8 April 2025
    (r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4})', None),  # 8 Apr 2025
]


def parse_date(date_value: Any) -> Optional[datetime]:
    """
    Parse a date value into a datetime object.
    
    Handles multiple input formats:
    - ISO 8601 strings: "2025-11-06", "2025-11-06T10:30:00"
    - Human-readable dates: "November 6, 2025", "6 Nov 2025"
    - Datetime objects (returned as-is)
    - Unix timestamps (integers/floats)
    
    Args:
        date_value: Date value to parse (str, datetime, int, float, or None)
        
    Returns:
        Parsed datetime object, or None if parsing fails or value is None/empty
    """
    if not date_value:
        return None
    
    # If already a datetime, return it
    if isinstance(date_value, datetime):
        return date_value
    
    # If it's a string, try to parse it
    if isinstance(date_value, str):
        date_str = date_value.strip()
        if not date_str or date_str.lower() == "unknown":
            return None
        
        try:
            # Use dateutil.parser which handles many formats
            return date_parser.parse(date_str)
        except Exception as e:
            logger.warning(f"Failed to parse date string '{date_str}': {e}")
            return None
    
    # If it's a numeric timestamp (Unix epoch)
    if isinstance(date_value, (int, float)):
        try:
            return datetime.fromtimestamp(date_value)
        except Exception as e:
            logger.warning(f"Failed to parse timestamp {date_value}: {e}")
            return None
    
    logger.warning(f"Unsupported date type: {type(date_value)}")
    return None


def extract_date_from_title(title: str) -> Optional[date]:
    """
    Extract a date from a document title.
    
    This function searches for date patterns within document titles to identify
    meeting-related documents. Documents with dates in their titles typically
    represent meeting minutes, attendance records, agendas, etc.
    
    Args:
        title: The document title to search for dates
        
    Returns:
        A date object if a date was found, None otherwise
        
    Examples:
        >>> extract_date_from_title("Meeting Minutes 2025-04-08")
        datetime.date(2025, 4, 8)
        
        >>> extract_date_from_title("Attendance_20250408.pdf")
        datetime.date(2025, 4, 8)
        
        >>> extract_date_from_title("Wi-Fi 7 Specification v1.0")
        None
    """
    if not title:
        return None
    
    # Normalize whitespace but preserve original for pattern matching
    normalized_title = ' '.join(title.split())
    
    for pattern, date_format in TITLE_DATE_PATTERNS:
        match = re.search(pattern, normalized_title, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            
            try:
                if date_format:
                    # Parse with explicit format
                    parsed_dt = datetime.strptime(date_str, date_format)
                else:
                    # Use dateutil for written formats
                    parsed_dt = date_parser.parse(date_str, fuzzy=False)
                
                # Validate the date is reasonable (not too far in past or future)
                result_date = parsed_dt.date()
                
                # Sanity check: dates should be between 2000 and 2100
                if 2000 <= result_date.year <= 2100:
                    return result_date
                    
            except (ValueError, TypeError):
                # This pattern matched but couldn't parse - try next pattern
                continue
    
    return None
