.PHONY: help build clean test test-verbose test-similarity test-similarity-local test-thresholds test-case neo4j-start neo4j-stop neo4j-wait

# Load environment variables from root .env file
include ../.env
export

# Docker configuration
DOCKER_IMAGE = neo4j-client-tests
NEO4J_CONTAINER = neo4j-test-instance
DOCKER_NETWORK = aurora-test-network

# Test environment configuration
TEST_NEO4J_URI = bolt://$(NEO4J_CONTAINER):7687
TEST_NEO4J_USER = $(NEO4J_USER)
TEST_NEO4J_PASSWORD = $(NEO4J_PASSWORD)
TEST_NEO4J_DATABASE = $(NEO4J_DATABASE)

DOCKER_RUN = docker run --rm \
	--network $(DOCKER_NETWORK) \
	-v $(PWD):/app \
	-e NEO4J_URI=$(TEST_NEO4J_URI) \
	-e NEO4J_USER=$(TEST_NEO4J_USER) \
	-e NEO4J_PASSWORD=$(TEST_NEO4J_PASSWORD) \
	-e NEO4J_DATABASE=$(TEST_NEO4J_DATABASE) \
	-e AZURE_OPENAI_API_KEY=$(AZURE_OPENAI_API_KEY) \
	-e AZURE_OPENAI_ENDPOINT=$(AZURE_OPENAI_ENDPOINT) \
	-e AZURE_OPENAI_API_VERSION=$(AZURE_OPENAI_API_VERSION) \
	-e AZURE_OPENAI_DEPLOYMENT=$(AZURE_OPENAI_DEPLOYMENT) \
	-e LLM_MAX_TOKENS=$(LLM_MAX_TOKENS) \
	-e LLM_TEMPERATURE=$(LLM_TEMPERATURE) \
	-e EMBEDDING_PROVIDER=$(EMBEDDING_PROVIDER) \
	-e EMBEDDING_MODEL=$(EMBEDDING_MODEL) \
	$(DOCKER_IMAGE)

DOCKER_RUN_NO_ENV = docker run --rm -v $(PWD):/app $(DOCKER_IMAGE)

# Default target
help:
	@echo "Neo4j Client Test Commands (All tests run in Docker)"
	@echo ""
	@echo "Run Tests (auto-manages Neo4j instance):"
	@echo "  make test               - Run all tests (summary)"
	@echo "  make test-verbose       - Run all tests with detailed output"
	@echo "  make test-similarity    - Run similarity tests (in Docker, no Neo4j)"
	@echo "  make test-similarity-local - Run similarity tests locally (fastest)"
	@echo "  make test-thresholds    - Run threshold sensitivity analysis"
	@echo "  make test-case NAME=... - Run specific test case"
	@echo ""
	@echo "Neo4j Management:"
	@echo "  make neo4j-start        - Start temporary Neo4j instance"
	@echo "  make neo4j-stop         - Stop and remove Neo4j instance"
	@echo ""
	@echo "Utilities:"
	@echo "  make build              - Build Docker test image"
	@echo "  make clean              - Remove Docker image and cache"
	@echo ""
	@echo "Examples:"
	@echo "  make test-verbose"
	@echo "  make test-case NAME='IEEE 802.11 Variants - Should Deduplicate'"
	@echo ""
	@echo "Note: All Docker-based tests rebuild the image automatically"
	@echo "      Tests automatically start/stop a temporary Neo4j instance"
	@echo "      Azure OpenAI credentials are loaded from root .env for LLM judgement"

# Internal target to ensure network exists
.ensure-network:
	@if ! docker network inspect $(DOCKER_NETWORK) >/dev/null 2>&1; then \
		echo "Creating test network..."; \
		docker network create $(DOCKER_NETWORK); \
	fi

# Start Neo4j test instance
neo4j-start: .ensure-network
	@echo "Starting temporary Neo4j instance..."
	@docker run -d \
		--name $(NEO4J_CONTAINER) \
		--network $(DOCKER_NETWORK) \
		-e NEO4J_AUTH=$(NEO4J_USER)/$(NEO4J_PASSWORD) \
		-e NEO4J_PLUGINS='["apoc"]' \
		$(NEO4J_IMAGE) >/dev/null
	@$(MAKE) neo4j-wait

# Wait for Neo4j to be ready
neo4j-wait:
	@echo -n "Waiting for Neo4j to be ready"
	@max_attempts=30; \
	attempt=0; \
	while [ $$attempt -lt $$max_attempts ]; do \
		if docker exec $(NEO4J_CONTAINER) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "RETURN 1" >/dev/null 2>&1; then \
			echo ""; \
			echo "✅ Neo4j is ready!"; \
			exit 0; \
		fi; \
		echo -n "."; \
		sleep 1; \
		attempt=$$((attempt + 1)); \
	done; \
	echo ""; \
	echo "❌ Neo4j failed to start in time"; \
	exit 1

# Stop Neo4j test instance
neo4j-stop:
	@echo "Stopping Neo4j test instance..."
	@docker stop $(NEO4J_CONTAINER) >/dev/null 2>&1 || true
	@docker rm $(NEO4J_CONTAINER) >/dev/null 2>&1 || true
	@echo "✅ Neo4j stopped"

# Build Docker image
build:
	@echo "Building Docker test image..."
	@docker build -f tests/Dockerfile -t $(DOCKER_IMAGE) .
	@echo ""
	@echo "✅ Build complete!"

# Run all tests (summary only)
test: build
	@$(MAKE) neo4j-start
	@echo "Running all tests..."
	@$(DOCKER_RUN) python test_deduplication.py; \
	result=$$?; \
	$(MAKE) neo4j-stop; \
	exit $$result

# Run all tests with verbose output
test-verbose: build
	@$(MAKE) neo4j-start
	@echo "Running all tests with verbose output..."
	@$(DOCKER_RUN) python test_deduplication.py --verbose; \
	result=$$?; \
	$(MAKE) neo4j-stop; \
	exit $$result

# Run similarity function tests (no Neo4j required)
test-similarity: build
	@echo "Running similarity function tests (no Neo4j required)..."
	@echo "Testing algorithms directly from deduplicator with JSON test cases"
	@echo ""
	@$(DOCKER_RUN_NO_ENV) python test_similarity_functions.py

# Run similarity tests locally (fastest, no Docker)
test-similarity-local:
	@echo "Running similarity function tests locally..."
	@echo "Testing algorithms directly from deduplicator with JSON test cases"
	@echo ""
	@cd tests && python test_similarity_functions.py

# Run threshold sensitivity analysis
test-thresholds: build
	@$(MAKE) neo4j-start
	@echo "Running threshold sensitivity analysis..."
	@$(DOCKER_RUN) python test_deduplication.py --thresholds --verbose; \
	result=$$?; \
	$(MAKE) neo4j-stop; \
	exit $$result

# Run specific test case
test-case: build
	@ifndef NAME
		$(error ❌ NAME is required. Usage: make test-case NAME="Test Case Name")
	@endif
	@$(MAKE) neo4j-start
	@echo "Running test case: $(NAME)"
	@$(DOCKER_RUN) python test_deduplication.py --test-case "$(NAME)" --verbose; \
	result=$$?; \
	$(MAKE) neo4j-stop; \
	exit $$result

# Clean up Docker image and cache
clean:
	@echo "Cleaning up..."
	@$(MAKE) neo4j-stop 2>/dev/null || true
	@docker network rm $(DOCKER_NETWORK) 2>/dev/null || true
	@docker rmi $(DOCKER_IMAGE) 2>/dev/null || echo "  (Image not found, skipping)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Clean complete!"
