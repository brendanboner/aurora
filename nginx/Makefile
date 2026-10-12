# =============================================================================
# Nginx Service Makefile
# =============================================================================
# This Makefile provides commands to test, build, and push the nginx Docker
# image to AWS ECR.
#
# The nginx service is a reverse proxy with Let's Encrypt SSL support for
# production deployments.
#
# Commands:
#   make test         - Run basic configuration tests
#   make build        - Build the Docker image locally
#   make push         - Push the Docker image to ECR
#   make build-push   - Build and push the Docker image
#   make ship         - Test, build, and push (complete workflow)
#   make clean        - Clean up local Docker images
# =============================================================================

# Service-specific configuration
SERVICE_NAME := aurora-nginx
BUILD_CONTEXT := ..
DOCKERFILE := Dockerfile.cloudfront

# Load common configuration and targets (build-push, ship, clean)
include ../Makefile.common

# =============================================================================
# Test
# =============================================================================

test:
	@echo "$(CYAN)Testing nginx configuration...$(NC)"
	@echo "$(GREEN)→ Validating nginx.cloudfront.conf syntax...$(NC)"
	@docker run --rm \
		--add-host=auth:127.0.0.1 \
		--add-host=kg-view-frontend:127.0.0.1 \
		-v $(PWD)/nginx.cloudfront.conf:/etc/nginx/conf.d/default.conf:ro \
		nginx:alpine nginx -t
	@echo "$(GREEN)→ Validating Dockerfile.cloudfront exists...$(NC)"
	@test -f $(DOCKERFILE) || (echo "$(RED)✗ $(DOCKERFILE) not found$(NC)" && exit 1)
	@echo "$(GREEN)✓ All nginx configuration tests passed$(NC)"

# =============================================================================
# Common targets (build-push, ship, clean) inherited from Makefile.common
# =============================================================================

# =============================================================================
# Help
# =============================================================================

help:
	@echo "$(CYAN)Nginx Service Makefile$(NC)"
	@echo ""
	@echo "$(GREEN)Commands:$(NC)"
	@echo "  make test         - Run configuration tests"
	@echo "  make build-push   - Build and push to ECR (from Makefile.common)"
	@echo "  make ship         - Test, build, and push (from Makefile.common)"
	@echo "  make clean        - Clean artifacts (from Makefile.common)"
	@echo ""
	@echo "$(GREEN)Configuration:$(NC)"
	@echo "  SERVICE:  $(SERVICE_NAME)"
	@echo "  IMAGE:    $(IMAGE_NAME)"
	@echo "  VERSION:  $(VERSION)"

.PHONY: test help
