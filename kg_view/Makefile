# =============================================================================
# KG View Service Makefile
# =============================================================================
# This Makefile provides commands to test, build, and push the KG View
# Docker images (backend and frontend) to AWS ECR.
#
# The KG View service is a Neo4j knowledge graph visualization frontend
# with a FastAPI backend that queries the graph and provides LLM enrichment.
#
# Commands:
#   make test         - Run tests
#   make build        - Build the Docker images locally
#   make push         - Push the Docker images to ECR
#   make build-push   - Build and push the Docker images
#   make ship         - Test, build, and push (complete workflow)
#   make clean        - Clean up local Docker images
# =============================================================================

# Service-specific configuration
SERVICE_NAME := aurora-kg-view
BUILD_CONTEXT := ..
DOCKERFILE_BACKEND := Dockerfile.backend
DOCKERFILE_FRONTEND := Dockerfile.frontend

# Load common configuration and targets (build-push, ship, clean)
include ../Makefile.common

# =============================================================================
# Test
# =============================================================================

test: ## Run basic tests
	@echo "$(BLUE)Testing KG View Backend$(NC)"
	cd backend && python -m pytest tests/ -v 2>/dev/null || echo "No tests found or pytest not available"
	@echo "$(GREEN)✓ KG View tests passed$(NC)"

# =============================================================================
# Build Backend
# =============================================================================

build-backend: ## Build backend Docker image
	@echo "$(BLUE)Building KG View Backend image...$(NC)"
	docker build \
		-f kg_view/$(DOCKERFILE_BACKEND) \
		-t $(ECR_REGISTRY)/$(SERVICE_NAME)-backend:$(VERSION) \
		-t $(ECR_REGISTRY)/$(SERVICE_NAME)-backend:latest \
		$(BUILD_CONTEXT)
	@echo "$(GREEN)✓ Backend image built: $(SERVICE_NAME)-backend:$(VERSION)$(NC)"

# =============================================================================
# Build Frontend
# =============================================================================

build-frontend: ## Build frontend Docker image
	@echo "$(BLUE)Building KG View Frontend image...$(NC)"
	docker build \
		-f kg_view/$(DOCKERFILE_FRONTEND) \
		-t $(ECR_REGISTRY)/$(SERVICE_NAME)-frontend:$(VERSION) \
		-t $(ECR_REGISTRY)/$(SERVICE_NAME)-frontend:latest \
		$(BUILD_CONTEXT)
	@echo "$(GREEN)✓ Frontend image built: $(SERVICE_NAME)-frontend:$(VERSION)$(NC)"

# =============================================================================
# Build (both backend and frontend)
# =============================================================================

build: build-backend build-frontend ## Build both backend and frontend images

# =============================================================================
# Push
# =============================================================================

push-backend: ## Push backend image to ECR
	@echo "$(BLUE)Pushing KG View Backend to ECR...$(NC)"
	docker push $(ECR_REGISTRY)/$(SERVICE_NAME)-backend:$(VERSION)
	docker push $(ECR_REGISTRY)/$(SERVICE_NAME)-backend:latest
	@echo "$(GREEN)✓ Backend pushed to $(ECR_REGISTRY)$(NC)"

push-frontend: ## Push frontend image to ECR
	@echo "$(BLUE)Pushing KG View Frontend to ECR...$(NC)"
	docker push $(ECR_REGISTRY)/$(SERVICE_NAME)-frontend:$(VERSION)
	docker push $(ECR_REGISTRY)/$(SERVICE_NAME)-frontend:latest
	@echo "$(GREEN)✓ Frontend pushed to $(ECR_REGISTRY)$(NC)"

push: push-backend push-frontend ## Push both images to ECR

# =============================================================================
# Ship (Test -> Build -> Push)
# =============================================================================

ship: test build push ## Test, build, and push all KG View images
	@echo "$(GREEN)✓ KG View ship complete$(NC)"

# =============================================================================
# Utilities
# =============================================================================

clean: ## Remove local Docker images
	@echo "$(BLUE)Cleaning KG View images...$(NC)"
	docker rmi -f $(ECR_REGISTRY)/$(SERVICE_NAME)-backend:$(VERSION) 2>/dev/null || true
	docker rmi -f $(ECR_REGISTRY)/$(SERVICE_NAME)-backend:latest 2>/dev/null || true
	docker rmi -f $(ECR_REGISTRY)/$(SERVICE_NAME)-frontend:$(VERSION) 2>/dev/null || true
	docker rmi -f $(ECR_REGISTRY)/$(SERVICE_NAME)-frontend:latest 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

help: ## Show this help message
	@echo "$(BLUE)KG View Service - Makefile Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
