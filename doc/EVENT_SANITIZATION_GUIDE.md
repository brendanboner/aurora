# Event Sanitization: Security & Privacy Guide

## Overview

The Aurora system now includes automatic sanitization of sensitive meeting information from event data. This prevents storage of security-sensitive details like meeting URLs, passcodes, meeting IDs, and dial-in numbers while preserving useful event descriptions.

## Problem Statement

Virtual meetings (Zoom, Teams, GoToMeeting, Webex, etc.) often include sensitive information in event locations and descriptions:

- **Meeting URLs** with authentication tokens
- **Passcodes and passwords**
- **Meeting IDs**
- **Dial-in phone numbers**
- **Access codes**

Storing this information creates privacy and security risks:
- Unauthorized access to meetings
- Exposure of internal meeting structures
- Compliance issues with data protection regulations

## Solution

### Multi-Layer Pattern-Based Sanitization

The system uses **advanced regex pattern matching** to detect and remove sensitive information while preserving useful event context.

**Detection Scope:**
- ✅ Zoom, Microsoft Teams, Google Meet URLs
- ✅ GoToMeeting, Webex, BlueJeans, Cisco, Amazon Chime, Skype
- ✅ Meeting IDs in various formats (123-456-789, 123456789, 123 456 789)
- ✅ Passcodes, passwords, PINs, access codes
- ✅ Dial-in numbers and conference phone lines
- ✅ Multi-line meeting information blocks

## Architecture

### Where Sanitization Happens

**Primary Layer: Retriever Service**
- Location: `retriever/utils/sensitive_info_scrubber.py`
- Triggered: In `Event.to_message()` before sending to RabbitMQ
- Effect: Prevents sensitive data from entering the system pipeline

```
Event Scraped → Sanitized → RabbitMQ → Digester → Neo4j
                    ↑
            (Primary defense)
```

### Configuration

**Retriever Settings** (`retriever/settings.py`):
```python
# Enable/disable sanitization
sanitize_events: bool = True  # Set to False to disable

# Customize replacement text
sanitization_replacement_text: str = "[Meeting access details removed for security]"
```

**Environment Variables:**
```bash
# Disable sanitization (not recommended for production)
SANITIZE_EVENTS=false

# Custom replacement text
SANITIZATION_REPLACEMENT_TEXT="[REDACTED]"
```

## Example Transformations

### Example 1: Simple Zoom Link

**Before:**
```
Location: https://zoom.us/j/123456789?pwd=abc123def
Description: Join our Q1 planning meeting
```

**After:**
```
Location: Virtual Meeting
Description: Join our Q1 planning meeting
```

### Example 2: Mixed Content in Description

**Before:**
```
Location: Virtual
Description: 
Wi-Fi Alliance Technical Committee Meeting

Agenda:
1. Review 802.11be amendments
2. Wi-Fi 7 certification timeline
3. Security updates

Join Zoom Meeting: https://zoom.us/j/987654321?pwd=secret
Meeting ID: 987 654 321
Passcode: secure123
```

**After:**
```
Location: Virtual
Description:
Wi-Fi Alliance Technical Committee Meeting

Agenda:
1. Review 802.11be amendments
2. Wi-Fi 7 certification timeline
3. Security updates

[Meeting access details removed for security]
```

### Example 3: Multiple Platforms

**Before:**
```
Description:
You can join via:
Zoom: https://zoom.us/j/111111
Teams: https://teams.microsoft.com/l/meetup-join/abc
Google Meet: https://meet.google.com/xyz-abcd

Dial-in: +1-555-123-4567
Access code: 12345#
```

**After:**
```
Description:
You can join via:

[Meeting access details removed for security]
```

## Database Migration

### Scrubbing Existing Events

Use the provided migration script to clean historical data:

```bash
# Step 1: Check database statistics
python scrub_existing_events.py --stats-only

# Step 2: Dry run (preview changes - ALWAYS DO THIS FIRST)
python scrub_existing_events.py --dry-run --verbose

# Step 3: Review the dry run output and generated report
cat scrub_report_dry_run_*.json

# Step 4: Backup your database
# Follow your backup procedures here!

# Step 5: Run the migration (after backup!)
python scrub_existing_events.py

# Step 6: Verify results
python scrub_existing_events.py --stats-only
```

### Migration Script Options

```bash
# Show help
python scrub_existing_events.py --help

# Filter by datasource
python scrub_existing_events.py --dry-run --datasource wfa_causeway

# Custom Neo4j connection
python scrub_existing_events.py \
  --neo4j-uri bolt://localhost:7687 \
  --neo4j-user neo4j \
  --neo4j-password mypassword \
  --dry-run

# Use environment variables
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="mypassword"
python scrub_existing_events.py --dry-run
```

### Migration Output

The script generates:
1. **Console output** with statistics and summary
2. **JSON report file** with detailed changes: `scrub_report_[dry_run_]YYYYMMDD_HHMMSS.json`

**Report Structure:**
```json
{
  "stats": {
    "total_events": 150,
    "events_with_sensitive_data": 42,
    "location_sanitized": 38,
    "description_sanitized": 28,
    "patterns_detected": {
      "zoom": 25,
      "teams": 10,
      "meeting_id_spaces": 30,
      "passcode_general": 20
    }
  },
  "changes": [
    {
      "url_hash": "abc123...",
      "name": "Q1 Planning Meeting",
      "datasource_id": "wfa_causeway",
      "location_changed": true,
      "original_location": "https://zoom.us/j/123",
      "new_location": "Virtual Meeting",
      "detected_patterns": ["zoom"]
    }
  ],
  "dry_run": true,
  "timestamp": "2026-01-14T10:30:00"
}
```

## Testing

### Running Tests

```bash
# Run all sanitization tests
cd retriever
pytest tests/test_sensitive_info_scrubber.py -v

# Run specific test class
pytest tests/test_sensitive_info_scrubber.py::TestLocationSanitization -v

# Run with coverage
pytest tests/test_sensitive_info_scrubber.py --cov=utils.sensitive_info_scrubber --cov-report=html
```

### Test Coverage

The test suite includes:
- ✅ All major meeting platforms (Zoom, Teams, Meet, Webex, etc.)
- ✅ Various ID formats (spaced, consecutive, with dashes)
- ✅ Multiple passcode patterns
- ✅ Phone number formats
- ✅ Multi-line meeting blocks
- ✅ Mixed content preservation
- ✅ Edge cases (unicode, HTML, very long text)
- ✅ Configuration options

## Security Best Practices

### 1. Always Enable in Production
```bash
# In production .env file
SANITIZE_EVENTS=true
```

### 2. Regular Audits
Periodically check for sensitive data:
```bash
# Check current events
python scrub_existing_events.py --stats-only

# Run sanitization on new datasources
python scrub_existing_events.py --datasource new_source --dry-run
```

### 3. Monitor Logs
The retriever logs sanitization activities:
```python
# Look for these log entries
"Failed to sanitize event data"  # Indicates a problem
```

### 4. Database Backups
**CRITICAL**: Always backup before running migration:
```bash
# Neo4j backup example
neo4j-admin dump --database=neo4j --to=/backups/pre-sanitization-$(date +%Y%m%d).dump

# Or use your regular backup process
```

### 5. Review Dry Run Reports
Always review the JSON report before running actual migration:
```bash
# Generate report
python scrub_existing_events.py --dry-run --verbose > preview.log

# Review changes
less preview.log
cat scrub_report_dry_run_*.json | jq '.changes[] | {name, patterns: .detected_patterns}'
```

## Monitoring

### What to Monitor

1. **Sanitization Failures**
   - Check retriever logs for "Failed to sanitize" errors
   - Indicates potential bugs or new patterns

2. **False Positives**
   - Review sanitized events to ensure useful info isn't removed
   - Adjust patterns if legitimate content is being scrubbed

3. **New Meeting Platforms**
   - Watch for new meeting platforms in your data
   - Add patterns to `sensitive_info_scrubber.py` as needed

### Metrics to Track

```python
# Add to your monitoring/logging
- events_scraped_total
- events_sanitized_count
- sanitization_failures_count
- sensitive_patterns_detected_by_type
```

## Troubleshooting

### Issue: Sanitization Not Working

**Symptoms:** Sensitive info still appearing in events

**Checks:**
1. Verify setting: `SANITIZE_EVENTS=true` in `.env`
2. Check retriever logs for errors
3. Verify `utils/sensitive_info_scrubber.py` exists
4. Test pattern matching:
   ```python
   from retriever.utils.sensitive_info_scrubber import sanitize_event_location
   result = sanitize_event_location("https://zoom.us/j/123")
   print(result)  # Should be "Virtual Meeting"
   ```

### Issue: Useful Info Being Removed

**Symptoms:** Important event details are missing

**Solution:** Adjust patterns or add exceptions

1. Identify the pattern causing issues
2. Check the detected patterns in dry run reports
3. Modify `sensitive_info_scrubber.py` patterns
4. Run tests: `pytest tests/test_sensitive_info_scrubber.py -v`
5. Redeploy

### Issue: New Meeting Platform Not Detected

**Symptoms:** New platform URLs not being sanitized

**Solution:** Add pattern to scrubber

```python
# In sensitive_info_scrubber.py, add to MEETING_URL_PATTERNS:
(r'https?://(?:[\w-]+\.)?newplatform\.com/[^\s<>"\)]+', 'newplatform'),
```

Then:
1. Add test case
2. Run tests
3. Redeploy
4. Run migration script for historical data

### Issue: Migration Script Fails

**Symptoms:** Script crashes or reports errors

**Common Causes:**
1. **Neo4j Connection**: Check credentials and URI
2. **Memory Issues**: Process large databases in batches
3. **Permission Issues**: Ensure write permissions

**Solutions:**
```bash
# Test connection
python -c "from neo4j_client import Neo4jClient; c=Neo4jClient('bolt://localhost:7687', 'neo4j', 'password'); print('Connected!')"

# Check available memory
free -h

# Run with verbose logging
python scrub_existing_events.py --dry-run --verbose 2>&1 | tee migration.log
```

## Maintenance

### Adding New Patterns

When you discover new meeting platforms or patterns:

1. **Add Pattern** to `retriever/utils/sensitive_info_scrubber.py`:
   ```python
   MEETING_URL_PATTERNS = [
       # ... existing patterns ...
       (r'https?://new-platform\.com/[^\s]+', 'new_platform'),
   ]
   ```

2. **Add Test** in `retriever/tests/test_sensitive_info_scrubber.py`:
   ```python
   def test_new_platform_url(self):
       location = "https://new-platform.com/meeting/123"
       result = self.scrubber.sanitize_location(location)
       assert result.was_modified
       assert 'new_platform' in result.detected_patterns
   ```

3. **Run Tests**:
   ```bash
   pytest tests/test_sensitive_info_scrubber.py -v
   ```

4. **Deploy** updated code

5. **Run Migration** for existing events:
   ```bash
   python scrub_existing_events.py --dry-run
   python scrub_existing_events.py  # After review
   ```

### Updating Patterns

To make patterns more specific or general:

1. Modify pattern in `sensitive_info_scrubber.py`
2. Update or add tests
3. Run full test suite
4. Deploy
5. Run migration script

## Integration with Existing System

### No Breaking Changes

The sanitization is transparent to the rest of the system:
- Events still have `location` and `description` fields
- Same data structure and format
- Frontend displays sanitized data normally
- No API changes required

### Disable if Needed

To temporarily disable:
```bash
# In .env file
SANITIZE_EVENTS=false
```

Or programmatically:
```python
from retriever.settings import settings
settings.sanitize_events = False
```

## Compliance & Regulations

This sanitization helps with:
- **GDPR**: Reduces PII exposure
- **SOC 2**: Security controls for access management
- **Industry Standards**: Meeting security best practices
- **Internal Policies**: Prevents credential leakage

**Note:** Consult your legal/compliance team to ensure this meets your specific requirements.

## Support & Questions

For issues or questions:
1. Check this documentation
2. Review test cases for examples
3. Check logs for errors
4. Contact the Aurora development team

## Summary

✅ **Implemented**: Pattern-based sanitization at retriever level
✅ **Configured**: Feature flags for enable/disable
✅ **Tested**: Comprehensive test coverage
✅ **Documented**: Full implementation guide
✅ **Migration**: Script for historical data cleanup

**Next Steps:**
1. Run dry-run migration to preview changes
2. Backup database
3. Run actual migration
4. Monitor for any issues
5. Adjust patterns as needed for your specific data sources

---

**Version:** 1.0
**Last Updated:** January 14, 2026
**Maintained By:** Aurora Platform Team
