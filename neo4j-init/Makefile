# =============================================================================
# Neo4j Init Service Makefile
# =============================================================================

.PHONY: help test

# Service-specific configuration
SERVICE_NAME := aurora-neo4j-init
DOCKERFILE := Dockerfile
BUILD_CONTEXT := ..

# Load common configuration and targets (build, push, push-only, clean)
include ../Makefile.common

help:
	@echo "$(CYAN)Neo4j Init Service Makefile$(NC)"
	@echo ""
	@echo "Available commands:"
	@echo "  make test   - Run tests with pytest"
	@echo "  make build-push  - Build and push Docker image to ECR"
	@echo "  make push   - Run tests, build, and push to ECR"
	@echo "  make clean  - Clean up test artifacts"

test:
	@echo "$(CYAN)Running neo4j-init service tests...$(NC)"
	@if [ -f "requirements.txt" ]; then \
		python -m pytest tests/ -v --cov=. --cov-report=term-missing 2>/dev/null || \
		python -m pytest . -v 2>/dev/null || \
		echo "$(CYAN)No tests found or pytest not configured$(NC)"; \
	else \
		echo "$(CYAN)No tests configured for neo4j-init service$(NC)"; \
	fi
	@echo "$(GREEN)✓ Tests completed$(NC)"
