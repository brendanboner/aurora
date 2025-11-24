# Aurora Digester Makefile

# Service identifier (used by make-utils.mk to generate container names)
SERVICE_NAME := digester

# Include master environment variables
include ../.env
export

# Include shared Docker utilities (auto-generates container/network names)
include ../common/make-utils.mk

.PHONY: help deploy-isolated deploy-shared clean-isolated clean-shared nuke validate-env \
	ensure-network ensure-rabbitmq ensure-neo4j wait-for-rabbitmq wait-for-neo4j \
	load_isolated_queue load_shared_queue build-load-test-image \
	compose-up compose-down compose-restart

# Default target
help:
	@echo "Aurora Digester - Available commands:"
	@echo ""
	@echo "  Deployment:"
	@echo "    make deploy-isolated        - Deploy digester in isolated environment (own network + deps)"
	@echo "    make deploy-shared          - Deploy digester on shared network (reuses existing deps)"
	@echo "    make compose-up             - Start digester via root docker-compose (preferred shared)"
	@echo "    make compose-down           - Stop digester service (docker-compose)"
	@echo "    make compose-restart        - Restart digester service (docker-compose)"
	@echo ""
	@echo "  Testing:"
	@echo "    make load_isolated_queue    - Load test messages into isolated RabbitMQ queue"
	@echo "    make load_shared_queue      - Load test messages into shared RabbitMQ queue"
	@echo "                                  Optional: FILE=<filename> or FILE=all (default: wfa_public.json)"
	@echo ""
	@echo "  Cleanup:"
	@echo "    make clean-isolated         - Clean ALL isolated environments (all services)"
	@echo "    make clean-shared           - Clean shared resources (use with caution)"
	@echo "    make nuke                   - 💥 Nuke everything (containers + images + system prune)"

# Validate environment variables
validate-env:
	@test -n "$(RABBITMQ_HOST)" || (echo "❌ RABBITMQ_HOST not set" && exit 1)
	@test -n "$(RABBITMQ_USER)" || (echo "❌ RABBITMQ_USER not set" && exit 1)
	@test -n "$(RABBITMQ_PASSWORD)" || (echo "❌ RABBITMQ_PASSWORD not set" && exit 1)
	@test -n "$(NEO4J_URI)" || (echo "❌ NEO4J_URI not set" && exit 1)
	@test -n "$(NEO4J_USER)" || (echo "❌ NEO4J_USER not set" && exit 1)
	@test -n "$(NEO4J_PASSWORD)" || (echo "❌ NEO4J_PASSWORD not set" && exit 1)
	@test -n "$(DOCKER_NETWORK)" || (echo "❌ DOCKER_NETWORK not set" && exit 1)
	@test -n "$(RABBITMQ_IMAGE)" || (echo "❌ RABBITMQ_IMAGE not set" && exit 1)
	@test -n "$(NEO4J_IMAGE)" || (echo "❌ NEO4J_IMAGE not set" && exit 1)
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
	@echo "🗄️  Starting isolated Neo4j..."
	@docker run -d \
		--name $(ISOLATED_NEO4J_CONTAINER) \
		--network $(ISOLATED_NETWORK) \
		-p $(ISOLATED_NEO4J_HTTP_PORT):7474 \
		-p $(ISOLATED_NEO4J_BOLT_PORT):7687 \
		-e NEO4J_AUTH=$(NEO4J_USER)/$(NEO4J_PASSWORD) \
		-e NEO4J_PLUGINS='["apoc"]' \
		$(NEO4J_IMAGE)
	@$(MAKE) wait-for-rabbitmq RABBITMQ_CONTAINER=$(ISOLATED_RABBITMQ_CONTAINER)
	@$(MAKE) wait-for-neo4j NEO4J_CONTAINER=$(ISOLATED_NEO4J_CONTAINER)
	@echo "🚀 Building and running digester (isolated)..."
	@cd .. && docker build -f digester/Dockerfile -t $(SERVICE_IMAGE) .
	@docker run --rm --name $(ISOLATED_SERVICE_CONTAINER) \
		--network $(ISOLATED_NETWORK) \
		-e RABBITMQ_HOST=$(ISOLATED_RABBITMQ_CONTAINER) \
		-e RABBITMQ_PORT=$(RABBITMQ_PORT) \
		-e RABBITMQ_USER=$(RABBITMQ_USER) \
		-e RABBITMQ_PASSWORD=$(RABBITMQ_PASSWORD) \
		-e RABBITMQ_QUEUE=$(RABBITMQ_QUEUE) \
		-e NEO4J_URI=bolt://$(ISOLATED_NEO4J_CONTAINER):7687 \
		-e NEO4J_USER=$(NEO4J_USER) \
		-e NEO4J_PASSWORD=$(NEO4J_PASSWORD) \
		-e NEO4J_DATABASE=$(NEO4J_DATABASE) \
		-e AZURE_OPENAI_API_KEY=$(AZURE_OPENAI_API_KEY) \
		-e AZURE_OPENAI_ENDPOINT=$(AZURE_OPENAI_ENDPOINT) \
		-e AZURE_OPENAI_API_VERSION=$(AZURE_OPENAI_API_VERSION) \
		-e AZURE_OPENAI_DEPLOYMENT=$(AZURE_OPENAI_DEPLOYMENT) \
		-e LLM_MAX_TOKENS=$(LLM_MAX_TOKENS) \
		-e LLM_TEMPERATURE=$(LLM_TEMPERATURE) \
		-e EMBEDDING_PROVIDER=$(EMBEDDING_PROVIDER) \
		-e EMBEDDING_MODEL=$(EMBEDDING_MODEL) \
		-e MAX_CHUNK_SIZE=$(MAX_CHUNK_SIZE) \
		-e CHUNK_OVERLAP=$(CHUNK_OVERLAP) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)

# Deploy on shared network (checks for existing dependencies)
deploy-shared: validate-env ensure-rabbitmq ensure-neo4j
	@echo "🌐 Deploying in SHARED mode (shared network)..."
	@echo "🚀 Building and running digester..."
	@cd .. && docker build -f digester/Dockerfile -t $(SERVICE_IMAGE) .
	@docker run --rm --name $(SHARED_SERVICE_CONTAINER) \
		--network $(DOCKER_NETWORK) \
		-e RABBITMQ_HOST=$(RABBITMQ_HOST) \
		-e RABBITMQ_PORT=$(RABBITMQ_PORT) \
		-e RABBITMQ_USER=$(RABBITMQ_USER) \
		-e RABBITMQ_PASSWORD=$(RABBITMQ_PASSWORD) \
		-e RABBITMQ_QUEUE=$(RABBITMQ_QUEUE) \
		-e NEO4J_URI=$(NEO4J_URI) \
		-e NEO4J_USER=$(NEO4J_USER) \
		-e NEO4J_PASSWORD=$(NEO4J_PASSWORD) \
		-e NEO4J_DATABASE=$(NEO4J_DATABASE) \
		-e AZURE_OPENAI_API_KEY=$(AZURE_OPENAI_API_KEY) \
		-e AZURE_OPENAI_ENDPOINT=$(AZURE_OPENAI_ENDPOINT) \
		-e AZURE_OPENAI_API_VERSION=$(AZURE_OPENAI_API_VERSION) \
		-e AZURE_OPENAI_DEPLOYMENT=$(AZURE_OPENAI_DEPLOYMENT) \
		-e LLM_MAX_TOKENS=$(LLM_MAX_TOKENS) \
		-e LLM_TEMPERATURE=$(LLM_TEMPERATURE) \
		-e EMBEDDING_PROVIDER=$(EMBEDDING_PROVIDER) \
		-e EMBEDDING_MODEL=$(EMBEDDING_MODEL) \
		-e MAX_CHUNK_SIZE=$(MAX_CHUNK_SIZE) \
		-e CHUNK_OVERLAP=$(CHUNK_OVERLAP) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)

#=============================================================================
# docker-compose integration (preferred path for shared deployment)
#=============================================================================

compose-up:
	@echo "🔧 Starting digester via root docker-compose (build if needed)..."
	@docker compose build digester
	@docker compose up -d digester
	@echo "✅ Digester running under docker-compose"

compose-down:
	@echo "🛑 Stopping digester service via docker-compose..."
	@docker compose stop digester || true
	@echo "✅ Digester service stopped"

compose-restart:
	@echo "🔁 Restarting digester service via docker-compose..."
	@docker compose restart digester
	@echo "✅ Digester service restarted"



#==============================================================================
# TEST DATA LOADING
#==============================================================================

# Default test message file
TEST_FILE ?= wfa_public.json

# Image name for load test messages container
LOAD_TEST_IMAGE := load-test-messages


# Load test messages into isolated RabbitMQ queue
load_isolated_queue:
	@echo "🔍 Checking if isolated RabbitMQ is running..."
	@if ! docker ps --filter "name=$(ISOLATED_RABBITMQ_CONTAINER)" --filter "status=running" --format "{{.Names}}" | grep -q "^$(ISOLATED_RABBITMQ_CONTAINER)$$"; then \
		echo "❌ Isolated RabbitMQ is not running!"; \
		echo "💡 Start it with: make deploy-isolated"; \
		exit 1; \
	fi
	@$(MAKE) wait-for-rabbitmq RABBITMQ_CONTAINER=$(ISOLATED_RABBITMQ_CONTAINER)
	@echo "✅ Isolated RabbitMQ is ready"
	@cd .. && docker build -f digester/test_queue/Dockerfile -t $(LOAD_TEST_IMAGE) .
	@echo "📤 Loading messages from: $(TEST_FILE)"
	docker run --rm \
		--network $(ISOLATED_NETWORK) \
		$(LOAD_TEST_IMAGE) \
		--host $(ISOLATED_RABBITMQ_CONTAINER) \
		--port 5672 \
		--user $(RABBITMQ_USER) \
		--password $(RABBITMQ_PASSWORD) \
		--queue $(RABBITMQ_QUEUE) \
		--file $(TEST_FILE); 
	@echo "✅ Test messages loaded into isolated queue!"

# Load test messages into shared RabbitMQ queue
load_shared_queue: ensure-rabbitmq
	@echo "📨 Loading test messages into shared RabbitMQ queue..."
	@echo "✅ Shared RabbitMQ is ready"
	@cd .. && docker build -f digester/test_queue/Dockerfile -t $(LOAD_TEST_IMAGE) .
	@echo "📤 Loading messages from: $(TEST_FILE)"
	docker run --rm \
		--network $(DOCKER_NETWORK) \
		$(LOAD_TEST_IMAGE) \
		--host $(RABBITMQ_HOST) \
		--port 5672 \
		--user $(RABBITMQ_USER) \
		--password $(RABBITMQ_PASSWORD) \
		--queue $(RABBITMQ_QUEUE) \
		--file $(TEST_FILE);
	@echo "✅ Test messages loaded into shared queue!"
