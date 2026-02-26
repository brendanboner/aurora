# =============================================================================
# Aurora - Root Makefile
# =============================================================================
# This Makefile provides commands to test, build, and push Docker images
# for all Aurora services to AWS ECR.
#
# Quick Start:
#   1. Copy .env.example to .env and add your ECR_REGISTRY
#   2. Run: make aws-login (authenticate to ECR)
#   3. Run: make test-all (run all tests)
#   4. Run: make ship-all (test, build, and ship all services to ECR)
#
# Main Commands:
#   make test-all         - Run tests for all services
#   make build-push-all   - Build and push all service images
#   make ship-all         - Test, build, and ship all services to ECR
#   make aws-login            - Login to AWS ECR
#
# Configuration:
#   ECR_REGISTRY and AWS_REGION are loaded from .env file
#   VERSION is automatically determined from git SHA
# =============================================================================

.PHONY: help test-all build-push-all ship-all aws-login connect_aurora_ec2clean-all \
        test-auth test-backend test-curator test-digester test-retriever test-frontend test-neo4j-init test-nginx test-oracle test-content-creator test-kg-view \
        build-push-auth build-push-backend build-push-curator build-push-digester build-push-retriever build-push-frontend build-push-neo4j-init build-push-nginx build-push-oracle build-push-content-creator build-push-kg-view \
        ship-auth ship-backend ship-curator ship-digester ship-retriever ship-frontend ship-neo4j-init ship-nginx ship-oracle ship-content-creator ship-kg-view \
        dev

# Load common configuration (colors, ECR, region)
# Note: Root Makefile overrides the service-level targets with orchestration targets
include Makefile.common

# Services
SERVICES := auth backend curator digester retriever frontend neo4j-init nginx oracle content_creator_service kg_view

# =============================================================================
# Help
# =============================================================================

help:
	@echo "$(CYAN)Aurora Makefile Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Development:$(NC)"
	@echo "  make dev               - Start development environment"
	@echo "  make migrate           - Run PostgreSQL database migrations"
	@echo "  make migrate-status    - Show PostgreSQL migration status"
	@echo ""
	@echo "$(GREEN)Production Deployment:$(NC)"
	@echo "  See prod-deployment/ folder for EC2 deployment"
	@echo "  - prod-deployment/Makefile has deployment commands"
	@echo "  - prod-deployment/README.md has complete guide"
	@echo ""
	@echo "$(GREEN)Testing & ECR Deployment:$(NC)"
	@echo "  make test-all          - Run tests for all services"
	@echo "  make build-push-all    - Build and push all service images to ECR"
	@echo "  make ship-all          - Test, build, and ship all services to ECR"
	@echo "  make aws-login             - Login to AWS ECR"
	@echo "  make connect_aurora_ec2 - Connect to Aurora EC2 instance via SSM"
	@echo ""
	@echo "$(GREEN)Service-Specific Commands:$(NC)"
	@echo "  make test-<service>         - Run tests for a specific service"
	@echo "  make build-push-<service>   - Build and push a specific service image"
	@echo "  make ship-<service>         - Test, build, and ship a specific service"
	@echo ""
	@echo "  Or from service directory:"
	@echo "    cd <service> && make test"
	@echo "    cd <service> && make build-push"
	@echo "    cd <service> && make ship"
	@echo ""
	@echo "$(GREEN)Available Services:$(NC)"
	@echo "  auth backend curator digester retriever frontend neo4j-init nginx oracle content_creator_service kg_view"
	@echo ""
	@echo "$(GREEN)Utility Commands:$(NC)"
	@echo "  make clean-all         - Clean up temporary files in all services"
	@echo ""
	@echo "$(YELLOW)Configuration:$(NC)"
	@echo "  ECR_REGISTRY: $(ECR_REGISTRY)"
	@echo "  AWS_REGION:   $(AWS_REGION)"
	@echo "  VERSION:      $(VERSION) (git SHA)"

# =============================================================================
# Test All Services
# =============================================================================

test-all: test-auth test-backend test-curator test-digester test-retriever test-frontend test-neo4j-init test-oracle test-content-creator test-kg-view
	@echo "$(GREEN)✓ All tests completed$(NC)"

test-auth:
	@echo "$(CYAN)Running tests for auth service...$(NC)"
	@cd auth && $(MAKE) test

test-backend:
	@echo "$(CYAN)Running tests for backend service...$(NC)"
	@cd backend && $(MAKE) test

test-curator:
	@echo "$(CYAN)Running tests for curator service...$(NC)"
	@cd curator && $(MAKE) test

test-digester:
	@echo "$(CYAN)Running tests for digester service...$(NC)"
	@cd digester && $(MAKE) test

test-retriever:
	@echo "$(CYAN)Running tests for retriever service...$(NC)"
	@cd retriever && $(MAKE) test

test-frontend:
	@echo "$(CYAN)Running tests for frontend service...$(NC)"
	@cd frontend && $(MAKE) test

test-neo4j-init:
	@echo "$(CYAN)Running tests for neo4j-init service...$(NC)"
	@cd neo4j-init && $(MAKE) test

test-nginx:
	@echo "$(CYAN)Running tests for nginx service...$(NC)"
	@cd nginx && $(MAKE) test

test-oracle:
	@echo "$(CYAN)Running tests for oracle service...$(NC)"
	@cd oracle && $(MAKE) test

test-content-creator:
	@echo "$(CYAN)Running tests for content-creator service...$(NC)"
	@cd content_creator_service && $(MAKE) test

test-kg-view:
	@echo "$(CYAN)Running tests for kg-view service...$(NC)"
	@cd kg_view && $(MAKE) test

# =============================================================================
# Build and Push All Services
# =============================================================================

build-push-all: build-push-auth build-push-backend build-push-curator build-push-digester build-push-retriever build-push-frontend build-push-neo4j-init build-push-nginx build-push-oracle build-push-content-creator build-push-kg-view
	@echo "$(GREEN)✓ All images built and pushed successfully$(NC)"

build-push-auth:
	@echo "$(CYAN)Building and pushing auth service...$(NC)"
	@cd auth && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-backend:
	@echo "$(CYAN)Building and pushing backend service...$(NC)"
	@cd backend && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-curator:
	@echo "$(CYAN)Building and pushing curator service...$(NC)"
	@cd curator && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-digester:
	@echo "$(CYAN)Building and pushing digester service...$(NC)"
	@cd digester && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-retriever:
	@echo "$(CYAN)Building and pushing retriever service...$(NC)"
	@cd retriever && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-frontend:
	@echo "$(CYAN)Building and pushing frontend service...$(NC)"
	@cd frontend && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-neo4j-init:
	@echo "$(CYAN)Building and pushing neo4j-init service...$(NC)"
	@cd neo4j-init && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-nginx:
	@echo "$(CYAN)Building and pushing nginx service...$(NC)"
	@cd nginx && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-oracle:
	@echo "$(CYAN)Building and pushing oracle service...$(NC)"
	@cd oracle && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-content-creator:
	@echo "$(CYAN)Building and pushing content-creator service...$(NC)"
	@cd content_creator_service && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

build-push-kg-view:
	@echo "$(CYAN)Building and pushing kg-view service...$(NC)"
	@cd kg_view && $(MAKE) build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION)

# =============================================================================
# Ship All Services (with tests and builds)
# =============================================================================

ship-all: test-all build-push-all
	@echo "$(GREEN)✓ All services tested, built, and shipped to ECR$(NC)"

ship-auth:
	@echo "$(CYAN)Testing, building, and shipping auth service...$(NC)"
	@cd auth && $(MAKE) ship

ship-backend:
	@echo "$(CYAN)Testing, building, and shipping backend service...$(NC)"
	@cd backend && $(MAKE) ship

ship-curator:
	@echo "$(CYAN)Testing, building, and shipping curator service...$(NC)"
	@cd curator && $(MAKE) ship

ship-digester:
	@echo "$(CYAN)Testing, building, and shipping digester service...$(NC)"
	@cd digester && $(MAKE) ship

ship-retriever:
	@echo "$(CYAN)Testing, building, and shipping retriever service...$(NC)"
	@cd retriever && $(MAKE) ship

ship-frontend:
	@echo "$(CYAN)Testing, building, and shipping frontend service...$(NC)"
	@cd frontend && $(MAKE) ship

ship-neo4j-init:
	@echo "$(CYAN)Testing, building, and shipping neo4j-init service...$(NC)"
	@cd neo4j-init && $(MAKE) ship

ship-nginx:
	@echo "$(CYAN)Testing, building, and shipping nginx service...$(NC)"
	@cd nginx && $(MAKE) ship

ship-oracle:
	@echo "$(CYAN)Testing, building, and shipping oracle service...$(NC)"
	@cd oracle && $(MAKE) ship

ship-content-creator:
	@echo "$(CYAN)Testing, building, and shipping content-creator service...$(NC)"
	@cd content_creator_service && $(MAKE) ship

ship-kg-view:
	@echo "$(CYAN)Testing, building, and shipping kg-view service...$(NC)"
	@cd kg_view && $(MAKE) ship

# =============================================================================
# AWS ECR Login
# =============================================================================

# Will need to have AWS SSO configured with a profile named in AWS_SSO_PROFILE
aws-login:
	@echo "$(CYAN)Starting AWS SSO login...$(NC)"
	@aws sso login --profile $(AWS_SSO_PROFILE)
	@echo "$(CYAN)Logging into AWS ECR...$(NC)"
	@aws ecr get-login-password --region $(AWS_REGION) --profile $(AWS_SSO_PROFILE) | docker login --username AWS --password-stdin $(ECR_REGISTRY)
	@echo "$(GREEN)✓ Successfully logged into ECR$(NC)"

connect_aurora_ec2:
	@echo "$(CYAN)Connecting to Aurora EC2 instance...$(NC)"
	@echo "$(CYAN)To switch to ec2-user run 'sudo -i -u ec2-user' after connecting$(NC)"
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--profile $(AWS_SSO_PROFILE) \
		--region $(AWS_REGION)


# =============================================================================
# Environment Management
# =============================================================================

dev:
	@echo "$(CYAN)Starting development environment...$(NC)"
	@docker compose up --build -d
	@echo "$(GREEN)✓ Development environment started$(NC)"
	@echo "  Frontend: http://localhost:3000"
	@echo "  Auth:     http://localhost:8000"
	@echo ""

# =============================================================================
# Database Migrations
# =============================================================================

migrate:
	@echo "$(CYAN)Running database migrations...$(NC)"
	@./prod-deployment/scripts/migrate.sh
	@echo "$(GREEN)✓ Migrations complete$(NC)"

migrate-status:
	@echo "$(CYAN)Checking migration status...$(NC)"
	@./prod-deployment/scripts/migrate.sh --status

# =============================================================================
# Neo4j Graph Migrations
# =============================================================================

# =============================================================================
# Cleanup
# =============================================================================

clean-all:
	@echo "$(CYAN)Cleaning all services...$(NC)"
	@for service in $(SERVICES); do \
		echo "$(CYAN)Cleaning $$service...$(NC)"; \
		cd $$service && $(MAKE) clean && cd ..; \
	done
	@echo "$(GREEN)✓ All services cleaned$(NC)"
