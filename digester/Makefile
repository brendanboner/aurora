# Aurora Digester Makefile

# Service identifier (used by make-utils.mk to generate container names)
SERVICE_NAME := digester

# Include master environment variables
include ../.env
export

# Include shared Docker utilities (auto-generates container/network names)
include ../common/make-utils.mk

.PHONY: help deploy-isolated deploy-local clean-isolated clean-shared nuke validate-env \
        ensure-network ensure-rabbitmq ensure-neo4j wait-for-rabbitmq wait-for-neo4j

# Default target
help:
	@echo "Aurora Digester - Available commands:"
	@echo ""
	@echo "  make deploy-isolated - Deploy digester in isolated environment (own network + deps)"
	@echo "  make deploy-local    - Deploy digester on shared network (reuses existing deps)"
	@echo "  make clean-isolated  - Clean ALL isolated environments (all services)"
	@echo "  make clean-shared   - Clean shared resources (use with caution)"
	@echo "  make nuke           - 💥 Nuke everything (containers + images + system prune)"

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
		-e MAX_CHUNK_SIZE=$(MAX_CHUNK_SIZE) \
		-e CHUNK_OVERLAP=$(CHUNK_OVERLAP) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)

# Deploy on shared network (checks for existing dependencies)
deploy-local: validate-env ensure-rabbitmq ensure-neo4j
	@echo "🌐 Deploying in LOCAL mode (shared network)..."
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
		-e MAX_CHUNK_SIZE=$(MAX_CHUNK_SIZE) \
		-e CHUNK_OVERLAP=$(CHUNK_OVERLAP) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)
