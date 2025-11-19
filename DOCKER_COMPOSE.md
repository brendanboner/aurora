# Docker Compose Deployment Guide

This guide covers deploying the entire Octo Rapid Aurora stack using Docker Compose. This approach is complementary to the Makefile-based deployment and provides a unified way to run all services together.

## Overview

The Docker Compose setup orchestrates all services with:
- **Shared network** (`aurora-network`)
- **Persistent volumes** for data retention
- **Health checks** for proper startup sequencing
- **Environment variable** management via `.env` file

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Frontend (React + Nginx)                                    │
│  └─> http://localhost:3000                                   │
│                                                               │
│  Backend (FastAPI)                                           │
│  └─> http://localhost:8000                                   │
│      └─> /health, /docs, /api/*                             │
│                                                               │
│  Retriever (Web Scraper + API)                               │
│  └─> http://localhost:8001                                   │
│                                                               │
│  Digester (Message Consumer + LLM Processor)                 │
│  └─> Consumes from RabbitMQ queue                           │
│                                                               │
├─────────────────────────────────────────────────────────────┤
│                  Infrastructure Services                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  PostgreSQL (User Database)                                  │
│  └─> localhost:5432                                          │
│      Volume: postgres-data                                   │
│                                                               │
│  Neo4j (Knowledge Graph)                                     │
│  └─> localhost:7474 (HTTP), localhost:7687 (Bolt)           │
│      Volumes: neo4j-data, neo4j-logs                         │
│                                                               │
│  RabbitMQ (Message Queue)                                    │
│  └─> localhost:5672 (AMQP), localhost:15672 (Management)    │
│      Volume: rabbitmq-data                                   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Docker** (20.10+) and **Docker Compose** (2.0+)
2. **Azure OpenAI credentials** (API key and endpoint)
3. At least **8GB RAM** available for Docker
4. Ports **3000, 5432, 5672, 7474, 7687, 8000, 8001, 15672** available

## Quick Start

### 1. Configure Environment

```bash
# Copy the template
cp .env.docker .env

# Edit with your values
nano .env  # or vim, code, etc.
```

**Required changes:**
- `POSTGRES_PASSWORD` - Set a secure password
- `NEO4J_PASSWORD` - Set a secure password
- `RABBITMQ_PASSWORD` - Set a secure password
- `AZURE_OPENAI_API_KEY` - Your Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT` - Your Azure OpenAI endpoint URL
- `AZURE_OPENAI_DEPLOYMENT` - Your deployment name

### 2. Start All Services

```bash
# Start everything in detached mode
docker-compose up -d

# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f backend
```

### 3. Verify Services

```bash
# Check all services are running
docker-compose ps

# Test backend health
curl http://localhost:8000/health

# Access services:
# - Frontend: http://localhost:3000
# - Backend API: http://localhost:8000/docs
# - RabbitMQ Management: http://localhost:15672 (user/password from .env)
# - Neo4j Browser: http://localhost:7474 (neo4j/password from .env)
```

## Service Management

### Start/Stop Services

```bash
# Start all services
docker-compose up -d

# Stop all services (keeps data)
docker-compose stop

# Stop and remove containers (keeps data volumes)
docker-compose down

# Stop, remove containers AND volumes (destroys data)
docker-compose down -v
```

### Individual Service Control

```bash
# Restart a specific service
docker-compose restart backend

# View logs for a service
docker-compose logs -f digester

# Execute commands in a service
docker-compose exec backend bash
docker-compose exec postgres psql -U aurora -d aurora

# Rebuild a service after code changes
docker-compose build backend
docker-compose up -d backend
```

### Scaling Services

```bash
# Run multiple digester instances for parallel processing
docker-compose up -d --scale digester=3

# Note: Only digester can be scaled (stateless consumer)
```

## Data Persistence

All data is stored in Docker volumes:

```bash
# List volumes
docker volume ls | grep aurora

# Inspect a volume
docker volume inspect octo-rapid-aurora_postgres-data

# Backup volumes
docker run --rm -v octo-rapid-aurora_postgres-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres-backup.tar.gz -C /data .

# Restore volumes
docker run --rm -v octo-rapid-aurora_postgres-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/postgres-backup.tar.gz -C /data
```

## Development Workflow

### Making Code Changes

```bash
# 1. Make changes to code
# 2. Rebuild the affected service
docker-compose build backend

# 3. Restart the service
docker-compose up -d backend

# 4. Check logs
docker-compose logs -f backend
```

### Hot Reload (Development Mode)

For development with hot reload, use volume mounts:

```bash
# Edit docker-compose.override.yml
cat > docker-compose.override.yml <<EOF
version: "3.9"
services:
  backend:
    volumes:
      - ./backend:/app/backend
    command: uvicorn api:app --host 0.0.0.0 --port 8000 --reload
  
  frontend:
    volumes:
      - ./frontend/src:/app/src
    command: npm start
EOF

docker-compose up -d
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker-compose logs <service-name>

# Check if dependencies are healthy
docker-compose ps

# Restart dependencies
docker-compose restart postgres neo4j rabbitmq
```

### Database Connection Issues

```bash
# Check PostgreSQL is ready
docker-compose exec postgres pg_isready -U aurora

# Connect to PostgreSQL
docker-compose exec postgres psql -U aurora -d aurora

# Recreate database
docker-compose stop backend
docker-compose exec postgres psql -U aurora -d aurora -f /docker-entrypoint-initdb.d/01-schema.sql
docker-compose start backend
```

### Neo4j Connection Issues

```bash
# Check Neo4j health
docker-compose exec neo4j cypher-shell -u neo4j -p your_password "RETURN 1;"

# View Neo4j logs
docker-compose logs neo4j
```

### RabbitMQ Issues

```bash
# Check queue status
docker-compose exec rabbitmq rabbitmqctl list_queues

# View connections
docker-compose exec rabbitmq rabbitmqctl list_connections

# Purge queue
docker-compose exec rabbitmq rabbitmqctl purge_queue scraped_content
```

### Port Conflicts

If ports are already in use, modify `.env`:

```bash
# Change port mappings
FRONTEND_PORT=3001
BACKEND_PORT=8001
POSTGRES_PORT=5433
# etc...
```

Then restart:
```bash
docker-compose down
docker-compose up -d
```

## Integration with Makefile

The Docker Compose setup and Makefile approach can coexist:

```bash
# Use Docker Compose for full stack
docker-compose up -d

# Use Makefile for isolated service testing
cd digester
make deploy-isolated
```

**Note:** Isolated Makefile deployments use different ports to avoid conflicts.

## Production Considerations

### Security

1. **Change default passwords** in `.env`
2. **Use secrets management** (Docker secrets, vault, etc.)
3. **Enable TLS** for Neo4j and RabbitMQ
4. **Configure firewall** rules to restrict port access
5. **Run services as non-root** users

### Performance

1. **Adjust resource limits** in `docker-compose.yml`:
   ```yaml
   services:
     digester:
       deploy:
         resources:
           limits:
             cpus: '2'
             memory: 4G
   ```

2. **Scale workers**:
   ```bash
   docker-compose up -d --scale digester=5
   ```

3. **Monitor resources**:
   ```bash
   docker stats
   ```

### Monitoring

```bash
# View resource usage
docker-compose stats

# Export metrics (requires prometheus)
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

## Cleanup

```bash
# Stop and remove containers (keeps volumes)
docker-compose down

# Remove everything including volumes
docker-compose down -v

# Remove images as well
docker-compose down -v --rmi all

# Full cleanup including system cache
docker-compose down -v --rmi all
docker system prune -af --volumes
```

## Environment Variables Reference

See `.env.docker` for complete list. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_PASSWORD` | PostgreSQL password | aurora_password_change_me |
| `NEO4J_PASSWORD` | Neo4j password | your_neo4j_password_here |
| `RABBITMQ_PASSWORD` | RabbitMQ password | your_rabbitmq_password_here |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key | (required) |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint | (required) |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name | (required) |
| `LOG_LEVEL` | Logging level | INFO |
| `RABBITMQ_MAX_WORKERS` | Digester worker threads | 4 |

## Next Steps

1. **Access Frontend**: http://localhost:3000
2. **Create a user** via Admin page
3. **Set preferences** in Profile page
4. **Load test data** (optional):
   ```bash
   cd digester
   make load_shared_queue
   ```
5. **Start querying** in the Chatbot interface

## Support

- Check service logs: `docker-compose logs -f <service>`
- View health status: `docker-compose ps`
- Backend API docs: http://localhost:8000/docs
- RabbitMQ management: http://localhost:15672
- Neo4j browser: http://localhost:7474
