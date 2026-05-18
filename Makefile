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

.PHONY: help test-all build-push-all build-push-parallel ship-all aws-login setup-oidc gh-secrets connect_aurora_ec2clean-all \
        teams-test teams-test-stop teams-test-prod teams-test-stop-prod teams-test-tool teams-test-install \
        teams-test-announce teams-test-prod-backend teams-test-prod-oracle teams-test-prod-cc \
        test-auth test-backend test-curator test-digester test-retriever test-frontend test-neo4j-init test-nginx test-oracle test-content-creator test-kg-view \
        build-push-auth build-push-backend build-push-curator build-push-digester build-push-retriever build-push-frontend build-push-neo4j-init build-push-nginx build-push-oracle build-push-content-creator build-push-kg-view build-push-teams-agent \
        ship-auth ship-backend ship-curator ship-digester ship-retriever ship-frontend ship-neo4j-init ship-nginx ship-oracle ship-content-creator ship-kg-view \
        deploy-auth deploy-backend deploy-curator deploy-digester deploy-retriever deploy-frontend deploy-neo4j-init deploy-nginx deploy-oracle deploy-content-creator deploy-kg-view \
        release-auth release-backend release-curator release-digester release-retriever release-frontend release-neo4j-init release-nginx release-oracle release-content-creator release-kg-view \
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
	@echo "  make aws-login             - Login to AWS ECR (opens browser SSO)"
	@echo "  make setup-oidc            - One-time OIDC setup for GitHub Actions (needs admin AWS profile)"
	@echo "  make gh-secrets            - Fallback: push SSO credentials to GitHub secrets (expires ~1hr)"
	@echo "  make connect_aurora_ec2 - Connect to Aurora EC2 instance via SSM"
	@echo ""
	@echo "$(GREEN)Service-Specific Commands:$(NC)"
	@echo "  make test-<service>         - Run tests for a specific service"
	@echo "  make build-push-<service>   - Build and push a specific service image"
	@echo "  make ship-<service>         - Test, build, and push a specific service to ECR"
	@echo "  make deploy-<service>       - Pull latest image + restart on EC2 via SSM"
	@echo "  make release-<service>      - ship + deploy in one step"
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

build-push-all: build-push-auth build-push-backend build-push-curator build-push-digester build-push-retriever build-push-frontend build-push-neo4j-init build-push-nginx build-push-oracle build-push-content-creator build-push-kg-view build-push-teams-agent
	@echo "$(GREEN)✓ All images built and pushed successfully$(NC)"

# Build all services concurrently (faster, but uses more CPU/memory)
build-push-parallel:
	@echo "$(CYAN)Building all services in parallel...$(NC)"
	@for svc in auth backend curator digester retriever frontend neo4j-init nginx oracle content_creator_service kg_view; do \
		(cd $$svc && $(MAKE) -s build-push ECR_REGISTRY=$(ECR_REGISTRY) VERSION=$(VERSION) && echo "$(GREEN)✓ $$svc$(NC)") & \
	done; \
	(docker buildx build \
		--platform linux/amd64,linux/arm64 \
		-t $(ECR_REGISTRY)/aurora-teams-agent:$(VERSION) \
		-t $(ECR_REGISTRY)/aurora-teams-agent:latest \
		--push -f teams-agent/Dockerfile teams-agent/ \
		&& echo "$(GREEN)✓ teams-agent$(NC)") & \
	wait
	@echo "$(GREEN)✓ All images built and pushed in parallel$(NC)"

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

build-push-teams-agent:
	@echo "$(CYAN)Building and pushing teams-agent service (multi-platform)...$(NC)"
	docker buildx build \
		--platform linux/amd64,linux/arm64 \
		-t $(ECR_REGISTRY)/aurora-teams-agent:$(VERSION) \
		-t $(ECR_REGISTRY)/aurora-teams-agent:latest \
		--push \
		-f teams-agent/Dockerfile \
		teams-agent/
	@echo "$(GREEN)✓ teams-agent pushed: $(ECR_REGISTRY)/aurora-teams-agent:$(VERSION)$(NC)"

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
# Deploy to Production (pull latest image + restart on EC2 via SSM)
# =============================================================================
# Usage: make deploy-<service>    — pull + restart one service on EC2
#        make release-<service>   — ship (test+build+push) then deploy

EC2_DEPLOY_PATH ?= /home/ec2-user/octo-rapid-aurora/prod-deployment
EC2_COMPOSE     ?= docker compose -f docker-compose.prod.yml

# Internal macro: send a shell command to EC2 via SSM and wait for it to finish
define ssm-run
	@echo "$(CYAN)Deploying to EC2 via SSM...$(NC)"
	@CMD_ID=$$(aws ssm send-command \
		--instance-ids $(EC2_INSTANCE_ID) \
		--document-name "AWS-RunShellScript" \
		--parameters 'commands=["sudo -u ec2-user bash -c \"cd $(EC2_DEPLOY_PATH) && $(1)\""]' \
		--profile $(AWS_SSO_PROFILE) \
		--region $(AWS_REGION) \
		--output text --query 'Command.CommandId'); \
	echo "  SSM command: $$CMD_ID"; \
	STATUS="InProgress"; \
	while [ "$$STATUS" = "InProgress" ] || [ "$$STATUS" = "Pending" ]; do \
		sleep 3; \
		STATUS=$$(aws ssm get-command-invocation \
			--command-id $$CMD_ID \
			--instance-id $(EC2_INSTANCE_ID) \
			--profile $(AWS_SSO_PROFILE) \
			--region $(AWS_REGION) \
			--output text --query 'Status' 2>/dev/null || echo "Pending"); \
	done; \
	aws ssm get-command-invocation \
		--command-id $$CMD_ID \
		--instance-id $(EC2_INSTANCE_ID) \
		--profile $(AWS_SSO_PROFILE) \
		--region $(AWS_REGION) \
		--output text --query 'StandardOutputContent'; \
	if [ "$$STATUS" != "Success" ]; then \
		aws ssm get-command-invocation \
			--command-id $$CMD_ID \
			--instance-id $(EC2_INSTANCE_ID) \
			--profile $(AWS_SSO_PROFILE) \
			--region $(AWS_REGION) \
			--output text --query 'StandardErrorContent'; \
		echo "$(RED)✗ Deploy failed (status: $$STATUS)$(NC)"; exit 1; \
	fi; \
	echo "$(GREEN)✓ $@ deployed$(NC)"
endef

deploy-auth:
	$(call ssm-run,$(EC2_COMPOSE) pull auth && $(EC2_COMPOSE) up -d auth)

deploy-backend:
	$(call ssm-run,$(EC2_COMPOSE) pull backend && $(EC2_COMPOSE) up -d backend)

deploy-curator:
	$(call ssm-run,$(EC2_COMPOSE) pull curator && $(EC2_COMPOSE) up -d curator)

deploy-digester:
	$(call ssm-run,$(EC2_COMPOSE) pull digester && $(EC2_COMPOSE) up -d digester)

deploy-retriever:
	$(call ssm-run,$(EC2_COMPOSE) pull retriever && $(EC2_COMPOSE) up -d retriever)

deploy-frontend:
	$(call ssm-run,$(EC2_COMPOSE) pull frontend && $(EC2_COMPOSE) up -d frontend)

deploy-neo4j-init:
	$(call ssm-run,$(EC2_COMPOSE) pull neo4j-init && $(EC2_COMPOSE) run --rm neo4j-init)

deploy-nginx:
	$(call ssm-run,$(EC2_COMPOSE) pull nginx && $(EC2_COMPOSE) up -d nginx)

deploy-oracle:
	$(call ssm-run,$(EC2_COMPOSE) pull oracle && $(EC2_COMPOSE) up -d oracle)

deploy-content-creator:
	$(call ssm-run,$(EC2_COMPOSE) pull content_creator_service && $(EC2_COMPOSE) up -d content_creator_service)

deploy-kg-view:
	$(call ssm-run,$(EC2_COMPOSE) pull kg-view-frontend kg-view-backend && $(EC2_COMPOSE) up -d kg-view-frontend kg-view-backend)

release-auth:          ship-auth          deploy-auth
release-backend:       ship-backend       deploy-backend
release-curator:       ship-curator       deploy-curator
release-digester:      ship-digester      deploy-digester
release-retriever:     ship-retriever     deploy-retriever
release-frontend:      ship-frontend      deploy-frontend
release-neo4j-init:    ship-neo4j-init    deploy-neo4j-init
release-nginx:         ship-nginx         deploy-nginx
release-oracle:        ship-oracle        deploy-oracle
release-content-creator: ship-content-creator deploy-content-creator
release-kg-view:       ship-kg-view       deploy-kg-view

# Reset WBA Extranet child community last_scraped_at so the next scrape treats
# every community as a first run (30-day lookback instead of 1-day incremental).
# Use after a failed/empty scrape that incorrectly set the timestamps.
reset-wba-communities:
	$(call ssm-run,docker exec aurora-neo4j cypher-shell -u $$NEO4J_USER -p $$NEO4J_PASSWORD "MATCH (d:DataSource) WHERE d.datasource_id STARTS WITH 'wba_extranet_' SET d.last_scraped_at = null RETURN count(d) AS reset;")

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

# One-time OIDC setup — requires AdministratorAccess (not PowerUserAccess)
# Creates an IAM OIDC provider + deploy role scoped to this repo's main branch.
# After this runs once, GitHub Actions authenticates automatically — no stored keys.
setup-oidc:
	@echo "$(CYAN)Setting up GitHub Actions OIDC authentication...$(NC)"
	@echo "$(YELLOW)Note: requires AdministratorAccess or IAM write permissions$(NC)"
	@echo "$(YELLOW)      Run: AWS_PROFILE=<admin-profile> make setup-oidc$(NC)"
	@chmod +x scripts/setup-oidc.sh
	@./scripts/setup-oidc.sh

# Extract current AWS credentials from SSO session and push them to GitHub Actions secrets.
# Run 'make aws-login' first so the SSO session is active, then run this target.
gh-secrets:
	@echo "$(CYAN)Reading AWS credentials from SSO session...$(NC)"
	@CREDS=$$(aws configure export-credentials --profile $(AWS_SSO_PROFILE) --format env 2>/dev/null) || \
	 CREDS=$$(aws configure export-credentials --format env 2>/dev/null); \
	if [ -z "$$CREDS" ]; then \
		echo "$(RED)✗ Could not read credentials — run 'make aws-login' first$(NC)"; exit 1; \
	fi; \
	KEY_ID=$$(echo "$$CREDS" | grep AWS_ACCESS_KEY_ID | cut -d= -f2 | tr -d '"' | tr -d "'"); \
	SECRET=$$(echo "$$CREDS" | grep AWS_SECRET_ACCESS_KEY | cut -d= -f2 | tr -d '"' | tr -d "'"); \
	SESSION=$$(echo "$$CREDS" | grep AWS_SESSION_TOKEN | cut -d= -f2 | tr -d '"' | tr -d "'"); \
	if [ -z "$$KEY_ID" ]; then \
		echo "$(RED)✗ No credentials found — run 'make aws-login' first$(NC)"; exit 1; \
	fi; \
	echo "$(CYAN)Setting GitHub Actions secrets...$(NC)"; \
	echo "$$KEY_ID"    | gh secret set AWS_ACCESS_KEY_ID    --repo $(shell git remote get-url origin | sed 's|.*github.com/||' | sed 's|\.git||'); \
	echo "$$SECRET"    | gh secret set AWS_SECRET_ACCESS_KEY --repo $(shell git remote get-url origin | sed 's|.*github.com/||' | sed 's|\.git||'); \
	if [ -n "$$SESSION" ]; then \
		echo "$$SESSION" | gh secret set AWS_SESSION_TOKEN --repo $(shell git remote get-url origin | sed 's|.*github.com/||' | sed 's|\.git||'); \
		echo "$(YELLOW)⚠  SSO session token set — expires in ~1hr. Re-run after next 'make aws-login'.$(NC)"; \
	fi; \
	echo "$(ECR_REGISTRY)" | gh secret set ECR_REGISTRY --repo $(shell git remote get-url origin | sed 's|.*github.com/||' | sed 's|\.git||'); \
	echo "$(EC2_INSTANCE_ID)" | gh secret set EC2_INSTANCE_ID --repo $(shell git remote get-url origin | sed 's|.*github.com/||' | sed 's|\.git||'); \
	echo "$(GREEN)✓ Secrets pushed to GitHub Actions$(NC)"; \
	echo ""; \
	echo "  AWS_ACCESS_KEY_ID      ✓"; \
	echo "  AWS_SECRET_ACCESS_KEY  ✓"; \
	[ -n "$$SESSION" ] && echo "  AWS_SESSION_TOKEN      ✓ (expires ~1hr)" || true; \
	echo "  ECR_REGISTRY           ✓ ($(ECR_REGISTRY))"; \
	echo "  EC2_INSTANCE_ID        ✓ ($(EC2_INSTANCE_ID))"

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
	@POSTGRES_USER=$${POSTGRES_USER:-aurora} POSTGRES_DB=$${POSTGRES_DB:-aurora} POSTGRES_CONTAINER=$${POSTGRES_CONTAINER:-aurora-postgres} ./prod-deployment/scripts/migrate.sh
	@echo "$(GREEN)✓ Migrations complete$(NC)"

migrate-status:
	@echo "$(CYAN)Checking migration status...$(NC)"
	@POSTGRES_USER=$${POSTGRES_USER:-aurora} POSTGRES_DB=$${POSTGRES_DB:-aurora} POSTGRES_CONTAINER=$${POSTGRES_CONTAINER:-aurora-postgres} ./prod-deployment/scripts/migrate.sh --status

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

# =============================================================================
# Teams App Test Tool
# =============================================================================
# Runs the bot + a local Teams-like UI that renders Adaptive Cards.
# No manifest upload or IT approval required.
#
# Local  (Docker Compose Aurora):  make teams-test
# Prod   (EC2 Aurora via tunnel):  make teams-test-prod   [blocks — keep open]
#                                  make teams-test-tool   [new terminal]
# Stop:                            make teams-test-stop / teams-test-stop-prod
#
# One-time:  make teams-test-install
# =============================================================================

TEAMS_BOT_PORT   ?= 3978
TEAMS_TEST_CFG    = teams-agent/teamsapptesttool.config.json

# Create the test tool config pointing at the local bot port
$(TEAMS_TEST_CFG):
	@printf '{"botMessagingEndpoint":"http://localhost:%s/api/messages"}\n' $(TEAMS_BOT_PORT) > $@
	@echo "$(GREEN)✓ Created $(TEAMS_TEST_CFG)$(NC)"

# Install @microsoft/teams-app-test-tool as a dev dependency (one-time)
teams-test-install:
	@echo "$(CYAN)Installing Teams App Test Tool...$(NC)"
	cd teams-agent && npm install --save-dev @microsoft/teams-app-test-tool
	@echo "$(GREEN)✓ Done — run 'make teams-test' to start$(NC)"

# ── LOCAL ─────────────────────────────────────────────────────────────────────
# Starts the Aurora Teams bot in Docker (local data) then opens the Test Tool.
# Ctrl-C stops the Test Tool; then run 'make teams-test-stop' to clean up.

teams-test: $(TEAMS_TEST_CFG)
	@echo "$(CYAN)Starting Teams bot (local Aurora — requires Docker)...$(NC)"
	@docker info >/dev/null 2>&1 || (echo "$(RED)✗ Docker is not running. Start Docker Desktop or use 'make teams-test-prod' for production testing (no Docker needed).$(NC)" && exit 1)
	docker compose --profile teams up -d --force-recreate teams-agent
	@echo "$(GREEN)✓ Bot running on localhost:$(TEAMS_BOT_PORT)$(NC)"
	@echo "$(CYAN)Opening Agents Playground...$(NC)"
	@cd teams-agent && ./node_modules/.bin/agentsplayground &
	@open http://localhost:$(AGENTS_PLAYGROUND_PORT) 2>/dev/null || true
	@echo "$(GREEN)✓ Ready — send a message in the browser$(NC)"

teams-test-stop:
	@echo "$(CYAN)Stopping local Teams test environment...$(NC)"
	@pkill -f "agentsplayground" 2>/dev/null || true
	@docker compose stop teams-agent 2>/dev/null || true
	@echo "$(GREEN)✓ Stopped$(NC)"

# Push a system announcement to all group channels (demo: shows proactive broadcast)
# Usage: make teams-test-announce
#        make teams-test-announce TITLE="..." SUMMARY="..." IMPORTANCE=critical
ANNOUNCE_TITLE    ?= Aurora Update: IEEE 802.11bn (Wi-Fi 8) D2.0 ballot opens May 2026
ANNOUNCE_SUMMARY  ?= TGbn has resolved ~60% of D1.0 ballot comments. D2.0 expected to go to WG ballot at the May Antwerp session (Session 216, May 10-15, Hilton Antwerp Old Town). Key resolved topics: coordinated spatial reuse, distributed resource units, channel access improvements.
ANNOUNCE_TAGS     ?= ["802.11bn","Wi-Fi 8","TGbn","IEEE","ballot","Antwerp"]
ANNOUNCE_IMPORTANCE ?= high

teams-test-announce:
	@echo "$(CYAN)Pushing announcement to all conversations...$(NC)"
	@printf '{"title":"Aurora Update: IEEE 802.11bn D2.0 ballot May 2026","summary":"TGbn resolved ~60%% of D1.0 comments. D2.0 ballot at Antwerp session (May 10-15, Hilton Old Town). Topics: coordinated spatial reuse, distributed resource units.","importance":"high","scope":"all"}' \
		| curl -s -X POST http://localhost:$(TEAMS_BOT_PORT)/internal/push-announcement \
			-H "Content-Type: application/json" --data-binary @- \
		&& echo "$(GREEN)✓ Announcement queued$(NC)" \
		|| echo "$(RED)✗ Bot not running — start with: make teams-test$(NC)"

# ── PRODUCTION ────────────────────────────────────────────────────────────────
# Bot + Playground run LOCALLY on this Mac against prod services via SSM tunnels.
# This avoids the serviceUrl callback problem: Bot Framework expects to reply to
# the same host that sent the message; if bot and playground are co-located on
# localhost the serviceUrl (localhost:56150) works in both directions.
#
# Architecture:
#   Mac: bot (Node 20) on :3978  +  playground on :56150
#   SSM tunnels: EC2 backend → localhost:8001, EC2 oracle → localhost:8010
#
# Usage (ONE terminal — blocks until Ctrl-C):
#   make teams-test-prod       open tunnels + start bot + playground + browser
#   make teams-test-stop-prod  kill bot + playground

# Node 20 is required (node_modules built for it; system node may be newer)
NODE_20 ?= $(HOME)/.nvm/versions/node/v20.20.2/bin/node

AGENTS_PLAYGROUND_PORT ?= 56150
TST_CFG = '{"botMessagingEndpoint":"http://localhost:$(TEAMS_BOT_PORT)/api/messages"}'

# Container IPs on EC2 (stable unless containers are recreated)
PROD_BACKEND_HOST  ?= 172.24.0.15
PROD_ORACLE_HOST   ?= 172.24.0.14
PROD_CC_HOST       ?= 172.24.0.18
PROD_SVC_PORT      ?= 8000
PROD_BACKEND_LOCAL ?= 8001
PROD_ORACLE_LOCAL  ?= 8010
PROD_CC_LOCAL      ?= 8003

# SSM port-forwards — run each in its own terminal, keep open while testing
teams-test-prod-backend:
	@echo "$(CYAN)SSM tunnel: production backend → localhost:$(PROD_BACKEND_LOCAL)  (keep open)$(NC)"
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(PROD_BACKEND_HOST)"],"portNumber":["$(PROD_SVC_PORT)"],"localPortNumber":["$(PROD_BACKEND_LOCAL)"]}' \
		--profile $(AWS_SSO_PROFILE) \
		--region $(AWS_REGION)

teams-test-prod-oracle:
	@echo "$(CYAN)SSM tunnel: production oracle → localhost:$(PROD_ORACLE_LOCAL)  (keep open)$(NC)"
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(PROD_ORACLE_HOST)"],"portNumber":["$(PROD_SVC_PORT)"],"localPortNumber":["$(PROD_ORACLE_LOCAL)"]}' \
		--profile $(AWS_SSO_PROFILE) \
		--region $(AWS_REGION)

teams-test-prod-cc:
	@echo "$(CYAN)SSM tunnel: production content-creator → localhost:$(PROD_CC_LOCAL)  (keep open)$(NC)"
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(PROD_CC_HOST)"],"portNumber":["$(PROD_SVC_PORT)"],"localPortNumber":["$(PROD_CC_LOCAL)"]}' \
		--profile $(AWS_SSO_PROFILE) \
		--region $(AWS_REGION)

teams-test-prod: $(TEAMS_TEST_CFG)
	@echo "$(CYAN)Cleaning up any stale instances...$(NC)"
	@pkill -f "agentsplayground" 2>/dev/null || true
	@pkill -f "dist/index.js" 2>/dev/null || true
	@pkill -f "portNumber.*$(PROD_BACKEND_LOCAL)" 2>/dev/null || true
	@pkill -f "portNumber.*$(PROD_ORACLE_LOCAL)" 2>/dev/null || true
	@pkill -f "portNumber.*$(PROD_CC_LOCAL)" 2>/dev/null || true
	@sleep 1
	@echo "$(CYAN)Opening SSM tunnels to production backend, oracle, content-creator...$(NC)"
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(PROD_BACKEND_HOST)"],"portNumber":["$(PROD_SVC_PORT)"],"localPortNumber":["$(PROD_BACKEND_LOCAL)"]}' \
		--profile $(AWS_SSO_PROFILE) --region $(AWS_REGION) &
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(PROD_ORACLE_HOST)"],"portNumber":["$(PROD_SVC_PORT)"],"localPortNumber":["$(PROD_ORACLE_LOCAL)"]}' \
		--profile $(AWS_SSO_PROFILE) --region $(AWS_REGION) &
	@aws ssm start-session \
		--target $(EC2_INSTANCE_ID) \
		--document-name AWS-StartPortForwardingSessionToRemoteHost \
		--parameters '{"host":["$(PROD_CC_HOST)"],"portNumber":["$(PROD_SVC_PORT)"],"localPortNumber":["$(PROD_CC_LOCAL)"]}' \
		--profile $(AWS_SSO_PROFILE) --region $(AWS_REGION) &
	@sleep 6
	@echo "$(CYAN)Starting bot locally (Node 20) against production services...$(NC)"
	@cd teams-agent && \
		BOT_ID= BOT_PASSWORD= BOT_PORT=$(TEAMS_BOT_PORT) NODE_ENV=production \
		AURORA_API_URL=http://localhost:$(PROD_BACKEND_LOCAL) \
		AURORA_ORACLE_URL=http://localhost:$(PROD_ORACLE_LOCAL) \
		AURORA_CONTENT_CREATOR_URL=http://localhost:$(PROD_CC_LOCAL) \
		TEST_USER_EMAIL=$(TEST_USER_EMAIL) TEST_USER_ID=$(TEST_USER_ID) \
		USE_MOCK_DATA=true \
		$(NODE_20) dist/index.js &
	@sleep 3
	@echo "$(CYAN)Starting Agents Playground...$(NC)"
	@cd teams-agent && ./node_modules/.bin/agentsplayground &
	@sleep 2
	@open -g http://localhost:$(AGENTS_PLAYGROUND_PORT) 2>/dev/null || true
	@echo "$(GREEN)✓ Ready — bot :$(TEAMS_BOT_PORT) · playground :$(AGENTS_PLAYGROUND_PORT) · backend :$(PROD_BACKEND_LOCAL) · oracle :$(PROD_ORACLE_LOCAL)$(NC)"
	@echo "$(YELLOW)Ctrl-C or make teams-test-stop-prod to stop$(NC)"

# Launch only the browser UI against local bot
teams-test-tool: $(TEAMS_TEST_CFG)
	@echo "$(CYAN)Starting Agents Playground → localhost:$(TEAMS_BOT_PORT)$(NC)"
	@cd teams-agent && ./node_modules/.bin/agentsplayground &
	@open http://localhost:$(AGENTS_PLAYGROUND_PORT) 2>/dev/null || true
	@echo "$(GREEN)✓ Browser opened$(NC)"

teams-test-stop-prod:
	@echo "$(CYAN)Stopping Teams prod test environment...$(NC)"
	@pkill -f "agentsplayground" 2>/dev/null || true
	@pkill -f "dist/index.js" 2>/dev/null || true
	@pkill -f "portNumber.*$(PROD_BACKEND_LOCAL)" 2>/dev/null || true
	@pkill -f "portNumber.*$(PROD_ORACLE_LOCAL)" 2>/dev/null || true
	@pkill -f "portNumber.*$(PROD_CC_LOCAL)" 2>/dev/null || true
	@echo "$(GREEN)✓ Stopped$(NC)"
