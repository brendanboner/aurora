# Aurora Retriever Makefile

# Service identifier (used by make-utils.mk to generate container names)
SERVICE_NAME := retriever

# Include master environment variables
include ../.env
export

# Include shared Docker utilities (auto-generates container/network names)
include ../common/make-utils.mk

.PHONY: help deploy-isolated deploy-shared clean-isolated clean-shared nuke validate-env \
        ensure-network ensure-rabbitmq wait-for-rabbitmq run-json check-venv
	compose-up compose-down compose-restart

# Default target
help:
	@echo "Aurora Retriever - Available commands:"
	@echo ""
	@echo "  make deploy-isolated - Deploy retriever in isolated environment (own network + deps)"
	@echo "  make deploy-shared    - Deploy retriever on shared network (reuses existing deps)"
	@echo "  make compose-up       - Start retriever via root docker-compose (preferred shared)"
	@echo "  make compose-down     - Stop retriever service (docker-compose)"
	@echo "  make compose-restart  - Restart retriever service (docker-compose)"
	@echo "  make run-json        - Run retriever locally with JSON output (generates test messages)"
	@echo "  make clean-isolated  - Clean ALL isolated environments (all services)"
	@echo "  make clean-shared   - Clean shared resources (use with caution)"
	@echo "  make nuke           - 💥 Nuke everything (containers + images + system prune)"

# Validate environment variables
validate-env:
	@test -n "$(RABBITMQ_HOST)" || (echo "❌ RABBITMQ_HOST not set" && exit 1)
	@test -n "$(RABBITMQ_USER)" || (echo "❌ RABBITMQ_USER not set" && exit 1)
	@test -n "$(RABBITMQ_PASSWORD)" || (echo "❌ RABBITMQ_PASSWORD not set" && exit 1)
	@test -n "$(DOCKER_NETWORK)" || (echo "❌ DOCKER_NETWORK not set" && exit 1)
	@test -n "$(RABBITMQ_IMAGE)" || (echo "❌ RABBITMQ_IMAGE not set" && exit 1)
	@echo "✅ Environment validated"

# Deploy in complete isolation (own network + dependencies)
deploy-isolated: validate-env clean-isolated
	@echo "🔒 Deploying in ISOLATED mode..."
	@echo "📡 Creating isolated network..."
	@docker network create $(ISOLATED_NETWORK)
	@echo "🐰 Starting isolated RabbitMQ..."
	@docker run -d \
		--name $(ISOLATED_RABBITMQ_CONTAINER) \
		--network $(ISOLATED_NETWORK) \
		-p $(ISOLATED_RABBITMQ_MANAGEMENT_PORT):15672 \
		-e RABBITMQ_DEFAULT_USER=$(RABBITMQ_USER) \
		-e RABBITMQ_DEFAULT_PASS=$(RABBITMQ_PASSWORD) \
		$(RABBITMQ_IMAGE)
	@$(MAKE) wait-for-rabbitmq RABBITMQ_CONTAINER=$(ISOLATED_RABBITMQ_CONTAINER)
	@echo "🚀 Building and running retriever (isolated)..."
	@cd .. && docker build -f retriever/Dockerfile -t $(SERVICE_IMAGE) .
	@docker run --rm --name $(ISOLATED_SERVICE_CONTAINER) \
		--network $(ISOLATED_NETWORK) \
		-e RABBITMQ_HOST=$(ISOLATED_RABBITMQ_CONTAINER) \
		-e RABBITMQ_PORT=$(RABBITMQ_PORT) \
		-e RABBITMQ_USER=$(RABBITMQ_USER) \
		-e RABBITMQ_PASSWORD=$(RABBITMQ_PASSWORD) \
		-e RABBITMQ_QUEUE=$(RABBITMQ_QUEUE) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)

# Deploy on shared network (checks for existing dependencies)
deploy-shared: validate-env ensure-rabbitmq
	@echo "🌐 Deploying in SAHRED mode (shared network)..."
	@echo "🚀 Building and running retriever..."
	@cd .. && docker build -f retriever/Dockerfile -t $(SERVICE_IMAGE) .
	@docker run --rm --name $(SHARED_SERVICE_CONTAINER) \
		--network $(DOCKER_NETWORK) \
		-e RABBITMQ_HOST=$(RABBITMQ_HOST) \
		-e RABBITMQ_PORT=$(RABBITMQ_PORT) \
		-e RABBITMQ_USER=$(RABBITMQ_USER) \
		-e RABBITMQ_PASSWORD=$(RABBITMQ_PASSWORD) \
		-e RABBITMQ_QUEUE=$(RABBITMQ_QUEUE) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)

#=============================================================================
# docker-compose integration (preferred path for shared deployment)
#=============================================================================

compose-up:
	@echo "🔧 Starting retriever via root docker-compose (build if needed)..."
	@docker compose build retriever
	@docker compose up -d retriever
	@echo "✅ Retriever running under docker-compose"

compose-down:
	@echo "🛑 Stopping retriever service via docker-compose..."
	@docker compose stop retriever || true
	@echo "✅ Retriever service stopped"

compose-restart:
	@echo "🔁 Restarting retriever service via docker-compose..."
	@docker compose restart retriever
	@echo "✅ Retriever service restarted"

# Check venv & requirements creating and installing if missing
check-requirements: 
	@echo "🔍 Ensuring virtual environment exists..."
	@if [ ! -d "venv" ]; then \
		echo "❌ Virtual environment not found. Creating venv..."; \
		python3 -m venv venv; \
		echo "✅ Virtual environment created"; \
	else \
		echo "✅ Virtual environment exists"; \
	fi
	@venv/bin/pip show beautifulsoup4 > /dev/null 2>&1 || \
		(echo "❌ Requirements not installed in venv. Installing..." && cd .. && retriever/venv/bin/pip install -r retriever/requirements.txt)
	@echo "✅ All requirements installed (in venv)"

# Run locally with JSON output (for generating test messages)
run-json: check-venv check-requirements
	@echo "🚀 Running retriever locally with JSON output..."
	@echo "📝 Output Mode: json"
	@echo "📄 JSON Output: $(JSON_OUTPUT_FILE)"
	@echo ""
	@OUTPUT_MODE=json venv/bin/python main.py
	@echo ""
	@echo "✅ Test messages generated: $(JSON_OUTPUT_FILE)"
