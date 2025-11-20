# Aurora CLI

Command-line interface for querying the Aurora knowledge graph backend.

## Installation

Using `uv` (recommended):
```bash
uv sync
```

Or using pip:
```bash
pip install -r requirements.txt
```

## Usage

### Basic Query (uses user_id=1 by default)
```bash
./aurora What are the latest Wi-Fi Alliance updates?
```

### Specify User ID
```bash
./aurora --user-id 2 Tell me about 802.11ax standards
```

### Verbose Mode (show filter details)
```bash
./aurora -v What happened last week in wireless communications?
```

### Custom Backend URL
```bash
./aurora --backend http://production-server:8000 What is Wi-Fi 6E?
```

## Features

- 🔄 **Spinner Animation**: Shows progress while waiting for API response
- 📊 **Structured Output**: Clean, formatted display of answers and sources
- 🎯 **Default User**: Defaults to user_id=1 for quick queries
- 📚 **Source Citations**: Shows up to 10 most relevant documents
- 🔍 **Verbose Mode**: Optional filter details for debugging
- ⚙️ **Configurable**: Customize backend URL and user ID

## Output Format

```
🔍 Question: What are the latest Wi-Fi Alliance updates?
👤 User ID: 1

[Spinner appears here while processing...]

================================================================================
💬 ANSWER
================================================================================

[Generated answer based on knowledge graph documents]

================================================================================
📄 SOURCES (15 documents retrieved)
================================================================================

[1] Wi-Fi Alliance Announces New Certification Program
    📅 2025-11-15
    🔗 https://...
    🏷️  Wi-Fi 6, Certification, Standards

[2] Latest Wi-Fi Technology Updates
    📅 2025-11-10
    🔗 https://...

... and 13 more documents

================================================================================
✅ Query complete
================================================================================
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--user-id` | User ID for preference loading | 1 |
| `--backend` | Backend API URL | http://localhost:8000 |
| `-v, --verbose` | Show detailed filter information | Off |

## Examples

### Ask about recent updates
```bash
./aurora What happened this week?
```

### Query specific organization
```bash
./aurora What are the latest IEEE standards?
```

### Ask about technology
```bash
./aurora Tell me about Wi-Fi 6 and Wi-Fi 6E
```

### With user preferences
```bash
# User 2 might have different preferences that influence results
./aurora --user-id 2 What's new in wireless?
```

## Troubleshooting

### Backend not responding
```bash
# Check if backend is running
curl http://localhost:8000/health

# Start backend if needed
cd ../backend && make run
```

### Permission denied
```bash
chmod +x aurora
```

### Module not found
```bash
pip install -r requirements.txt
```

## Integration

The CLI can be used in scripts:

```bash
#!/bin/bash
# daily-update.sh

echo "Getting daily wireless industry updates..."
./aurora --user-id 1 What happened today in wireless communications? > daily-report.txt
```

Or in automation:

```bash
# Cron job: daily at 9 AM
0 9 * * * /path/to/aurora "What are today's updates?" | mail -s "Daily Aurora Report" user@example.com
```
