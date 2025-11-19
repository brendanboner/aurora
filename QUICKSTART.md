# 🚀 Aurora Quick Reference

## One-Command Start

```bash
./start.sh
```

## Manual Start

```bash
cp .env.docker .env        # First time only
# Edit .env with your credentials
docker-compose up -d        # Start all services
```

## Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| **Frontend** | http://localhost:3000 | Main web interface |
| **Backend API** | http://localhost:8000 | REST API endpoints |
| **API Docs** | http://localhost:8000/docs | Interactive API documentation |
| **RabbitMQ** | http://localhost:15672 | Message queue management |
| **Neo4j** | http://localhost:7474 | Knowledge graph browser |
| **Retriever** | http://localhost:8001 | Scraper API |

## Quick Commands

### Using Make (Recommended)
```bash
make help           # Show all commands
make up             # Start everything
make down           # Stop everything
make logs           # View all logs
make logs-backend   # View backend logs
make health         # Check service health
make ps             # List running services
make restart        # Restart all services
make clean          # Remove containers (keep data)
```

### Using Docker Compose
```bash
docker-compose up -d                 # Start
docker-compose down                  # Stop
docker-compose ps                    # Status
docker-compose logs -f               # Logs
docker-compose logs -f backend       # Service logs
docker-compose restart backend       # Restart service
docker-compose exec backend bash     # Shell access
```

## First Time Setup

1. **Copy environment file**
   ```bash
   cp .env.docker .env
   ```

2. **Edit .env with your values**
   - `POSTGRES_PASSWORD` - Database password
   - `NEO4J_PASSWORD` - Graph database password
   - `RABBITMQ_PASSWORD` - Message queue password
   - `AZURE_OPENAI_API_KEY` - Your Azure OpenAI key
   - `AZURE_OPENAI_ENDPOINT` - Your Azure endpoint URL
   - `AZURE_OPENAI_DEPLOYMENT` - Your deployment name

3. **Start services**
   ```bash
   docker-compose up -d
   ```

4. **Wait for services to be ready** (~30 seconds)
   ```bash
   docker-compose logs -f backend
   # Wait for "Application startup complete"
   ```

5. **Access frontend**
   ```bash
   open http://localhost:3000
   ```

## User Workflow

### 1. Create User
- Go to **Admin** page
- Enter email and display name
- Click "Create User"
- Click "Select" to make user active

### 2. Set Preferences
- Go to **Profile** page
- Select topics of interest
- Choose organizations to follow
- Pick people to track
- Save preferences

### 3. Query Knowledge
- Return to **Chatbot** page
- Type your question
- View documents and responses
- See applied filters

## Service Management

### View Logs
```bash
# All services
make logs

# Specific service
make logs-backend
make logs-digester
make logs-retriever
```

### Restart Service
```bash
# All services
make restart

# Specific service
make restart-backend
docker-compose restart digester
```

### Rebuild After Code Changes
```bash
# Rebuild specific service
make build-backend
docker-compose build frontend

# Rebuild and restart
docker-compose up -d --build backend
```

### Check Health
```bash
make health
curl http://localhost:8000/health
docker-compose ps
```

## Data Management

### Backup
```bash
# PostgreSQL
docker-compose exec postgres pg_dump -U aurora aurora > backup.sql

# All volumes
make backup
```

### View Volumes
```bash
docker volume ls | grep aurora
```

### Restore
```bash
# PostgreSQL
docker-compose exec -T postgres psql -U aurora aurora < backup.sql
```

## Troubleshooting

### Service Won't Start
```bash
# Check logs
docker-compose logs <service-name>

# Check status
docker-compose ps

# Restart
docker-compose restart <service-name>
```

### Database Issues
```bash
# PostgreSQL shell
make shell-postgres

# Neo4j shell
make shell-neo4j

# Check RabbitMQ queues
docker-compose exec rabbitmq rabbitmqctl list_queues
```

### Port Conflicts
Edit `.env` and change port mappings:
```
FRONTEND_PORT=3001
BACKEND_PORT=8001
```

### Reset Everything
```bash
# Stop and remove (keep data)
docker-compose down

# Stop and remove ALL data
docker-compose down -v

# Nuclear option
make nuke
```

## Development

### Hot Reload (Backend)
```bash
# Add to docker-compose.override.yml
cat > docker-compose.override.yml <<EOF
version: "3.9"
services:
  backend:
    volumes:
      - ./backend:/app/backend
    command: uvicorn api:app --host 0.0.0.0 --port 8000 --reload
EOF

docker-compose up -d backend
```

### Shell Access
```bash
make shell-backend    # Backend bash
make shell-postgres   # PostgreSQL psql
make shell-neo4j      # Neo4j cypher-shell
```

### Run Tests
```bash
# Backend
docker-compose exec backend pytest

# Frontend
docker-compose exec frontend npm test
```

## Alternative: Makefile Deployment

For individual service development:

### Isolated Mode
```bash
cd digester
make deploy-isolated  # Own infrastructure
```

### Shared Mode
```bash
cd retriever
make deploy-shared    # Uses shared infra
```

### Load Test Data
```bash
cd digester
make load_shared_queue
```

## Environment Variables

Required in `.env`:

| Variable | Example | Purpose |
|----------|---------|---------|
| `POSTGRES_PASSWORD` | `secure_password` | PostgreSQL auth |
| `NEO4J_PASSWORD` | `neo4j_password` | Neo4j auth |
| `RABBITMQ_PASSWORD` | `rabbit_password` | RabbitMQ auth |
| `AZURE_OPENAI_API_KEY` | `abc123...` | Azure OpenAI key |
| `AZURE_OPENAI_ENDPOINT` | `https://...openai.azure.com/` | Azure endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4` | Deployment name |

See `.env.docker` for complete list.

## Documentation

- **[DOCKER_COMPOSE.md](./DOCKER_COMPOSE.md)** - Complete Docker Compose guide
- **[DOCKER_IMPLEMENTATION.md](./DOCKER_IMPLEMENTATION.md)** - Implementation details
- **[README.md](./README.md)** - Architecture overview
- **[frontend/README.md](./frontend/README.md)** - Frontend documentation

## Common Issues

### "Backend not responding"
```bash
docker-compose logs backend
# Check for errors, restart if needed
docker-compose restart backend
```

### "Neo4j connection refused"
```bash
docker-compose logs neo4j
# Wait for "Started."
docker-compose restart digester backend
```

### "RabbitMQ queue not found"
```bash
docker-compose exec rabbitmq rabbitmqctl list_queues
# Queue is created automatically on first publish
```

### "Frontend shows blank page"
```bash
docker-compose logs frontend
# Check browser console for errors
# Verify backend is running
curl http://localhost:8000/health
```

## Monitoring

```bash
# Resource usage
docker-compose stats

# Service status
docker-compose ps

# All logs
docker-compose logs -f

# Specific timeframe
docker-compose logs --since 5m backend
```

## Cleanup

```bash
# Stop services (keep data)
docker-compose down

# Stop and remove data
docker-compose down -v

# Full cleanup
make nuke
```

## Getting Help

1. Check logs: `make logs-<service>`
2. Review documentation in `DOCKER_COMPOSE.md`
3. Check service health: `make health`
4. Verify environment: `docker-compose config`

## Tips

- Use `make help` to see all available commands
- Start with `./start.sh` for guided setup
- Check `docker-compose ps` to see service status
- Use `make logs` with `-f` flag to follow logs
- Backend API docs at `/docs` endpoint are interactive
- RabbitMQ management UI shows queue depths
- Neo4j browser visualizes the knowledge graph

## Next Steps

1. ✅ Start services: `./start.sh`
2. ✅ Create user in Admin page
3. ✅ Set preferences in Profile page
4. ✅ Start querying in Chatbot
5. 📝 Customize settings in `.env`
6. 🔧 Load test data (optional)
7. 📊 Monitor with `make health`
