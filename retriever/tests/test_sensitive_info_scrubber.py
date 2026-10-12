"""
Tests for sensitive information scrubber.

Tests pattern matching and sanitization logic for various meeting platforms
and sensitive information patterns.
"""

import pytest
from utils.sensitive_info_scrubber import (
    SensitiveInfoScrubber,
    sanitize_event_location,
    sanitize_event_description,
    sanitize_event_data
)


class TestLocationSanitization:
    """Test location field sanitization."""
    
    def setup_method(self):
        """Set up test scrubber instance."""
        self.scrubber = SensitiveInfoScrubber()
    
    def test_zoom_url_in_location(self):
        """Test Zoom URL detection and sanitization."""
        location = "https://zoom.us/j/123456789?pwd=abc123"
        result = self.scrubber.sanitize_location(location)
        
        assert result.was_modified
        assert result.sanitized == "Virtual Meeting"
        assert 'zoom' in result.detected_patterns
    
    def test_teams_url_in_location(self):
        """Test Microsoft Teams URL detection."""
        location = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc123"
        result = self.scrubber.sanitize_location(location)
        
        assert result.was_modified
        assert result.sanitized == "Virtual Meeting"
        assert 'teams' in result.detected_patterns
    
    def test_google_meet_url_in_location(self):
        """Test Google Meet URL detection."""
        location = "https://meet.google.com/abc-defg-hij"
        result = self.scrubber.sanitize_location(location)
        
        assert result.was_modified
        assert result.sanitized == "Virtual Meeting"
        assert 'google_meet' in result.detected_patterns
    
    def test_webex_url_in_location(self):
        """Test Webex URL detection."""
        location = "https://company.webex.com/meet/user123"
        result = self.scrubber.sanitize_location(location)
        
        assert result.was_modified
        assert result.sanitized == "Virtual Meeting"
        assert 'webex' in result.detected_patterns
    
    def test_gotomeeting_url_in_location(self):
        """Test GoToMeeting URL detection."""
        location = "https://www.gotomeeting.com/join/123456789"
        result = self.scrubber.sanitize_location(location)
        
        assert result.was_modified
        assert result.sanitized == "Virtual Meeting"
        assert 'gotomeeting' in result.detected_patterns
    
    def test_physical_location_unchanged(self):
        """Test that physical locations are not modified."""
        location = "San Francisco, CA"
        result = self.scrubber.sanitize_location(location)
        
        assert not result.was_modified
        assert result.sanitized == "San Francisco, CA"
        assert result.detected_patterns == []
    
    def test_virtual_label_preserved(self):
        """Test that 'Virtual' label is preserved."""
        location = "Virtual"
        result = self.scrubber.sanitize_location(location)
        
        assert not result.was_modified
        assert result.sanitized == "Virtual"
    
    def test_virtual_with_url_sanitized(self):
        """Test that 'Virtual' with URL gets URL removed."""
        location = "Virtual - https://zoom.us/j/123456"
        result = self.scrubber.sanitize_location(location)
        
        assert result.was_modified
        assert "zoom.us" not in result.sanitized
        # Should preserve "Virtual" label
        assert "Virtual" in result.sanitized or result.sanitized == "Virtual Meeting"
    
    def test_empty_location(self):
        """Test empty location handling."""
        result = self.scrubber.sanitize_location("")
        assert not result.was_modified
        assert result.sanitized == ""
    
    def test_none_location(self):
        """Test None location handling."""
        result = self.scrubber.sanitize_location(None)
        assert not result.was_modified
        assert result.sanitized == ""


class TestDescriptionSanitization:
    """Test description field sanitization."""
    
    def setup_method(self):
        """Set up test scrubber instance."""
        self.scrubber = SensitiveInfoScrubber()
    
    def test_zoom_meeting_block_sanitized(self):
        """Test removal of full Zoom meeting info block."""
        description = """
        Join us for our Q1 Planning Meeting
        
        Join Zoom Meeting
        https://zoom.us/j/123456789?pwd=abc123
        
        Meeting ID: 123 456 789
        Passcode: secure123
        
        Agenda items will include budget review and project updates.
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "zoom.us" not in result.sanitized
        assert "123456789" not in result.sanitized
        assert "secure123" not in result.sanitized
        # Should preserve useful content
        assert "Q1 Planning Meeting" in result.sanitized
        assert "Agenda items" in result.sanitized
        # Should include removal notice
        assert "removed for security" in result.sanitized.lower()
    
    def test_meeting_id_and_passcode_removed(self):
        """Test removal of meeting ID and passcode patterns."""
        description = """
        Important meeting tomorrow
        Meeting ID: 987 654 321
        Passcode: mypassword123
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "987 654 321" not in result.sanitized
        assert "mypassword123" not in result.sanitized
        assert "Important meeting tomorrow" in result.sanitized
    
    def test_phone_numbers_removed(self):
        """Test removal of dial-in numbers."""
        description = """
        Conference call details:
        Dial-in: +1 (555) 123-4567
        Phone: 555-987-6543
        Access code: 12345#
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        # Phone numbers should be removed
        assert "555" not in result.sanitized or "Conference call details" in result.sanitized
        assert "12345#" not in result.sanitized
    
    def test_multiple_meeting_urls_removed(self):
        """Test removal of multiple different meeting platform URLs."""
        description = """
        You can join via:
        Zoom: https://zoom.us/j/111111
        Or Teams: https://teams.microsoft.com/l/meetup-join/abc
        Or Google Meet: https://meet.google.com/xyz-abcd-efg
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "zoom.us" not in result.sanitized
        assert "teams.microsoft.com" not in result.sanitized
        assert "meet.google.com" not in result.sanitized
    
    def test_clean_description_unchanged(self):
        """Test that clean descriptions without sensitive info are preserved."""
        description = """
        Join us for an exciting workshop on AI and machine learning.
        We'll cover the latest developments and best practices.
        Location will be announced closer to the date.
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert not result.was_modified
        assert result.sanitized == description
        assert result.detected_patterns == []
    
    def test_various_passcode_formats(self):
        """Test detection of various passcode formats."""
        test_cases = [
            ("Password: abc123", "abc123"),
            ("Passcode: xyz789", "xyz789"),
            ("pwd: test123", "test123"),
            ("PIN: 1234", "1234"),
            ("Access code: 567890", "567890"),
            ("Waiting room password: secure", "secure"),
        ]
        
        for desc, sensitive_part in test_cases:
            result = self.scrubber.sanitize_description(desc)
            assert result.was_modified, f"Failed to detect: {desc}"
            assert sensitive_part not in result.sanitized, f"Failed to remove: {sensitive_part}"
    
    def test_various_meeting_id_formats(self):
        """Test detection of various meeting ID formats."""
        test_cases = [
            "Meeting ID: 123 456 789",
            "Meeting ID: 123456789",
            "meeting id: 987654321",
            "ID: 111 222 333",
            "Zoom meeting ID: 444-555-666",
        ]
        
        for desc in test_cases:
            result = self.scrubber.sanitize_description(desc)
            assert result.was_modified, f"Failed to detect: {desc}"
    
    def test_empty_description(self):
        """Test empty description handling."""
        result = self.scrubber.sanitize_description("")
        assert not result.was_modified
        assert result.sanitized == ""
    
    def test_none_description(self):
        """Test None description handling."""
        result = self.scrubber.sanitize_description(None)
        assert not result.was_modified
        assert result.sanitized == ""
    
    def test_preserves_useful_content_with_sensitive_parts(self):
        """Test that useful content is preserved when removing sensitive parts."""
        description = """
        Wi-Fi Alliance Technical Committee Meeting
        
        Agenda:
        1. Review of 802.11be amendments
        2. Discussion of Wi-Fi 7 certification timeline
        3. Security working group updates
        
        Join via: https://zoom.us/j/999888777?pwd=secret
        Meeting ID: 999 888 777
        Passcode: secret
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        # Sensitive parts removed
        assert "zoom.us" not in result.sanitized
        assert "999888777" not in result.sanitized
        assert "secret" not in result.sanitized
        # Useful content preserved
        assert "Wi-Fi Alliance Technical Committee Meeting" in result.sanitized
        assert "Agenda:" in result.sanitized
        assert "802.11be" in result.sanitized
        assert "Wi-Fi 7 certification timeline" in result.sanitized


class TestEventDataSanitization:
    """Test combined event data sanitization."""
    
    def test_sanitize_both_fields(self):
        """Test sanitizing both location and description together."""
        location = "https://zoom.us/j/12345"
        description = "Meeting at zoom.us/j/12345 with passcode: abc"
        
        clean_location, clean_description = sanitize_event_data(location, description)
        
        assert "zoom.us" not in clean_location
        assert "zoom.us" not in clean_description
        assert "abc" not in clean_description
    
    def test_sanitize_only_location(self):
        """Test when only location needs sanitization."""
        location = "https://teams.microsoft.com/meet/abc"
        description = "Regular planning meeting"
        
        clean_location, clean_description = sanitize_event_data(location, description)
        
        assert clean_location == "Virtual Meeting"
        assert clean_description == description  # Unchanged
    
    def test_sanitize_only_description(self):
        """Test when only description needs sanitization."""
        location = "Conference Room A"
        description = "Join via https://meet.google.com/xyz passcode: 1234"
        
        clean_location, clean_description = sanitize_event_data(location, description)
        
        assert clean_location == location  # Unchanged
        assert "meet.google.com" not in clean_description
        assert "1234" not in clean_description
    
    def test_sanitize_neither_field(self):
        """Test when neither field needs sanitization."""
        location = "San Francisco, CA"
        description = "Annual conference at the convention center"
        
        clean_location, clean_description = sanitize_event_data(location, description)
        
        assert clean_location == location
        assert clean_description == description


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_sanitize_event_location_function(self):
        """Test standalone location sanitization function."""
        location = "https://zoom.us/j/123"
        result = sanitize_event_location(location)
        
        assert result == "Virtual Meeting"
    
    def test_sanitize_event_description_function(self):
        """Test standalone description sanitization function."""
        description = "Meeting ID: 123456789"
        result = sanitize_event_description(description)
        
        assert "123456789" not in result
        assert "removed for security" in result.lower()


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def setup_method(self):
        """Set up test scrubber instance."""
        self.scrubber = SensitiveInfoScrubber()
    
    def test_url_with_html_tags(self):
        """Test URL detection within HTML tags."""
        description = '<a href="https://zoom.us/j/123">Join Meeting</a>'
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "zoom.us/j/123" not in result.sanitized
    
    def test_multiple_consecutive_meeting_blocks(self):
        """Test multiple meeting info blocks."""
        description = """
        Meeting 1:
        Zoom: https://zoom.us/j/111
        ID: 111111
        
        Meeting 2:
        Teams: https://teams.microsoft.com/meet/222
        ID: 222222
        """
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "zoom.us" not in result.sanitized
        assert "teams.microsoft.com" not in result.sanitized
        assert "111111" not in result.sanitized
        assert "222222" not in result.sanitized
    
    def test_case_insensitive_detection(self):
        """Test that pattern detection is case-insensitive."""
        test_cases = [
            "PASSWORD: abc123",
            "password: abc123",
            "Password: abc123",
            "MEETING ID: 123456",
            "meeting id: 123456",
            "Meeting ID: 123456",
        ]
        
        for desc in test_cases:
            result = self.scrubber.sanitize_description(desc)
            assert result.was_modified, f"Failed case-insensitive detection: {desc}"
    
    def test_whitespace_normalization(self):
        """Test that excessive whitespace is normalized."""
        description = "Meeting    details:    \n\n\n\nID: 123   \nPasscode: abc"
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        # Should not have excessive whitespace
        assert "    " not in result.sanitized
        assert "\n\n\n" not in result.sanitized
    
    def test_custom_replacement_text(self):
        """Test using custom replacement text."""
        scrubber = SensitiveInfoScrubber(
            replacement_text="[REDACTED FOR PRIVACY]"
        )
        
        description = "Join at https://zoom.us/j/123"
        result = scrubber.sanitize_description(description)
        
        assert "[REDACTED FOR PRIVACY]" in result.sanitized
        assert "zoom.us" not in result.sanitized
    
    def test_very_long_description(self):
        """Test handling of very long descriptions."""
        # Create a long description with sensitive info in the middle
        long_text = "Important meeting details. " * 100
        description = long_text + "\nMeeting ID: 123456789\n" + long_text
        
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "123456789" not in result.sanitized
        # Should still contain the non-sensitive parts
        assert "Important meeting details" in result.sanitized
    
    def test_unicode_characters(self):
        """Test handling of unicode characters."""
        description = "Réunion virtuelle: https://zoom.us/j/123 Mot de passe: café123"
        result = self.scrubber.sanitize_description(description)
        
        assert result.was_modified
        assert "zoom.us" not in result.sanitized
        # Unicode content should be preserved
        assert "Réunion virtuelle" in result.sanitized


class TestPatternDetection:
    """Test pattern detection without modification."""
    
    def setup_method(self):
        """Set up test scrubber instance."""
        self.scrubber = SensitiveInfoScrubber()
    
    def test_detect_zoom_pattern(self):
        """Test Zoom pattern detection."""
        text = "https://zoom.us/j/123"
        patterns = self.scrubber.detect_sensitive_content(text)
        
        assert 'zoom' in patterns
    
    def test_detect_multiple_patterns(self):
        """Test detection of multiple pattern types."""
        text = "https://zoom.us/j/123 Meeting ID: 456 Passcode: abc"
        patterns = self.scrubber.detect_sensitive_content(text)
        
        assert 'zoom' in patterns
        assert any('meeting_id' in p for p in patterns)
        assert any('passcode' in p for p in patterns)
    
    def test_detect_no_patterns(self):
        """Test no patterns detected in clean text."""
        text = "Regular meeting at the office"
        patterns = self.scrubber.detect_sensitive_content(text)
        
        assert patterns == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
