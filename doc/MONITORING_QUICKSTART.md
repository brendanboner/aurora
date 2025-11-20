# Monitoring System Quick Start

## Starting the System

1. **Bring up all services including Redis**:
   ```bash
   docker-compose up -d
   ```

2. **Verify all services are healthy**:
   ```bash
   docker ps --format "table {{.Names}}\t{{.Status}}"
   ```
   
   You should see:
   - aurora-redis (healthy)
   - aurora-rabbitmq (healthy)
   - aurora-neo4j (healthy)
   - aurora-postgres (healthy)
   - aurora-backend (healthy)
   - aurora-retriever (healthy)
   - aurora-digester (healthy)
   - aurora-frontend (healthy)

3. **Check Redis connection**:
   ```bash
   docker exec -it aurora-redis redis-cli ping
   # Should return: PONG
   ```

4. **Access the monitoring dashboard**:
   - Open browser to: http://localhost:3000
   - Navigate to Admin → Monitoring tab

## Triggering Document Processing

To see the monitoring system in action:

1. **Trigger a scraping job via API**:
   ```bash
   curl -X POST http://localhost:8001/scrape \
     -H "Content-Type: application/json" \
     -d '{"scraper_type": "wfa", "full_scrape": false}'
   ```

2. **Watch the monitoring dashboard**:
   - Retriever status will show "active" with current document
   - Queue will populate with scraped documents
   - Digester will process documents from the queue
   - Recent activity will show completed/failed documents

## Monitoring Commands

### Check Redis data directly

**View heartbeats**:
```bash
docker exec -it aurora-redis redis-cli
> GET retriever:heartbeat
> GET digester:heartbeat
> TTL retriever:heartbeat
```

**View current processing**:
```bash
docker exec -it aurora-redis redis-cli
> GET retriever:current
> GET digester:current
```

**View recent activity**:
```bash
docker exec -it aurora-redis redis-cli
> LRANGE processing:completed 0 9
> LRANGE processing:failed 0 9
```

### Check RabbitMQ queue

**Via Management UI**:
- Open: http://localhost:15672
- Login: user / password (from .env)
- Go to Queues tab
- Click on "scraped_content" queue

**Via CLI**:
```bash
docker exec -it aurora-rabbitmq rabbitmqctl list_queues name messages consumers
```

### Check Docker health

```bash
# All containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Specific service
docker inspect --format='{{.State.Health.Status}}' aurora-digester
docker inspect --format='{{.State.Health.Status}}' aurora-retriever
```

### Check service logs

```bash
# Retriever logs
docker logs -f aurora-retriever

# Digester logs
docker logs -f aurora-digester

# Backend logs (for monitoring API)
docker logs -f aurora-backend

# Redis logs
docker logs -f aurora-redis
```

## Testing the Monitoring System

### Test 1: Service Heartbeat Tracking

1. Start the digester: `docker start aurora-digester`
2. Wait 10 seconds
3. Check monitoring dashboard - digester should show "active"
4. Stop the digester: `docker stop aurora-digester`
5. Wait 70 seconds (longer than 60s heartbeat threshold)
6. Check monitoring dashboard - digester should show "inactive"

### Test 2: Docker Health Status

1. Check current health: 
   ```bash
   docker inspect --format='{{.State.Health.Status}}' aurora-digester
   ```
2. View in monitoring dashboard
3. Health status colors should match:
   - Green = healthy
   - Yellow = starting
   - Red = unhealthy
   - Gray = stopped

### Test 3: Queue Monitoring

1. Load test messages:
   ```bash
   # Add messages to queue
   cd digester/test_queue
   docker build -t test-queue-loader .
   docker run --rm --network aurora-network \
     -e RABBITMQ_HOST=rabbitmq \
     -e RABBITMQ_USER=user \
     -e RABBITMQ_PASSWORD=password \
     test-queue-loader
   ```

2. Check monitoring dashboard
3. Queue section should show:
   - Message count
   - List of documents in queue

### Test 4: Processing Status

1. Trigger a scrape job (see above)
2. Watch the monitoring dashboard update in real-time
3. Verify:
   - Retriever "current" shows document being scraped
   - Queue populates with documents
   - Digester "current" shows document being processed
   - Completed documents appear in recent activity

## Troubleshooting

### Redis not connecting

```bash
# Check if Redis is running
docker ps | grep redis

# Check Redis logs
docker logs aurora-redis

# Test connection
docker exec -it aurora-redis redis-cli ping

# Restart Redis
docker restart aurora-redis
```

### Services showing as inactive despite running

1. Check if services can reach Redis:
   ```bash
   docker exec -it aurora-digester sh -c 'ping -c 1 redis'
   ```

2. Check service logs for Redis connection errors:
   ```bash
   docker logs aurora-digester 2>&1 | grep -i redis
   ```

3. Verify environment variables:
   ```bash
   docker inspect aurora-digester | grep -A 5 Env
   ```

### Monitoring dashboard not updating

1. Check backend API is accessible:
   ```bash
   curl http://localhost:8000/admin/dashboard
   ```

2. Check browser console for errors (F12)

3. Verify backend can reach Redis:
   ```bash
   docker logs aurora-backend 2>&1 | grep -i redis
   ```

### Queue not showing resources

1. Check RabbitMQ is accessible:
   ```bash
   curl -u user:password http://localhost:15672/api/queues/%2F/scraped_content
   ```

2. Check if queue exists:
   ```bash
   docker exec -it aurora-rabbitmq rabbitmqctl list_queues
   ```

3. Check backend environment variables:
   ```bash
   docker inspect aurora-backend | grep RABBITMQ
   ```

## API Testing

### Test monitoring endpoints directly

**Queue status**:
```bash
curl http://localhost:8000/admin/queue-status | jq
```

**Processing status**:
```bash
curl http://localhost:8000/admin/processing-status | jq
```

**Full dashboard**:
```bash
curl http://localhost:8000/admin/dashboard | jq
```

### Watch real-time updates

```bash
# Poll dashboard every 5 seconds
watch -n 5 'curl -s http://localhost:8000/admin/dashboard | jq ".processing_status.digester_current"'
```

## Performance Notes

- Frontend polls every 5 seconds (configurable in AdminMonitoring.jsx)
- Queue inspection limited to first 50 messages
- Recent activity limited to last 20 items per list
- Heartbeat threshold is 60 seconds
- All operations are non-blocking and fail gracefully

## Clean Shutdown

```bash
# Stop all services gracefully
docker-compose down

# Stop and remove volumes (clears Redis data)
docker-compose down -v
```

## Monitoring System Health Checklist

Before considering the system healthy:

- [ ] All Docker containers show "healthy" status
- [ ] Redis responding to PING
- [ ] RabbitMQ management UI accessible
- [ ] Backend API `/health` endpoint returns 200
- [ ] Frontend accessible at http://localhost:3000
- [ ] Monitoring dashboard loads without errors
- [ ] Retriever and digester show Docker health status
- [ ] Queue status visible in dashboard
- [ ] Can trigger a scrape and see it in monitoring
