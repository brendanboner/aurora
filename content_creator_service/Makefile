# Aurora Content Creator Service Makefile

SERVICE_NAME := content-creator-service

include ../.env
export

include ../common/make-utils.mk

PYTHON_RUNNER ?= uv run python

.PHONY: help deploy-shared clean-shared logs nuke validate-env run-local trigger-agent

help:
	@echo "Aurora Content Creator Service Commands:"
	@echo "  make deploy-shared   - Build + replace service container"
	@echo "  make clean-shared    - Stop service container"
	@echo "  make logs            - Tail logs"
	@echo "  make run-local       - Run uvicorn with local env"
	@echo "  make trigger-agent   - Force a CreatorAgent to create a post"
	@echo "  make nuke            - Remove image + container"

validate-env:
	@test -n "$(POSTGRES_HOST)" || (echo '❌ POSTGRES_HOST missing' && exit 1)
	@test -n "$(POSTGRES_DB)" || (echo '❌ POSTGRES_DB missing' && exit 1)
	@test -n "$(NEO4J_URI)" || (echo '❌ NEO4J_URI missing' && exit 1)
	@test -n "$(AZURE_OPENAI_ENDPOINT)" || (echo '❌ AZURE_OPENAI_ENDPOINT missing' && exit 1)
	@test -n "$(AZURE_OPENAI_API_KEY)" || (echo '❌ AZURE_OPENAI_API_KEY missing' && exit 1)
	@echo "✅ Environment OK"

run-local:
	uvicorn src.api:app --reload --port 8003

deploy-shared: validate-env
	@echo "🛑 Stopping old content creator container (if running)..."
	-@docker rm -f $(SHARED_SERVICE_CONTAINER) 2>/dev/null || true

	@echo "📦 Rebuilding content creator image: $(SERVICE_IMAGE)"
	cd .. && docker build -f content_creator_service/Dockerfile -t $(SERVICE_IMAGE) .

	@echo "🚀 Starting fresh content creator container: $(SHARED_SERVICE_CONTAINER)"
	docker run -d \
		--name $(SHARED_SERVICE_CONTAINER) \
		--network $(DOCKER_NETWORK) \
		-p 8003:8003 \
		-e PG_DSN="$(PG_DSN)" \
		-e POSTGRES_HOST="$(POSTGRES_HOST)" \
		-e POSTGRES_PORT="$(POSTGRES_PORT)" \
		-e POSTGRES_USER="$(POSTGRES_USER)" \
		-e POSTGRES_PASSWORD="$(POSTGRES_PASSWORD)" \
		-e POSTGRES_DB="$(POSTGRES_DB)" \
		-e NEO4J_URI="$(NEO4J_URI)" \
		-e NEO4J_USER="$(NEO4J_USER)" \
		-e NEO4J_PASSWORD="$(NEO4J_PASSWORD)" \
		-e NEO4J_DATABASE="$(NEO4J_DATABASE)" \
		-e RABBITMQ_HOST="$(RABBITMQ_HOST)" \
		-e RABBITMQ_PORT="$(RABBITMQ_PORT)" \
		-e RABBITMQ_USER="$(RABBITMQ_USER)" \
		-e RABBITMQ_PASSWORD="$(RABBITMQ_PASSWORD)" \
		-e AZURE_OPENAI_API_KEY="$(AZURE_OPENAI_API_KEY)" \
		-e AZURE_OPENAI_ENDPOINT="$(AZURE_OPENAI_ENDPOINT)" \
		-e AZURE_OPENAI_API_VERSION="$(AZURE_OPENAI_API_VERSION)" \
		-e AZURE_OPENAI_DEPLOYMENT="$(AZURE_OPENAI_DEPLOYMENT)" \
		$(SERVICE_IMAGE)

clean-shared:
	-@docker rm -f $(SHARED_SERVICE_CONTAINER)

logs:
	docker logs -f $(SHARED_SERVICE_CONTAINER)

nuke:
	-@docker rm -f $(SHARED_SERVICE_CONTAINER)
	-@docker rmi $(SERVICE_IMAGE)

trigger-agent:
	@test -n "$(AGENT_ID)$(AGENT_NAME)" || (echo 'Provide AGENT_ID or AGENT_NAME' && exit 1)
	@if [ -n "$(AGENT_ID)" ]; then \
		AGENT="$(AGENT_ID)"; \
	else \
		echo "Resolving agent '$(AGENT_NAME)'..."; \
		AGENT=$$(curl -s http://localhost:8003/agents?include_disabled=true | jq -r '.[] | select(.name | ascii_downcase == "$(shell echo $(AGENT_NAME) | tr A-Z a-z)") | .id'); \
		if [ -z "$$AGENT" ]; then echo "❌ Agent '$(AGENT_NAME)' not found"; exit 1; fi; \
	fi; \
	FORCE_FLAG=$$([ -n "$(FORCE)" ] && echo "true" || echo "false"); \
	LIMIT_VAL=$${LIMIT:-5}; \
	echo "🚀 Triggering agent $$AGENT (force=$$FORCE_FLAG, limit=$$LIMIT_VAL)"; \
	curl -s -X POST "http://localhost:8003/agents/$$AGENT/trigger" \
		-H "Content-Type: application/json" \
		-d "{\"force\": $$FORCE_FLAG, \"limit\": $$LIMIT_VAL}" | jq .
