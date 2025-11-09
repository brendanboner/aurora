# Shared Docker Utilities for Aurora Microservices
# Include this in your service Makefile with: include ../common/make-utils.mk
#
# Required variables from service Makefile:
#   SERVICE_NAME - The name of the service (e.g., "retriever", "digester")
#
# Auto-generated variables (available in service Makefiles):
#   Container names:
#     ISOLATED_RABBITMQ_CONTAINER, ISOLATED_NEO4J_CONTAINER, ISOLATED_SERVICE_CONTAINER
#     SHARED_RABBITMQ_CONTAINER, SHARED_NEO4J_CONTAINER, SHARED_SERVICE_CONTAINER
#   Network name:
#     ISOLATED_NETWORK
#   Image name:
#     SERVICE_IMAGE

# Generate container and network names based on SERVICE_NAME
# Isolated environment (unique per service)
ISOLATED_NETWORK := $(SERVICE_NAME)-network-isolated
ISOLATED_RABBITMQ_CONTAINER := $(SERVICE_NAME)-rabbitmq-isolated
ISOLATED_NEO4J_CONTAINER := $(SERVICE_NAME)-neo4j-isolated
ISOLATED_SERVICE_CONTAINER := $(SERVICE_NAME)-service-isolated

# Shared environment (shared across services)
SHARED_RABBITMQ_CONTAINER := aurora-rabbitmq
SHARED_NEO4J_CONTAINER := aurora-neo4j
SHARED_SERVICE_CONTAINER := aurora-$(SERVICE_NAME)

# Docker images
SERVICE_IMAGE := $(SERVICE_NAME)-image

#==============================================================================
# SHARED CLEANUP TARGETS
# These can be called directly from service Makefiles
#==============================================================================

# Clean isolated environment (cleans ALL isolated environments across all services)
.PHONY: clean-isolated
clean-isolated:
	@echo "🧹 Cleaning ALL isolated environments..."
	@docker ps -a --filter "name=-isolated" --format "{{.Names}}" | xargs -r docker stop 2>/dev/null || true
	@docker ps -a --filter "name=-isolated" --format "{{.Names}}" | xargs -r docker rm 2>/dev/null || true
	@docker network ls --filter "name=-isolated" --format "{{.Name}}" | xargs -r docker network rm 2>/dev/null || true
	@echo "✅ All isolated environments cleaned"

# Clean shared resources (careful - affects all services)
.PHONY: clean-shared
clean-shared:
	@echo "⚠️  Cleaning SHARED resources (affects all services)..."
	@docker stop $(SHARED_RABBITMQ_CONTAINER) 2>/dev/null || true
	@docker rm $(SHARED_RABBITMQ_CONTAINER) 2>/dev/null || true
	@docker stop $(SHARED_NEO4J_CONTAINER) 2>/dev/null || true
	@docker rm $(SHARED_NEO4J_CONTAINER) 2>/dev/null || true
	@docker stop $(SHARED_SERVICE_CONTAINER) 2>/dev/null || true
	@docker rm $(SHARED_SERVICE_CONTAINER) 2>/dev/null || true
	@docker network rm $(DOCKER_NETWORK) 2>/dev/null || true

# Nuke everything - removes all containers, networks, images, and prunes system (full reset)
.PHONY: nuke
nuke: clean-isolated clean-shared
	@echo "💥 Nuking everything (removing all service and infrastructure images)..."
	@echo "🗑️  Removing Aurora service images..."
	@docker rmi retriever-image 2>/dev/null || true
	@docker rmi digester-image 2>/dev/null || true
	@echo "🗑️  Removing shared infrastructure images..."
	@docker rmi $(RABBITMQ_IMAGE) 2>/dev/null || true
	@docker rmi $(NEO4J_IMAGE) 2>/dev/null || true
	@echo "🧹 Running system cleanup..."
	@docker system prune -f
	@echo "✅ Nuclear cleanup complete!"

#==============================================================================
# SHARED DEPENDENCY MANAGEMENT TARGETS
# These ensure dependencies are running (idempotent)
#==============================================================================

# Ensure shared network exists
# Requires: DOCKER_NETWORK
.PHONY: ensure-network
ensure-network:
	@docker network inspect $(DOCKER_NETWORK) >/dev/null 2>&1 || \
		(echo "📡 Creating shared network $(DOCKER_NETWORK)..." && docker network create $(DOCKER_NETWORK))

# Ensure shared RabbitMQ is running (idempotent)
# Requires: RABBITMQ_USER, RABBITMQ_PASSWORD, RABBITMQ_IMAGE, RABBITMQ_AMQP_PORT, RABBITMQ_MANAGEMENT_PORT
.PHONY: ensure-rabbitmq
ensure-rabbitmq: ensure-network
	@if docker ps -a --filter "name=$(SHARED_RABBITMQ_CONTAINER)" --format "{{.Names}}" | grep -q "^$(SHARED_RABBITMQ_CONTAINER)$$"; then \
		if ! docker ps --filter "name=$(SHARED_RABBITMQ_CONTAINER)" --filter "status=running" --format "{{.Names}}" | grep -q "^$(SHARED_RABBITMQ_CONTAINER)$$"; then \
			echo "▶️  Starting existing RabbitMQ..."; \
			docker start $(SHARED_RABBITMQ_CONTAINER); \
		else \
			echo "✅ RabbitMQ already running"; \
		fi \
	else \
		echo "🐰 Creating new RabbitMQ container..."; \
		docker run -d \
			--name $(SHARED_RABBITMQ_CONTAINER) \
			--network $(DOCKER_NETWORK) \
			-p $(RABBITMQ_AMQP_PORT):5672 \
			-p $(RABBITMQ_MANAGEMENT_PORT):15672 \
			-e RABBITMQ_DEFAULT_USER=$(RABBITMQ_USER) \
			-e RABBITMQ_DEFAULT_PASS=$(RABBITMQ_PASSWORD) \
			$(RABBITMQ_IMAGE); \
	fi
	@$(MAKE) wait-for-rabbitmq RABBITMQ_CONTAINER=$(SHARED_RABBITMQ_CONTAINER)

# Ensure shared Neo4j is running (idempotent)
# Requires: NEO4J_USER, NEO4J_PASSWORD, NEO4J_IMAGE, NEO4J_HTTP_PORT, NEO4J_BOLT_PORT
.PHONY: ensure-neo4j
ensure-neo4j: ensure-network
	@if docker ps -a --filter "name=$(SHARED_NEO4J_CONTAINER)" --format "{{.Names}}" | grep -q "^$(SHARED_NEO4J_CONTAINER)$$"; then \
		if ! docker ps --filter "name=$(SHARED_NEO4J_CONTAINER)" --filter "status=running" --format "{{.Names}}" | grep -q "^$(SHARED_NEO4J_CONTAINER)$$"; then \
			echo "▶️  Starting existing Neo4j..."; \
			docker start $(SHARED_NEO4J_CONTAINER); \
		else \
			echo "✅ Neo4j already running"; \
		fi \
	else \
		echo "🗄️  Creating new Neo4j container..."; \
		docker run -d \
			--name $(SHARED_NEO4J_CONTAINER) \
			--network $(DOCKER_NETWORK) \
			-p $(NEO4J_HTTP_PORT):7474 \
			-p $(NEO4J_BOLT_PORT):7687 \
			-e NEO4J_AUTH=$(NEO4J_USER)/$(NEO4J_PASSWORD) \
			-e NEO4J_PLUGINS='["apoc"]' \
			$(NEO4J_IMAGE); \
	fi
	@$(MAKE) wait-for-neo4j NEO4J_CONTAINER=$(SHARED_NEO4J_CONTAINER)

#==============================================================================
# SHARED HEALTH CHECK TARGETS
# These wait for services to be ready
#==============================================================================

# Wait for RabbitMQ to be ready with health check
# Requires: RABBITMQ_CONTAINER (passed as parameter)
.PHONY: wait-for-rabbitmq
wait-for-rabbitmq:
	@echo "⏳ Waiting for $(RABBITMQ_CONTAINER) to be ready..."
	@timeout=60; \
	while [ $$timeout -gt 0 ]; do \
		if docker logs $(RABBITMQ_CONTAINER) 2>&1 | grep -q "Server startup complete"; then \
			echo "✅ $(RABBITMQ_CONTAINER) is ready"; \
			exit 0; \
		fi; \
		if ! docker ps --filter "name=$(RABBITMQ_CONTAINER)" --filter "status=running" --format "{{.Names}}" | grep -q "^$(RABBITMQ_CONTAINER)$$"; then \
			echo "❌ $(RABBITMQ_CONTAINER) stopped or crashed"; \
			exit 1; \
		fi; \
		sleep 2; \
		timeout=$$((timeout-2)); \
	done; \
	echo "❌ $(RABBITMQ_CONTAINER) failed to start in time"; exit 1

# Wait for Neo4j to be ready with health check
# Requires: NEO4J_CONTAINER (passed as parameter), NEO4J_USER, NEO4J_PASSWORD
.PHONY: wait-for-neo4j
wait-for-neo4j:
	@echo "⏳ Waiting for $(NEO4J_CONTAINER) to be ready..."
	@timeout=90; \
	while [ $$timeout -gt 0 ]; do \
		if docker exec $(NEO4J_CONTAINER) cypher-shell -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) "RETURN 1;" 2>/dev/null | grep -q "1"; then \
			echo "✅ $(NEO4J_CONTAINER) is ready"; \
			exit 0; \
		fi; \
		sleep 2; \
		timeout=$$((timeout-2)); \
	done; \
	echo "❌ $(NEO4J_CONTAINER) failed to start"; exit 1

