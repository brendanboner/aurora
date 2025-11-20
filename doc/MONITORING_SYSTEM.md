# Document Processing Monitoring System

## Overview

This document describes the comprehensive monitoring system implemented for tracking the document processing pipeline in the Aurora application. The system provides real-time visibility into the retriever, digester, RabbitMQ queue, and document processing status.

## Architecture

### Components

1. **Redis** - Central state tracking and heartbeat management
2. **Docker Health Checks** - Container-level health monitoring
3. **RabbitMQ Queue Inspection** - Non-destructive message queue monitoring
4. **Backend Admin API** - Aggregates monitoring data and provides REST endpoints
5. **Frontend Monitoring Dashboard** - Real-time UI displaying system status

### Data Flow

```
┌─────────────┐     Heartbeat/Status     ┌───────────┐
│  Retriever  │ ──────────────────────> │   Redis   │
└─────────────┘                          │           │
                                         │  - Tracks │
┌─────────────┐     Heartbeat/Status     │    active │
│  Digester   │ ──────────────────────> │    status │
└─────────────┘                          │  - Current│
                                         │    docs   │
                                         │  - Recent │
       ┌─────────────────────────────────┤    history│
       │                                 └───────────┘
       │                                       ▲
       │                                       │
       ▼                                       │
┌────────────┐                          ┌───────────┐
│  RabbitMQ  │ ◀──── Queue Inspection ──│  Backend  │
│   Queue    │                          │   Admin   │
└────────────┘                          │    API    │
                                        └───────────┘
       ▲                                       │
       │ Docker Health                         │
       │ Check (subprocess)                    │
       │                                       │
       │                                       ▼
┌─────────────┐                         ┌───────────┐
│   Docker    │                         │ Frontend  │
│ Containers  │                         │Monitoring │
└─────────────┘                         │    Page   │
                                        └───────────┘
```

## Implementation Details

### 1. Redis Tracking

**Purpose**: Track service heartbeats, current processing status, and document history.

**Keys Used**:
- `retriever:heartbeat` - Timestamp of last retriever activity
- `digester:heartbeat` - Timestamp of last digester activity
- `retriever:current` - JSON object of currently processing document in retriever
- `digester:current` - JSON object of currently processing document in digester
- `processing:completed` - List of last 20 successfully processed documents
- `processing:failed` - List of last 20 failed documents

**Data Structure**:
```json
{
  "title": "Document Title",
  "url": "https://example.com/doc",
  "category": "white paper",
  "status": "processing",
  "stage": "extracting metadata",
  "started_at": "2025-11-20T10:30:00",
  "updated_at": "2025-11-20T10:30:15",
  "error": "Optional error message"
}
```

### 2. Digester Instrumentation

**Location**: `/digester/main.py`

**Key Changes**:
- Added Redis client initialization in `__init__`
- Implemented heartbeat updates every message processing cycle
- Tracks current processing status with stage information
- Records completed/failed documents to Redis lists
- Gracefully handles Redis connection failures

**Tracking Points**:
1. Start of message processing - update heartbeat
2. Each pipeline stage - update current processing status
3. Success - record to completed list
4. Failure - record to failed list with error message

### 3. Retriever Instrumentation

**Location**: `/retriever/scrapers/base.py` and `/retriever/scrapers/WFA.py`

**Key Changes**:
- Added Redis client to base scraper class
- Implemented heartbeat updates during scraping
- Tracks current resource being scraped
- Updates stage information (scraping, publishing to queue)

**Tracking Points**:
1. Start of resource scraping - update heartbeat and current status
2. Publishing to queue - update stage
3. Completion - clear current status

### 4. Backend Admin API

**Location**: `/backend/src/routes/admin.py`

**New Features**:

#### Docker Health Checking
```python
def get_docker_container_health(container_name: str) -> ServiceHealth
```
- Uses `docker inspect` to check container status
- Returns health status: healthy, unhealthy, starting, stopped, not_found
- Handles Docker unavailability gracefully

#### Enhanced Queue Inspection
- Non-destructive message peeking (uses `basic_get` + `basic_nack`)
- Properly requeues all peeked messages in reverse order
- Limits to first 50 messages for performance
- Handles queue inspection errors gracefully

#### Processing Status Endpoint
**GET** `/admin/processing-status`

Returns:
- Service activity status (based on heartbeat age)
- Docker health status for both services
- Current processing documents (if any)
- Last 10 completed documents
- Last 10 failed documents

#### Dashboard Endpoint
**GET** `/admin/dashboard`

Aggregates:
- Queue status (message count, resources in queue)
- Processing status (service health, current/recent activity)

### 5. Frontend Monitoring Dashboard

**Location**: `/frontend/src/pages/AdminMonitoring.jsx`

**Features**:
- Real-time updates every 5 seconds
- Service status cards showing:
  - Active/Inactive status (heartbeat-based)
  - Docker health status with color coding
  - Currently processing document
  - Processing stage
- Queue status showing:
  - Queue name, message count, consumer count
  - List of resources in queue with details
- Recent activity columns:
  - Recently completed documents
  - Recently failed documents with error messages

**Visual Indicators**:
- Green (healthy) - Service running and healthy
- Yellow (starting) - Service starting up
- Red (unhealthy) - Service has health issues
- Gray (stopped/inactive) - Service not running or no heartbeat

### 6. Docker Compose Configuration

**New Service**:
```yaml
redis:
  image: redis:7-alpine
  container_name: aurora-redis
  ports:
    - "6379:6379"
  volumes:
    - redis-data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
```

**Environment Variables Added**:
- `REDIS_HOST` - Redis hostname
- `REDIS_PORT` - Redis port

All application services now depend on Redis being healthy.

## Configuration

### Environment Variables

All services use these Redis configuration variables:
- `REDIS_HOST` (default: "redis")
- `REDIS_PORT` (default: 6379)

### Heartbeat Settings

Services are considered "active" if their heartbeat was updated within the last 60 seconds. This threshold is defined in `/backend/src/routes/admin.py`.

### History Limits

- Completed documents: Last 20 retained
- Failed documents: Last 20 retained
- Queue inspection: First 50 messages shown

## Best Practices Implemented

1. **Non-destructive Queue Monitoring**
   - Messages are peeked but immediately requeued
   - Order preservation using reverse requeue

2. **Graceful Degradation**
   - Redis unavailable → monitoring disabled but services continue
   - Docker unavailable → health checks return "unknown" status
   - RabbitMQ unavailable → empty queue status returned

3. **Performance Optimization**
   - Heartbeat updates use simple SET operations
   - List trimming prevents unbounded growth
   - Queue inspection limited to first 50 messages
   - Redis connections use connection timeout

4. **Real-time Updates**
   - Frontend polls every 5 seconds
   - Heartbeat age checked on each request
   - No polling loops in backend (stateless)

5. **Error Handling**
   - All Redis operations wrapped in try-catch
   - Warnings logged but don't stop processing
   - Services continue working even if monitoring fails

## Usage

### Accessing the Monitoring Dashboard

1. Navigate to the Admin section in the Aurora frontend
2. Click on the "Monitoring" tab
3. Dashboard auto-refreshes every 5 seconds

### Interpreting Service Status

**Active + Healthy**: Service is running normally
- Heartbeat recent (< 60 seconds)
- Docker health check passing
- Processing documents as expected

**Active + Unhealthy**: Service running but has issues
- Heartbeat recent but Docker health failing
- May need investigation

**Inactive**: Service not processing
- No recent heartbeat
- May be stopped or idle

**Docker Status**:
- `healthy` - Container health check passing
- `unhealthy` - Container health check failing
- `starting` - Container starting up
- `stopped` - Container not running
- `not_found` - Container doesn't exist

### Troubleshooting

**No data showing**:
1. Check if Redis is running: `docker ps | grep redis`
2. Check backend logs: `docker logs aurora-backend`
3. Verify backend can reach Redis: Check environment variables

**Services showing as inactive**:
1. Check if services are actually processing documents
2. Verify Redis connection in service logs
3. Check if services are configured with correct Redis host

**Queue not showing resources**:
1. Verify RabbitMQ is accessible from backend
2. Check queue name matches configuration
3. Look for errors in backend logs

## Monitoring API Reference

### GET /admin/queue-status

Returns current RabbitMQ queue status.

**Response**:
```json
{
  "queue_name": "scraped_content",
  "message_count": 15,
  "consumer_count": 4,
  "resources": [
    {
      "title": "Wi-Fi 7 Whitepaper",
      "url": "https://...",
      "category": "white paper",
      "publish_date": "2025-11-15",
      "scraped_at": 1732098000,
      "position": 1
    }
  ]
}
```

### GET /admin/processing-status

Returns current processing status and service health.

**Response**:
```json
{
  "retriever_active": true,
  "digester_active": true,
  "retriever_health": {
    "container_name": "aurora-retriever",
    "status": "healthy",
    "health_status": "healthy"
  },
  "digester_health": {
    "container_name": "aurora-digester",
    "status": "healthy",
    "health_status": "healthy"
  },
  "retriever_current": {
    "title": "Current Document",
    "url": "https://...",
    "category": "article",
    "status": "retrieving",
    "stage": "scraping",
    "started_at": "2025-11-20T10:30:00",
    "updated_at": "2025-11-20T10:30:15"
  },
  "digester_current": null,
  "recent_completed": [...],
  "recent_failed": [...]
}
```

### GET /admin/dashboard

Returns complete dashboard data combining queue and processing status.

**Response**: Combination of queue-status and processing-status responses.

## Future Enhancements

Potential improvements to consider:

1. **Metrics Collection**
   - Processing time tracking
   - Success/failure rates
   - Throughput metrics

2. **Alerting**
   - Email/Slack notifications for failures
   - Service down alerts
   - Queue depth thresholds

3. **Historical Data**
   - Time-series metrics storage
   - Trend analysis
   - Performance graphs

4. **Extended Monitoring**
   - Neo4j database metrics
   - PostgreSQL query performance
   - LLM API latency tracking

5. **Auto-Recovery**
   - Automatic service restarts
   - Dead letter queue processing
   - Retry mechanisms

## Summary

This monitoring system provides comprehensive visibility into the document processing pipeline with minimal performance overhead. It's designed to be resilient, degrading gracefully when components are unavailable, while providing actionable real-time information about system health and processing status.
