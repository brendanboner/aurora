# Aurora - Docker Compose Makefile Wrapper
# Provides convenient shortcuts for docker-compose commands

.PHONY: help up down restart logs ps build clean health shell

help:
	@echo "Aurora Docker Compose - Quick Commands"
	@echo ""
	@echo "  Setup:"
	@echo "    make setup       - Copy .env.docker to .env (first time setup)"
	@echo "    make config      - Validate docker-compose configuration"
	@echo ""
	@echo "  Service Management:"
	@echo "    make up          - Start all services"
	@echo "    make down        - Stop all services (keep data)"
	@echo "    make restart     - Restart all services"
	@echo "    make rebuild     - Rebuild and restart all services"
	@echo "    make stop        - Stop all services"
	@echo "    make start       - Start stopped services"
	@echo ""
	@echo "  Monitoring:"
	@echo "    make ps          - List running services"
	@echo "    make logs        - View all logs (follow mode)"
	@echo "    make health      - Check health status of all services"
	@echo "    make stats       - Show resource usage"
	@echo ""
	@echo "  Individual Services:"
	@echo "    make logs-backend    - View backend logs"
	@echo "    make logs-frontend   - View frontend logs"
	@echo "    make logs-digester   - View digester logs"
	@echo "    make logs-retriever  - View retriever logs"
	@echo "    make restart-backend - Restart backend service"
	@echo ""
	@echo "  Development:"
	@echo "    make shell-backend   - Open shell in backend container"
	@echo "    make shell-postgres  - Open psql in PostgreSQL"
	@echo "    make shell-neo4j     - Open cypher-shell in Neo4j"
	@echo "    make build           - Rebuild all images"
	@echo "    make build-backend   - Rebuild backend image"
	@echo "    make build-frontend  - Rebuild frontend image"
	@echo ""
	@echo "  Testing:"
	@echo "    make test-health     - Test backend health endpoint"
	@echo "    make test-api        - Open API docs in browser"
	@echo ""
	@echo "  Scraping:"
	@echo "    make scrape-wfa      - Trigger WFA daily scrape (first page)"
	@echo "    make scrape-wfa-full - Trigger WFA full scrape (all pages)"
	@echo "    make scrape-status   - Check scraper status"
	@echo ""
	@echo "  Data Management:"
	@echo "    make backup          - Backup all volumes"
	@echo "    make volumes         - List all volumes"
	@echo ""
	@echo "  Cleanup:"
	@echo "    make clean           - Remove containers and networks (keep volumes)"
	@echo "    make clean-volumes   - Remove containers, networks AND volumes"
	@echo "    make nuke            - Nuclear option - remove everything"

# Setup
setup:
	@if [ ! -f .env ]; then \
		cp .env.docker .env; \
		echo "✅ Created .env from .env.docker"; \
		echo "⚠️  Please edit .env with your credentials before running 'make up'"; \
	else \
		echo "ℹ️  .env already exists"; \
	fi

config:
	@docker-compose config

# Service Management
up: setup
	@echo "🚀 Starting all services..."
	@docker-compose up -d
	@echo "✅ Services started!"
	@echo ""
	@echo "Access points:"
	@echo "  Frontend:  http://localhost:3000"
	@echo "  Backend:   http://localhost:8000"
	@echo "  API Docs:  http://localhost:8000/docs"
	@echo ""
	@echo "Run 'make logs' to view service logs"

down:
	@echo "🛑 Stopping all services..."
	@docker-compose down
	@echo "✅ Services stopped (volumes preserved)"

restart:
	@echo "🔄 Restarting all services..."
	@docker-compose restart
	@echo "✅ Services restarted"

rebuild:
	@echo "🔨 Rebuilding and restarting services..."
	@docker-compose up -d --build
	@echo "✅ Services rebuilt and restarted"

stop:
	@docker-compose stop

start:
	@docker-compose start

# Monitoring
ps:
	@docker-compose ps

logs:
	@docker-compose logs -f

health:
	@echo "Health Status:"
	@docker-compose ps
	@echo ""
	@echo "Backend Health:"
	@curl -s http://localhost:8000/health | python3 -m json.tool || echo "❌ Backend not responding"

stats:
	@docker-compose stats

# Individual Service Logs
logs-backend:
	@docker-compose logs -f backend

logs-frontend:
	@docker-compose logs -f frontend

logs-digester:
	@docker-compose logs -f digester

logs-retriever:
	@docker-compose logs -f retriever

logs-postgres:
	@docker-compose logs -f postgres

logs-neo4j:
	@docker-compose logs -f neo4j

logs-rabbitmq:
	@docker-compose logs -f rabbitmq

# Individual Service Restarts
restart-backend:
	@docker-compose restart backend

restart-frontend:
	@docker-compose restart frontend

restart-digester:
	@docker-compose restart digester

restart-retriever:
	@docker-compose restart retriever

# Build Commands
build:
	@docker-compose build

build-backend:
	@docker-compose build backend
	@docker-compose up -d backend

build-frontend:
	@docker-compose build frontend
	@docker-compose up -d frontend

build-digester:
	@docker-compose build digester
	@docker-compose up -d digester

build-retriever:
	@docker-compose build retriever
	@docker-compose up -d retriever

# Shell Access
shell-backend:
	@docker-compose exec backend bash

shell-frontend:
	@docker-compose exec frontend sh

shell-digester:
	@docker-compose exec digester bash

shell-retriever:
	@docker-compose exec retriever bash

shell-postgres:
	@docker-compose exec postgres psql -U aurora -d aurora

shell-neo4j:
	@docker-compose exec neo4j cypher-shell -u neo4j -p $$(grep NEO4J_PASSWORD .env | cut -d '=' -f2)

shell-rabbitmq:
	@docker-compose exec rabbitmq bash

# Testing
test-health:
	@echo "Testing backend health..."
	@curl -f http://localhost:8000/health && echo "✅ Backend healthy" || echo "❌ Backend unhealthy"

test-api:
	@echo "Opening API docs..."
	@open http://localhost:8000/docs || xdg-open http://localhost:8000/docs || echo "Visit http://localhost:8000/docs"

# Data Management
volumes:
	@docker volume ls | grep aurora

backup:
	@mkdir -p backups
	@echo "Backing up PostgreSQL..."
	@docker-compose exec -T postgres pg_dump -U aurora aurora > backups/postgres-$$(date +%Y%m%d-%H%M%S).sql
	@echo "✅ Backup complete: backups/postgres-$$(date +%Y%m%d-%H%M%S).sql"

# Cleanup
clean:
	@echo "🧹 Cleaning up (keeping volumes)..."
	@docker-compose down
	@echo "✅ Cleanup complete (volumes preserved)"

clean-volumes:
	@echo "⚠️  This will delete all data volumes!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v; \
		echo "✅ Volumes removed"; \
	else \
		echo "❌ Cancelled"; \
	fi

nuke:
	@echo "💥 Nuclear option - removing everything!"
	@read -p "Are you sure? This will delete ALL data! [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v --rmi all; \
		docker system prune -af; \
		echo "✅ Everything removed"; \
	else \
		echo "❌ Cancelled"; \
	fi

# Scraping Commands
scrape-wfa:
	@echo "🔍 Triggering WFA daily scrape (first page only)..."
	@curl -s -X POST http://localhost:8001/scrape \
		-H "Content-Type: application/json" \
		-d '{"scraper_type": "wfa", "full_scrape": false}' | python3 -m json.tool
	@echo ""
	@echo "✅ Daily scrape triggered. Run 'make logs-retriever' to watch progress"

scrape-wfa-full:
	@echo "🔍 Triggering WFA full scrape (all pages)..."
	@curl -s -X POST http://localhost:8001/scrape \
		-H "Content-Type: application/json" \
		-d '{"scraper_type": "wfa", "full_scrape": true}' | python3 -m json.tool
	@echo ""
	@echo "✅ Full scrape triggered. Run 'make logs-retriever' to watch progress"

scrape-status:
	@echo "📊 Scraper Status:"
	@curl -s http://localhost:8001/status | python3 -m json.tool

# Quick shortcuts
.PHONY: start-all stop-all
start-all: up
stop-all: down
