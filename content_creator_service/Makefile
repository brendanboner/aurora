# =============================================================================
# Content Creator Service Makefile
# =============================================================================

.PHONY: help test install clean-venv deploy-shared clean-shared logs nuke validate-env run-local trigger-agent

# Service-specific configuration for ECR
SERVICE_NAME := aurora-content-creator
DOCKERFILE := Dockerfile
BUILD_CONTEXT := ..

# Virtual environment configuration
VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
PYTEST = $(VENV)/bin/pytest

# Load common configuration and targets (build-push, ship, clean)
include ../Makefile.common

# Legacy config (for deploy-shared)
-include ../.env
export

PYTHON_RUNNER ?= uv run python

help:
	@echo "$(CYAN)Content Creator Service Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)ECR Deployment:$(NC)"
	@echo "  make test        - Run tests with pytest (creates venv automatically)"
	@echo "  make build-push  - Build and push Docker image to ECR (skips tests)"
	@echo "  make ship        - Run tests, build, and ship to ECR"
	@echo "  make clean       - Clean up test artifacts"
	@echo "  make clean-venv  - Remove virtual environment"
	@echo ""
	@echo "$(GREEN)Local Development:$(NC)"
	@echo "  make deploy-shared   - Build + replace service container"
	@echo "  make clean-shared    - Stop service container"
	@echo "  make logs            - Tail logs"
	@echo "  make run-local       - Run uvicorn with local env"
	@echo "  make trigger-agent   - Force a CreatorAgent to create a post"
	@echo "  make nuke            - Remove image + container"

# Create virtual environment
$(VENV)/bin/activate:
	@echo "$(CYAN)Creating virtual environment with Python 3.12...$(NC)"
	@python3.12 -m venv $(VENV) || python3 -m venv $(VENV)

# Install dependencies in venv
install: $(VENV)/bin/activate
	@echo "$(CYAN)Installing dependencies...$(NC)"
	@$(PIP) install --upgrade pip
	@$(PIP) install -e ../neo4j-client
	@$(PIP) install -e ../rabbitmq-client
	@$(PIP) install -e .

# Run tests in venv
test: install
	@echo "$(CYAN)Running content creator service tests...$(NC)"
	@$(PYTEST) -v --cov=src --cov-report=term-missing || echo "$(YELLOW)No tests found or tests skipped$(NC)"
	@echo "$(GREEN)✓ Tests completed$(NC)"
	@$(MAKE) clean-venv

# Override clean to also clean venv artifacts
clean:
	@echo "$(CYAN)Cleaning $(SERVICE_NAME) artifacts...$(NC)"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache .coverage htmlcov
	@rm -rf build .cache test_results
	@echo "$(GREEN)✓ Cleanup completed$(NC)"

# Clean virtual environment
clean-venv:
	@echo "$(CYAN)Removing virtual environment...$(NC)"
	@rm -rf $(VENV)
	@echo "$(GREEN)✓ Virtual environment removed$(NC)"

# =============================================================================
# Local Development Commands (Legacy)
# =============================================================================

validate-env:
	@test -n "$(POSTGRES_HOST)" || (echo '❌ POSTGRES_HOST missing' && exit 1)
	@test -n "$(POSTGRES_DB)" || (echo '❌ POSTGRES_DB missing' && exit 1)
	@test -n "$(NEO4J_URI)" || (echo '❌ NEO4J_URI missing' && exit 1)
	@test -n "$(AZURE_OPENAI_ENDPOINT)" || (echo '❌ AZURE_OPENAI_ENDPOINT missing' && exit 1)
	@test -n "$(AZURE_OPENAI_API_KEY)" || (echo '❌ AZURE_OPENAI_API_KEY missing' && exit 1)
	@echo "✅ Environment OK"

run-local:
	uvicorn src.api:app --reload --port 8000

deploy-shared: validate-env
	@echo "🛑 Stopping old content creator container (if running)..."
	-@docker rm -f $(SHARED_SERVICE_CONTAINER) 2>/dev/null || true

	@echo "📦 Rebuilding content creator image: $(SERVICE_IMAGE)"
	cd .. && docker build -f content_creator_service/Dockerfile -t $(SERVICE_IMAGE) .

	@echo "🚀 Starting fresh content creator container: $(SHARED_SERVICE_CONTAINER)"
	docker run -d \
		--name $(SHARED_SERVICE_CONTAINER) \
		--network $(DOCKER_NETWORK) \
		-p 8000:8000 \
		-e PG_DSN="$(PG_DSN)" \
		-e POSTGRES_HOST="$(POSTGRES_HOST)" \
		-e POSTGRES_PORT="$(POSTGRES_PORT)" \
		-e POSTGRES_USER="$(POSTGRES_USER)" \
		-e POSTGRES_PASSWORD="$(POSTGRES_PASSWORD)" \
		-e POSTGRES_DB="$(POSTGRES_DB)" \
		-e NEO4J_URI="$(NEO4J_URI)" \
		-e NEO4J_USER="$(NEO4J_USER)" \
		-e NEO4J_PASSWORD="$(NEO4J_PASSWORD)" \
		-e NEO4J_DATABASE="$(NEO4J_DATABASE)" \
		-e RABBITMQ_HOST="$(RABBITMQ_HOST)" \
		-e RABBITMQ_PORT="$(RABBITMQ_PORT)" \
		-e RABBITMQ_USER="$(RABBITMQ_USER)" \
		-e RABBITMQ_PASSWORD="$(RABBITMQ_PASSWORD)" \
		-e AZURE_OPENAI_API_KEY="$(AZURE_OPENAI_API_KEY)" \
		-e AZURE_OPENAI_ENDPOINT="$(AZURE_OPENAI_ENDPOINT)" \
		-e AZURE_OPENAI_API_VERSION="$(AZURE_OPENAI_API_VERSION)" \
		-e AZURE_OPENAI_DEPLOYMENT="$(AZURE_OPENAI_DEPLOYMENT)" \
		$(SERVICE_IMAGE)

clean-shared:
	-@docker rm -f $(SHARED_SERVICE_CONTAINER)

logs:
	docker logs -f $(SHARED_SERVICE_CONTAINER)

nuke:
	-@docker rm -f $(SHARED_SERVICE_CONTAINER)
	-@docker rmi $(SERVICE_IMAGE)

trigger-agent:
	@test -n "$(AGENT_ID)$(AGENT_NAME)" || (echo 'Provide AGENT_ID or AGENT_NAME' && exit 1)
	@if [ -n "$(AGENT_ID)" ]; then \
		AGENT="$(AGENT_ID)"; \
	else \
		echo "Resolving agent '$(AGENT_NAME)'..."; \
		AGENT=$$(curl -s http://localhost:8000/agents?include_disabled=true | jq -r '.[] | select(.name | ascii_downcase == "$(shell echo $(AGENT_NAME) | tr A-Z a-z)") | .id'); \
		if [ -z "$$AGENT" ]; then echo "❌ Agent '$(AGENT_NAME)' not found"; exit 1; fi; \
	fi; \
	FORCE_FLAG=$$([ -n "$(FORCE)" ] && echo "true" || echo "false"); \
	LIMIT_VAL=$${LIMIT:-5}; \
	echo "🚀 Triggering agent $$AGENT (force=$$FORCE_FLAG, limit=$$LIMIT_VAL)"; \
	curl -s -X POST "http://localhost:8000/agents/$$AGENT/trigger" \
		-H "Content-Type: application/json" \
		-d "{\"force\": $$FORCE_FLAG, \"limit\": $$LIMIT_VAL}" | jq .
