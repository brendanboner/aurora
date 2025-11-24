# Aurora Retriever Service

The Retriever service is responsible for fetching content from various sources and feeding it into the Aurora knowledge graph pipeline.

## Features

### 1. Scheduled Scraping
- **Automatic Daily Scrapes**: Runs all configured scrapers daily at a scheduled time (default: 2 AM)
- **Startup Scrape**: Performs an initial scrape when the service starts
- **Extensible**: Easily add new scrapers to the registry
- **Non-blocking**: All scrapers run concurrently using asyncio

### 2. On-Demand API
The service provides REST endpoints for immediate document processing:

- **Submit URL**: Fetch and process a webpage or document from a URL
- **Submit Content**: Process raw text content directly
- **Submit File**: Upload and process text files
- **Manual Trigger**: Trigger scrapers manually via API

### 3. Concurrent Execution
- Scheduled scrapes and API requests run concurrently without blocking
- Multiple API requests can be processed simultaneously
- Scraping operations don't interfere with API responsiveness

### Current Scrapers
- **Wi-Fi Alliance (WFA)**: Scrapes articles, white papers, and technical documents

## API Endpoints

### Health & Status

#### `GET /`
Root endpoint with service information.

```json
{
  "service": "Aurora Retriever",
  "version": "1.0.0",
  "description": "Scheduled scraping and on-demand document processing"
}
```

#### `GET /health`
Health check endpoint for container orchestration.

```json
{
  "status": "healthy"
}
```

#### `GET /status`
Get current status of the retriever service.

```json
{
  "scheduler_running": true,
  "next_scheduled_scrape": "2025-11-22 02:00:00",
  "active_scrapes": 0,
  "total_scrapes_today": 1,
  "registered_scrapers": ["wfa"]
}
```

### Document Submission

#### `POST /submit/url`
Submit a URL for immediate processing.

**Request Body:**
```json
{
  "url": "https://example.com/document.pdf",
  "title": "Optional Document Title",
  "category": "user_submitted",
  "datasource_id": "api_submission"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "URL processed successfully: Document Title",
  "resource_id": "https://example.com/document.pdf"
}
```

#### `POST /submit/content`
Submit raw text content for immediate processing.

**Request Body:**
```json
{
  "content": "Your document text here...",
  "title": "Document Title",
  "category": "user_submitted",
  "datasource_id": "api_submission",
  "url": "optional-identifier"
}
```

#### `POST /submit/file`
Upload and process a text file.

**Form Data:**
- `file`: The file to upload
- `title`: Optional title (defaults to filename)
- `category`: Optional category (default: "user_submitted")
- `datasource_id`: Optional source ID (default: "api_submission")

**Example with curl:**
```bash
curl -X POST "http://localhost:8000/submit/file" \
  -F "file=@document.txt" \
  -F "title=My Document" \
  -F "category=research"
```

### Manual Scraper Control

#### `POST /scrape/trigger/{scraper_name}?full_scrape=false`
Manually trigger a scraper.

**Parameters:**
- `scraper_name`: Name of scraper (e.g., "wfa")
- `full_scrape`: `true` for full scrape, `false` for daily scrape (default: false)

**Example:**
```bash
curl -X POST "http://localhost:8000/scrape/trigger/wfa?full_scrape=false"
```

## Configuration

Configuration is managed through environment variables (see `settings.py`):

```env
# RabbitMQ Configuration
RABBITMQ_HOST=aurora-rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=user
RABBITMQ_PASSWORD=password
RABBITMQ_QUEUE=scraped_content

# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Scheduler Configuration
SCRAPE_SCHEDULE_HOUR=2    # Hour to run daily scrape (0-23)
SCRAPE_SCHEDULE_MINUTE=0  # Minute to run daily scrape (0-59)

# Scraper Configuration
SCRAPER_DELAY=0.5         # Delay between requests in seconds

# Logging
LOG_LEVEL=INFO
```

## Adding New Scrapers

To add a new scraper:

1. Create a new scraper class in `scrapers/` that inherits from `BaseScraper`
2. Implement the required methods:
   - `run_scraper()`: Daily scrape logic
   - `run_full_scraper()`: Full scrape logic  
   - `scrape_resource()`: Individual resource scraping

3. Register it in `retriever.py`:

```python
from scrapers.YourScraper import YourScraper

SCRAPER_REGISTRY = {
    "wfa": WFAScraper,
    "yourscraper": YourScraper,  # Add your scraper here
}
```

The scheduler will automatically include it in daily scrapes!

## Architecture

### Concurrent Design

The service uses Python's `asyncio` for concurrent execution:

```
┌─────────────────────────────────────────┐
│        Retriever Service                │
│                                         │
│  ┌─────────────┐    ┌───────────────┐ │
│  │  Scheduler  │    │   API Server  │ │
│  │  (asyncio)  │    │   (FastAPI)   │ │
│  └──────┬──────┘    └───────┬───────┘ │
│         │                   │         │
│         ├───Concurrent──────┤         │
│         │                   │         │
│    ┌────▼────┐         ┌────▼────┐   │
│    │ Scraper │         │ Process │   │
│    │  Tasks  │         │  API    │   │
│    │         │         │ Requests│   │
│    └────┬────┘         └────┬────┘   │
│         │                   │         │
│         └────────┬──────────┘         │
│                  ▼                    │
│         ┌────────────────┐            │
│         │   RabbitMQ     │            │
│         │   Publisher    │            │
│         └────────────────┘            │
└─────────────────────────────────────────┘
```

### Message Flow

1. **Scheduled Path**: 
   - Scheduler triggers at configured time
   - All scrapers run concurrently
   - Resources published to RabbitMQ

2. **API Path**:
   - API receives URL/content request
   - Processes immediately in async task
   - Published to RabbitMQ
   - Returns response to client

Both paths use the same `Resource` model and publishing mechanism, ensuring consistency.

## Running the Service

### Standalone (Development)

```bash
cd retriever
pip install -r requirements.txt
python retriever.py
```

### Docker

```bash
docker build -t aurora-retriever .
docker run -p 8000:8000 aurora-retriever
```

### Docker Compose

The service is part of the Aurora stack and will be started with:

```bash
docker-compose up retriever
```

## Testing

### Test URL Submission

```bash
curl -X POST "http://localhost:8000/submit/url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.wi-fi.org/discover-wi-fi/wi-fi-certified-7",
    "title": "WiFi 7 Overview"
  }'
```

### Test Content Submission

```bash
curl -X POST "http://localhost:8000/submit/content" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "WiFi 7 introduces new features...",
    "title": "WiFi 7 Notes"
  }'
```

### Test File Upload

```bash
curl -X POST "http://localhost:8000/submit/file" \
  -F "file=@test_documents/test_wifi_paper.md" \
  -F "title=WiFi Test Paper"
```

### Check Status

```bash
curl http://localhost:8000/status
```

### Trigger Manual Scrape

```bash
# Daily scrape
curl -X POST "http://localhost:8000/scrape/trigger/wfa"

# Full scrape
curl -X POST "http://localhost:8000/scrape/trigger/wfa?full_scrape=true"
```

## Message Format

Resources are published to RabbitMQ as JSON messages with the following structure:

```json
{
  "title": "Wi-Fi CERTIFIED 7: Next Evolution of Wi-Fi",
  "url": "https://www.wi-fi.org/news-events/newsroom/wi-fi-certified-7",
  "category": "article",
  "content": "Full extracted text content from the webpage or PDF...",
  "publish_date": "2024-01-15",
  "datasource_id": "wfa",
  "scraped_at": 1699123456.789
}
```

## Monitoring

The service integrates with the Aurora monitoring system via Redis. Metrics include:
- Active scraping tasks
- Scrapes completed per day
- Scheduler status
- API request counts

Check the `/status` endpoint for real-time service status.

## Troubleshooting

**Scheduler not running:**
- Check logs for startup errors
- Verify asyncio event loop is running
- Check `/status` endpoint

**API requests timing out:**
- Check RabbitMQ connectivity
- Verify scrapers can fetch URLs
- Check network/firewall settings

**Documents not appearing in pipeline:**
- Verify RabbitMQ connection and queue name
- Monitor digester service logs
- Check RabbitMQ management UI (port 15672)

## Migration from Old API

The old `api.py` has been replaced with `retriever.py`. Key improvements:

| Old API | New Retriever |
|---------|---------------|
| Single scrape trigger | Automatic scheduling + manual trigger |
| Only WFA scraper | Extensible scraper registry |
| Background tasks dict | Proper asyncio task management |
| No on-demand processing | Full API for URLs/content/files |
| Startup scrape only | Scheduled daily scrapes |

The new service is a drop-in replacement with enhanced functionality.
