"""
Sensitive Information Scrubber

This module provides utilities to detect and remove sensitive meeting information
from event locations and descriptions, including:
- Meeting platform URLs (Zoom, Teams, GoToMeeting, Webex, Google Meet, etc.)
- Meeting IDs and passcodes
- Dial-in numbers and access codes
- Authentication tokens and keys

The scrubber uses pattern matching to identify and remove sensitive data while
preserving useful event information where possible.
"""

import re
from typing import Tuple, Optional, Dict, List
from dataclasses import dataclass


@dataclass
class SanitizationResult:
    """Result of sanitization operation"""
    original: str
    sanitized: str
    was_modified: bool
    detected_patterns: List[str]  # List of pattern types that were detected


class SensitiveInfoScrubber:
    """
    Scrubs sensitive meeting information from text while preserving useful content.
    
    Example usage:
        scrubber = SensitiveInfoScrubber()
        result = scrubber.sanitize_location("https://zoom.us/j/123456?pwd=abc")
        print(result.sanitized)  # "Virtual Meeting"
    """
    
    # Meeting platform URL patterns
    MEETING_URL_PATTERNS = [
        # Zoom
        (r'https?://(?:[\w-]+\.)?zoom\.us/[^\s<>"\)]+', 'zoom'),
        (r'https?://(?:[\w-]+\.)?zoom\.com/[^\s<>"\)]+', 'zoom'),
        (r'https?://(?:[\w-]+\.)?zoomgov\.com/[^\s<>"\)]+', 'zoom'),
        
        # Microsoft Teams
        (r'https?://teams\.microsoft\.com/[^\s<>"\)]+', 'teams'),
        (r'https?://(?:[\w-]+\.)?teams\.live\.com/[^\s<>"\)]+', 'teams'),
        
        # Google Meet
        (r'https?://meet\.google\.com/[^\s<>"\)]+', 'google_meet'),
        
        # Webex
        (r'https?://(?:[\w-]+\.)?webex\.com/[^\s<>"\)]+', 'webex'),
        
        # GoToMeeting
        (r'https?://(?:www\.)?gotomeeting\.com/[^\s<>"\)]+', 'gotomeeting'),
        (r'https?://(?:www\.)?goto\.com/[^\s<>"\)]+', 'gotomeeting'),
        (r'https?://(?:global\.)?gotomeeting\.com/[^\s<>"\)]+', 'gotomeeting'),
        
        # BlueJeans
        (r'https?://(?:[\w-]+\.)?bluejeans\.com/[^\s<>"\)]+', 'bluejeans'),
        
        # Cisco
        (r'https?://(?:[\w-]+\.)?ciscospark\.com/[^\s<>"\)]+', 'cisco'),
        
        # Amazon Chime
        (r'https?://(?:[\w-]+\.)?chime\.aws/[^\s<>"\)]+', 'chime'),
        
        # Skype
        (r'https?://(?:join\.)?skype\.com/[^\s<>"\)]+', 'skype'),
        
        # Generic meeting links (be careful with these)
        (r'https?://meet\.[^\s<>"\)]+', 'generic_meet'),
        (r'https?://join\.[^\s<>"\)]+', 'generic_join'),
        
        # Bare domain references (without protocol)
        (r'(?:[\w-]+\.)?zoom\.us/[^\s<>"\)]+', 'zoom_bare'),
        (r'teams\.microsoft\.com/[^\s<>"\)]+', 'teams_bare'),
        (r'meet\.google\.com/[^\s<>"\)]+', 'google_meet_bare'),
        (r'(?:[\w-]+\.)?webex\.com/[^\s<>"\)]+', 'webex_bare'),
    ]
    
    # Meeting ID patterns (various formats)
    MEETING_ID_PATTERNS = [
        (r'(?:meeting\s+)?(?:id|ID|number)[\s:]*\d{3}[\s\-]?\d{3}[\s\-]?\d{3,4}', 'meeting_id_spaces'),
        (r'(?:meeting\s+)?(?:id|ID|number)[\s:]*\d{9,12}', 'meeting_id_consecutive'),
        (r'(?:meeting\s+)?(?:id|ID|number)[\s:]*\d{6,8}', 'meeting_id_short'),
        (r'(?:zoom|webex|teams)\s+(?:meeting\s+)?(?:id|ID)[\s:]*[\d\s\-]+', 'platform_meeting_id'),
        (r'(?:join|meeting)\s+(?:id|ID|code)[\s:]*[\d\s\-]+', 'generic_meeting_id'),
    ]
    
    # Passcode patterns
    PASSCODE_PATTERNS = [
        (r'(?:passcode|password|pass|pwd)[\s:]*\w+', 'passcode_general'),
        (r'(?:access\s+)?code[\s:]*\w+', 'access_code'),
        (r'(?:pin|PIN)[\s:]*\d+', 'pin_number'),
        (r'waiting\s+room\s+password[\s:]*\w+', 'waiting_room_password'),
    ]
    
    # Phone number patterns (dial-in)
    PHONE_PATTERNS = [
        (r'(?:dial[\s-]?in|call[\s-]?in)[\s:]*\+?[\d\s\(\)\-\.]+(?:ext|x)?\.?\s*\d*', 'dialin_number'),
        (r'(?:phone|tel|telephone)[\s:]*\+?[\d\s\(\)\-\.]+(?:ext|x)?\.?\s*\d*', 'phone_number'),
        (r'\+?1?[\s\-\.]?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}', 'formatted_phone'),
        (r'(?:conference|meeting)\s+(?:phone|number|line)[\s:]*\+?[\d\s\(\)\-\.]+', 'conference_phone'),
    ]
    
    # Comprehensive multi-line patterns for meeting details blocks
    MEETING_BLOCK_PATTERNS = [
        # Zoom-style blocks
        (r'(?:join\s+zoom\s+meeting.*?(?:meeting\s+id.*?passcode.*?|passcode.*?meeting\s+id.*?)(?:\n|$))', 
         re.IGNORECASE | re.DOTALL, 'zoom_block'),
        
        # Teams-style blocks
        (r'(?:join\s+microsoft\s+teams\s+meeting.*?(?:\n.*?){0,5})', 
         re.IGNORECASE | re.DOTALL, 'teams_block'),
        
        # Generic meeting info blocks (lines starting with Meeting ID, Passcode, etc.)
        (r'(?:^|\n)(?:meeting\s+id|passcode|password|dial[\s-]?in|phone|access\s+code)[\s:][^\n]*(?:\n(?:meeting\s+id|passcode|password|dial[\s-]?in|phone|access\s+code)[\s:][^\n]*)*',
         re.IGNORECASE | re.MULTILINE, 'credentials_block'),
    ]
    
    # Common phrases that indicate virtual meetings (preserve these as generic labels)
    VIRTUAL_INDICATORS = [
        'virtual', 'online', 'remote', 'webinar', 'video conference',
        'video call', 'online meeting', 'virtual meeting'
    ]
    
    def __init__(self, replacement_text: str = "[Meeting access details removed for security. Please view the source link for access details.]"):
        """
        Initialize the scrubber.
        
        Args:
            replacement_text: Text to replace sensitive sections with in descriptions
        """
        self.replacement_text = replacement_text
        
        # Compile all patterns for efficiency
        self.compiled_url_patterns = [
            (re.compile(pattern, re.IGNORECASE), name) 
            for pattern, name in self.MEETING_URL_PATTERNS
        ]
        
        self.compiled_id_patterns = [
            (re.compile(pattern, re.IGNORECASE), name)
            for pattern, name in self.MEETING_ID_PATTERNS
        ]
        
        self.compiled_passcode_patterns = [
            (re.compile(pattern, re.IGNORECASE), name)
            for pattern, name in self.PASSCODE_PATTERNS
        ]
        
        self.compiled_phone_patterns = [
            (re.compile(pattern, re.IGNORECASE), name)
            for pattern, name in self.PHONE_PATTERNS
        ]
        
        self.compiled_block_patterns = [
            (re.compile(pattern, flags), name)
            for pattern, flags, name in self.MEETING_BLOCK_PATTERNS
        ]
    
    def detect_sensitive_content(self, text: str) -> List[str]:
        """
        Detect what types of sensitive content are present in the text.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of detected pattern types
        """
        if not text:
            return []
        
        detected = []
        
        # Check URL patterns
        for pattern, name in self.compiled_url_patterns:
            if pattern.search(text):
                detected.append(name)
        
        # Check ID patterns
        for pattern, name in self.compiled_id_patterns:
            if pattern.search(text):
                detected.append(name)
        
        # Check passcode patterns
        for pattern, name in self.compiled_passcode_patterns:
            if pattern.search(text):
                detected.append(name)
        
        # Check phone patterns
        for pattern, name in self.compiled_phone_patterns:
            if pattern.search(text):
                detected.append(name)
        
        return list(set(detected))  # Remove duplicates
    
    def sanitize_location(self, location: Optional[str]) -> SanitizationResult:
        """
        Sanitize location field, which often contains meeting URLs.
        
        Strategy:
        - If contains meeting URL or credentials: replace with "Virtual Meeting"
        - If already says "Virtual", "Online", etc.: keep as is
        - If appears to be physical location: keep as is
        
        Args:
            location: Location string to sanitize
            
        Returns:
            SanitizationResult with sanitized location
        """
        if not location:
            return SanitizationResult(
                original="",
                sanitized="",
                was_modified=False,
                detected_patterns=[]
            )
        
        original = location
        detected = self.detect_sensitive_content(location)
        
        # If no sensitive content detected, return as-is
        if not detected:
            return SanitizationResult(
                original=original,
                sanitized=location,
                was_modified=False,
                detected_patterns=[]
            )
        
        # Check if already labeled as virtual
        lower_location = location.lower()
        if any(indicator in lower_location for indicator in self.VIRTUAL_INDICATORS):
            # Already labeled generically - just remove any URLs/credentials
            sanitized = location
            for pattern, _ in self.compiled_url_patterns:
                sanitized = pattern.sub('', sanitized)
            for pattern, _ in self.compiled_id_patterns:
                sanitized = pattern.sub('', sanitized)
            for pattern, _ in self.compiled_passcode_patterns:
                sanitized = pattern.sub('', sanitized)
            for pattern, _ in self.compiled_phone_patterns:
                sanitized = pattern.sub('', sanitized)
            
            sanitized = ' '.join(sanitized.split())  # Clean up whitespace
            
            if not sanitized.strip():
                sanitized = "Virtual Meeting"
        else:
            # Replace entirely with generic label
            sanitized = "Virtual Meeting"
        
        return SanitizationResult(
            original=original,
            sanitized=sanitized,
            was_modified=True,
            detected_patterns=detected
        )
    
    def sanitize_description(self, description: Optional[str]) -> SanitizationResult:
        """
        Sanitize description field while preserving useful event information.
        
        Strategy:
        - Remove meeting URLs, IDs, passcodes, phone numbers
        - Remove entire blocks of meeting credentials
        - Preserve general event description and context
        - Add notice that meeting details were removed
        
        Args:
            description: Description string to sanitize
            
        Returns:
            SanitizationResult with sanitized description
        """
        if not description:
            return SanitizationResult(
                original="",
                sanitized="",
                was_modified=False,
                detected_patterns=[]
            )
        
        original = description
        detected = self.detect_sensitive_content(description)
        
        # If no sensitive content, return as-is
        if not detected:
            return SanitizationResult(
                original=original,
                sanitized=description,
                was_modified=False,
                detected_patterns=[]
            )
        
        sanitized = description
        
        # First pass: Remove large blocks of meeting info
        for pattern, name in self.compiled_block_patterns:
            if pattern.search(sanitized):
                detected.append(name)
                sanitized = pattern.sub('\n' + self.replacement_text + '\n', sanitized)
        
        # Second pass: Remove individual sensitive elements
        for pattern, _ in self.compiled_url_patterns:
            sanitized = pattern.sub('', sanitized)
        
        for pattern, _ in self.compiled_id_patterns:
            sanitized = pattern.sub('', sanitized)
        
        for pattern, _ in self.compiled_passcode_patterns:
            sanitized = pattern.sub('', sanitized)
        
        for pattern, _ in self.compiled_phone_patterns:
            sanitized = pattern.sub('', sanitized)
        
        # Clean up whitespace and multiple newlines
        sanitized = re.sub(r'\n\s*\n\s*\n+', '\n\n', sanitized)  # Max 2 newlines
        sanitized = re.sub(r'[ \t]+', ' ', sanitized)  # Normalize spaces
        sanitized = sanitized.strip()
        
        # If we removed sensitive content but didn't add notice via block removal,
        # add it at the end
        if detected and self.replacement_text not in sanitized:
            if sanitized:
                sanitized += '\n\n' + self.replacement_text
            else:
                sanitized = self.replacement_text
        
        return SanitizationResult(
            original=original,
            sanitized=sanitized,
            was_modified=True,
            detected_patterns=list(set(detected))
        )
    
    def sanitize_text(self, text: Optional[str]) -> SanitizationResult:
        """
        Sanitize free-form text — strips meeting URLs, IDs, passcodes, and phone
        numbers without imposing event-specific framing.

        Designed for resource content/summary scrubbing (e.g., discussion threads,
        digest posts, prep-call write-ups) where we want to keep the text but
        remove sensitive meeting access details.

        Args:
            text: Arbitrary text content

        Returns:
            SanitizationResult with sanitized text
        """
        if not text:
            return SanitizationResult(
                original="",
                sanitized="",
                was_modified=False,
                detected_patterns=[]
            )

        original = text
        detected = self.detect_sensitive_content(text)

        if not detected:
            return SanitizationResult(
                original=original,
                sanitized=text,
                was_modified=False,
                detected_patterns=[]
            )

        sanitized = text

        # First pass: meeting credential blocks
        for pattern, name in self.compiled_block_patterns:
            if pattern.search(sanitized):
                detected.append(name)
                sanitized = pattern.sub(' [meeting access details removed] ', sanitized)

        # Second pass: individual URLs / IDs / passcodes / phones
        for pattern, _ in self.compiled_url_patterns:
            sanitized = pattern.sub('', sanitized)
        for pattern, _ in self.compiled_id_patterns:
            sanitized = pattern.sub('', sanitized)
        for pattern, _ in self.compiled_passcode_patterns:
            sanitized = pattern.sub('', sanitized)
        for pattern, _ in self.compiled_phone_patterns:
            sanitized = pattern.sub('', sanitized)

        # Whitespace cleanup
        sanitized = re.sub(r'\n\s*\n\s*\n+', '\n\n', sanitized)
        sanitized = re.sub(r'[ \t]+', ' ', sanitized)
        sanitized = sanitized.strip()

        return SanitizationResult(
            original=original,
            sanitized=sanitized,
            was_modified=True,
            detected_patterns=list(set(detected))
        )

    def sanitize_event_data(
        self,
        location: Optional[str],
        description: Optional[str]
    ) -> Tuple[str, str, bool]:
        """
        Sanitize both location and description fields together.
        
        Convenience method for processing event data.
        
        Args:
            location: Event location string
            description: Event description string
            
        Returns:
            Tuple of (sanitized_location, sanitized_description, was_any_modified)
        """
        location_result = self.sanitize_location(location)
        description_result = self.sanitize_description(description)
        
        return (
            location_result.sanitized,
            description_result.sanitized,
            location_result.was_modified or description_result.was_modified
        )


# Global instance for easy import
default_scrubber = SensitiveInfoScrubber()


def sanitize_event_location(location: Optional[str]) -> str:
    """
    Convenience function to sanitize location using default scrubber.
    
    Args:
        location: Location string to sanitize
        
    Returns:
        Sanitized location string
    """
    return default_scrubber.sanitize_location(location).sanitized


def sanitize_event_description(description: Optional[str]) -> str:
    """
    Convenience function to sanitize description using default scrubber.
    
    Args:
        description: Description string to sanitize
        
    Returns:
        Sanitized description string
    """
    return default_scrubber.sanitize_description(description).sanitized


def sanitize_event_data(
    location: Optional[str],
    description: Optional[str]
) -> Tuple[str, str]:
    """
    Convenience function to sanitize both fields using default scrubber.

    Args:
        location: Event location string
        description: Event description string

    Returns:
        Tuple of (sanitized_location, sanitized_description)
    """
    sanitized_location, sanitized_description, _ = default_scrubber.sanitize_event_data(
        location, description
    )
    return sanitized_location, sanitized_description


def sanitize_text(text: Optional[str]) -> str:
    """
    Convenience function for general-purpose meeting-info scrubbing on arbitrary
    text (e.g., discussion bodies, digest posts). Returns the sanitized string.

    Use for Resource.content / Resource.summary on sources that may contain
    Zoom / Teams / Meet URLs and credentials.
    """
    if text is None:
        return ""
    return default_scrubber.sanitize_text(text).sanitized
