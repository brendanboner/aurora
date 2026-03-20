# =============================================================================
# Aurora EC2 Deployment Makefile
# =============================================================================
# This Makefile is for EC2 production deployment operations.
# It contains only the commands needed to run Aurora on EC2 using pre-built
# ECR images - no build/push commands needed.
#
# Commands:
#   make deploy        - Deploy production services from ECR
#   make start         - Start all services
#   make stop          - Stop all services
#   make restart       - Restart all services (in place)
#   make restart-nginx - Restart nginx only
#   make logs          - View logs (all services)
#   make status        - Check service status
#   make backup        - Run backup now
#   make backup-setup  - Setup automated backups
#   make backup-status - Check backup status
#   make backup-logs   - View backup logs
#   make update        - Pull latest images and restart
#   make clean         - Remove stopped containers
# =============================================================================

# Load colors
CYAN := \033[0;36m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m

# Load environment variables from .env
-include .env
export

# Docker compose file
COMPOSE_FILE := docker-compose.prod.yml

.PHONY: help deploy start stop restart logs status backup backup-setup backup-status backup-logs update clean ecr-login

# =============================================================================
# Help
# =============================================================================

help:
	@echo "$(CYAN)Aurora EC2 Deployment Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Deployment:$(NC)"
	@echo "  make deploy        - Deploy production (setup backups + start services)"
	@echo "  make start         - Start all services"
	@echo "  make stop          - Stop all services"
	@echo "  make restart       - Restart all services (in place)"
	@echo "  make restart-nginx - Restart nginx only"
	@echo "  make restart-kg-view - Restart KG View services only"
	@echo "  make update        - Pull latest images and restart"
	@echo "  make update-kg-view - Pull and restart KG View services only"
	@echo ""
	@echo "$(GREEN)Monitoring:$(NC)"
	@echo "  make status        - Check service status"
	@echo "  make logs          - View logs (all services)"
	@echo "  make logs-nginx    - View nginx logs"
	@echo "  make logs-auth     - View auth logs"
	@echo "  make logs-backend  - View backend logs"
	@echo "  make logs-kg-view  - View KG View logs"
	@echo ""
	@echo "$(GREEN)Database:$(NC)"
	@echo "  make migrate       - Run database migrations"
	@echo "  make migrate-status - Show migration status"
	@echo ""
	@echo "$(GREEN)Backup:$(NC)"
	@echo "  make backup        - Run backup now"
	@echo "  make backup-setup  - Setup automated backups"
	@echo "  make backup-status - Check backup status"
	@echo "  make backup-logs   - View backup logs"
	@echo ""
	@echo "$(GREEN)Maintenance:$(NC)"
	@echo "  make clean         - Remove stopped containers"
	@echo "  make pull          - Pull latest images from ECR"
	@echo "  make ecr-login     - Login to Amazon ECR"
	@echo "  make health        - Check service health"
	@echo ""
	@echo "$(GREEN)Quick Checks:$(NC)"
	@echo "  make ps            - List running containers"
	@echo "  make disk          - Check disk usage"
	@echo ""

# =============================================================================
# Deployment Prep
# =============================================================================

ecr-login:
	@echo "$(CYAN)Logging into Amazon ECR...$(NC)"
	@aws ecr get-login-password --region $(AWS_REGION) \
		| docker login --username AWS --password-stdin \
		  $(ECR_REGISTRY)

# =============================================================================
# Deployment
# =============================================================================

deploy: backup-setup start
	@echo "$(GREEN)✓ Production deployment complete$(NC)"
	@echo ""
	@echo "Your application should be available at:"
	@echo "  https://$$(grep '^DEPLOYMENT_DOMAIN=' .env | cut -d'=' -f2)"
	@echo ""
	@echo "Check status: make status"
	@echo "View logs:    make logs"

start:
	@echo "$(CYAN)Starting production services...$(NC)"
	@docker compose -f $(COMPOSE_FILE) up -d
	@echo "$(GREEN)✓ Services started$(NC)"

stop:
	@echo "$(CYAN)Stopping all services...$(NC)"
	@docker compose -f $(COMPOSE_FILE) down
	@echo "$(GREEN)✓ Services stopped$(NC)"

restart:
	@echo "$(CYAN)Restarting all services...$(NC)"
	@docker compose -f $(COMPOSE_FILE) restart
	@echo "$(GREEN)✓ Services restarted$(NC)"

restart-nginx:
	@echo "$(CYAN)Restarting nginx...$(NC)"
	@docker compose -f $(COMPOSE_FILE) restart nginx
	@echo "$(GREEN)✓ Nginx restarted$(NC)"

update-kg-view: ecr-login
	@echo "$(CYAN)Updating KG View services...$(NC)"
	@echo "$(YELLOW)→ Pulling latest kg-view images...$(NC)"
	@docker compose -f $(COMPOSE_FILE) pull kg-view-frontend kg-view-backend
	@echo "$(YELLOW)→ Restarting kg-view services...$(NC)"
	@docker compose -f $(COMPOSE_FILE) up -d kg-view-frontend kg-view-backend
	@echo "$(GREEN)✓ KG View services updated$(NC)"
	@echo "$(CYAN)Tailing logs (Ctrl+C to exit)...$(NC)"
	@docker compose -f $(COMPOSE_FILE) logs -f kg-view-frontend kg-view-backend

restart-kg-view:
	@echo "$(CYAN)Restarting KG View services...$(NC)"
	@docker compose -f $(COMPOSE_FILE) restart kg-view-frontend kg-view-backend
	@echo "$(GREEN)✓ KG View services restarted$(NC)"
	@docker compose -f $(COMPOSE_FILE) logs -f kg-view-frontend kg-view-backend

logs-kg-view:
	@docker compose -f $(COMPOSE_FILE) logs -f kg-view-frontend kg-view-backend

update: ecr-login
	@echo "$(CYAN)Updating services...$(NC)"
	@echo "$(YELLOW)→ Creating backup first...$(NC)"
	@$(MAKE) backup
	@echo "$(YELLOW)→ Pulling latest images...$(NC)"
	@docker compose -f $(COMPOSE_FILE) pull
	@echo "$(YELLOW)→ Running database migrations...$(NC)"
	@$(MAKE) migrate
	@echo "$(YELLOW)→ Restarting services...$(NC)"
	@docker compose -f $(COMPOSE_FILE) up -d
	@echo "$(GREEN)✓ Services updated$(NC)"

pull: ecr-login
	@echo "$(CYAN)Pulling latest images from ECR...$(NC)"
	@docker compose -f $(COMPOSE_FILE) pull
	@echo "$(GREEN)✓ Images pulled$(NC)"

# =============================================================================
# Monitoring
# =============================================================================

status:
	@echo "$(CYAN)Service Status$(NC)"
	@echo ""
	@docker compose -f $(COMPOSE_FILE) ps

ps:
	@docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

logs:
	@docker compose -f $(COMPOSE_FILE) logs -f

logs-nginx:
	@docker logs -f aurora-nginx

logs-auth:
	@docker logs -f aurora-auth

logs-backend:
	@docker logs -f aurora-backend

logs-frontend:
	@docker logs -f aurora-frontend

logs-retriever:
	@docker logs -f aurora-retriever

logs-digester:
	@docker logs -f aurora-digester

logs-curator:
	@docker logs -f aurora-curator

logs-rabbitmq:
	@docker logs -f aurora-rabbitmq 

logs-postgres:
	@docker logs -f aurora-postgres

logs-neo4j:
	@docker logs -f aurora-neo4j 

logs-redis:
	@docker logs -f aurora-redis 


health:
	@echo "$(CYAN)Service Health$(NC)"
	@echo ""
	@echo "$(GREEN)Checking containers...$(NC)"
	@docker ps --filter "name=aurora-" --format "table {{.Names}}\t{{.Status}}" | grep -E "aurora-|NAMES"
	@echo ""
	@echo "$(GREEN)Checking endpoints...$(NC)"
	@curl -s -o /dev/null -w "Frontend:  %{http_code}\n" http://localhost || echo "Frontend:  unreachable"
	@curl -s -o /dev/null -w "Auth:      %{http_code}\n" http://localhost:8000/health || echo "Auth:      unreachable"
	@curl -s -o /dev/null -w "Backend:   %{http_code}\n" http://localhost:8001/health || echo "Backend:   unreachable"

disk:
	@echo "$(CYAN)Disk Usage$(NC)"
	@echo ""
	@echo "$(GREEN)System:$(NC)"
	@df -h / | grep -v Filesystem
	@echo ""
	@echo "$(GREEN)Docker:$(NC)"
	@docker system df
	@echo ""
	@echo "$(GREEN)Backups:$(NC)"
	@if [ -f .env ]; then \
		export $$(grep -v '^#' .env | grep -v '^$$' | xargs) && \
		BACKUP_DIR=$${BACKUP_DIR:-$$HOME/backups/aurora} && \
		du -sh $$BACKUP_DIR 2>/dev/null || echo "  No backup directory"; \
	else \
		du -sh ~/backups/aurora 2>/dev/null || echo "  No backup directory"; \
	fi

# =============================================================================
# Database Migrations
# =============================================================================

migrate:
	@echo "$(CYAN)Running database migrations...$(NC)"
	@chmod +x scripts/migrate.sh
	@./scripts/migrate.sh
	@echo "$(GREEN)✓ Migrations complete$(NC)"

migrate-status:
	@echo "$(CYAN)Checking migration status...$(NC)"
	@chmod +x scripts/migrate.sh
	@./scripts/migrate.sh --status

# =============================================================================
# Backup Management
# =============================================================================

backup:
	@echo "$(CYAN)Running backup...$(NC)"
	@chmod +x scripts/backup.sh
	@./scripts/backup.sh

backup-setup:
	@echo "$(CYAN)Setting up automated backups...$(NC)"
	@chmod +x scripts/backup.sh
	@chmod +x scripts/setup-backups.sh
	@./scripts/setup-backups.sh

backup-status:
	@echo "$(CYAN)Backup Status$(NC)"
	@echo ""
	@echo "$(GREEN)Cron Jobs:$(NC)"
	@crontab -l 2>/dev/null | grep -i backup || echo "  No backup cron jobs found"
	@echo ""
	@echo "$(GREEN)Recent Backups:$(NC)"
	@if [ -f .env ]; then \
		export $$(grep -v '^#' .env | grep -v '^$$' | xargs) && \
		BACKUP_DIR=$${BACKUP_DIR:-$$HOME/backups/aurora} && \
		ls -lht $$BACKUP_DIR 2>/dev/null | head -10 || echo "  No backups found at $$BACKUP_DIR"; \
	else \
		ls -lht ~/backups/aurora 2>/dev/null | head -10 || echo "  No backups found"; \
	fi
	@echo ""
	@echo "$(GREEN)Disk Usage:$(NC)"
	@if [ -f .env ]; then \
		export $$(grep -v '^#' .env | grep -v '^$$' | xargs) && \
		BACKUP_DIR=$${BACKUP_DIR:-$$HOME/backups/aurora} && \
		du -sh $$BACKUP_DIR 2>/dev/null || echo "  No backup directory"; \
	else \
		du -sh ~/backups/aurora 2>/dev/null || echo "  No backup directory"; \
	fi

backup-logs:
	@echo "$(CYAN)Recent Backup Logs$(NC)"
	@echo ""
	@if [ -f .env ]; then \
		export $$(grep -v '^#' .env | grep -v '^$$' | xargs) && \
		BACKUP_DIR=$${BACKUP_DIR:-$$HOME/backups/aurora} && \
		tail -50 $$BACKUP_DIR/backup.log 2>/dev/null || echo "No backup logs found at $$BACKUP_DIR/backup.log"; \
	else \
		tail -50 ~/backups/aurora/backup.log 2>/dev/null || echo "No backup logs found"; \
	fi

# =============================================================================
# Maintenance
# =============================================================================

clean:
	@echo "$(CYAN)Cleaning up...$(NC)"
	@echo "$(YELLOW)→ Removing stopped containers...$(NC)"
	@docker compose -f $(COMPOSE_FILE) rm -f
	@echo "$(YELLOW)→ Removing unused images...$(NC)"
	@docker image prune -f
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

clean-all:
	@echo "$(RED)⚠️  This will remove all stopped containers, unused networks, and dangling images$(NC)"
	@echo "$(YELLOW)Continue? [y/N]$(NC) " && read ans && [ $${ans:-N} = y ]
	@docker system prune -f
	@echo "$(GREEN)✓ System cleaned$(NC)"
