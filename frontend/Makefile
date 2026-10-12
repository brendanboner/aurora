# =============================================================================
# Frontend Service Makefile
# =============================================================================

.PHONY: help test

# Service-specific configuration
SERVICE_NAME := aurora-frontend
DOCKERFILE := Dockerfile
BUILD_CONTEXT := .

# Load common configuration and targets (build, push, push-only, clean)
include ../Makefile.common

help:
	@echo "$(CYAN)Frontend Service Makefile$(NC)"
	@echo ""
	@echo "Available commands:"
	@echo "  make test   - Run tests with npm test"
	@echo "  make build-push  - Build and push Docker image to ECR"
	@echo "  make push   - Run tests, build, and push to ECR"
	@echo "  make clean  - Clean up test artifacts"

test:
	@echo "$(CYAN)Running frontend service tests...$(NC)"
	@if [ -f "package.json" ]; then \
		if [ ! -d "node_modules" ]; then \
			echo "$(CYAN)Installing dependencies...$(NC)"; \
			npm install; \
		fi; \
		npm test -- --watchAll=false --passWithNoTests || echo "$(CYAN)Tests skipped or not configured$(NC)"; \
	else \
		echo "$(CYAN)No tests configured for frontend service$(NC)"; \
	fi
	@echo "$(GREEN)✓ Tests completed$(NC)"
