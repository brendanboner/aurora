# Aurora Retriever Service

The Retriever service is responsible for fetching content from various sources and feeding it into the Aurora knowledge graph pipeline.

## Features

### 1. Database-Driven Scheduling
- **Cron-Based Schedules**: Each datasource has its own cron schedule stored in PostgreSQL (`system_configuration` table)
- **Startup Datasources**: Datasources with `run_on_startup=true` are scraped when the service starts
- **Scheduled Datasources**: The scheduler polls every 60 seconds for datasources whose cron schedule is due
- **Missed Window Detection**: Automatically catches and runs missed scheduled scrapes
- **Extensible**: Easily add new scrapers to the registry

### 2. On-Demand API
The service provides REST endpoints for document processing:

- **Manual Trigger (Single)**: Trigger a specific datasource scrape via API
- **Manual Trigger (All)**: Trigger all configured datasources at once
- **Submit URL/Content/File**: Endpoints defined but not yet implemented

### 3. Concurrent Execution
- Scheduled scrapes and API requests run concurrently without blocking
- Datasources are grouped by `scraper_type` for session reuse (e.g., single authentication for multiple Causeway datasources)
- Multiple API requests can be processed simultaneously

### Current Scrapers
- **Wi-Fi Alliance Public (wfa)**: Scrapes articles, white papers, and technical documents from the public WFA website
- **Wi-Fi Alliance Causeway (wfa_causeway)**: Scrapes documents from the internal WFA Causeway portal (requires member authentication via SAML SSO)

### Authentication Support
The retriever supports scrapers that require authentication:

**Supported authentication methods:**
- Form-based login with SAML SSO (Causeway portal)
- Session cookie management
- Automatic re-authentication on session expiry

**Example Scrapers:**
- `scrapers/WFA.py` - Public website scraper (no authentication)
- `scrapers/WFA_causeway.py` - Authenticated portal scraper with SAML SSO

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
Get current status of the retriever service including all datasource schedules.

```json
{
  "scheduler_running": true,
  "poll_interval_seconds": 60,
  "active_scrapes": 0,
  "total_scrapes_today": 1,
  "available_scraper_types": ["wfa", "wfa_causeway"],
  "active_scraper_types": ["wfa_causeway"],
  "total_datasources": 3,
  "datasource_schedules": [
    {
      "datasource_id": "wfa_causeway_wifi7mtg",
      "name": "WFA Causeway - WiFi 7 MTG",
      "schedule": "0 2 * * *",
      "run_on_startup": true,
      "last_scraped_at": "2025-12-01T02:00:00"
    }
  ]
}
```

### Manual Scraper Control

#### `POST /scrape/datasource/{datasource_id}`
Manually trigger a scrape for a single datasource.

**Parameters:**
- `datasource_id`: The datasource identifier (e.g., `wfa_causeway_wifi7mtg`)

**Example:**
```bash
curl -X POST "http://localhost:8000/scrape/datasource/wfa_causeway_wifi7mtg"
```

**Response:**
```json
{
  "status": "started",
  "message": "Scrape started for WFA Causeway - WiFi 7 MTG",
  "datasource_id": "wfa_causeway_wifi7mtg",
  "datasource_name": "WFA Causeway - WiFi 7 MTG",
  "scraper_type": "wfa_causeway"
}
```

#### `POST /scrape/all`
Manually trigger a scrape for all configured datasources. Datasources are grouped by `scraper_type` to allow session reuse (e.g., single Causeway authentication for all Causeway datasources).

**Example:**
```bash
curl -X POST "http://localhost:8000/scrape/all"
```

**Response:**
```json
{
  "status": "started",
  "message": "Scrape started for 3 datasource(s) across 2 scraper type(s)",
  "started": [
    {
      "scraper_type": "wfa_causeway",
      "datasources": [
        {"datasource_id": "wfa_causeway_wifi7mtg", "name": "WFA Causeway - WiFi 7 MTG"},
        {"datasource_id": "wfa_causeway_hotspot", "name": "WFA Causeway - Hotspot"}
      ]
    }
  ],
  "skipped": []
}
```

### Document Submission (Not Yet Implemented)

The following endpoints are defined but return `not_implemented` status:

#### `POST /submit/url`
Submit a URL for immediate processing.

#### `POST /submit/content`
Submit raw text content for immediate processing.

#### `POST /submit/file`
Upload and process a file.

## Configuration

### Environment Variables (settings.py)

```env
# RabbitMQ Configuration
RABBITMQ_HOST=aurora-rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=user
RABBITMQ_PASSWORD=password
RABBITMQ_QUEUE=scraped_content

# Redis Configuration (for monitoring)
REDIS_HOST=redis
REDIS_PORT=6379

# Neo4j Configuration (for URL deduplication)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

# PostgreSQL Configuration (for datasource configuration)
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=aurora
POSTGRES_PASSWORD=aurora_password
POSTGRES_DB=aurora

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000

# Scheduler Configuration
SCHEDULER_POLL_INTERVAL=60  # Seconds between checking for due datasources

# WFA Causeway Authentication
WFA_CAUSEWAY_USERNAME=your_username
WFA_CAUSEWAY_PASSWORD=your_password

# Logging
LOG_LEVEL=INFO
```

### Database Configuration (system_configuration table)

Datasource configuration is stored in PostgreSQL. Each datasource has:

| Column | Description |
|--------|-------------|
| `datasource_id` | Unique identifier (e.g., `wfa_causeway_wifi7mtg`) |
| `name` | Human-readable name |
| `scraper_type` | Scraper class to use (`wfa`, `wfa_causeway`) |
| `resource_url` | URL path to scrape |
| `scrape_schedule` | Cron expression (e.g., `0 2 * * *` for 2 AM daily) |
| `run_on_startup` | Whether to scrape when service starts |
| `folders` | JSONB array of folder paths to scrape (Causeway only) |
| `max_resources` | Maximum resources per scrape (-1 = unlimited) |
| `scraper_delay` | Delay between requests in seconds |
| `last_scraped_at` | Timestamp of last successful scrape |

## Adding New Scrapers

To add a new scraper:

1. Create a new scraper class in `scrapers/` that inherits from `BaseScraper`
2. Implement the required methods:
   - `run_scraper(datasource_config)`: Scrape logic receiving datasource config from database
   - `scrape_resource(resource)`: Individual resource scraping

3. Register it in `retriever.py`:

```python
from scrapers.YourScraper import YourScraper

SCRAPER_CLASSES: Dict[str, Type[BaseScraper]] = {
    "wfa": WFAScraper,
    "wfa_causeway": WFACausewayScraper,
    "yourscraper": YourScraper,  # Add your scraper here
}
```

4. Export it in `scrapers/__init__.py`:

```python
from .YourScraper import YourScraper

__all__ = [
    'BaseScraper',
    'WFAScraper',
    'WFACausewayScraper',
    'YourScraper',
]
```

5. Add datasource configuration to the `system_configuration` table in PostgreSQL with `scraper_type` matching your registry key.

## Architecture

### Scheduler Flow

The service uses a polling-based scheduler that checks for due datasources:

```
┌─────────────────────────────────────────────────────────┐
│                  Retriever Service                       │
│                                                         │
│  ┌──────────────────┐    ┌─────────────────────────┐   │
│  │    Scheduler     │    │      API Server         │   │
│  │   (polls every   │    │      (FastAPI)          │   │
│  │    60 seconds)   │    │                         │   │
│  └────────┬─────────┘    └───────────┬─────────────┘   │
│           │                          │                  │
│           ▼                          │                  │
│  ┌──────────────────┐                │                  │
│  │   PostgreSQL     │◄───────────────┘                  │
│  │ (system_config)  │   (manual trigger)               │
│  └────────┬─────────┘                                   │
│           │                                             │
│           ▼                                             │
│  ┌──────────────────┐                                   │
│  │ Group datasources│                                   │
│  │ by scraper_type  │                                   │
│  └────────┬─────────┘                                   │
│           │                                             │
│           ▼                                             │
│  ┌──────────────────────────────────────┐              │
│  │    Per Scraper Type:                  │              │
│  │    1. Create single scraper instance  │              │
│  │    2. Authenticate once (if needed)   │              │
│  │    3. Process all datasources         │              │
│  └────────┬─────────────────────────────┘              │
│           │                                             │
│           ▼                                             │
│  ┌──────────────────┐    ┌──────────────────┐         │
│  │    RabbitMQ      │    │     Neo4j        │         │
│  │   (publish)      │    │ (deduplication)  │         │
│  └──────────────────┘    └──────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

### Scheduling Logic

1. **On Startup**: Run all datasources with `run_on_startup=true`
2. **Polling Loop** (every 60 seconds):
   - Query PostgreSQL for datasources with `scrape_schedule` set
   - For each datasource, check if cron schedule is due:
     - Parse cron expression to get previous scheduled time
     - Compare with `last_scraped_at`
     - If `prev_scheduled_time > last_scraped_at`, datasource is due
3. **Session Reuse**: Group due datasources by `scraper_type` to share authentication

### Message Flow

1. **Scheduled Path**: 
   - Scheduler polls and finds due datasources
   - Grouped by scraper_type for session reuse
   - Resources published to RabbitMQ

2. **API Path**:
   - API receives manual trigger request
   - Fetches datasource config from PostgreSQL
   - Runs scraper in background task
   - Published to RabbitMQ

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

### Check Status

```bash
curl http://localhost:8000/status
```

### Trigger Single Datasource Scrape

```bash
curl -X POST "http://localhost:8000/scrape/datasource/wfa_causeway_wifi7mtg"
```

### Trigger All Datasources

```bash
curl -X POST "http://localhost:8000/scrape/all"
```

## Message Format

Resources and events are published to RabbitMQ with the following structure:

```json
{
  "message_type": "resource",
  "resource_data": {
    "title": "Wi-Fi CERTIFIED 7: Next Evolution of Wi-Fi",
    "url": "https://www.wi-fi.org/news-events/newsroom/wi-fi-certified-7",
    "category": "article",
    "content": "Full extracted text content from the webpage or PDF...",
    "publish_date": "2024-01-15"
  },
  "datasource_id": "wfa_resource_page",
  "scraped_at": "2025-12-01T14:30:00"
}
```

```json
{
  "message_type": "event",
  "event_data": {
    "name": "Wi-Fi Alliance Member Meeting",
    "event_type": "meeting",
    "start_date": "2025-03-15",
    "end_date": "2025-03-17",
    "location": "San Francisco, CA",
    "timezone": "America/Los_Angeles",
    "description": "Quarterly member meeting...",
    "url": "https://groups.wi-fi.org/event/123",
    "status": "scheduled"
  },
  "datasource_id": "wfa_events",
  "scraped_at": "2025-12-01T14:30:00"
}
```

## Monitoring

The service integrates with the Aurora monitoring system via Redis. Metrics include:
- Active scraping tasks
- Scrapes completed per day
- Scheduler status
- Current processing status (which document is being scraped)
- Heartbeat timestamps

Check the `/status` endpoint for real-time service status.

## Key Dependencies

- **PostgreSQL**: Datasource configuration and scheduling (`system_configuration` table)
- **Neo4j**: URL deduplication (checks if resource already exists before scraping)
- **Redis**: Monitoring and heartbeat tracking
- **RabbitMQ**: Message publishing to downstream pipeline
- **croniter**: Cron expression parsing for schedule evaluation

## Troubleshooting

**Scheduler not running:**
- Check logs for startup errors
- Verify PostgreSQL connection (`POSTGRES_*` env vars)
- Check `/status` endpoint for `scheduler_running` status

**Datasource not being scraped:**
- Verify `scraper_type` is set in `system_configuration` table
- Check if `scraper_type` is registered in `SCRAPER_CLASSES` dict
- Verify cron schedule format is valid (use `croniter` to test)
- Check `last_scraped_at` vs schedule to see if it's due

**Causeway authentication failing:**
- Verify `WFA_CAUSEWAY_USERNAME` and `WFA_CAUSEWAY_PASSWORD` are set
- Check for credential expiration
- Review logs for SAML flow errors

**Documents not appearing in pipeline:**
- Verify RabbitMQ connection and queue name
- Check if URL already exists in Neo4j (deduplication)
- Monitor digester service logs
- Check RabbitMQ management UI (port 15672)

**Duplicate documents being processed:**
- Verify Neo4j connection for deduplication
- Check `url_hash` field in Resource nodes

## File Structure

```
retriever/
├── retriever.py          # Main service with FastAPI app and scheduler
├── config_manager.py     # PostgreSQL config and cron schedule management
├── settings.py           # Pydantic settings from environment variables
├── requirements.txt      # Python dependencies
├── Dockerfile
├── Makefile
├── README.md
└── scrapers/
    ├── __init__.py       # Exports all scrapers
    ├── base.py           # BaseScraper with RabbitMQ/Neo4j/Redis integration
    ├── WFA.py            # Public WFA website scraper
    └── WFA_causeway.py   # Authenticated WFA Causeway portal scraper
```
