.PHONY: help build build-dev up up-dev down logs logs-dev shell test clean

# Default target
.DEFAULT_GOAL := help

# Colors for output
CYAN := \033[0;36m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Show this help message
	@echo "$(CYAN)Aurora Teams Agent - Docker Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-15s$(NC) %s\n", $$1, $$2}'
	@echo ""

# Check if .env file exists
check-env:
	@if [ ! -f .env ]; then \
		echo "$(RED)Error: .env file not found!$(NC)"; \
		echo "$(YELLOW)Copy .env.dev to .env and configure your Bot ID and Password$(NC)"; \
		exit 1; \
	fi

# Production builds
build: check-env ## Build production Docker image
	@echo "$(CYAN)Building production Teams agent...$(NC)"
	docker-compose build teams-agent
	@echo "$(GREEN)✓ Production build complete$(NC)"

up: check-env ## Start production container
	@echo "$(CYAN)Starting production Teams agent...$(NC)"
	docker-compose up -d teams-agent
	@echo "$(GREEN)✓ Teams agent running at http://localhost:3978$(NC)"
	@echo "$(YELLOW)View logs: make logs$(NC)"

# Development builds
build-dev: check-env ## Build development Docker image (with debugging)
	@echo "$(CYAN)Building development Teams agent...$(NC)"
	docker-compose build teams-agent-dev
	@echo "$(GREEN)✓ Development build complete$(NC)"

up-dev: check-env ## Start development container with hot reload and debugging
	@echo "$(CYAN)Starting development Teams agent...$(NC)"
	@echo "$(YELLOW)Debug port: 9229$(NC)"
	docker-compose up -d teams-agent-dev
	@echo "$(GREEN)✓ Teams agent running at http://localhost:3978$(NC)"
	@echo "$(GREEN)✓ Debug port available at localhost:9229$(NC)"
	@echo "$(YELLOW)View logs: make logs-dev$(NC)"
	@echo "$(YELLOW)Attach debugger in VS Code with F5$(NC)"

# Container management
down: ## Stop and remove containers
	@echo "$(CYAN)Stopping Teams agent...$(NC)"
	docker-compose down
	@echo "$(GREEN)✓ Containers stopped$(NC)"

restart: down up ## Restart production container

restart-dev: down up-dev ## Restart development container

# Logs
logs: ## View production container logs
	docker-compose logs -f teams-agent

logs-dev: ## View development container logs
	docker-compose logs -f teams-agent-dev

# Shell access
shell: ## Open shell in production container
	docker-compose exec teams-agent sh

shell-dev: ## Open shell in development container
	docker-compose exec teams-agent-dev sh

# Status and health
status: ## Check container status
	@echo "$(CYAN)Container Status:$(NC)"
	@docker-compose ps
	@echo ""
	@echo "$(CYAN)Health Check:$(NC)"
	@curl -s http://localhost:3978/api/health | jq . || echo "$(RED)Service not reachable$(NC)"

# Testing
test: ## Run tests inside container
	@echo "$(CYAN)Running tests...$(NC)"
	docker-compose exec teams-agent-dev npm test

# Cleanup
clean: down ## Remove containers, images, and volumes
	@echo "$(CYAN)Cleaning up...$(NC)"
	docker-compose down -v --rmi local
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

# Debug helpers
debug-attach: ## Show instructions for attaching debugger
	@echo "$(CYAN)Debugger Attachment Instructions:$(NC)"
	@echo ""
	@echo "$(GREEN)VS Code:$(NC)"
	@echo "  1. Make sure teams-agent-dev is running: make up-dev"
	@echo "  2. Open VS Code in teams-agent folder"
	@echo "  3. Go to Run and Debug (Cmd+Shift+D)"
	@echo "  4. Select 'Attach to Docker' configuration"
	@echo "  5. Press F5 to attach"
	@echo ""
	@echo "$(GREEN)Chrome DevTools:$(NC)"
	@echo "  1. Open chrome://inspect"
	@echo "  2. Click 'Configure' and add localhost:9229"
	@echo "  3. Click 'inspect' under your node process"
	@echo ""

# Quick start
quickstart: build-dev up-dev logs-dev ## Quick start in development mode with logs
