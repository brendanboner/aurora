# Aurora Curator Makefile

# Service identifier (used by make-utils.mk to generate container names)
SERVICE_NAME := curator

# Include master environment variables
include ../.env
export

# Include shared Docker utilities (auto-generates container/network names)
include ../common/make-utils.mk

.PHONY: help deploy-isolated deploy-shared clean-isolated clean-shared nuke validate-env \
	ensure-network ensure-neo4j wait-for-neo4j

# Default target
help:
	@echo "Aurora Curator - Available commands:"
	@echo ""
	@echo "  Deployment:"
	@echo "    make deploy-isolated        - Deploy curator in isolated environment (own network + deps)"
	@echo "    make deploy-shared          - Deploy curator on shared network (reuses existing deps)"
	@echo ""
	@echo "  Cleanup:"
	@echo "    make clean-isolated         - Clean ALL isolated environments (all services)"
	@echo "    make clean-shared           - Clean shared resources (use with caution)"
	@echo "    make nuke                   - 💥 Nuke everything (containers + images + system prune)"

# Validate environment variables
validate-env:
	@test -n "$(NEO4J_URI)" || (echo "❌ NEO4J_URI not set" && exit 1)
	@test -n "$(NEO4J_USER)" || (echo "❌ NEO4J_USER not set" && exit 1)
	@test -n "$(NEO4J_PASSWORD)" || (echo "❌ NEO4J_PASSWORD not set" && exit 1)
	@test -n "$(DOCKER_NETWORK)" || (echo "❌ DOCKER_NETWORK not set" && exit 1)
	@test -n "$(NEO4J_IMAGE)" || (echo "❌ NEO4J_IMAGE not set" && exit 1)
	@echo "✅ Environment validated"

# Deploy in complete isolation (own network + dependencies)
deploy-isolated: validate-env clean-isolated
	@echo "🔒 Deploying in ISOLATED mode..."
	@echo "📡 Creating isolated network..."
	@docker network create $(ISOLATED_NETWORK)
	@echo "🗄️  Starting isolated Neo4j..."
	@docker run -d \
		--name $(ISOLATED_NEO4J_CONTAINER) \
		--network $(ISOLATED_NETWORK) \
		-p $(ISOLATED_NEO4J_HTTP_PORT):7474 \
		-p $(ISOLATED_NEO4J_BOLT_PORT):7687 \
		-e NEO4J_AUTH=$(NEO4J_USER)/$(NEO4J_PASSWORD) \
		-e NEO4J_PLUGINS='["apoc"]' \
		$(NEO4J_IMAGE)
	@$(MAKE) wait-for-neo4j NEO4J_CONTAINER=$(ISOLATED_NEO4J_CONTAINER)
	@echo "🚀 Building and running curator (isolated)..."
	@cd .. && docker build -f curator/Dockerfile -t $(SERVICE_IMAGE) .
	@docker run --rm --name $(ISOLATED_SERVICE_CONTAINER) \
		--network $(ISOLATED_NETWORK) \
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
		-e CLUSTER_MIN_SIZE=$(CLUSTER_MIN_SIZE) \
		-e CLUSTER_MAX_SIZE=$(CLUSTER_MAX_SIZE) \
		-e CLUSTER_DISTANCE_THRESHOLD=$(CLUSTER_DISTANCE_THRESHOLD) \
		-e HIERARCHY_CONFIDENCE_THRESHOLD=$(HIERARCHY_CONFIDENCE_THRESHOLD) \
		-e ENABLE_CROSS_CLUSTER_ANALYSIS=$(ENABLE_CROSS_CLUSTER_ANALYSIS) \
		-e PROCESS_ALL_TOPICS=$(PROCESS_ALL_TOPICS) \
		-e CURATION_INTERVAL_HOURS=$(CURATION_INTERVAL_HOURS) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)

# Deploy on shared network (checks for existing dependencies)
deploy-shared: validate-env ensure-neo4j
	@echo "🌐 Deploying in SHARED mode (shared network)..."
	@echo "🚀 Building and running curator..."
	@cd .. && docker build -f curator/Dockerfile -t $(SERVICE_IMAGE) .
	@docker run --rm --name $(SHARED_SERVICE_CONTAINER) \
		--network $(DOCKER_NETWORK) \
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
		-e CLUSTER_MIN_SIZE=$(CLUSTER_MIN_SIZE) \
		-e CLUSTER_MAX_SIZE=$(CLUSTER_MAX_SIZE) \
		-e CLUSTER_DISTANCE_THRESHOLD=$(CLUSTER_DISTANCE_THRESHOLD) \
		-e HIERARCHY_CONFIDENCE_THRESHOLD=$(HIERARCHY_CONFIDENCE_THRESHOLD) \
		-e ENABLE_CROSS_CLUSTER_ANALYSIS=$(ENABLE_CROSS_CLUSTER_ANALYSIS) \
		-e PROCESS_ALL_TOPICS=$(PROCESS_ALL_TOPICS) \
		-e CURATION_INTERVAL_HOURS=$(CURATION_INTERVAL_HOURS) \
		-e LOG_LEVEL=$(LOG_LEVEL) \
		$(SERVICE_IMAGE)
