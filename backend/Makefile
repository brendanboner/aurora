# Aurora Backend Makefile

SERVICE_NAME := backend

include ../.env
export

include ../common/make-utils.mk

.PHONY: help deploy-shared clean-shared logs nuke validate-env

help:
	@echo "Aurora Backend Commands:"
	@echo "  make deploy-shared   - Build + replace backend container"
	@echo "  make clean-shared    - Stop backend"
	@echo "  make logs            - Tail logs"
	@echo "  make nuke            - Remove image + container"

validate-env:
	@test -n "$(NEO4J_URI)" || (echo '❌ NEO4J_URI missing' && exit 1)
	@test -n "$(PG_DSN)" || (echo '❌ PG_DSN missing' && exit 1)
	@test -n "$(DOCKER_NETWORK)" || (echo '❌ DOCKER_NETWORK missing' && exit 1)
	@echo "✅ Environment OK"

seed-users:
	@echo "🌱 Seeding sample backend users..."
	@docker exec -i $(POSTGRES_CONTAINER) psql "$(PG_DSN)" < db_seed.sql
	@echo "✅ User seed complete"

deploy-shared: validate-env
	@echo "🛑 Stopping old backend container (if running)..."
	-@docker rm -f $(SHARED_SERVICE_CONTAINER) 2>/dev/null || true

	@echo "📦 Rebuilding backend image: $(SERVICE_IMAGE)"
	cd .. && docker build -f backend/Dockerfile -t $(SERVICE_IMAGE) .

	@echo "🚀 Starting fresh backend container: $(SHARED_SERVICE_CONTAINER)"
	docker run -d \
		--name $(SHARED_SERVICE_CONTAINER) \
		--network $(DOCKER_NETWORK) \
		-p 8000:8000 \
		-e PG_DSN="$(PG_DSN)" \
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

	@echo "✨ Backend updated successfully"

clean-shared:
	-@docker rm -f $(SHARED_SERVICE_CONTAINER)

logs:
	@docker logs -f $(SHARED_SERVICE_CONTAINER)

nuke:
	-@docker rm -f $(SHARED_SERVICE_CONTAINER)
	-@docker rmi $(SERVICE_IMAGE)
